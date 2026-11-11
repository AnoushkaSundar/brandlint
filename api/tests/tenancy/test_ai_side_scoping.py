"""Block 4: the engine, memory, gateway and governance never mix orgs.

The route test shows org B can't reach org A's rows. These cover what it can't see: the
verdict cache, the graph's edges, the precedents, the masking deny-list, the eval set,
and a review that runs in the background.
"""

from __future__ import annotations

import json

from app import db
from app.admin import models as admin
from app.contracts import ContentSource, Proposal
from app.engine import models as engine
from app.engine import reviews
from app.engine.cache import VerdictCache
from app.engine.evaluation import gate
from app.gateway import masking
from app.memory.models import Edge
from app.tenancy import bind_org, org_sessions
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def bound(org_id: str) -> Session:
    session = db.get_sessionmaker()()
    bind_org(session, org_id)
    return session


# The verdict cache


def put(cache: VerdictCache, key: str, note: str) -> None:
    cache.put(
        key, unit_type="chunk", verdict="VIOLATION", payload={"note": note}, manifest={}
    )


def test_the_same_chunk_text_in_two_orgs_gives_two_cache_rows(world, database):
    key = "the-same-key-for-the-same-text"
    cache_a = VerdictCache(org_sessions(db.get_sessionmaker(), world.a.org.id))
    cache_b = VerdictCache(org_sessions(db.get_sessionmaker(), world.b.org.id))

    put(cache_a, key, "A")
    put(cache_b, key, "B")

    with database.connect() as connection:
        rows = connection.scalar(
            select(func.count())
            .select_from(engine.ReviewCache.__table__)
            .where(engine.ReviewCache.payload.in_([{"note": "A"}, {"note": "B"}]))
        )
    assert rows == 2


def test_a_cache_hit_never_comes_from_another_org(world):
    key = "a-key"
    cache_a = VerdictCache(org_sessions(db.get_sessionmaker(), world.a.org.id))
    cache_b = VerdictCache(org_sessions(db.get_sessionmaker(), world.b.org.id))
    put(cache_a, key, "A")

    assert cache_b.get(key, {}) is None
    assert cache_a.get(key, {}) == {"note": "A"}


def test_each_org_reads_its_own_answer_for_the_same_key(world):
    key = "a-key"
    cache_a = VerdictCache(org_sessions(db.get_sessionmaker(), world.a.org.id))
    cache_b = VerdictCache(org_sessions(db.get_sessionmaker(), world.b.org.id))
    put(cache_a, key, "A")
    put(cache_b, key, "B")

    assert cache_a.get(key, {}) == {"note": "A"}
    assert cache_b.get(key, {}) == {"note": "B"}


# Precedents


def test_precedents_come_only_from_the_callers_own_org(world, client_for):
    """Both orgs have the same rule, channel and almost the same text, so mixing would show."""
    for org in (world.a, world.b):
        response = client_for(org.admin).get(
            "/memory/precedents", params={"finding_id": org.ids["finding_id"]}
        )
        reasons = [p["reason"] for p in response.json()]

        assert len(reasons) == 1
        assert org.marker in reasons[0]
        other = world.b if org is world.a else world.a
        assert other.marker not in json.dumps(response.json())


# The graph


def edges_of(database, org_id: str) -> set[tuple[str, str]]:
    with Session(database) as session:
        rows = session.execute(
            select(Edge.__table__.c.id, Edge.__table__.c.type).where(
                Edge.__table__.c.org_id == org_id
            )
        )
        return {(row.id, row.type) for row in rows}


def test_a_sync_for_one_org_does_not_touch_the_others_edges(
    world, client_for, database
):
    client_for(world.a.admin).get(
        "/memory/graph", params={"root": world.a.ids["fact_id"]}
    )
    a_before = edges_of(database, world.a.org.id)
    assert a_before

    client_for(world.b.admin).get(
        "/memory/graph", params={"root": world.b.ids["fact_id"]}
    )

    assert edges_of(database, world.a.org.id) == a_before
    assert edges_of(database, world.b.org.id)


