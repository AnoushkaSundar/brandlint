"""Overrides and the state machine, called directly on the API.

These are the rules the demo promises, so each one is tested against the server: the
UI hiding a button proves nothing.
"""

import app.admin.models  # noqa: F401
import pytest
from app.auth.models import User
from app.auth.router import router as auth_router
from app.auth.security import SESSION_COOKIE, create_token, hash_password
from app.content.models import Content, ContentVersion
from app.content.router import router as content_router
from app.contracts import Chunk, Finding, FindingStatus, FixSuggestion, Role, Span
from app.db import Base, get_session
from app.workflow.decisions import FindingProgress
from app.workflow.fixes import FixCannotApply, FixesOverlap, text_with_fixes
from app.workflow.models import AuditLog, Decision, ReviewStateLog
from app.workflow.router import router as workflow_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mocks import data
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

HIGH_FIX = "fnd-agency-blog-01"
MEDIUM_FIX = "fnd-agency-blog-02"
LOW_FIX = "fnd-agency-blog-03"
CRITICAL = "fnd-agency-blog-04"
HIGH_CLAIM = "fnd-agency-blog-05"
HIGH_CLAIM_FIX = "fnd-agency-blog-06"
UNSURE = "fnd-agency-blog-07"
ALL_FINDINGS = [
    HIGH_FIX,
    MEDIUM_FIX,
    LOW_FIX,
    CRITICAL,
    HIGH_CLAIM,
    HIGH_CLAIM_FIX,
    UNSURE,
]
FORM = {
    "title": "First week guide",
    "channel": "blog",
    "source": "in-house",
    "data_class": "public",
    "text": "Hello there",
}


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    monkeypatch.setenv("JWT_SECRET", "a-test-only-secret-that-is-long-enough-for-hs256")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.delenv("USE_MOCK_ENGINE", raising=False)


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as db:
        yield db


@pytest.fixture
def client_for(session):
    api = FastAPI()
    api.include_router(auth_router)
    api.include_router(content_router)
    api.include_router(workflow_router)
    api.dependency_overrides[get_session] = lambda: session
    made = {}

    def make(role=Role.creator, name="sam"):
        key = (role, name)
        if key not in made:
            user = User(
                email=f"{name}-{role.value}@example.com",
                name=name,
                role=role.value,
                password_hash=hash_password("not-used"),
            )
            session.add(user)
            session.commit()
            client = TestClient(api)
            client.cookies.set(SESSION_COOKIE, create_token(user))
            made[key] = client
        return made[key]

    return make


@pytest.fixture
def no_findings(monkeypatch):
    monkeypatch.setattr("app.clients.engine.list_findings", lambda review_id: [])


def started(client):
    content_id = client.post("/content", data=FORM).json()["id"]
    assert client.post(f"/content/{content_id}/reviews").status_code == 201
    return content_id


def move(client, content_id, to, reason=None):
    return client.post(
        f"/workflow/content/{content_id}/transitions",
        json={"to": to, "reason": reason},
    )


def resolving(client):
    content_id = started(client)
    assert move(client, content_id, "resolving").status_code == 200
    return content_id


def decide(
    client, content_id, finding_id, action, reason=None, fix_text=None, attempt=None
):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/decisions",
        json={
            "action": action,
            "reason": reason,
            "fix_text": fix_text,
            "attempt": attempt,
        },
    )


def offer(client, content_id, finding_id, again=False):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/fix",
        json={"again": again},
    )


def accept(client, content_id, finding_id):
    made = offer(client, content_id, finding_id)
    assert made.status_code == 200
    return decide(
        client, content_id, finding_id, "accept_fix", attempt=made.json()["attempt"]
    )


def board(client, content_id):
    return client.get(f"/workflow/content/{content_id}/board").json()


def standing(client, content_id, finding_id):
    return next(
        item
        for item in board(client, content_id)["findings"]
        if item["id"] == finding_id
    )


def clear_everything(creator, reviewer, content_id):
    """Takes the demo blog to the point where it can leave `resolving`."""
    for finding_id in (HIGH_FIX, MEDIUM_FIX, LOW_FIX, HIGH_CLAIM_FIX):
        assert accept(creator, content_id, finding_id).status_code == 201
    for finding_id in (CRITICAL, HIGH_CLAIM):
        assert (
            decide(reviewer, content_id, finding_id, "override", "Approved copy").status_code
            == 201
        )
    assert decide(reviewer, content_id, UNSURE, "resolve", "This is fine").status_code == 201
    # A claim fix rewrites one of its two spans, so a reviewer has to agree to it.
    assert (
        decide(reviewer, content_id, HIGH_CLAIM_FIX, "resolve", "Reads fine").status_code
        == 201
    )


# Overrides


