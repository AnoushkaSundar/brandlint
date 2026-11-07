"""The brand graph, as a Postgres edge table.

The table is a projection: `sync` rebuilds it from claims, findings, decisions and
the facts store, and runs when the graph is read, so nothing is written during a
review. Only a piece's latest review counts, so a claim fixed away leaves the graph.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin.brand import list_facts, list_terms
from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.engine.models import ClaimUnit, Finding
from app.memory.models import Edge
from app.workflow.models import Decision, Review


def _edge(
    kind: str, src: tuple[str, str, str], dst: tuple[str, str, str]
) -> Edge:
    """`src` and `dst` are (node type, id, label)."""
    key = hashlib.sha256("|".join((kind, src[1], dst[1])).encode()).hexdigest()
    return Edge(
        id=key, type=kind, src_type=src[0], src_id=src[1], dst_type=dst[0], dst_id=dst[1],
        meta={"src_label": src[2], "dst_label": dst[2]},
    )


def latest_reviews(session: Session) -> dict[str, str]:
    """Content id to the engine id of its newest review."""
    rows = session.execute(
        select(ContentVersion.content_id, Review.engine_review_id)
        .join(Review, Review.content_version_id == ContentVersion.id)
        .order_by(Review.created_at)
    ).all()
    return {content_id: review_id for content_id, review_id in rows}


def _brand_edges(session: Session) -> list[Edge]:
    edges = []
    for fact in list_facts(session):
        doc = ("SourceDoc", fact.source_doc, fact.source_doc)
        edges.append(_edge("SUPPORTED_BY", ("Fact", fact.id, fact.id), doc))
    for term in list_terms(session):
        if term.renamed_from:
            edges.append(
                _edge(
                    "RENAMED_TO",
                    ("Term", term.renamed_from, term.renamed_from),
                    ("Term", term.preferred, term.preferred),
                )
            )
    return edges


def _review_edges(session: Session, review_id: str, content: Content) -> list[Edge]:
    node = ("Content", content.id, content.title)
    edges = [_edge("AUTHORED_BY", node, ("Team", content.source, content.source))]
    claims = session.scalars(select(ClaimUnit).where(ClaimUnit.review_id == review_id))
    for claim in claims.all():
        unit = ("Claim", claim.id, claim.normalized_claim)
        edges.append(_edge("CONTAINS", node, unit))
        for dependency in claim.depends_on or []:
            fact_id = dependency["fact_id"]
            edges.append(_edge("CITES", unit, ("Fact", fact_id, fact_id)))

    findings = session.scalars(select(Finding).where(Finding.review_id == review_id))
    for finding in findings.all():
        unit = ("Finding", finding.id, finding.check)
        edges.append(_edge("HAS", node, unit))
        if finding.rule_id:
            edges.append(
                _edge("VIOLATES", unit, ("Rule", finding.rule_id, finding.rule_id))
            )
        decisions = session.execute(
            select(Decision, User.name)
            .join(User, User.id == Decision.actor_id)
            .where(Decision.finding_id == finding.id)
        )
        for decision, reviewer in decisions.all():
            made = ("Decision", decision.id, decision.action)
            edges.append(_edge("RESOLVED_BY", unit, made))
            edges.append(_edge("MADE_BY", made, ("Reviewer", decision.actor_id, reviewer)))
    return edges


def sync(session: Session) -> None:
    """Brings the table in line with what's true now. Safe to run at any time."""
    latest = latest_reviews(session)
    wanted = {edge.id: edge for edge in _brand_edges(session)}
    contents = session.scalars(select(Content).where(Content.id.in_(latest))).all()
    for content in contents:
        for edge in _review_edges(session, latest[content.id], content):
            wanted[edge.id] = edge

    existing = set(session.scalars(select(Edge.id)))
    stale = existing - set(wanted)
    if stale:
        session.execute(delete(Edge).where(Edge.id.in_(stale)))
    session.add_all(edge for key, edge in wanted.items() if key not in existing)
    try:
        session.commit()
    except IntegrityError:
        # Another read synced the same edges first.
        session.rollback()