def test_org_b_cannot_trigger_a_sync_of_org_as_edges(world, client_for, database):
    """Org A's content has never been synced. B asking for the graph must not sync it."""
    before = edges_of(database, world.a.org.id)

    client_for(world.b.admin).get(
        "/memory/graph", params={"root": world.a.ids["fact_id"]}
    )
    client_for(world.b.admin).get(
        "/memory/impact", params={"fact_id": world.a.ids["fact_id"]}
    )

    assert edges_of(database, world.a.org.id) == before


def test_edges_carry_their_orgs_id_and_the_same_edge_can_exist_in_both(
    world, client_for, database
):
    """Two orgs can hold a fact with the same id, and so the same edge."""
    for org in (world.a, world.b):
        with Session(database) as session:
            session.add(
                admin.Fact(
                    org_id=org.org.id,
                    id="F-SHARED",
                    version=1,
                    statement="s",
                    value="v",
                    source_doc="Shared study",
                    owner="o",
                    valid_until=None,
                    data_class="public",
                )
            )
            session.commit()
        client_for(org.admin).get("/memory/graph", params={"root": "F-SHARED"})

    shared_a = {e for e in edges_of(database, world.a.org.id) if e[1] == "SUPPORTED_BY"}
    shared_b = {e for e in edges_of(database, world.b.org.id) if e[1] == "SUPPORTED_BY"}
    assert shared_a & shared_b


# Masking


def test_the_deny_list_holds_only_the_orgs_own_protected_values(world, database):
    for org, value in ((world.a, "Bluewren-A"), (world.b, "Redstart-B")):
        with Session(database) as session:
            session.add(
                admin.Fact(
                    org_id=org.org.id,
                    id="F-SECRET",
                    version=1,
                    statement="s",
                    value=value,
                    source_doc="d",
                    owner="o",
                    valid_until=None,
                    data_class="confidential",
                )
            )
            session.commit()
    masking._deny_cache.clear()

    deny_a = masking.deny_list(database, world.a.org.id)
    deny_b = masking.deny_list(database, world.b.org.id)

    assert "Bluewren-A" in deny_a.terms and "Redstart-B" not in deny_a.terms
    assert "Redstart-B" in deny_b.terms and "Bluewren-A" not in deny_b.terms


def test_tokens_are_allocated_for_the_org_that_asked(world, database, monkeypatch):
    from app.contracts import DataClass
    from app.gateway.models import TokenVault

    monkeypatch.setattr(
        masking,
        "deny_list",
        lambda bind, org_id: masking.DenyList(("Bluewren",), frozenset()),
    )

    masked = masking.mask_messages(
        [{"role": "user", "content": "Meet Bluewren"}],
        data_class=DataClass.public,
        scope="rev-x",
        bind=database,
        org_id=world.a.org.id,
    )

    assert masked.messages[0]["content"] == "Meet [PRODUCT_1]"
    with database.connect() as connection:
        rows = connection.execute(
            select(TokenVault.__table__.c.org_id, TokenVault.__table__.c.token).where(
                TokenVault.__table__.c.scope == "rev-x"
            )
        ).all()
    assert [(str(row.org_id), row.token) for row in rows] == [
        (world.a.org.id, "[PRODUCT_1]")
    ]


# Governance


def test_each_org_has_its_own_proposals_and_spot_checks(world, client_for):
    for org, other in ((world.a, world.b), (world.b, world.a)):
        proposals = client_for(org.admin).get("/governance/proposals").json()
        spots = client_for(org.reviewer).get("/governance/spot-checks").json()

        assert [p["id"] for p in proposals] == [f"p-{org.tag}-1"]
        assert [s["content_id"] for s in spots] == [f"c-{org.tag}-2"]
        assert other.marker not in json.dumps([proposals, spots])


