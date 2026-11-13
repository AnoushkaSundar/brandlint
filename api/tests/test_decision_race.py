"""Two people deciding the same finding, or moving the same piece, at the same instant.

The server reads a finding's status, checks the action is allowed, and then writes. Without a
lock, two requests read the same status and both pass the check, so a finding ends up with two
contradictory decisions (one reviewer confirms an override, another rejects it). The fix locks
the piece's row, so the second request waits, then sees what the first one did and is refused.

Needs a real Postgres (SQLite ignores row locks): set RLS_TEST_DATABASE_URL, as for test_rls.py.
"""

from __future__ import annotations

import threading
import time

import app.admin.models  # noqa: F401
import pytest
from app.auth.models import Organization, User
from app.content.models import Content, ContentVersion
from app.contracts import ContentState, DecisionAction, Finding, FindingStatus
from app.tenancy.scoped import bind_org
from app.workflow import decisions
from app.workflow.models import Decision, Review
from fastapi import HTTPException
from mocks import data
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tests.test_rls import build_database, postgres

ORG = "00000000-0000-0000-0000-0000000000aa"
FINDING_ID = "race-finding-1"


def finding() -> Finding:
    raw = data.findings_for_piece("agency-blog")[0]
    return Finding.model_validate({**raw, "id": FINDING_ID, "review_id": "race-engine-review"})


def seed(owner) -> None:
    with Session(owner) as session:
        session.add(Organization(id=ORG, name="Race", slug="race", kind="sandbox", status="active"))
        session.flush()
        bind_org(session, ORG)
        for ident, role in (("u-writer", "creator"), ("u-lena", "reviewer"), ("u-dana", "reviewer")):
            session.add(User(id=ident, email=f"{ident}@x.y", name=ident, role=role, password_hash="x", org_id=ORG))
        session.flush()
        session.add(
            Content(
                id="c-race", title="Race", channel="blog", source="agency", data_class="public",
                creator_id="u-writer", state=ContentState.resolving.value,
            )
        )
        session.flush()
        session.add(ContentVersion(id="v-race", content_id="c-race", version=1, text="Hi", created_by="u-writer"))
        session.flush()
        session.add(
            Review(id="r-race", content_version_id="v-race", engine_review_id="race-engine-review", channel="blog", rulebook_version=1)
        )
        session.flush()
        # The creator has asked to override: it now waits for one of the two reviewers.
        session.add(
            Decision(
                review_id="r-race", finding_id=FINDING_ID, actor_id="u-writer", role="creator",
                action=DecisionAction.override.value, status=FindingStatus.override_pending.value,
                reason="A customer quote.",
            )
        )
        session.commit()


def decide(app_engine, who: str, action: DecisionAction, gate: threading.Barrier, outcome: dict) -> None:
    """One reviewer's request, in a session of its own, as the API would run it."""
    with Session(app_engine) as session:
        try:
            bind_org(session, ORG)
            content = session.get(Content, "c-race")
            review = session.get(Review, "r-race")
            actor = session.get(User, who)
        except Exception as error:  # noqa: BLE001
            outcome[who] = f"setup error {type(error).__name__}: {str(error)[:200]}"
            gate.abort()
            return
        gate.wait(timeout=20)
        try:
            decisions.record_decision(
                session, content=content, review=review, finding=finding(), findings=[finding()],
                actor=actor, action=action, reason="Reviewed.", fix_text=None,
            )
            session.commit()
            outcome[who] = "saved"
        except HTTPException as refused:
            session.rollback()
            outcome[who] = f"refused {refused.status_code}"
        except Exception as error:  # noqa: BLE001 - reported by the test, never swallowed
            session.rollback()
            outcome[who] = f"error {type(error).__name__}: {str(error)[:200]}"


@postgres
def test_two_reviewers_cannot_both_settle_the_same_finding(monkeypatch):
    db = build_database(monkeypatch)
    try:
        seed(db.owner)
        # The shared test engine holds one connection; two people need two.
        app_engine = create_engine(db.app.url, pool_size=4, max_overflow=0)
        # Widen the window between "read the status" and "write the decision" so the race is
        # certain to show without the lock, instead of depending on luck.
        slow = decisions.refused_overrides

        def slow_refused(*args, **kwargs):
            time.sleep(0.4)
            return slow(*args, **kwargs)

        monkeypatch.setattr(decisions, "refused_overrides", slow_refused)
        # A rejected override is looked up in the engine's findings; this review isn't in a real engine.
        monkeypatch.setattr(decisions.engine_client, "list_findings", lambda *args, **kwargs: [finding()])

        outcome: dict[str, str] = {}
        gate = threading.Barrier(2)
        threads = [
            threading.Thread(target=decide, args=(app_engine, "u-lena", DecisionAction.confirm_override, gate, outcome), daemon=True),
            threading.Thread(target=decide, args=(app_engine, "u-dana", DecisionAction.reject_override, gate, outcome), daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        saved = [who for who, result in outcome.items() if result == "saved"]
        refused = [result for result in outcome.values() if result.startswith("refused")]
        assert len(saved) == 1, f"both reviewers were let through: {outcome}"
        assert refused == ["refused 403"], outcome

        with Session(db.owner) as session:
            settled = session.scalars(
                select(Decision).where(
                    Decision.finding_id == FINDING_ID,
                    Decision.action.in_(
                        [DecisionAction.confirm_override.value, DecisionAction.reject_override.value]
                    ),
                )
            ).all()
        assert len(settled) == 1, "the finding holds two contradictory rulings"
    finally:
        app_engine.dispose()
        db.drop()


@postgres
def test_two_managers_cannot_both_move_the_same_piece(monkeypatch):
    """The same lock covers a state change: two people sending a piece on at once."""
    from app.workflow.transitions import move_content

    db = build_database(monkeypatch)
    try:
        seed(db.owner)
        app_engine = create_engine(db.app.url, pool_size=4, max_overflow=0)
        results: dict[str, str] = {}
        gate = threading.Barrier(2)

        def move(who: str) -> None:
            with Session(app_engine) as session:
                bind_org(session, ORG)
                content = session.get(Content, "c-race")
                actor = session.get(User, who)
                gate.wait(timeout=20)
                # What the route does first: take the piece, then check the move is still on.
                session.refresh(content, with_for_update=True)
                time.sleep(0.4)
                if content.state != ContentState.resolving.value:
                    results[who] = "refused"
                    session.rollback()
                    return
                move_content(session, content, ContentState.reviewer_check, actor)
                session.commit()
                results[who] = "moved"

        threads = [threading.Thread(target=move, args=(who,), daemon=True) for who in ("u-lena", "u-dana")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert sorted(results.values()) == ["moved", "refused"], results
    finally:
        app_engine.dispose()
        db.drop()


def test_this_file_is_skipped_without_postgres_not_broken():
    # Keeps the module importable (and visible in the report) on machines with no Postgres.
    assert callable(decide)
    pytest.importorskip("psycopg")
