"""Impact, precedents and the graph view, all read from the edge table."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content
from app.contracts import DecisionAction, FindingStatus, Precedent
from app.engine.models import Chunk, Finding
from app.memory import edges
from app.memory.models import Edge
from app.tenancy import scoped, scoped_get
from app.workflow.models import Decision

# Text similarity, not pgvector cosine: nothing here produces embeddings yet.
SIMILAR_TEXT = 0.6
GRAPH_DEPTH = 2
MAX_GRAPH_EDGES = 200


def impact(fact_id: str, session: Session) -> list[dict[str, str]]:
    """Every piece whose latest review holds a claim citing this fact."""
    edges.sync(session)
    cites = scoped(session, Edge, Edge.src_id).where(Edge.type == "CITES", Edge.dst_id == fact_id)
    rows = session.execute(
        scoped(session, Edge, Edge, Content.state)
        .scoped_join(session, Content, Content.id == Edge.src_id)
        .where(Edge.type == "CONTAINS", Edge.dst_id.in_(cites))
    ).all()
    found = {(edge.src_id, edge.meta["dst_label"]): state for edge, state in rows}
    return [
        {"content_id": content_id, "state": state, "claim_text": claim}
        for (content_id, claim), state in sorted(found.items())
    ]


def _flagged_text(finding: Finding, session: Session) -> str:
    pieces = []
    for span in finding.spans or []:
        chunk = scoped_get(session, Chunk, span["chunk_id"])
        if chunk is not None:
            pieces.append(chunk.text[span["start"] : span["end"]])
    return " ".join(pieces).casefold()


def _channel(finding: Finding) -> str | None:
    return (finding.manifest or {}).get("channel")


def precedents(finding_id: str, session: Session) -> list[Precedent]:
    """Confirmed overrides of the same rule version, channel and similar text."""
    finding = scoped_get(session, Finding, finding_id)
    if finding is None or not finding.rule_id or finding.rule_version is None:
        return []
    text = _flagged_text(finding, session)
    confirmed = session.execute(
        scoped(session, Decision, Decision, Finding, User.name)
        .scoped_join(session, Finding, Finding.id == Decision.finding_id)
        .scoped_join(session, User, User.id == Decision.actor_id)
        .where(
            Decision.status == FindingStatus.override_confirmed.value,
            Finding.rule_id == finding.rule_id,
            Finding.rule_version == finding.rule_version,
            Finding.id != finding.id,
        )
        .order_by(Decision.created_at.desc())
    ).all()

    found = []
    for decision, earlier, reviewer in confirmed:
        if _channel(earlier) != _channel(finding):
            continue
        other = _flagged_text(earlier, session)
        if SequenceMatcher(None, text, other).ratio() < SIMILAR_TEXT:
            continue
        requested = session.scalar(
            scoped(session, Decision, Decision.reason)
            .where(
                Decision.finding_id == earlier.id,
                Decision.action == DecisionAction.override.value,
            )
            .order_by(Decision.created_at.desc())
        )
        found.append(
            Precedent(
                decision_id=decision.id,
                rule_id=earlier.rule_id,
                rule_version=earlier.rule_version,
                channel=_channel(earlier),
                reason=decision.reason or requested or "",
                reviewer=reviewer,
                date=decision.created_at,
            )
        )
    return found


def graph(root: str, session: Session) -> dict[str, list[dict[str, Any]]]:
    """Everything within two steps of `root`: fact, claim, content."""
    edges.sync(session)
    seen = {root}
    frontier = {root}
    found: dict[str, Edge] = {}
    for _ in range(GRAPH_DEPTH):
        rows = session.scalars(
            scoped(session, Edge)
            .where(or_(Edge.src_id.in_(frontier), Edge.dst_id.in_(frontier)))
            .limit(MAX_GRAPH_EDGES)
        ).all()
        found.update({edge.id: edge for edge in rows})
        frontier = {i for edge in rows for i in (edge.src_id, edge.dst_id)} - seen
        seen |= frontier

    nodes = {}
    for edge in found.values():
        nodes[edge.src_id] = {
            "id": edge.src_id, "type": edge.src_type, "label": edge.meta["src_label"],
        }
        nodes[edge.dst_id] = {
            "id": edge.dst_id, "type": edge.dst_type, "label": edge.meta["dst_label"],
        }
    return {
        "nodes": list(nodes.values()),
        "edges": [
            {"source": edge.src_id, "target": edge.dst_id, "type": edge.type}
            for edge in found.values()
        ],
    }