def test_another_orgs_proposal_cannot_be_decided(world, client_for, database):
    response = client_for(world.b.admin).post(
        f"/governance/proposals/p-{world.a.tag}-1", json={"status": "approved"}
    )

    assert response.status_code == 404
    with Session(database) as session:
        from app.governance.models import Proposal as ProposalRow

        assert session.get(ProposalRow, f"p-{world.a.tag}-1").status == "pending"


def proposal_for(rule_id: str) -> Proposal:
    return Proposal(
        id="p",
        rule_id=rule_id,
        kind="amendment",
        current="a",
        suggested="b",
        evidence={"count": 3, "examples": []},
        status="pending",
    )


def test_the_demo_eval_set_is_used_only_for_the_demo_org(world, monkeypatch):
    from app.auth.orgs import DEMO_ORG_ID

    calls = []
    monkeypatch.setattr(
        "app.engine.evaluation.load_examples",
        lambda rule_id: calls.append(rule_id) or [],
    )
    rule = __import__("app.contracts", fromlist=["Rule"]).Rule(
        id="R-X",
        version=1,
        type="judgment",
        text="t",
        clause_ref="c",
        severity="low",
        channel_scope=[],
        status="approved",
    )

    with bound(world.a.org.id) as session:
        result = gate(proposal_for("R-X"), rule, session, lambda *a, **k: {}, model="m")

    assert result["passed"] is False
    assert calls == [], "a sandbox org must not read the demo's labelled examples"
    with bound(DEMO_ORG_ID) as session:
        gate(proposal_for("R-X"), rule, session, lambda *a, **k: {}, model="m")
    assert calls == ["R-X"]


# A review that runs in the background


def test_everything_a_background_review_saves_belongs_to_its_org(world, database):
    from app.contracts import Rule
    from app.engine.agents.language import _WORD
    from app.engine.brand import BrandData

    def model(data_class, rule_ids, payload, review_id):
        prompt = payload["messages"][-1]["content"]
        text = prompt.split("\n")[-2]
        words = _WORD.findall(text)
        first = "What is the first word" in prompt
        return {
            "control_answer": words[0] if first else words[-1],
            "verdicts": [
                {
                    "rule_id": rule_ids[0],
                    "verdict": "VIOLATION",
                    "span": text,
                    "confidence": 0.8,
                    "explanation": "Too pushy.",
                }
            ],
        }

    rule = Rule(
        id="R-TONE-02",
        version=1,
        type="judgment",
        text="Stay calm.",
        clause_ref="§2.2",
        severity="medium",
        channel_scope=[],
        status="approved",
    )
    review_id = reviews.start_review(
        "cv-bg",
        "blog",
        1,
        ContentSource(data_class="public", text="You must act now!"),
        classify=model,
        brand_loader=lambda version: BrandData(rules=[rule], facts=[], terms=[]),
        org_id=world.a.org.id,
    )
    assert reviews.get_run(review_id).finished.wait(20)

    def orgs(table, *conditions):
        with database.connect() as connection:
            rows = connection.execute(select(table.c.org_id).where(*conditions)).all()
        return {str(row.org_id) for row in rows}

    chunks, findings, cache = (
        engine.Chunk.__table__,
        engine.Finding.__table__,
        engine.ReviewCache.__table__,
    )
    assert orgs(findings, findings.c.review_id == review_id) == {world.a.org.id}
    assert orgs(chunks, chunks.c.content_version_id == "cv-bg") == {world.a.org.id}
    # The world's own cache rows are there too, so look at the ones the review wrote.
    assert world.a.org.id in orgs(
        cache, cache.c.cache_key != f"cache-key-{world.a.tag}"
    )


def test_a_finished_reviews_findings_are_read_back_only_by_its_org(world, client_for):
    review_id = world.a.ids["review_id"]

    mine = client_for(world.a.admin).get(f"/engine/reviews/{review_id}/findings")
    theirs = client_for(world.b.admin).get(f"/engine/reviews/{review_id}/findings")

    assert mine.status_code == 200
    assert theirs.status_code == 404
