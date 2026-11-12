"""The reviewer queue, comments, history and the audit log."""

import app.admin.models  # noqa: F401
import pytest
from app.auth.models import User
from app.auth.router import router as auth_router
from app.auth.security import SESSION_COOKIE, create_token, hash_password
from app.clients.engine import list_findings
from app.content.router import router as content_router
from app.contracts import Role
from app.db import Base, get_session
from app.workflow.router import router as workflow_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

LOW = "fnd-agency-blog-03"
MEDIUM = "fnd-agency-blog-02"
HIGH = "fnd-agency-blog-01"
CRITICAL = "fnd-agency-blog-04"
UNSURE = "fnd-agency-blog-07"


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

    def make(role=Role.creator, handle=None, name=None):
        handle = handle or role.value
        if handle not in made:
            user = User(
                email=f"{handle}@example.com",
                name=name or handle.title(),
                role=role.value,
                password_hash=hash_password("not-used"),
            )
            session.add(user)
            session.commit()
            client = TestClient(api)
            client.cookies.set(SESSION_COOKIE, create_token(user))
            made[handle] = client
        return made[handle]

    return make


@pytest.fixture
def no_findings(monkeypatch):
    monkeypatch.setattr("app.clients.engine.list_findings", lambda review_id, **kwargs: [])


def resolving(client, title="First week guide"):
    form = {
        "title": title,
        "channel": "blog",
        "source": "in-house",
        "data_class": "public",
        "text": "Hello there",
    }
    content_id = client.post("/content", data=form).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    move(client, content_id, "resolving")
    return content_id


def move(client, content_id, to, reason=None):
    return client.post(
        f"/workflow/content/{content_id}/transitions",
        json={"to": to, "reason": reason},
    )


def decide(client, content_id, finding_id, action, reason=None, fix_text=None):
    return client.post(
        f"/workflow/content/{content_id}/findings/{finding_id}/decisions",
        json={"action": action, "reason": reason, "fix_text": fix_text},
    )


def version_of(client, content_id):
    return client.get(f"/content/{content_id}").json()["versions"][0]["id"]


def comment(client, content_id, body="Looks fine", **fields):
    return client.post(
        f"/workflow/content/{content_id}/comments",
        json={
            "body": body,
            "content_version_id": version_of(client, content_id),
            **fields,
        },
    )


def comments(client, content_id):
    return client.get(f"/workflow/content/{content_id}/comments").json()


# The queue


def queue(client):
    return client.get("/workflow/queue").json()


def test_the_queue_shows_unsure_findings(client_for):
    creator = client_for()
    content_id = resolving(creator)

    items = of_kind(client_for(Role.reviewer), "unsure")

    assert len(items) == 1
    assert items[0]["finding_id"] == UNSURE
    assert items[0]["content_id"] == content_id
    assert items[0]["title"] == "First week guide"


def of_kind(client, kind):
    return [item for item in queue(client)["items"] if item["kind"] == kind]


def test_a_finding_only_a_reviewer_can_clear_reaches_the_queue(client_for):
    creator = client_for()
    resolving(creator)

    items = of_kind(client_for(Role.reviewer), "needs_override")

    assert {item["severity"] for item in items} == {"critical", "high"}
    assert CRITICAL in {item["finding_id"] for item in items}


def test_clearing_it_takes_it_out_of_the_queue(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer)
    content_id = resolving(creator)

    decide(reviewer, content_id, CRITICAL, "override", "Checked")

    assert CRITICAL not in {i["finding_id"] for i in of_kind(reviewer, "needs_override")}


def test_a_low_finding_stays_the_creators_to_fix(client_for):
    creator = client_for()
    resolving(creator)

    items = queue(client_for(Role.reviewer))["items"]

    assert LOW not in {item["finding_id"] for item in items}


def test_every_queue_item_carries_its_source(client_for):
    creator = client_for()
    resolving(creator)

    items = queue(client_for(Role.reviewer))["items"]

    assert items
    for item in items:
        assert item["cited_text"]
        assert item["rule_id"] or item["fact_ids"]


def test_one_failing_piece_does_not_empty_the_queue(client_for, monkeypatch):
    creator = client_for()
    resolving(creator, "Good piece")
    resolving(creator, "Broken piece")
    real = list_findings
    calls = []

    def flaky(review_id, **kwargs):
        calls.append(review_id)
        if len(calls) == 1:
            raise RuntimeError("engine fell over")
        return real(review_id, **kwargs)

    monkeypatch.setattr("app.clients.engine.list_findings", flaky)

    result = queue(client_for(Role.reviewer))

    assert len(result["unavailable"]) == 1
    assert result["items"]


def test_a_pending_override_shows_the_creators_reason(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "It's a direct quote")

    items = queue(client_for(Role.reviewer))["items"]

    override = next(item for item in items if item["kind"] == "override")
    assert override["finding_id"] == LOW
    assert override["reason"] == "It's a direct quote"


