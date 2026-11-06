"""Stands in for /gateway and llm.call until the real AI gateway lands."""

import re

from fastapi import APIRouter

from mocks import data

router = APIRouter(prefix="/gateway", tags=["mock gateway"])

CODENAME = "Bluewren"
CODENAME_TOKEN = "[PRODUCT_1]"


@router.get("/reviews/{review_id}/disclosure")
def disclosure(review_id: str) -> dict:
    return {
        "models": ["claude-haiku-4-5", "gpt-6-luna"],
        "masked": {"PRODUCT": 1},
        "routes": ["cloud"],
    }


@router.get("/reviews/{review_id}/masking-preview")
def masking_preview(review_id: str) -> dict:
    original = data.chunks_for_piece("agency-blog")["blog-p6"]
    return {"original": original, "sent": original.replace(CODENAME, CODENAME_TOKEN)}


_MATERIAL = re.compile(r"<<<(MATERIAL-\w+)\n(.*)\n\1>>>", re.DOTALL)
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


def _control_answer(payload: dict) -> str:
    """Answers the question the Language agent uses to check a model read the text."""
    messages = payload.get("messages") or [{}]
    prompt = str(messages[-1].get("content", ""))
    material = _MATERIAL.search(prompt)
    words = _WORD.findall(material.group(2)) if material else []
    if not words:
        return ""
    first = "Control question: What is the first word" in prompt
    return words[0] if first else words[-1]


def _verdicts(rule_ids: list[str], payload: dict) -> dict:
    return {
        "control_answer": _control_answer(payload),
        "verdicts": [
            {
                "rule_id": rule_id,
                "verdict": "PASS",
                "span": None,
                "confidence": 0.9,
                "explanation": "Mock verdict.",
            }
            for rule_id in rule_ids
        ]
    }


def _draft_rules() -> dict:
    fields = ("type", "text", "clause_ref", "severity", "channel_scope")
    return {
        "rules": [{field: rule[field] for field in fields} for rule in data.rules()],
        "conflicts": [{"clause_refs": ["§2.4", "§3.4"]}],
    }


def llm_call(
    purpose: str, data_class: str, rule_ids: list[str], payload: dict
) -> dict:
    """Same signature as llm.call in app.gateway. Unknown purposes fail loudly."""
    if purpose == "ingest":
        return _draft_rules()
    if purpose in ("visual", "classify"):
        return _verdicts(rule_ids, payload)
    raise ValueError(f"The mock llm.call has no response for purpose {purpose!r}")
