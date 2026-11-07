"""What a review showed to which model. Backs the disclosure panel and masking preview.

Neither answer relies on the call log alone: a re-run of the same piece is served
from the verdict cache, so it makes no calls and logs nothing. The preview runs the
real masking code over the review's chunks, and nothing goes to a model.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import DataClass
from app.engine import reviews
from app.engine.models import Finding
from app.gateway import masking, policy
from app.gateway.models import GatewayLog, TokenVault


def _masked_chunks(review_id: str, session: Session) -> list[tuple[str, str]]:
    pairs = []
    for chunk in reviews.list_chunks(review_id, session):
        data_class = DataClass(chunk.data_class)
        if policy.stays_local(data_class):
            pairs.append((chunk.text, chunk.text))
            continue
        masked = masking.mask_messages(
            [{"role": "user", "content": chunk.text}],
            data_class=data_class,
            scope=review_id,
            bind=session.get_bind(),
        )
        pairs.append((chunk.text, masked.messages[0]["content"]))
    return pairs


def masking_preview(review_id: str, session: Session) -> dict[str, str]:
    """Only the passages masking changed, or the whole piece if it changed nothing."""
    pairs = _masked_chunks(review_id, session)
    shown = [pair for pair in pairs if pair[0] != pair[1]] or pairs
    return {
        "original": "\n\n".join(original for original, _ in shown),
        "sent": "\n\n".join(sent for _, sent in shown),
    }


def disclosure(review_id: str, session: Session) -> dict[str, Any]:
    _masked_chunks(review_id, session)
    calls = session.execute(
        select(GatewayLog.model, GatewayLog.status).where(
            GatewayLog.review_id == review_id
        )
    ).all()
    answered = {model for model, status in calls if model and status == "ok"}
    # A finding names the model it asked, even if the call failed. A model with no
    # logged calls at all answered from the cache on an earlier run, so it counts.
    only_failed = {model for model, _ in calls} - answered
    verdicts = session.scalars(
        select(Finding.models_used).where(Finding.review_id == review_id)
    ).all()
    named = {model for used in verdicts for model in used or []}
    models = sorted(answered | (named - only_failed))
    entities = session.scalars(
        select(TokenVault.entity).where(TokenVault.scope == review_id)
    ).all()
    return {
        "models": models,
        "masked": dict(Counter(entities)),
        "routes": sorted({policy.route_label(model) for model in models}),
    }
