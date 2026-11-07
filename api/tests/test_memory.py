"""Brand memory: impact, precedents and the graph view."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import app.admin.models  # noqa: F401
import pytest
from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.db import Base
from app.engine import models as engine_models
from app.memory import edges, queries
from app.memory.models import Edge
from app.workflow.models import Decision, Review
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 7, tzinfo=UTC)


@pytest.fixture()
def session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(
            User(id="u1", email="a@b.c", name="Lena", password_hash="x", role="reviewer")
        )
        s.add(User(id="u2", email="b@b.c", name="Cam", password_hash="x", role="creator"))
        s.commit()
        yield s


def piece(session, name="blog", state="resolving"):
    session.add(
        Content(
            id=name, title=f"The {name}", channel="blog", source="Agency",
            data_class="public", state=state, creator_id="u2",
        )
    )
    session.commit()


def review(session, name, review_id, *claims, version=1, age=0):
    session.add(
        ContentVersion(
            id=f"{name}-v{version}", content_id=name, version=version, text="",
            created_by="u2",
        )
    )
    session.add(
        Review(
            id=review_id, content_version_id=f"{name}-v{version}",
            engine_review_id=review_id, channel="blog", rulebook_version=1,
            created_at=NOW - timedelta(hours=age),
        )
    )
    for number, (text, fact_id) in enumerate(claims):
        session.add(
            engine_models.ClaimUnit(
                id=f"{review_id}-c{number}", review_id=review_id,
                content_version_id=f"{name}-v{version}", normalized_claim=text,
                span_refs=[], depends_on=[{"fact_id": fact_id, "version": 1}],
            )
        )
    session.commit()


def finding(session, number, text="newbies", rule="R-TERM-03", channel="blog", version=1):
    session.add(
        engine_models.Chunk(
            id=f"c{number}", content_version_id="v", ordinal=number, kind="paragraph",
            text=text, content_hash=str(number), data_class="public",
        )
    )
    session.add(
        engine_models.Finding(
            id=f"f{number}", review_id="rev", content_version_id="v", unit_type="chunk",
            spans=[{"chunk_id": f"c{number}", "start": 0, "end": len(text)}],
            check="terminology", tier=0, verdict="VIOLATION", severity="low",
            confidence=1.0, rule_id=rule, rule_version=version, fact_ids=[],
            cited_text="c", explanation="e", trace={}, ai_generated=False,
            models_used=[], manifest={"channel": channel},
        )
    )
    session.commit()


def confirm(session, number):
    session.add(
        Decision(
            id=f"over{number}", review_id="r", finding_id=f"f{number}", actor_id="u2",
            role="creator", action="override", status="override_pending",
            reason="A direct quote.", created_at=NOW,
        )
    )
    session.add(
        Decision(
            id=f"conf{number}", review_id="r", finding_id=f"f{number}", actor_id="u1",
            role="reviewer", action="confirm_override", status="override_confirmed",
            created_at=NOW,
        )
    )
    session.commit()


def test_impact_lists_every_piece_citing_the_fact(session):
    piece(session)
    piece(session, "case", "published")
    review(session, "blog", "r1", ("cut time by 80%", "F-002"))
    review(session, "case", "r2", ("cut time by 38%", "F-002"), ("other", "F-009"))
    assert queries.impact("F-002", session) == [
        {"content_id": "blog", "state": "resolving", "claim_text": "cut time by 80%"},
        {"content_id": "case", "state": "published", "claim_text": "cut time by 38%"},
    ]


def test_a_piece_that_never_cited_the_fact_is_left_out(session):
    piece(session)
    review(session, "blog", "r1", ("other", "F-009"))
    assert queries.impact("F-002", session) == []


def test_only_the_latest_review_counts(session):
    piece(session)
    review(session, "blog", "r1", ("cut time by 80%", "F-002"), age=2)
    assert queries.impact("F-002", session)
    review(session, "blog", "r2", ("no claim left", "F-009"), version=2)
    assert queries.impact("F-002", session) == []


def test_sync_is_safe_to_repeat(session):
    piece(session)
    review(session, "blog", "r1", ("cut time by 80%", "F-002"))
    edges.sync(session)
    first = sorted(session.scalars(select(Edge.id)))
    edges.sync(session)
    assert sorted(session.scalars(select(Edge.id))) == first


def test_the_graph_runs_fact_to_claim_to_content(session):
    piece(session)
    review(session, "blog", "r1", ("cut time by 80%", "F-002"))
    graph = queries.graph("F-002", session)
    assert {(e["source"], e["target"], e["type"]) for e in graph["edges"]} >= {
        ("r1-c0", "F-002", "CITES"),
        ("blog", "r1-c0", "CONTAINS"),
    }
    labels = {node["id"]: (node["type"], node["label"]) for node in graph["nodes"]}
    assert labels["blog"] == ("Content", "The blog")
    assert labels["r1-c0"] == ("Claim", "cut time by 80%")


def test_an_unknown_root_is_an_empty_graph(session):
    assert queries.graph("nope", session) == {"nodes": [], "edges": []}


def test_a_confirmed_override_becomes_a_precedent(session):
    finding(session, 1)
    finding(session, 2)
    confirm(session, 1)
    found = queries.precedents("f2", session)
    assert [(p.decision_id, p.reviewer, p.reason, p.channel) for p in found] == [
        ("conf1", "Lena", "A direct quote.", "blog")
    ]


@pytest.mark.parametrize(
    "other",
    [
        {"rule": "R-OTHER"},
        {"version": 2},
        {"channel": "linkedin"},
        {"text": "a completely different sentence about something else"},
    ],
)
def test_a_precedent_must_match_rule_version_channel_and_text(session, other):
    finding(session, 1)
    finding(session, 2, **other)
    confirm(session, 1)
    assert queries.precedents("f2", session) == []


def test_an_override_still_pending_is_no_precedent(session):
    finding(session, 1)
    finding(session, 2)
    session.add(
        Decision(
            id="over1", review_id="r", finding_id="f1", actor_id="u2", role="creator",
            action="override", status="override_pending", reason="Why", created_at=NOW,
        )
    )
    session.commit()
    assert queries.precedents("f2", session) == []


def test_a_finding_is_not_its_own_precedent(session):
    finding(session, 1)
    confirm(session, 1)
    assert queries.precedents("f1", session) == []


def test_an_unknown_finding_has_no_precedents(session):
    assert queries.precedents("nope", session) == []