@pytest.mark.parametrize("finding_id", [MEDIUM_FIX, LOW_FIX])
def test_a_creator_override_on_low_or_medium_waits_for_a_reviewer(client_for, finding_id):
    creator = client_for()
    content_id = resolving(creator)

    response = decide(creator, content_id, finding_id, "override", "It's a quote")

    assert response.status_code == 201
    assert standing(creator, content_id, finding_id)["status"] == "override_pending"


@pytest.mark.parametrize("finding_id", [HIGH_FIX, HIGH_CLAIM, CRITICAL])
def test_a_creator_cannot_override_high_or_critical(client_for, session, finding_id):
    creator = client_for()
    content_id = resolving(creator)

    response = decide(creator, content_id, finding_id, "override", "Please let me")

    assert response.status_code == 403
    assert session.scalars(select(Decision)).first() is None
    assert standing(creator, content_id, finding_id)["status"] == "open"


@pytest.mark.parametrize("finding_id", [HIGH_FIX, HIGH_CLAIM, CRITICAL, LOW_FIX])
def test_a_reviewer_override_takes_effect_at_once(client_for, finding_id):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    response = decide(reviewer, content_id, finding_id, "override", "Reviewed the source")

    assert response.status_code == 201
    assert standing(reviewer, content_id, finding_id)["status"] == "override_confirmed"


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_an_override_needs_a_reason(client_for, session, reason):
    creator = client_for()
    content_id = resolving(creator)

    response = decide(creator, content_id, LOW_FIX, "override", reason)

    assert response.status_code == 422
    assert session.scalars(select(Decision)).first() is None