def test_the_queue_runs_from_most_to_least_serious(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A quote")
    decide(creator, content_id, MEDIUM, "override", "A quote")

    severities = [item["severity"] for item in queue(client_for(Role.reviewer))["items"]]

    ranks = ["critical", "high", "medium", "low"]
    assert severities == sorted(severities, key=ranks.index)
    assert severities[0] == "critical"


def test_an_edited_fix_is_queued_with_its_wording(client_for):
    creator = client_for()
    content_id = resolving(creator)
    decide(creator, content_id, HIGH, "edit_fix", fix_text="The Landing app")

    items = queue(client_for(Role.reviewer))["items"]

    edited = next(item for item in items if item["kind"] == "fix")
    assert edited["finding_id"] == HIGH
    assert edited["fix_text"] == "The Landing app"


def test_settled_items_leave_the_queue(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer)
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A quote")

    decide(reviewer, content_id, LOW, "confirm_override")
    decide(reviewer, content_id, UNSURE, "resolve", "Fine")

    settled = {item["finding_id"] for item in queue(reviewer)["items"]}
    assert not settled & {LOW, UNSURE}


def test_pieces_ready_for_a_reviewer_are_listed(client_for, no_findings):
    creator = client_for()
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")

    ready = queue(client_for(Role.reviewer))["ready"]

    assert [item["id"] for item in ready] == [content_id]


@pytest.mark.parametrize("role", [Role.creator, Role.manager, Role.legal, Role.admin])
def test_only_reviewers_read_the_queue(client_for, role):
    assert client_for(role).get("/workflow/queue").status_code == 403


# Comments


def test_a_comment_can_sit_on_a_version_a_finding_or_a_span(client_for):
    creator = client_for()
    content_id = resolving(creator)
    span = {"chunk_id": "blog-p1", "start": 0, "end": 5}

    assert comment(creator, content_id, "On the whole thing").status_code == 201
    assert comment(creator, content_id, "On a finding", finding_id=LOW).status_code == 201
    assert comment(creator, content_id, "On a span", span=span).status_code == 201

    found = {item["body"]: item for item in comments(creator, content_id)}
    assert found["On the whole thing"]["finding_id"] is None
    assert found["On a finding"]["finding_id"] == LOW
    assert found["On a span"]["span"] == span


def test_a_reply_joins_its_parents_thread(client_for):
    creator = client_for()
    reviewer = client_for(Role.reviewer)
    content_id = resolving(creator)
    comment(creator, content_id, "Is this ok?", finding_id=LOW)
    parent = comments(creator, content_id)[0]

    response = comment(reviewer, content_id, "Yes", parent_id=parent["id"])

    assert response.status_code == 201
    reply = comments(creator, content_id)[1]
    assert reply["parent_id"] == parent["id"]
    assert reply["finding_id"] == LOW
    assert reply["author"] == "Reviewer"


def test_a_mention_resolves_to_a_person(client_for):
    creator = client_for()
    client_for(Role.reviewer, "lena", "Lena Fischer")
    content_id = resolving(creator)

    comment(creator, content_id, "Could @lena check this?")

    assert comments(creator, content_id)[0]["mentions"] == ["Lena Fischer"]


@pytest.mark.parametrize(
    "body", ["Mail lena@example.com", "@nobody please look", "No mention here"]
)
def test_text_that_only_looks_like_a_mention_names_nobody(client_for, body):
    creator = client_for()
    client_for(Role.reviewer, "lena", "Lena Fischer")
    content_id = resolving(creator)

    comment(creator, content_id, body)

    assert comments(creator, content_id)[0]["mentions"] == []


def test_a_mention_only_reaches_people_who_can_see_the_piece(client_for):
    creator = client_for()
    client_for(Role.creator, "priya", "Priya Nair")
    content_id = resolving(creator)

    comment(creator, content_id, "Could @priya look?")

    assert comments(creator, content_id)[0]["mentions"] == []


def test_a_comment_cannot_point_at_an_unknown_finding(client_for):
    creator = client_for()
    content_id = resolving(creator)

    assert comment(creator, content_id, finding_id="nope").status_code == 404


@pytest.mark.parametrize(
    "span",
    [
        {"chunk_id": "nope", "start": 0, "end": 5},
        {"chunk_id": "blog-p1", "start": 5, "end": 5},
        {"chunk_id": "blog-p1", "start": 0, "end": 99999},
    ],
)
def test_a_comment_cannot_point_at_text_that_is_not_there(client_for, span):
    creator = client_for()
    content_id = resolving(creator)

    assert comment(creator, content_id, span=span).status_code == 422


def test_a_reply_from_a_newer_version_joins_the_older_thread(client_for):
    creator = client_for()
    content_id = resolving(creator)
    comment(creator, content_id, "On version one")
    parent = comments(creator, content_id)[0]
    creator.post(f"/content/{content_id}/versions", data={"text": "Newer"})

    response = comment(creator, content_id, "Replying later", parent_id=parent["id"])

    assert response.status_code == 201
    reply = comments(creator, content_id)[1]
    assert reply["content_version_id"] == parent["content_version_id"]


@pytest.mark.parametrize("body", ["", "   "])
def test_a_blank_comment_is_refused(client_for, body):
    creator = client_for()
    content_id = resolving(creator)

    assert comment(creator, content_id, body).status_code == 422


def test_a_comment_cannot_use_another_pieces_version(client_for):
    creator = client_for()
    first = resolving(creator)
    second = resolving(creator)

    response = creator.post(
        f"/workflow/content/{first}/comments",
        json={"body": "Hi", "content_version_id": version_of(creator, second)},
    )

    assert response.status_code == 404


def test_a_reply_cannot_join_another_pieces_thread(client_for):
    creator = client_for()
    first = resolving(creator)
    second = resolving(creator)
    comment(creator, first, "Here")
    parent = comments(creator, first)[0]

    assert comment(creator, second, "Hi", parent_id=parent["id"]).status_code == 404


def test_another_creator_cannot_read_or_write_comments(client_for):
    creator = client_for()
    other = client_for(Role.creator, "priya")
    content_id = resolving(creator)

    assert other.get(f"/workflow/content/{content_id}/comments").status_code == 404
    response = other.post(
        f"/workflow/content/{content_id}/comments",
        json={"body": "Hi", "content_version_id": "anything"},
    )
    assert response.status_code == 404


# History


def history(client, content_id):
    return client.get(f"/workflow/content/{content_id}/history").json()


def test_history_lists_moves_and_decisions_with_names(client_for):
    creator = client_for(Role.creator, "sam", "Sam Okafor")
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A quote")

    record = history(creator, content_id)

    assert [e["to_state"] for e in record["states"]] == ["ai_review", "resolving"]
    assert record["states"][0]["actor"] == "Sam Okafor"
    decision = record["decisions"][0]
    assert decision["action"] == "override"
    assert decision["actor"] == "Sam Okafor"
    assert decision["reason"] == "A quote"
    assert decision["version"] == 1
    assert record["stamp"] is None


def test_publishing_stamps_the_approvers_and_rulebook(client_for, no_findings):
    creator = client_for()
    reviewer = client_for(Role.reviewer, "lena", "Lena Fischer")
    manager = client_for(Role.manager, "marcus", "Marcus Bell")
    content_id = resolving(creator)
    move(creator, content_id, "reviewer_check")
    move(reviewer, content_id, "manager_approval")
    move(manager, content_id, "published")

    stamp = history(creator, content_id)["stamp"]

    assert stamp["approvers"] == ["Lena Fischer", "Marcus Bell"]
    assert stamp["rulebook_version"] == 1
    assert stamp["version"] == 1


def test_history_is_private_to_those_who_can_read_the_content(client_for):
    creator = client_for()
    content_id = resolving(creator)

    response = client_for(Role.creator, "priya").get(
        f"/workflow/content/{content_id}/history"
    )

    assert response.status_code == 404


# The audit log


def audit(client, **params):
    return client.get("/workflow/audit", params=params)


@pytest.mark.parametrize("role", [Role.admin, Role.manager])
def test_admins_and_managers_read_the_audit_log(client_for, role):
    creator = client_for()
    resolving(creator)

    page = audit(client_for(role)).json()

    assert page["total"] == 2
    assert {item["action"] for item in page["items"]} == {"state_change"}
    assert page["items"][0]["actor"] == "Creator"


@pytest.mark.parametrize("role", [Role.creator, Role.reviewer, Role.legal])
def test_other_roles_cannot_read_the_audit_log(client_for, role):
    assert audit(client_for(role)).status_code == 403


def test_the_audit_log_filters(client_for):
    creator = client_for()
    admin = client_for(Role.admin)
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A quote")

    assert audit(admin, action="decision:").json()["total"] == 1
    assert audit(admin, target_type="finding").json()["total"] == 1
    assert audit(admin, role="creator").json()["total"] == 3
    assert audit(admin, role="reviewer").json()["total"] == 0


def test_a_filter_is_matched_literally(client_for):
    creator = client_for()
    admin = client_for(Role.admin)
    resolving(creator)

    assert audit(admin, action="%").json()["total"] == 0


def test_the_audit_log_pages_newest_first(client_for):
    creator = client_for()
    admin = client_for(Role.admin)
    content_id = resolving(creator)
    decide(creator, content_id, LOW, "override", "A quote")

    first = audit(admin, limit=1).json()
    second = audit(admin, limit=1, offset=1).json()

    assert first["total"] == 3
    assert first["items"][0]["action"] == "decision:override"
    assert second["items"][0]["action"] == "state_change"


def test_the_audit_page_size_is_capped(client_for):
    assert audit(client_for(Role.admin), limit=1000).status_code == 422
