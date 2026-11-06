"""Real review entry point and findings stream, with a fake model."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest

pytest.importorskip("langgraph")

from app.admin import models as admin_models
from app.admin.seed import seed_brand
from app.auth.dependencies import current_user
from app.clients import engine as engine_client
from app.contracts import ContentSource, Gap, Rule, Term
from app.db import Base, get_session
from app.engine import graph as review_graph
from app.engine import models, reviews
from app.engine import router as engine_router
from app.engine.agents import language
from app.engine.brand import BrandData, load_brand
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

TONE = Rule(
    id="R-TONE-02", version=1, type="judgment", text="Stay calm.",
    clause_ref="§2.2", severity="medium", channel_scope=[], status="approved",
)
TERM_RULE = Rule(
    id="R-TERM-03", version=1, type="deterministic", text="Say new hire.",
    clause_ref="§3.3", severity="low", channel_scope=[], status="approved",
)
TERM = Term(id="T1", preferred="new hire", banned=["newbie"], rule_id=TERM_RULE.id)
BRAND = BrandData(rules=[TONE, TERM_RULE], facts=[], terms=[TERM])
TIMEOUT_S = 10


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine, tables=[models.Chunk.__table__, models.Finding.__table__]
    )
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def flagging_model(data_class, rule_ids, payload, review_id):
    prompt = payload["messages"][-1]["content"]
    text = prompt.split("\n")[-2]
    words = language._WORD.findall(text)
    first = "What is the first word" in prompt
    return {
        "control_answer": words[0] if first else words[-1],
        "verdicts": [
            {
                "rule_id": rule_ids[0], "verdict": "VIOLATION", "span": text,
                "confidence": 0.8, "explanation": "Too pushy.",
            }
        ],
    }


def start(session_factory, source=None, classify=flagging_model, brand=None):
    return reviews.start_review(
        "cv1", "blog", 1,
        source or ContentSource(data_class="public", text="The newbie must act now"),
        classify=classify,
        session_factory=session_factory,
        brand_loader=brand or (lambda version: BRAND),
    )


def finished_run(review_id):
    run = reviews.get_run(review_id)
    assert run.finished.wait(TIMEOUT_S)
    return run


def names(run):
    return [name for name, _ in run.events]


def test_tier0_comes_first_then_ai_then_done(session_factory):
    run = finished_run(start(session_factory))
    assert names(run) == ["finding", "finding", "done"]
    assert [payload["tier"] for _, payload in run.events[:2]] == [0, 1]
    assert run.events[-1][1] == {"count": 2}


def test_tier0_goes_first_even_when_the_model_is_faster(
    session_factory, monkeypatch
):
    model_done = threading.Event()

    def instant_model(*args):
        reply = flagging_model(*args)
        model_done.set()
        return reply

    real_run_tier0 = review_graph.run_tier0

    def slow_tier0(*args):
        assert model_done.wait(TIMEOUT_S)
        time.sleep(0.2)  # Let the language track report first.
        return real_run_tier0(*args)

    monkeypatch.setattr(review_graph, "run_tier0", slow_tier0)
    run = finished_run(start(session_factory, classify=instant_model))
    assert [payload["tier"] for name, payload in run.events if name == "finding"] == [
        0, 1,
    ]


def test_code_findings_arrive_while_the_model_is_still_working(session_factory):
    release = threading.Event()

    def slow_model(*args):
        assert release.wait(TIMEOUT_S)
        return flagging_model(*args)

    review_id = start(session_factory, classify=slow_model)
    run = reviews.get_run(review_id)
    deadline = threading.Event()
    for _ in range(100):
        if run.events:
            break
        deadline.wait(0.05)
    assert [payload["tier"] for _, payload in run.events] == [0]
    assert not run.finished.is_set()
    release.set()
    finished_run(review_id)


def test_results_and_chunks_are_saved(session_factory):
    review_id = start(session_factory)
    finished_run(review_id)
    with session_factory() as session:
        assert session.query(models.Finding).count() == 2
        assert session.query(models.Chunk).count() == 1
    assert reviews.get_run(review_id).chunks[0].data_class == "public"


def test_data_class_reaches_the_chunks_and_the_gateway(session_factory):
    seen = []

    def spy(data_class, rule_ids, payload, review_id):
        seen.append(data_class)
        return flagging_model(data_class, rule_ids, payload, review_id)

    source = ContentSource(data_class="confidential", text="Plain words here")
    finished_run(start(session_factory, source, classify=spy))
    assert seen == ["confidential"]


def test_unsupported_file_ends_with_an_error_not_an_empty_pass(session_factory):
    source = ContentSource(
        data_class="public", file_name="clip.mp4", file_bytes=b"data"
    )
    run = finished_run(start(session_factory, source))
    assert names(run) == ["error"]
    assert "unsupported" not in run.events[0][1]["message"]


def test_brand_failure_ends_with_an_error(session_factory):
    def broken(version):
        raise OSError("disk")

    run = finished_run(start(session_factory, brand=broken))
    assert names(run) == ["error"]


def test_model_outage_still_finishes_with_unsure_findings(session_factory):
    def down(*args):
        raise TimeoutError

    run = finished_run(start(session_factory, classify=down))
    assert names(run)[-1] == "done"
    assert [payload["verdict"] for _, payload in run.events[:2]] == [
        "VIOLATION", "UNSURE",
    ]


@pytest.mark.parametrize(
    ("name", "parser", "check"),
    [
        ("post.TXT", "txt", "text"),
        ("post.md", "md", "text"),
        ("post.htm", "htm", "html"),
        ("post.docx", "docx", "docx"),
        ("post.pdf", "pdf", "pdf"),
        ("banner.png", "png", "image"),
    ],
)
def test_formats_follow_the_file_name(name, parser, check):
    source = ContentSource(data_class="public", file_name=name, file_bytes=b"x")
    assert reviews.formats(source) == (b"x", parser, check)


def test_pasted_text_is_text():
    source = ContentSource(data_class="public", text="Hello")
    assert reviews.formats(source) == ("Hello", "text", "text")


@pytest.fixture()
def seeded(session_factory):
    engine = session_factory.kw["bind"]
    Base.metadata.create_all(
        engine,
        tables=[
            admin_models.Rule.__table__,
            admin_models.Fact.__table__,
            admin_models.Term.__table__,
            admin_models.Asset.__table__,
            admin_models.Gap.__table__,
        ],
    )
    with session_factory() as session:
        seed_brand(session)
    return session_factory


def test_brand_comes_from_the_admin_functions(seeded):
    with seeded() as session:
        brand = load_brand(session, 1)
    ids = {rule.id for rule in brand.rules}
    assert "R-TERM-04" not in ids  # A draft in the demo rulebook.
    assert "R-TONE-01" in ids
    assert brand.facts and brand.terms


def test_a_real_review_finds_the_planted_term_and_disclaimer(seeded):
    source = ContentSource(data_class="public", text="Tarnhollow Onramp is here.")
    review_id = reviews.start_review(
        "cv1", "linkedin", 1, source, classify=flagging_model, session_factory=seeded,
    )
    run = finished_run(review_id)
    assert names(run)[-1] == "done"
    rules = {payload["rule_id"] for name, payload in run.events if name == "finding"}
    assert {"R-TERM-02", "R-REQ-01"} <= rules


def test_an_empty_rulebook_fails_instead_of_passing(session_factory):
    Base.metadata.create_all(
        session_factory.kw["bind"],
        tables=[
            admin_models.Rule.__table__,
            admin_models.Fact.__table__,
            admin_models.Term.__table__,
        ],
    )
    review_id = reviews.start_review(
        "cv1", "blog", 1, ContentSource(data_class="public", text="Hello"),
        classify=flagging_model, session_factory=session_factory,
    )
    assert names(finished_run(review_id)) == ["error"]


def test_gaps_reach_the_gap_log_once(seeded):
    gap = Gap(
        id="gap:1", review_id="rev", check="tone", text="t", explanation="e",
        created_at=datetime(2026, 11, 6, tzinfo=UTC),
    )
    sink = reviews._gap_log(seeded)
    sink([gap])
    sink([gap])
    with seeded() as session:
        assert session.query(admin_models.Gap).count() == 1


def test_status_follows_a_review_to_done(session_factory):
    release = threading.Event()

    def slow_model(*args):
        assert release.wait(TIMEOUT_S)
        return flagging_model(*args)

    review_id = start(session_factory, classify=slow_model)
    with session_factory() as session:
        assert reviews.review_status(review_id, session) == "running"
        release.set()
        finished_run(review_id)
        assert reviews.review_status(review_id, session) == "done"


def test_status_reports_a_failed_review(session_factory):
    source = ContentSource(
        data_class="public", file_name="clip.mp4", file_bytes=b"data"
    )
    review_id = start(session_factory, source)
    finished_run(review_id)
    with session_factory() as session:
        assert reviews.review_status(review_id, session) == "failed"


def test_status_after_a_restart(session_factory):
    review_id = start(session_factory)
    finished_run(review_id)
    reviews._runs.pop(review_id)
    with session_factory() as session:
        assert reviews.review_status(review_id, session) == "done"
        assert reviews.review_status("rev-lost", session) == "unknown"


def test_the_client_reports_mock_reviews_as_done(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "true")
    assert engine_client.review_status("rev-demo-banner", None) == "done"


def client_for(session_factory, monkeypatch, *, signed_in=True) -> TestClient:
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    app = FastAPI()
    app.include_router(engine_router.build_router())

    def session_override():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    if signed_in:
        app.dependency_overrides[current_user] = lambda: object()
    return TestClient(app)


def test_stream_sends_named_events_in_order(session_factory, monkeypatch):
    client = client_for(session_factory, monkeypatch)
    review_id = start(session_factory)
    response = client.get(f"/engine/reviews/{review_id}/findings")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        line.removeprefix("event: ")
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]
    assert events == ["finding", "finding", "done"]


def test_stream_ends_on_error(session_factory, monkeypatch):
    client = client_for(session_factory, monkeypatch)
    source = ContentSource(
        data_class="public", file_name="clip.mp4", file_bytes=b"data"
    )
    review_id = start(session_factory, source)
    response = client.get(f"/engine/reviews/{review_id}/findings")
    assert "event: error" in response.text
    assert "event: done" not in response.text


def test_chunks_route_serves_the_contract_shape(session_factory, monkeypatch):
    client = client_for(session_factory, monkeypatch)
    review_id = start(session_factory)
    body = client.get(f"/engine/reviews/{review_id}/chunks").json()
    assert [chunk["ordinal"] for chunk in body] == [0]
    assert body[0]["id"] == "cv1:0"
    assert body[0]["data_class"] == "public"


def test_a_finished_review_survives_a_restart(session_factory, monkeypatch):
    client = client_for(session_factory, monkeypatch)
    review_id = start(session_factory)
    finished_run(review_id)
    live = client.get(f"/engine/reviews/{review_id}/findings").text
    reviews._runs.pop(review_id)
    restored = client.get(f"/engine/reviews/{review_id}/findings").text
    assert restored.count("event: finding") == live.count("event: finding") == 2
    assert "event: done" in restored


def test_unknown_review_is_404(session_factory, monkeypatch):
    client = client_for(session_factory, monkeypatch)
    assert client.get("/engine/reviews/nope/findings").status_code == 404
    assert client.get("/engine/reviews/nope/chunks").status_code == 404


def test_routes_need_a_signed_in_user(session_factory, monkeypatch):
    client = client_for(session_factory, monkeypatch, signed_in=False)
    assert client.get("/engine/reviews/nope/findings").status_code == 401


def test_real_routes_stand_down_while_the_mock_is_on(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "true")
    paths = {route.path for route in engine_router.build_router().routes}
    assert paths == {"/engine/health"}


def test_client_ignores_source_on_the_mock(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "true")
    assert engine_client.start_review("cv", "blog", 1).startswith("rev-demo-")


def test_client_refuses_a_real_review_with_no_content(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    with pytest.raises(NotImplementedError, match="content"):
        engine_client.start_review("cv", "blog", 1)


def test_client_hands_content_to_the_engine(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    calls = []

    def fake_start(*args):
        calls.append(args)
        return "rev-1"

    monkeypatch.setattr(reviews, "start_review", fake_start)
    source = ContentSource(data_class="public", text="Hi")
    assert engine_client.start_review("cv", "blog", 3, source) == "rev-1"
    assert calls == [("cv", "blog", 3, source)]


def test_findings_and_chunks_reach_the_workflow(session_factory):
    review_id = start(session_factory)
    finished_run(review_id)
    with session_factory() as session:
        findings = reviews.list_findings(review_id, session)
        chunks = reviews.list_chunks(review_id, session)
    assert [f.tier for f in findings] == [0, 1]
    assert [c.id for c in chunks] == ["cv1:0"]


def test_findings_and_chunks_survive_a_restart(session_factory):
    review_id = start(session_factory)
    finished_run(review_id)
    reviews._runs.pop(review_id)
    with session_factory() as session:
        assert len(reviews.list_findings(review_id, session)) == 2
        assert [c.id for c in reviews.list_chunks(review_id, session)] == ["cv1:0"]


def test_an_unknown_review_has_no_findings_and_an_unknown_status(session_factory):
    with session_factory() as session:
        assert reviews.list_findings("rev-lost", session) == []
        assert reviews.list_chunks("rev-lost", session) == []
        assert reviews.review_status("rev-lost", session) == "unknown"


def test_the_client_reads_findings_from_the_real_engine(session_factory, monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    monkeypatch.setattr(engine_client, "get_sessionmaker", lambda: session_factory)
    review_id = start(session_factory)
    finished_run(review_id)
    assert len(engine_client.list_findings(review_id)) == 2
    assert len(engine_client.list_chunks(review_id)) == 1
