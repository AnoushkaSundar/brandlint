"""Content upload and versions. Permissions are checked by calling the API directly,
because the UI hiding a button proves nothing.
"""

import app.admin.models
import app.content.models
import app.workflow.models  # noqa: F401
import pytest
from app.admin.seed import seed_brand
from app.auth.models import User
from app.auth.orgs import DEMO_ORG_ID
from app.auth.router import router as auth_router
from app.auth.security import SESSION_COOKIE, create_token, hash_password
from app.content import storage
from app.content.models import Content, ContentVersion
from app.content.router import router as content_router
from app.contracts import Role
from app.db import Base, get_session
from app.workflow.models import AuditLog, Review, ReviewStateLog
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

PDF = b"%PDF-1.7 demo"
PNG = b"\x89PNG\r\n\x1a\n demo"
JPEG = b"\xff\xd8\xff\xe0 demo"
DOCX = b"PK\x03\x04 demo"

FORM = {
    "title": "First week guide",
    "channel": "blog",
    "source": "in-house",
    "data_class": "public",
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
        # A review needs approved rules, as in any real workspace.
        seed_brand(db)
        yield db


@pytest.fixture
def client_for(session):
    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(content_router)
    app.dependency_overrides[get_session] = lambda: session
    made = {}

    def make(role: Role = Role.creator, name: str = "sam") -> TestClient:
        key = (role, name)
        if key not in made:
            user = User(
                email=f"{name}-{role.value}@example.com",
                name=name,
                role=role.value,
                tag=None,
                password_hash=hash_password("not-used"),
            )
            session.add(user)
            session.commit()
            client = TestClient(app)
            client.cookies.set(SESSION_COOKIE, create_token(user))
            client.user_id = user.id
            made[key] = client
        return made[key]

    return make


def create(client, text="Hello there", **overrides):
    return client.post("/content", data={**FORM, **overrides, "text": text})


def upload(client, name, data, **overrides):
    return client.post(
        "/content", data={**FORM, **overrides}, files={"file": (name, data)}
    )


def test_pasting_text_creates_version_one(client_for):
    response = create(client_for())

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "draft"
    assert body["title"] == "First week guide"
    assert [v["version"] for v in body["versions"]] == [1]
    assert body["versions"][0]["text"] == "Hello there"
    assert body["latest_review"] is None


def test_new_content_is_readable_straight_away(client_for):
    client = client_for()
    content_id = create(client).json()["id"]

    assert client.get(f"/content/{content_id}").status_code == 200


@pytest.mark.parametrize(
    "channel", ["blog", "linkedin", "email", "ad", "banner", "document"]
)
def test_every_channel_is_accepted(client_for, channel):
    assert create(client_for(), channel=channel).status_code == 201


@pytest.mark.parametrize(
    "field,value",
    [
        ("channel", "tiktok"),
        ("data_class", "secret"),
        ("title", ""),
        ("source", ""),
        ("title", "   "),
        ("source", "  	 "),
    ],
)
def test_invalid_fields_are_refused(client_for, field, value):
    assert create(client_for(), **{field: value}).status_code == 422


def test_blank_text_and_no_file_is_refused(client_for):
    response = create(client_for(), text="   ")

    assert response.status_code == 422
    assert response.json()["detail"] == "Paste some text or upload a file."


def test_text_and_a_file_together_are_refused(client_for):
    response = client_for().post(
        "/content",
        data={**FORM, "text": "Hello"},
        files={"file": ("a.txt", b"Hello")},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "name,data",
    [
        ("post.txt", b"Hello"),
        ("notes.md", b"# Hello"),
        ("post.html", b"<p>Hello</p>"),
        ("POST.HTM", b"<p>Hello</p>"),
        ("guide.pdf", PDF),
        ("guide.docx", DOCX),
        ("banner.png", PNG),
        ("photo.jpg", JPEG),
        ("photo.jpeg", JPEG),
    ],
)
def test_supported_files_are_accepted(client_for, name, data):
    response = upload(client_for(), name, data)

    assert response.status_code == 201
    assert response.json()["versions"][0]["file_name"] == name


def test_text_files_keep_their_text(client_for):
    response = upload(client_for(), "post.html", b"<p>Caf\xc3\xa9</p>")

    assert response.json()["versions"][0]["text"] == "<p>Café</p>"


@pytest.mark.parametrize(
    "name,data,message",
    [
        ("virus.exe", b"MZ", "Upload a text"),
        ("logo.svg", b"<svg/>", "Upload a text"),
        ("no-extension", b"Hello", "Upload a text"),
        ("empty.txt", b"", "empty"),
        ("fake.pdf", b"<script>alert(1)</script>", "valid PDF"),
        ("fake.png", b"not an image", "valid PNG"),
        ("latin.txt", b"caf\xe9", "UTF-8"),
    ],
)
def test_bad_files_are_refused(client_for, name, data, message):
    response = upload(client_for(), name, data)

    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_a_file_over_the_limit_is_refused(client_for):
    too_big = b"a" * (storage.MAX_UPLOAD_BYTES + 1)

    assert upload(client_for(), "big.txt", too_big).status_code == 413


def test_nothing_is_saved_when_an_upload_is_refused(client_for, session):
    upload(client_for(), "virus.exe", b"MZ")

    assert list(session.scalars(select(Content))) == []


def test_files_are_stored_under_a_generated_name(client_for, tmp_path):
    response = upload(client_for(), "../../evil.txt", b"Hello")

    assert response.status_code == 201
    stored = [
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    ]
    version_id = response.json()["versions"][0]["id"]
    assert stored == [f"{DEMO_ORG_ID}/{version_id}.txt"]


@pytest.mark.parametrize("role", [Role.reviewer, Role.manager, Role.legal, Role.admin])
def test_only_creators_can_submit(client_for, role):
    assert create(client_for(role)).status_code == 403


def test_creating_needs_a_session(client_for):
    client = client_for()
    client.cookies.clear()

    assert create(client).status_code == 401


def test_creators_only_see_their_own_content(client_for):
    mine, theirs = client_for(name="sam"), client_for(name="priya")
    content_id = create(mine).json()["id"]

    assert [item["id"] for item in mine.get("/content").json()] == [content_id]
    assert theirs.get("/content").json() == []
    assert theirs.get(f"/content/{content_id}").status_code == 404


@pytest.mark.parametrize("role", [Role.reviewer, Role.manager, Role.legal, Role.admin])
def test_other_roles_can_read_everything(client_for, role):
    content_id = create(client_for()).json()["id"]
    reader = client_for(role)

    assert len(reader.get("/content").json()) == 1
    assert reader.get(f"/content/{content_id}").status_code == 200


def test_every_edit_makes_a_new_version(client_for):
    client = client_for()
    content_id = create(client, text="One").json()["id"]

    response = client.post(f"/content/{content_id}/versions", data={"text": "Two"})

    assert response.status_code == 201
    versions = response.json()["versions"]
    assert [(v["version"], v["text"]) for v in versions] == [(2, "Two"), (1, "One")]


def test_a_new_version_can_be_a_file(client_for):
    client = client_for()
    content_id = create(client).json()["id"]

    response = client.post(
        f"/content/{content_id}/versions", files={"file": ("new.pdf", PDF)}
    )

    assert response.json()["versions"][0]["file_name"] == "new.pdf"


def test_another_creator_cannot_edit(client_for):
    content_id = create(client_for(name="sam")).json()["id"]

    response = client_for(name="priya").post(
        f"/content/{content_id}/versions", data={"text": "Mine now"}
    )

    assert response.status_code == 404


def test_a_reviewer_cannot_edit(client_for):
    content_id = create(client_for()).json()["id"]

    response = client_for(Role.reviewer).post(
        f"/content/{content_id}/versions", data={"text": "Changed"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize(
    "state",
    ["reviewer_check", "manager_approval", "legal_signoff", "published", "rejected"],
)
def test_locked_content_cannot_be_edited(client_for, session, state):
    client = client_for()
    content_id = create(client).json()["id"]
    session.get(Content, content_id).state = state
    session.commit()

    response = client.post(f"/content/{content_id}/versions", data={"text": "Late"})

    assert response.status_code == 409


def test_starting_a_review_pins_the_rulebook_and_uses_the_engine_id(client_for):
    client = client_for()
    content_id = create(client, channel="linkedin").json()["id"]

    response = client.post(f"/content/{content_id}/reviews")

    assert response.status_code == 201
    review = response.json()
    assert review["rulebook_version"] == 1
    assert review["engine_review_id"] == "rev-demo-linkedin-post"
    assert review["id"] != review["engine_review_id"]

    detail = client.get(f"/content/{content_id}").json()
    assert detail["state"] == "ai_review"
    assert detail["latest_review"]["id"] == review["id"]


def test_two_pieces_on_one_channel_can_both_be_reviewed(client_for):
    client = client_for()
    first = create(client).json()["id"]
    second = create(client).json()["id"]

    assert client.post(f"/content/{first}/reviews").status_code == 201
    assert client.post(f"/content/{second}/reviews").status_code == 201


def test_a_review_covers_the_latest_version(client_for, session):
    client = client_for()
    content_id = create(client, text="One").json()["id"]
    newest = client.post(f"/content/{content_id}/versions", data={"text": "Two"}).json()

    client.post(f"/content/{content_id}/reviews")

    review = session.scalar(select(Review))
    assert review.content_version_id == newest["versions"][0]["id"]


def test_the_state_change_is_logged_and_audited(client_for, session):
    client = client_for()
    content_id = create(client).json()["id"]

    client.post(f"/content/{content_id}/reviews")

    log = session.scalar(select(ReviewStateLog))
    assert (log.from_state, log.to_state) == ("draft", "ai_review")
    assert log.actor_id == client.user_id

    audit = session.scalar(select(AuditLog))
    assert audit.actor_id == client.user_id
    assert audit.role == "creator"
    assert audit.before == {"state": "draft"}
    assert audit.after == {"state": "ai_review"}
    assert audit.rulebook_version == 1


def test_a_repeat_review_does_not_log_a_change(client_for, session):
    client = client_for()
    content_id = create(client).json()["id"]

    client.post(f"/content/{content_id}/reviews")
    client.post(f"/content/{content_id}/reviews")

    assert len(list(session.scalars(select(ReviewStateLog)))) == 1


def test_only_the_creator_can_start_a_review(client_for):
    content_id = create(client_for(name="sam")).json()["id"]

    assert (
        client_for(Role.reviewer).post(f"/content/{content_id}/reviews").status_code
        == 403
    )
    assert (
        client_for(name="priya").post(f"/content/{content_id}/reviews").status_code
        == 404
    )


@pytest.mark.parametrize("state", ["manager_approval", "published", "rejected"])
def test_a_review_cannot_start_from_a_later_state(client_for, session, state):
    client = client_for()
    content_id = create(client).json()["id"]
    session.get(Content, content_id).state = state
    session.commit()

    assert client.post(f"/content/{content_id}/reviews").status_code == 409


def test_images_display_inline(client_for):
    client = client_for()
    version = upload(client, "banner.png", PNG).json()["versions"][0]

    response = client.get(f"/content/versions/{version['id']}/file")

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_uploaded_html_is_only_ever_a_download(client_for):
    client = client_for()
    version = upload(client, "post.html", b"<script>alert(1)</script>").json()[
        "versions"
    ][0]

    response = client.get(f"/content/versions/{version['id']}/file")

    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")


def test_another_creator_cannot_download_a_file(client_for):
    version = upload(client_for(name="sam"), "banner.png", PNG).json()["versions"][0]

    response = client_for(name="priya").get(f"/content/versions/{version['id']}/file")

    assert response.status_code == 404


def test_pasted_text_has_no_file(client_for):
    client = client_for()
    version = create(client).json()["versions"][0]

    assert client.get(f"/content/versions/{version['id']}/file").status_code == 404


def test_a_blank_file_field_from_a_browser_is_ignored(client_for):
    response = client_for().post(
        "/content",
        data={**FORM, "text": "Hello"},
        files={"file": ("", b"", "application/octet-stream")},
    )

    assert response.status_code == 201
    assert response.json()["versions"][0]["file_name"] is None


def captured_source(monkeypatch):
    calls = []

    def fake_start_review(
        content_version_id, channel, rulebook_version, source, **kwargs
    ):
        calls.append(source)
        return "rev-captured"

    monkeypatch.setattr("app.clients.engine.start_review", fake_start_review)
    return calls


def test_a_review_hands_the_engine_pasted_text(client_for, monkeypatch):
    calls = captured_source(monkeypatch)
    client = client_for()
    content_id = create(client, text="Hello there", data_class="internal").json()["id"]

    assert client.post(f"/content/{content_id}/reviews").status_code == 201

    source = calls[0]
    assert source.text == "Hello there"
    assert source.data_class.value == "internal"
    assert source.file_bytes is None


def test_a_review_hands_the_engine_the_uploaded_bytes(client_for, monkeypatch):
    calls = captured_source(monkeypatch)
    client = client_for()
    content_id = upload(client, "guide.pdf", PDF).json()["id"]

    assert client.post(f"/content/{content_id}/reviews").status_code == 201

    source = calls[0]
    assert source.file_bytes == PDF
    assert source.file_name == "guide.pdf"
    assert source.text == ""


def test_a_review_covers_the_newest_upload(client_for, monkeypatch):
    calls = captured_source(monkeypatch)
    client = client_for()
    content_id = upload(client, "first.pdf", PDF).json()["id"]
    client.post(f"/content/{content_id}/versions", files={"file": ("second.png", PNG)})

    client.post(f"/content/{content_id}/reviews")

    assert calls[0].file_name == "second.png"
    assert calls[0].file_bytes == PNG


def test_a_missing_upload_is_refused_and_changes_nothing(
    client_for, session, monkeypatch
):
    calls = captured_source(monkeypatch)
    client = client_for()
    content_id = upload(client, "guide.pdf", PDF).json()["id"]
    version = session.scalars(select(ContentVersion)).one()
    storage.stored_path(version.file_ref).unlink()

    response = client.post(f"/content/{content_id}/reviews")

    assert response.status_code == 409
    assert "Upload it again" in response.json()["detail"]
    assert calls == []
    assert client.get(f"/content/{content_id}").json()["state"] == "draft"
    assert session.scalars(select(Review)).first() is None


def test_reviewing_the_same_text_again_is_refused(client_for, session):
    client = client_for()
    content_id = create(client).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    session.get(Content, content_id).state = "resolving"
    session.commit()

    response = client.post(f"/content/{content_id}/reviews")

    assert response.status_code == 409
    assert "new version" in response.json()["detail"]


def test_a_new_version_can_be_reviewed_from_resolving(client_for, session):
    client = client_for()
    content_id = create(client).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    session.get(Content, content_id).state = "resolving"
    session.commit()
    client.post(f"/content/{content_id}/versions", data={"text": "Better words"})

    assert client.post(f"/content/{content_id}/reviews").status_code == 201


def test_a_new_rulebook_lets_unchanged_text_be_reviewed_again(
    client_for, session, monkeypatch
):
    client = client_for()
    content_id = create(client).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    session.get(Content, content_id).state = "resolving"
    session.commit()
    monkeypatch.setattr("app.content.reviewing.current_rulebook_version", lambda *args: 2)

    assert client.post(f"/content/{content_id}/reviews").status_code == 201


@pytest.mark.parametrize("field", ["text", "title", "source"])
def test_a_null_character_is_refused_not_a_server_error(client_for, field):
    overrides = (
        {"text": "Hello\x00 there"} if field == "text" else {field: "In\x00house"}
    )

    response = create(client_for(), **overrides)

    assert response.status_code == 422
    assert "null character" in response.json()["detail"]


def test_a_text_file_with_a_null_character_is_refused(client_for):
    response = upload(client_for(), "draft.txt", b"Hello\x00 there")

    assert response.status_code == 422
    assert "null character" in response.json()["detail"]


def test_a_new_version_with_a_null_character_is_refused(client_for):
    client = client_for()
    content_id = create(client).json()["id"]

    response = client.post(f"/content/{content_id}/versions", data={"text": "Hi\x00"})

    assert response.status_code == 422


def test_a_piece_shows_no_rereview_by_default(client_for):
    assert create(client_for()).json()["rereview"] is None


def test_a_queued_rereview_shows_and_lets_unchanged_text_be_reviewed(
    client_for, session
):
    from app.auth.models import User
    from app.content import rereview

    client = client_for()
    content_id = create(client).json()["id"]
    client.post(f"/content/{content_id}/reviews")
    session.get(Content, content_id).state = "resolving"
    session.commit()
    admin = session.scalars(select(User)).first()
    rereview.queue(session, "F-002", [content_id], admin)
    session.commit()

    detail = client.get(f"/content/{content_id}").json()
    assert detail["rereview"]["fact_id"] == "F-002"
    assert client.post(f"/content/{content_id}/reviews").status_code == 201
    assert client.get(f"/content/{content_id}").json()["rereview"] is None
