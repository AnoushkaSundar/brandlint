"""Replay: re-runs a verdict from its input manifest and compares the result.

This calls the model again rather than reading the cache, because a replay that
only returned the stored answer would always look identical and prove nothing.
Code findings re-run the tier-0 checks with the original date.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import Rule, Span, Verdict
from app.engine import models
from app.engine.agents import claims, language
from app.engine.agents.language import ClassifyFn
from app.engine.brand import load_brand
from app.engine.checks import CheckContext, run_tier0
from app.engine.chunking import ParsedChunk


class NotReplayable(LookupError):
    """The finding has no manifest, or the content it needs is gone."""


def _parsed(row: models.Chunk) -> ParsedChunk:
    return ParsedChunk(
        id=row.id,
        content_version_id=row.content_version_id,
        ordinal=row.ordinal,
        kind=row.kind,
        text=row.text,
        content_hash=row.content_hash,
        data_class=row.data_class,
        style=row.style,
    )


def _spans(spans: list) -> list[dict]:
    return sorted(
        (Span.model_validate(span).model_dump() for span in spans),
        key=lambda span: (span["chunk_id"], span["start"]),
    )


def _replay_language(
    finding: models.Finding, manifest: dict, session: Session, classify: ClassifyFn
) -> tuple[str, list[dict]]:
    row = session.get(models.Chunk, manifest["chunk_id"])
    if row is None or row.content_hash != manifest["content_hash"]:
        raise NotReplayable("The chunk this verdict judged has changed.")
    chunk = _parsed(row)
    ctx = CheckContext(
        review_id=finding.review_id,
        content_version_id=finding.content_version_id,
        channel=manifest["channel"],
    )
    candidate = language.judge(
        chunk,
        Rule.model_validate(manifest["rule"]),
        ctx,
        classify,
        flagged={chunk.id} if manifest["flagged"] else (),
        model=manifest["model"],
    )
    if candidate is None:
        return Verdict.PASS.value, []
    return candidate.verdict.value, _spans(candidate.spans)


def _replay_claim(
    finding: models.Finding, manifest: dict, session: Session, classify: ClassifyFn
) -> tuple[str, list[dict]]:
    brand = load_brand(session, manifest["rulebook_version"])
    ctx = CheckContext(
        review_id=finding.review_id,
        content_version_id=finding.content_version_id,
        channel=manifest["channel"],
        rules=brand.rules,
        facts=brand.facts,
        terms=brand.terms,
        as_of=date.fromisoformat(manifest["as_of"]),
    )
    first = session.get(models.Chunk, manifest["spans"][0]["chunk_id"])
    if first is None:
        raise NotReplayable("The chunk this verdict judged has changed.")
    unit = claims.ClaimUnit(manifest["claim"], manifest["spans"])
    candidate = claims.verify(
        unit, ctx, classify, data_class=first.data_class, flagged=(),
        model=manifest["model"],
    )
    if candidate is None:
        return Verdict.PASS.value, []
    return candidate.verdict.value, _spans(candidate.spans)


def _replay_code(
    finding: models.Finding, manifest: dict, session: Session
) -> tuple[str, list[dict]]:
    rows = session.scalars(
        select(models.Chunk)
        .where(models.Chunk.content_version_id == finding.content_version_id)
        .order_by(models.Chunk.ordinal)
    ).all()
    brand = load_brand(session, manifest["rulebook_version"])
    ctx = CheckContext(
        review_id=finding.review_id,
        content_version_id=finding.content_version_id,
        channel=manifest["channel"],
        rules=brand.rules,
        facts=brand.facts,
        terms=brand.terms,
        as_of=date.fromisoformat(manifest["as_of"]),
    )
    found = run_tier0([_parsed(row) for row in rows], ctx, manifest["fmt"])
    for candidate in found:
        if candidate.id == finding.id:
            return candidate.verdict.value, _spans(candidate.spans)
    return Verdict.PASS.value, []


def replay(finding_id: str, session: Session, classify: ClassifyFn) -> dict | None:
    """{identical, verdict, manifest}, or None if there is no such finding."""
    finding = session.get(models.Finding, finding_id)
    if finding is None:
        return None
    manifest = finding.manifest
    if not manifest:
        raise NotReplayable("This verdict has no stored inputs.")

    if manifest.get("kind") == "language":
        verdict, spans = _replay_language(finding, manifest, session, classify)
    elif manifest.get("kind") == "claim":
        if not manifest["spans"]:
            raise NotReplayable("This finding covers the whole document.")
        verdict, spans = _replay_claim(finding, manifest, session, classify)
    else:
        verdict, spans = _replay_code(finding, manifest, session)
    # The verdict is what must repeat. A model can quote a slightly different
    # passage even at temperature 0, so that's reported rather than hidden.
    return {
        "identical": verdict == finding.verdict,
        "verdict": verdict,
        "manifest": {**manifest, "spans_identical": spans == _spans(finding.spans)},
    }
