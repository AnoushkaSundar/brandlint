"""Masks what a model sees and restores what it says.

Values become numbered tokens such as `[PRODUCT_1]`, kept in `token_vault` and
consistent within a review. Fail closed: if the deny-list or Presidio can't be
reached, this raises and the call never leaves the gateway.

- The deny-list (protected fact values) applies to every call, whatever the
  upload label, because a draft labelled public can still name a codename.
- Presidio finds personal data in internal and confidential content.
- Text that already looks like a token is masked too. Otherwise a creator could
  type `[PRODUCT_1]` and have the model echo it back as the real codename.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import Engine, func
from sqlalchemy.orm import Session

from app.admin.brand import PROTECTED_CLASSES, list_facts, list_terms
from app.contracts import DataClass
from app.gateway.models import TokenVault
from app.tenancy import bind_org, scoped

PRESIDIO_URL = os.getenv("PRESIDIO_ANALYZER_URL", "http://localhost:5002")
PRESIDIO_TIMEOUT_S = float(os.getenv("PRESIDIO_TIMEOUT_S", "10"))
PRESIDIO_SCORE = 0.5
DENY_LIST_TTL_S = 60

_PERSONAL_DATA_CLASSES = {DataClass.internal, DataClass.confidential}
_LABELS = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CREDIT_CARD": "CARD",
    "IBAN_CODE": "IBAN",
}
_TOKEN = re.compile(r"\[[A-Z]+_\d+\]")

_allocate_lock = threading.Lock()
_deny_lock = threading.Lock()
# One deny-list per org, because each org's protected values are its own facts.
_deny_cache: dict[str, tuple[float, DenyList]] = {}


@dataclass(frozen=True)
class DenyList:
    terms: tuple[str, ...]
    allowed: frozenset[str]  # Brand vocabulary Presidio mistakes for people.


@dataclass
class Masked:
    messages: list[dict[str, Any]]
    tokens: dict[str, str] = field(default_factory=dict)
    counts: Counter = field(default_factory=Counter)


Analyzer = Callable[[str], list[dict[str, Any]]]


def _build_deny_list(bind: Engine, org_id: str) -> DenyList:
    with Session(bind) as session:
        bind_org(session, org_id)
        facts = list_facts(session)
        terms = list_terms(session)
    values = {
        fact.value.strip()
        for fact in facts
        if fact.data_class in PROTECTED_CLASSES and fact.value.strip()
    }
    allowed = {
        word.casefold()
        for term in terms
        for word in (term.preferred, term.renamed_from, *term.banned)
        if word
    }
    # Longest first, so a longer value wins over one inside it.
    return DenyList(tuple(sorted(values, key=len, reverse=True)), frozenset(allowed))


def deny_list(bind: Engine, org_id: str) -> DenyList:
    """The protected values and the brand vocabulary of one org, and nobody else's."""
    key = str(org_id).lower()
    with _deny_lock:
        cached = _deny_cache.get(key)
        if cached is None or time.monotonic() - cached[0] > DENY_LIST_TTL_S:
            cached = (time.monotonic(), _build_deny_list(bind, org_id))
            _deny_cache[key] = cached
        return cached[1]