def test_a_reviewer_confirms_a_pending_override(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    response = decide(reviewer, content_id, LOW_FIX, "confirm_override")

    assert response.status_code == 201
    assert standing(reviewer, content_id, LOW_FIX)["status"] == "override_confirmed"


def test_a_reviewer_rejects_with_a_reason_and_the_creator_must_fix_it(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    assert decide(reviewer, content_id, LOW_FIX, "reject_override").status_code == 422
    assert decide(reviewer, content_id, LOW_FIX, "reject_override", "No").status_code == 201

    found = standing(creator, content_id, LOW_FIX)
    assert found["status"] == "override_rejected"
    assert "override" not in found["allowed"]
    assert decide(creator, content_id, LOW_FIX, "override", "Again").status_code == 403
    assert accept(creator, content_id, LOW_FIX).status_code == 201


@pytest.mark.parametrize("role", [Role.creator, Role.manager, Role.legal, Role.admin])
def test_only_a_reviewer_confirms_an_override(client_for, role):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    response = decide(client_for(role, "other"), content_id, LOW_FIX, "confirm_override")

    # Another creator can't even see this content.
    assert response.status_code == (404 if role is Role.creator else 403)
    assert standing(creator, content_id, LOW_FIX)["status"] == "override_pending"


def test_an_override_with_nothing_pending_cannot_be_confirmed(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    assert decide(reviewer, content_id, LOW_FIX, "confirm_override").status_code == 403


# UNSURE


def test_a_creator_cannot_touch_an_unsure_finding(client_for):
    creator = client_for()
    content_id = resolving(creator)

    assert decide(creator, content_id, UNSURE, "override", "Looks fine").status_code == 403
    assert decide(creator, content_id, UNSURE, "resolve", "Looks fine").status_code == 403
    assert standing(creator, content_id, UNSURE)["allowed"] == []


def test_a_reviewer_resolves_an_unsure_finding_with_a_reason(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    assert decide(reviewer, content_id, UNSURE, "resolve").status_code == 422
    assert decide(reviewer, content_id, UNSURE, "resolve", "This is fine").status_code == 201
    assert standing(reviewer, content_id, UNSURE)["status"] == "resolved"


def test_an_unsure_finding_cannot_be_overridden_instead_of_resolved(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    assert decide(reviewer, content_id, UNSURE, "override", "Skip it").status_code == 403


def test_an_open_unsure_finding_blocks_leaving_resolving(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    for finding_id in (HIGH_FIX, MEDIUM_FIX, LOW_FIX, HIGH_CLAIM_FIX):
        accept(creator, content_id, finding_id)
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, content_id, finding_id, "override", "Approved copy")

    response = move(creator, content_id, "reviewer_check")

    assert response.status_code == 409
    assert response.json()["detail"] == "1 finding still open"


# Fixes


def test_a_fix_must_be_offered_before_it_can_be_accepted(client_for):
    creator = client_for()
    content_id = resolving(creator)

    response = decide(creator, content_id, HIGH_FIX, "accept_fix", fix_text="Anything")

    assert response.status_code == 409
    assert standing(creator, content_id, HIGH_FIX)["status"] == "open"


def test_accepting_uses_the_engines_wording_and_ignores_the_request(client_for):
    creator = client_for()
    content_id = resolving(creator)
    offer(creator, content_id, HIGH_FIX)

    decide(
        creator, content_id, HIGH_FIX, "accept_fix", fix_text="Tarnhollow Onramp", attempt=1
    )

    assert standing(creator, content_id, HIGH_FIX)["fix_text"] == "Tarnhollow Landing"


def test_a_fix_cannot_be_accepted_where_none_is_available(client_for):
    creator = client_for()
    content_id = resolving(creator)

    assert offer(creator, content_id, CRITICAL).status_code == 403
    response = decide(creator, content_id, CRITICAL, "accept_fix", fix_text="Anything")

    assert response.status_code == 403


def test_a_fix_cannot_be_accepted_twice(client_for):
    creator = client_for()
    content_id = resolving(creator)
    accept(creator, content_id, HIGH_FIX)

    assert decide(creator, content_id, HIGH_FIX, "accept_fix").status_code == 403


def test_only_the_creator_can_ask_for_a_fix(client_for):
    creator = client_for()
    content_id = resolving(creator)

    response = offer(client_for(Role.reviewer, "lena"), content_id, HIGH_FIX)

    assert response.status_code == 403


def test_reopening_returns_the_same_offer_and_spends_no_attempt(client_for):
    creator = client_for()
    content_id = resolving(creator)

    first = offer(creator, content_id, HIGH_FIX).json()
    second = offer(creator, content_id, HIGH_FIX).json()

    assert first == second
    assert second["attempt"] == 1


def test_a_second_attempt_is_available_and_a_third_is_refused(client_for):
    creator = client_for()
    content_id = resolving(creator)
    offer(creator, content_id, HIGH_FIX)

    assert offer(creator, content_id, HIGH_FIX, again=True).json()["attempt"] == 2

    third = offer(creator, content_id, HIGH_FIX, again=True)
    assert third.status_code == 422
    assert third.json()["detail"] == "No safe fix found; marked for review"


def test_attempts_are_counted_per_review_not_across_pieces(client_for):
    creator = client_for()
    first = resolving(creator)
    second = resolving(creator)
    offer(creator, first, HIGH_FIX)
    offer(creator, first, HIGH_FIX, again=True)

    assert offer(creator, second, HIGH_FIX).json()["attempt"] == 1


def test_accepting_needs_the_attempt_on_screen(client_for):
    creator = client_for()
    content_id = resolving(creator)
    offer(creator, content_id, HIGH_FIX)
    offer(creator, content_id, HIGH_FIX, again=True)

    stale = decide(creator, content_id, HIGH_FIX, "accept_fix", attempt=1)
    missing = decide(creator, content_id, HIGH_FIX, "accept_fix")

    assert stale.status_code == 409
    assert missing.status_code == 409
    assert standing(creator, content_id, HIGH_FIX)["status"] == "open"
    assert decide(creator, content_id, HIGH_FIX, "accept_fix", attempt=2).status_code == 201


def test_a_fix_on_hidden_text_is_refused_and_stays_open(client_for, monkeypatch):
    creator = client_for()
    content_id = resolving(creator)
    monkeypatch.setattr(
        "app.clients.engine.list_chunks",
        lambda review_id: [
            chunk("blog-p2", 0, "Tarnhollow Onramp is good", "paragraph").model_copy(
                update={"style": {"hidden": True}}
            )
        ],
    )

    response = accept(creator, content_id, HIGH_FIX)

    assert response.status_code == 409
    assert standing(creator, content_id, HIGH_FIX)["status"] == "open"


def test_an_empty_suggestion_counts_as_a_fix_and_reaches_the_text(client_for, monkeypatch):
    creator = client_for()
    content_id = resolving(creator)
    monkeypatch.setattr(
        "app.clients.engine.request_fix",
        lambda finding_id, attempt: FixSuggestion(
            finding_id=finding_id, original="x", suggested="", diff="", attempt=attempt
        ),
    )

    accept(creator, content_id, HIGH_FIX)

    assert standing(creator, content_id, HIGH_FIX)["fix_text"] == ""


def test_a_rejected_fix_does_not_refuse_a_later_override(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "edit_fix", fix_text="still newbies")

    decide(reviewer, content_id, LOW_FIX, "reject_override", "Still the banned word")

    assert "override" in standing(creator, content_id, LOW_FIX)["allowed"]


def test_a_blocked_move_says_why_rather_than_blaming_fixes(client_for, monkeypatch):
    creator = client_for()
    content_id = resolving(creator)

    def explode(*args):
        raise AssertionError("fixes were read before the move was allowed")

    monkeypatch.setattr("app.clients.engine.list_chunks", explode)

    assert move(creator, content_id, "manager_approval").status_code == 403


def test_an_edited_fix_needs_its_text(client_for):
    creator = client_for()
    content_id = resolving(creator)

    assert decide(creator, content_id, HIGH_FIX, "edit_fix").status_code == 422


def test_an_edited_fix_waits_for_a_reviewers_sign_off(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    decide(creator, content_id, HIGH_FIX, "edit_fix", fix_text="Tarnhollow Onramp")

    edited = standing(reviewer, content_id, HIGH_FIX)
    assert edited["status"] == "fix_edited"
    assert edited["fix_text"] == "Tarnhollow Onramp"
    assert edited["allowed"] == ["reject_override", "resolve"]


def test_a_reviewer_can_reject_an_edit_which_reopens_the_finding(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    decide(creator, content_id, HIGH_FIX, "edit_fix", fix_text="Tarnhollow Onramp")

    decide(reviewer, content_id, HIGH_FIX, "reject_override", "Still the old name")

    found = standing(creator, content_id, HIGH_FIX)
    assert found["status"] == "open"
    assert found["fix_text"] is None
    assert "accept_fix" in found["allowed"]


def test_a_signed_off_edit_keeps_its_wording(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    decide(creator, content_id, HIGH_FIX, "edit_fix", fix_text="The Landing app")

    decide(reviewer, content_id, HIGH_FIX, "resolve", "Reads fine")

    found = standing(creator, content_id, HIGH_FIX)
    assert (found["status"], found["fix_text"]) == ("resolved", "The Landing app")


def test_a_fix_for_part_of_a_split_claim_needs_a_reviewer(client_for):
    creator = client_for()
    content_id = resolving(creator)

    accept(creator, content_id, HIGH_CLAIM_FIX)

    assert standing(creator, content_id, HIGH_CLAIM_FIX)["status"] == "fix_edited"


def test_an_unsigned_edit_blocks_the_manager(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    clear_everything(creator, reviewer, content_id)
    second = resolving(creator)
    for finding_id in (MEDIUM_FIX, LOW_FIX, HIGH_CLAIM_FIX):
        accept(creator, second, finding_id)
    decide(creator, second, HIGH_FIX, "edit_fix", fix_text="The Landing app")
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, second, finding_id, "override", "Approved copy")
    decide(reviewer, second, UNSURE, "resolve", "This is fine")
    move(creator, second, "reviewer_check")

    response = move(reviewer, second, "manager_approval")

    assert response.status_code == 409
    assert response.json()["detail"] == "2 decisions waiting for a reviewer"


def overlapping(finding):
    return finding.model_copy(
        update={"spans": [Span(chunk_id="blog-p2", start=0, end=5)]}
    )


def test_overlapping_fixes_are_refused_when_the_second_is_saved(client_for, monkeypatch):
    creator = client_for()
    content_id = resolving(creator)
    findings = [
        Finding.model_validate(item) for item in data.findings_for_piece("agency-blog")
    ]
    monkeypatch.setattr(
        "app.clients.engine.list_findings",
        lambda review_id: [overlapping(item) for item in findings],
    )

    assert accept(creator, content_id, HIGH_FIX).status_code == 201
    response = accept(creator, content_id, MEDIUM_FIX)

    assert response.status_code == 409
    assert "overlaps" in response.json()["detail"]
    assert standing(creator, content_id, MEDIUM_FIX)["status"] == "open"


def test_an_accepted_and_an_edited_fix_keep_their_wording(client_for):
    creator = client_for()
    content_id = resolving(creator)

    accept(creator, content_id, HIGH_FIX)
    decide(creator, content_id, MEDIUM_FIX, "edit_fix", fix_text="trusted by teams")

    accepted = standing(creator, content_id, HIGH_FIX)
    edited = standing(creator, content_id, MEDIUM_FIX)
    assert (accepted["status"], accepted["fix_text"]) == (
        "fix_accepted",
        "Tarnhollow Landing",
    )
    assert (edited["status"], edited["fix_text"]) == ("fix_edited", "trusted by teams")


def test_a_creator_cannot_decide_on_someone_elses_content(client_for):
    creator = client_for()
    content_id = resolving(creator)
    other = client_for(Role.creator, "priya")

    response = decide(other, content_id, HIGH_FIX, "edit_fix", fix_text="Mine")

    assert response.status_code == 404


def test_decisions_on_one_piece_do_not_reach_another(client_for):
    creator = client_for()
    first = resolving(creator)
    second = resolving(creator)

    accept(creator, first, HIGH_FIX)

    assert standing(creator, first, HIGH_FIX)["status"] == "fix_accepted"
    assert standing(creator, second, HIGH_FIX)["status"] == "open"


def test_an_unknown_finding_is_not_found(client_for):
    creator = client_for()
    content_id = resolving(creator)

    assert decide(creator, content_id, "nope", "override", "Why").status_code == 404


def test_decisions_are_refused_before_resolving(client_for):
    creator = client_for()
    content_id = started(creator)

    assert decide(creator, content_id, LOW_FIX, "override", "Early").status_code == 403


def test_every_decision_is_audited_with_the_pinned_rulebook(client_for, session):
    creator = client_for()
    content_id = resolving(creator)

    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    entry = session.scalars(
        select(AuditLog).where(AuditLog.action == "decision:override")
    ).one()
    assert entry.target_type == "finding"
    assert entry.target_id == LOW_FIX
    assert entry.before == {"status": "open"}
    assert entry.after == {"status": "override_pending", "reason": "It's a quote"}
    assert entry.rulebook_version == 1


# The state machine


@pytest.mark.parametrize(
    "target",
    ["draft", "ai_review", "reviewer_check", "manager_approval", "legal_signoff", "published"],
)
def test_ai_review_can_only_move_to_resolving(client_for, target):
    creator = client_for()
    content_id = started(creator)

    assert move(creator, content_id, target).status_code == 403


def test_a_creator_cannot_publish_or_approve(client_for, no_findings):
    creator = client_for()
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")

    assert move(creator, content_id, "manager_approval").status_code == 403
    assert move(creator, content_id, "published").status_code == 403


def run_status(monkeypatch, value):
    monkeypatch.setattr(
        "app.clients.engine.review_status", lambda review_id, session: value
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("running", "The review is still running"),
        ("failed", "The review didn't finish. Start it again."),
        ("unknown", "The review didn't finish. Start it again."),
    ],
)
def test_an_unfinished_run_cannot_leave_ai_review(client_for, monkeypatch, value, message):
    creator = client_for()
    content_id = started(creator)
    run_status(monkeypatch, value)

    response = move(creator, content_id, "resolving")

    assert response.status_code == 409
    assert response.json()["detail"] == message
    assert board(creator, content_id)["state"] == "ai_review"


def test_a_failed_run_can_be_started_again(client_for, monkeypatch):
    creator = client_for()
    content_id = started(creator)
    run_status(monkeypatch, "failed")

    assert creator.post(f"/content/{content_id}/reviews").status_code == 201


def test_a_review_must_cover_the_newest_version(client_for, no_findings):
    creator = client_for()
    content_id = resolving(creator)
    creator.post(f"/content/{content_id}/versions", data={"text": "Newer text"})

    response = move(creator, content_id, "reviewer_check")

    assert response.status_code == 409
    assert response.json()["detail"] == "Review the newest version first"


def test_a_rejected_override_stays_rejected_after_a_new_review(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")
    decide(reviewer, content_id, LOW_FIX, "reject_override", "It isn't")

    creator.post(f"/content/{content_id}/versions", data={"text": "A small change"})
    assert creator.post(f"/content/{content_id}/reviews").status_code == 201
    move(creator, content_id, "resolving")

    assert standing(creator, content_id, LOW_FIX)["status"] == "open"
    assert "override" not in standing(creator, content_id, LOW_FIX)["allowed"]
    assert decide(creator, content_id, LOW_FIX, "override", "Again").status_code == 403


def test_open_findings_block_submission(client_for):
    creator = client_for()
    content_id = resolving(creator)

    response = move(creator, content_id, "reviewer_check")

    assert response.status_code == 409
    assert response.json()["detail"] == "7 findings still open"


def test_a_pending_override_can_reach_the_reviewer_but_not_the_manager(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    second = resolving(creator)
    for finding_id in (HIGH_FIX, HIGH_CLAIM_FIX):
        accept(creator, second, finding_id)
    decide(reviewer, second, HIGH_CLAIM_FIX, "resolve", "Reads fine")
    decide(creator, second, MEDIUM_FIX, "override", "It's a quote")
    decide(creator, second, LOW_FIX, "override", "It's a quote")
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, second, finding_id, "override", "Approved copy")
    decide(reviewer, second, UNSURE, "resolve", "This is fine")

    assert move(creator, second, "reviewer_check").status_code == 200

    response = move(reviewer, second, "manager_approval")
    assert response.status_code == 409
    assert response.json()["detail"] == "2 decisions waiting for a reviewer"

    decide(reviewer, second, MEDIUM_FIX, "confirm_override")
    decide(reviewer, second, LOW_FIX, "confirm_override")
    assert move(reviewer, second, "manager_approval").status_code == 200


def test_a_rejected_override_blocks_submission(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    second = resolving(creator)
    for finding_id in (HIGH_FIX, MEDIUM_FIX, HIGH_CLAIM_FIX):
        accept(creator, second, finding_id)
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, second, finding_id, "override", "Approved copy")
    decide(reviewer, second, UNSURE, "resolve", "This is fine")
    decide(creator, second, LOW_FIX, "override", "It's a quote")
    decide(reviewer, second, LOW_FIX, "reject_override", "It isn't")

    response = move(creator, second, "reviewer_check")

    assert response.status_code == 409
    assert response.json()["detail"] == "1 finding still open"


def test_a_high_severity_claim_must_go_through_legal(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    manager = client_for(Role.manager, "marcus")
    legal = client_for(Role.legal, "aisha")
    content_id = resolving(creator)
    clear_everything(creator, reviewer, content_id)
    move(creator, content_id, "reviewer_check")
    move(reviewer, content_id, "manager_approval")

    assert board(manager, content_id)["legal_required"] is True
    response = move(manager, content_id, "published")
    assert response.status_code == 409
    assert "legal sign-off" in response.json()["detail"]

    assert move(manager, content_id, "legal_signoff").status_code == 200
    assert move(manager, content_id, "published").status_code == 403
    assert move(legal, content_id, "published").status_code == 200
    assert board(legal, content_id)["state"] == "published"


def test_with_no_claim_the_manager_publishes_directly(client_for, no_findings):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    manager = client_for(Role.manager, "marcus")
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")
    move(reviewer, content_id, "manager_approval")

    assert board(manager, content_id)["legal_required"] is False
    assert move(manager, content_id, "legal_signoff").status_code == 409
    assert move(manager, content_id, "published").status_code == 200


def test_a_reviewer_can_send_it_back_with_a_reason(client_for, no_findings):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")

    assert move(reviewer, content_id, "resolving").status_code == 422
    assert move(reviewer, content_id, "resolving", "Reword it").status_code == 200
    assert board(creator, content_id)["state"] == "resolving"


@pytest.mark.parametrize("role", [Role.reviewer, Role.manager])
def test_rejecting_needs_a_reviewer_or_manager_and_a_reason(client_for, role):
    creator = client_for()
    content_id = resolving(creator)
    deciding = client_for(role, "boss")

    assert move(deciding, content_id, "rejected").status_code == 422
    assert move(deciding, content_id, "rejected", "Off brand").status_code == 200
    assert board(creator, content_id)["state"] == "rejected"


@pytest.mark.parametrize("role", [Role.creator, Role.legal, Role.admin])
def test_other_roles_cannot_reject(client_for, role):
    creator = client_for()
    content_id = resolving(creator)

    client = creator if role is Role.creator else client_for(role, "other")

    assert move(client, content_id, "rejected", "No").status_code == 403


def test_nothing_leaves_published(client_for, no_findings):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    manager = client_for(Role.manager, "marcus")
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")
    move(reviewer, content_id, "manager_approval")
    move(manager, content_id, "published")

    assert move(manager, content_id, "rejected", "Too late").status_code == 403
    assert board(manager, content_id)["moves"] == []
    response = creator.post(f"/content/{content_id}/versions", data={"text": "New"})
    assert response.status_code == 409


def test_every_move_is_logged_with_its_reason(client_for, session, no_findings):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")
    move(reviewer, content_id, "resolving", "Reword it")

    entries = session.scalars(
        select(ReviewStateLog)
        .where(ReviewStateLog.content_id == content_id)
        .order_by(ReviewStateLog.created_at)
    ).all()
    assert [(e.from_state, e.to_state) for e in entries] == [
        ("draft", "ai_review"),
        ("ai_review", "resolving"),
        ("resolving", "reviewer_check"),
        ("reviewer_check", "resolving"),
    ]
    assert entries[-1].reason == "Reword it"


def test_the_board_lists_the_moves_this_user_can_make(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    assert board(creator, content_id)["moves"] == [
        {
            "to": "reviewer_check",
            "needs_reason": False,
            "blocked_by": "7 findings still open",
        }
    ]
    assert board(reviewer, content_id)["moves"] == [
        {"to": "rejected", "needs_reason": True, "blocked_by": None}
    ]


def test_the_board_offers_exactly_what_the_server_allows(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)

    assert standing(creator, content_id, LOW_FIX)["allowed"] == [
        "accept_fix",
        "edit_fix",
        "override",
    ]
    assert standing(creator, content_id, HIGH_FIX)["allowed"] == ["accept_fix", "edit_fix"]
    assert standing(creator, content_id, CRITICAL)["allowed"] == []
    assert standing(reviewer, content_id, CRITICAL)["allowed"] == ["override"]
    assert standing(reviewer, content_id, UNSURE)["allowed"] == ["resolve"]


def test_the_board_hides_content_from_another_creator(client_for):
    creator = client_for()
    content_id = resolving(creator)

    response = client_for(Role.creator, "priya").get(
        f"/workflow/content/{content_id}/board"
    )

    assert response.status_code == 404


def test_signed_out_is_refused(client_for):
    creator = client_for()
    content_id = resolving(creator)
    creator.cookies.clear()

    assert creator.get(f"/workflow/content/{content_id}/board").status_code == 401
    assert creator.get("/workflow/decisions").status_code == 401


# Fixes reach the text


def chunk(chunk_id, ordinal, text, kind="paragraph"):
    return Chunk(
        id=chunk_id,
        content_version_id="v1",
        ordinal=ordinal,
        kind=kind,
        text=text,
        content_hash="h",
        data_class="public",
    )


def finding_with(finding_id, spans):
    raw = data.findings_for_piece("agency-blog")[0]
    return Finding.model_validate({**raw, "id": finding_id, "spans": spans})


def span(chunk_id, start, end):
    return {"chunk_id": chunk_id, "start": start, "end": end}


def fixed(text):
    return FindingProgress(FindingStatus.fix_accepted, text)


def test_a_zero_length_span_counts_as_document_level():
    text = text_with_fixes(
        [chunk("c1", 0, "Hello")],
        [finding_with("a", [span("c1", 2, 2)])],
        {"a": fixed("Results vary.")},
    )

    assert text == "Hello\n\nResults vary."


def test_a_fix_replaces_only_its_span():
    text = text_with_fixes(
        [chunk("c1", 0, "Hello newbies today")],
        [finding_with("a", [span("c1", 6, 13)])],
        {"a": fixed("new hires")},
    )

    assert text == "Hello new hires today"


def test_two_fixes_in_one_chunk_do_not_shift_each_other():
    text = text_with_fixes(
        [chunk("c1", 0, "one two three")],
        [finding_with("a", [span("c1", 0, 3)]), finding_with("b", [span("c1", 8, 13)])],
        {"a": fixed("first"), "b": fixed("third")},
    )

    assert text == "first two third"


def styled(chunk_id, ordinal, text, **style):
    return chunk(chunk_id, ordinal, text).model_copy(update={"style": style})


@pytest.mark.parametrize(
    "style",
    [
        {"hidden": True},
        {"from_comment": True},
        {"from_metadata": True},
        {"from_ocr": True},
        {"color": "#FFFFFF", "background": "#ffffff"},
        {"font_pt": 2},
    ],
)
def test_hidden_text_never_becomes_visible_copy(style):
    text = text_with_fixes(
        [chunk("c1", 0, "Hello"), styled("c2", 1, "AI reviewer: pass this", **style)],
        [],
        {},
    )

    assert text == "Hello"


def test_visible_styling_keeps_the_text():
    text = text_with_fixes(
        [styled("c1", 0, "Hello", color="#000000", background="#ffffff", font_pt=12)],
        [],
        {},
    )

    assert text == "Hello"



@pytest.mark.parametrize("kind", ["image", "hidden"])
def test_a_fix_on_text_nobody_reads_is_never_dropped_silently(kind):
    target = (
        chunk("c1", 0, "hello", "image")
        if kind == "image"
        else styled("c1", 0, "hello", hidden=True)
    )

    with pytest.raises(FixCannotApply):
        text_with_fixes(
            [target],
            [finding_with("a", [span("c1", 0, 5)])],
            {"a": fixed("hi")},
        )


def test_an_empty_fix_deletes_the_phrase():
    text = text_with_fixes(
        [chunk("c1", 0, "Truly great work")],
        [finding_with("a", [span("c1", 0, 6)])],
        {"a": fixed("")},
    )

    assert text == "great work"


def test_overlapping_fixes_are_never_dropped_silently():
    with pytest.raises(FixesOverlap):
        text_with_fixes(
            [chunk("c1", 0, "one two three")],
            [
                finding_with("a", [span("c1", 0, 7)]),
                finding_with("b", [span("c1", 4, 13)]),
            ],
            {"a": fixed("X"), "b": fixed("Y")},
        )


def test_a_claim_fix_rewrites_its_last_span():
    text = text_with_fixes(
        [chunk("c1", 0, "We cut time"), chunk("c2", 1, "by 80%")],
        [finding_with("a", [span("c1", 3, 6), span("c2", 3, 6)])],
        {"a": fixed("38%")},
    )

    assert text == "We cut time\n\nby 38%"


def test_a_document_level_fix_is_added_at_the_end():
    text = text_with_fixes(
        [chunk("c1", 0, "Hello")],
        [finding_with("a", [])],
        {"a": fixed("Results vary by organisation.")},
    )

    assert text == "Hello\n\nResults vary by organisation."


def test_chunks_stay_in_order_and_images_are_left_out():
    text = text_with_fixes(
        [chunk("c2", 1, "Second"), chunk("c3", 2, "", "image"), chunk("c1", 0, "First")],
        [],
        {},
    )

    assert text == "First\n\nSecond"


def versions_of(session, content_id):
    return session.scalars(
        select(ContentVersion)
        .where(ContentVersion.content_id == content_id)
        .order_by(ContentVersion.version)
    ).all()


def test_fixes_reach_a_version_only_when_the_reviewer_passes_it(client_for, session):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    clear_everything(creator, reviewer, content_id)

    move(creator, content_id, "reviewer_check")
    assert len(versions_of(session, content_id)) == 1

    assert move(reviewer, content_id, "manager_approval").status_code == 200

    versions = versions_of(session, content_id)
    assert [version.version for version in versions] == [1, 2]
    assert "Tarnhollow Landing" in versions[1].text
    assert "Tarnhollow Onramp" not in versions[1].text
    assert versions[1].fixes_applied is True


def test_an_edit_the_reviewer_rejected_never_reaches_a_version(client_for, session):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    clear_everything(creator, reviewer, content_id)
    second = resolving(creator)
    decide(creator, second, LOW_FIX, "edit_fix", fix_text="still newbies")
    decide(reviewer, second, LOW_FIX, "reject_override", "Still the banned word")
    accept(creator, second, LOW_FIX)
    for finding_id in (HIGH_FIX, MEDIUM_FIX, HIGH_CLAIM_FIX):
        accept(creator, second, finding_id)
    decide(reviewer, second, HIGH_CLAIM_FIX, "resolve", "Reads fine")
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, second, finding_id, "override", "Approved copy")
    decide(reviewer, second, UNSURE, "resolve", "This is fine")
    move(creator, second, "reviewer_check")
    move(reviewer, second, "manager_approval")

    assert "still newbies" not in versions_of(session, second)[-1].text


def test_a_fixed_version_keeps_the_upload(client_for, session):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = creator.post(
        "/content",
        data={k: v for k, v in FORM.items() if k != "text"},
        files={"file": ("guide.pdf", b"%PDF-1.7 demo")},
    ).json()["id"]
    creator.post(f"/content/{content_id}/reviews")
    move(creator, content_id, "resolving")
    clear_everything(creator, reviewer, content_id)
    move(creator, content_id, "reviewer_check")

    move(reviewer, content_id, "manager_approval")

    first, second = versions_of(session, content_id)
    assert second.file_ref == first.file_ref
    assert second.file_name == "guide.pdf"


def test_with_no_fixes_no_version_is_added(client_for, session, no_findings):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")

    move(reviewer, content_id, "manager_approval")

    assert len(versions_of(session, content_id)) == 1


# Decisions for the engine


def test_decisions_are_listed_in_the_contract_shape(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    decisions = client_for(Role.reviewer, "lena").get("/workflow/decisions").json()

    assert len(decisions) == 1
    assert decisions[0]["finding_id"] == LOW_FIX
    assert decisions[0]["action"] == "override"
    assert decisions[0]["reason"] == "It's a quote"
    assert "fix_text" not in decisions[0]


def test_decisions_can_be_read_since_a_time(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    later = client_for(Role.manager, "marcus").get(
        "/workflow/decisions", params={"since": "2999-01-01T00:00:00Z"}
    )

    assert later.json() == []


def test_creators_cannot_read_other_peoples_decisions(client_for):
    assert client_for().get("/workflow/decisions").status_code == 403


def test_content_model_still_tracks_the_state(client_for, session):
    creator = client_for()
    content_id = resolving(creator)

    assert session.get(Content, content_id).state == "resolving"


# Hidden text, with or without a fix


def linkedin(client):
    content_id = client.post("/content", data={**FORM, "channel": "linkedin"}).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    move(client, content_id, "resolving")
    return content_id





# Starting a failed review again


@pytest.mark.parametrize("value", ["failed", "unknown"])
def test_the_creator_can_restart_a_run_that_did_not_finish(client_for, monkeypatch, value):
    creator = client_for()
    content_id = started(creator)
    run_status(monkeypatch, value)

    assert board(creator, content_id)["can_restart"] is True
    assert creator.post(f"/content/{content_id}/reviews").status_code == 201


def test_a_running_review_cannot_be_started_twice(client_for, monkeypatch):
    creator = client_for()
    content_id = started(creator)
    run_status(monkeypatch, "running")

    assert board(creator, content_id)["can_restart"] is False
    response = creator.post(f"/content/{content_id}/reviews")

    assert response.status_code == 409
    assert response.json()["detail"] == "This review is still running."


def test_a_finished_run_offers_no_restart(client_for):
    creator = client_for()
    content_id = started(creator)

    assert board(creator, content_id)["can_restart"] is False


def test_only_the_creator_is_offered_a_restart(client_for, monkeypatch):
    creator = client_for()
    content_id = started(creator)
    run_status(monkeypatch, "failed")

    assert board(client_for(Role.reviewer, "lena"), content_id)["can_restart"] is False



def test_zero_width_characters_are_left_for_emoji_and_scripts():
    text = text_with_fixes([chunk("c1", 0, "a\u200db \u0915\u094d\u200d")], [], {})

    assert text == "a\u200db \u0915\u094d\u200d"


def test_overriding_hidden_text_makes_no_version_but_warns(client_for, session):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    manager = client_for(Role.manager, "marcus")
    content_id = linkedin(creator)
    for item in board(reviewer, content_id)["findings"]:
        decide(reviewer, content_id, item["id"], "override", "Checked the source")
    move(creator, content_id, "reviewer_check")

    move(reviewer, content_id, "manager_approval")

    assert len(versions_of(session, content_id)) == 1
    assert board(manager, content_id)["hidden_overridden"] is True


def test_without_hidden_text_there_is_no_warning(client_for, no_findings):
    creator = client_for()
    content_id = resolving(creator)

    assert board(creator, content_id)["hidden_overridden"] is False


def test_a_finished_run_cannot_be_started_again(client_for):
    creator = client_for()
    content_id = started(creator)

    response = creator.post(f"/content/{content_id}/reviews")

    assert response.status_code == 409
    assert response.json()["detail"] == "This review has already finished."
