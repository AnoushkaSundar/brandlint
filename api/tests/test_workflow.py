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
from app.contracts import Chunk, Finding, FindingStatus, Role
from app.db import Base, get_session
from app.workflow.decisions import FindingProgress
from app.workflow.fixes import text_with_fixes
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


def decide(client, content_id, finding_id, action, reason=None, fix_text=None):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/decisions",
        json={"action": action, "reason": reason, "fix_text": fix_text},
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
        assert (
            decide(
                creator, content_id, finding_id, "accept_fix", fix_text="Better words"
            ).status_code
            == 201
        )
    for finding_id in (CRITICAL, HIGH_CLAIM):
        assert (
            decide(reviewer, content_id, finding_id, "override", "Approved copy").status_code
            == 201
        )
    assert decide(reviewer, content_id, UNSURE, "resolve", "This is fine").status_code == 201


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
    assert (
        decide(creator, content_id, LOW_FIX, "accept_fix", fix_text="new hires").status_code
        == 201
    )


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
        decide(creator, content_id, finding_id, "accept_fix", fix_text="Better words")
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, content_id, finding_id, "override", "Approved copy")

    response = move(creator, content_id, "reviewer_check")

    assert response.status_code == 409
    assert response.json()["detail"] == "1 finding still open"


# Fixes


def test_accepting_a_fix_needs_its_text(client_for):
    creator = client_for()
    content_id = resolving(creator)

    assert decide(creator, content_id, HIGH_FIX, "accept_fix").status_code == 422


def test_a_fix_cannot_be_accepted_where_none_is_available(client_for):
    creator = client_for()
    content_id = resolving(creator)

    response = decide(creator, content_id, CRITICAL, "accept_fix", fix_text="Anything")

    assert response.status_code == 403


def test_a_fix_cannot_be_accepted_twice(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, HIGH_FIX, "accept_fix", fix_text="Tarnhollow Landing")

    response = decide(creator, content_id, HIGH_FIX, "accept_fix", fix_text="Again")

    assert response.status_code == 403


def test_an_accepted_and_an_edited_fix_keep_their_wording(client_for):
    creator = client_for()
    content_id = resolving(creator)

    decide(creator, content_id, HIGH_FIX, "accept_fix", fix_text="Tarnhollow Landing")
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

    response = decide(other, content_id, HIGH_FIX, "accept_fix", fix_text="Mine")

    assert response.status_code == 404


def test_decisions_on_one_piece_do_not_reach_another(client_for):
    creator = client_for()
    first = resolving(creator)
    second = resolving(creator)

    decide(creator, first, HIGH_FIX, "accept_fix", fix_text="Tarnhollow Landing")

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
        decide(creator, second, finding_id, "accept_fix", fix_text="Better words")
    decide(creator, second, MEDIUM_FIX, "override", "It's a quote")
    decide(creator, second, LOW_FIX, "override", "It's a quote")
    for finding_id in (CRITICAL, HIGH_CLAIM):
        decide(reviewer, second, finding_id, "override", "Approved copy")
    decide(reviewer, second, UNSURE, "resolve", "This is fine")

    assert move(creator, second, "reviewer_check").status_code == 200

    response = move(reviewer, second, "manager_approval")
    assert response.status_code == 409
    assert response.json()["detail"] == "2 overrides waiting for a reviewer"

    decide(reviewer, second, MEDIUM_FIX, "confirm_override")
    decide(reviewer, second, LOW_FIX, "confirm_override")
    assert move(reviewer, second, "manager_approval").status_code == 200


def test_a_rejected_override_blocks_submission(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    second = resolving(creator)
    for finding_id in (HIGH_FIX, MEDIUM_FIX, HIGH_CLAIM_FIX):
        decide(creator, second, finding_id, "accept_fix", fix_text="Better words")
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


def test_overlapping_fixes_never_corrupt_the_text():
    text = text_with_fixes(
        [chunk("c1", 0, "one two three")],
        [finding_with("a", [span("c1", 0, 7)]), finding_with("b", [span("c1", 4, 13)])],
        {"a": fixed("X"), "b": fixed("Y")},
    )

    assert text == "one Y"


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


def test_submitting_saves_a_version_with_the_fixes_applied(client_for, session):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    clear_everything(creator, reviewer, content_id)

    assert move(creator, content_id, "reviewer_check").status_code == 200

    versions = session.scalars(
        select(ContentVersion)
        .where(ContentVersion.content_id == content_id)
        .order_by(ContentVersion.version)
    ).all()
    assert [version.version for version in versions] == [1, 2]
    assert "Better words" in versions[1].text
    assert "Tarnhollow Onramp" not in versions[1].text


def test_submitting_twice_with_the_same_fixes_adds_one_version(client_for, session):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena")
    content_id = resolving(creator)
    clear_everything(creator, reviewer, content_id)
    move(creator, content_id, "reviewer_check")
    move(reviewer, content_id, "resolving", "Check it again")

    assert move(creator, content_id, "reviewer_check").status_code == 200

    versions = session.scalars(
        select(ContentVersion).where(ContentVersion.content_id == content_id)
    ).all()
    assert len(versions) == 2


def test_with_no_fixes_no_version_is_added(client_for, session, no_findings):
    creator = client_for()
    content_id = resolving(creator)

    move(creator, content_id, "reviewer_check")

    assert (
        len(
            session.scalars(
                select(ContentVersion).where(ContentVersion.content_id == content_id)
            ).all()
        )
        == 1
    )


# Decisions for the engine


def test_decisions_are_listed_in_the_contract_shape(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    decisions = creator.get("/workflow/decisions").json()

    assert len(decisions) == 1
    assert decisions[0]["finding_id"] == LOW_FIX
    assert decisions[0]["action"] == "override"
    assert decisions[0]["reason"] == "It's a quote"
    assert "fix_text" not in decisions[0]


def test_decisions_can_be_read_since_a_time(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW_FIX, "override", "It's a quote")

    later = creator.get("/workflow/decisions", params={"since": "2999-01-01T00:00:00Z"})

    assert later.json() == []


def test_content_model_still_tracks_the_state(client_for, session):
    creator = client_for()
    content_id = resolving(creator)

    assert session.get(Content, content_id).state == "resolving"