def analyze(text: str) -> list[dict[str, Any]]:
    response = httpx.post(
        f"{PRESIDIO_URL}/analyze",
        json={
            "text": text,
            "language": "en",
            "entities": list(_LABELS),
            "score_threshold": PRESIDIO_SCORE,
        },
        timeout=PRESIDIO_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.json()


def _find_spans(
    text: str, deny: DenyList, analyzer: Analyzer | None
) -> list[tuple[int, int, str]]:
    """Non-overlapping (start, end, label), strongest source first."""
    found: list[tuple[int, int, str]] = []

    def claim(start: int, end: int, label: str) -> None:
        if not any(start < e and s < end for s, e, _ in found):
            found.append((start, end, label))

    for match in _TOKEN.finditer(text):
        claim(match.start(), match.end(), "TOKEN")
    for term in deny.terms:
        pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
        for match in pattern.finditer(text):
            claim(match.start(), match.end(), "PRODUCT")
    if analyzer is not None:
        for entity in analyzer(text):
            start, end = entity["start"], entity["end"]
            if text[start:end].casefold() not in deny.allowed:
                claim(start, end, _LABELS[entity["entity_type"]])
    return sorted(found)


def _token_for(
    value: str, label: str, scope: str, bind: Engine, org_id: str
) -> str:
    """The token for a value in this scope. Runs in its own transaction so
    parallel calls in one review share tokens instead of racing to number them."""
    with _allocate_lock, Session(bind) as session:
        bind_org(session, org_id)
        existing = session.scalar(
            scoped(session, TokenVault, TokenVault.token).where(
                TokenVault.scope == scope, TokenVault.value == value
            )
        )
        if existing:
            return existing
        count = session.scalar(
            scoped(session, TokenVault, func.count())
            .where(TokenVault.scope == scope, TokenVault.entity == label)
        )
        token = f"[{label}_{(count or 0) + 1}]"
        session.add(
            TokenVault(
                id=str(uuid.uuid4()), scope=scope, token=token, value=value, entity=label
            )
        )
        session.commit()
        return token


def _mask_text(
    text: str,
    *,
    deny: DenyList,
    analyzer: Analyzer | None,
    scope: str,
    bind: Engine,
    org_id: str,
    masked: Masked,
) -> str:
    pieces: list[str] = []
    position = 0
    for start, end, label in _find_spans(text, deny, analyzer):
        value = text[start:end]
        token = _token_for(value, label, scope, bind, org_id)
        masked.tokens[token] = value
        masked.counts[label] += 1
        pieces += [text[position:start], token]
        position = end
    return "".join([*pieces, text[position:]])


def mask_messages(
    messages: Iterable[Mapping[str, Any]],
    *,
    data_class: DataClass,
    scope: str,
    bind: Engine,
    org_id: str,
) -> Masked:
    deny = deny_list(bind, org_id)
    masked = Masked(messages=[])
    personal = data_class in _PERSONAL_DATA_CLASSES

    for message in messages:
        analyzer = analyze if personal and message.get("role") == "user" else None
        common = {
            "deny": deny, "analyzer": analyzer, "scope": scope, "bind": bind,
            "org_id": org_id,
            "masked": masked,
        }
        content = message.get("content")
        if isinstance(content, str):
            content = _mask_text(content, **common)
        elif isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "text":
                    part = {**part, "text": _mask_text(part["text"], **common)}
                elif data_class == DataClass.confidential:
                    # An image can't be masked, so it can't leave the box.
                    raise ValueError("confidential visuals can't be masked")
                parts.append(part)
            content = parts
        masked.messages.append({**message, "content": content})
    return masked


def leak(content: Any, tokens: Mapping[str, str], deny: DenyList) -> str | None:
    """What's wrong with a reply, checked before its tokens are restored.

    A model only ever saw tokens, so a protected value in the raw reply, or a token
    it wasn't given, didn't come from what we sent. The reason never quotes the value.
    """
    text = str(content)
    if any(token not in tokens for token in _TOKEN.findall(text)):
        return "the reply holds a token this call didn't send"
    for term in deny.terms:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE):
            return "the reply holds a protected value"
    return None


def unmask(value: Any, tokens: Mapping[str, str]) -> Any:
    """Restores this call's tokens throughout the model's output. Tokens from
    other calls stay as they are, so a reply can't pull in values it wasn't given."""
    if isinstance(value, str):
        return _TOKEN.sub(lambda m: tokens.get(m.group(0), m.group(0)), value)
    if isinstance(value, list):
        return [unmask(item, tokens) for item in value]
    if isinstance(value, dict):
        return {key: unmask(item, tokens) for key, item in value.items()}
    return value
