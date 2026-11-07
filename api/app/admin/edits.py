"""Brand data an admin changes. Every change writes an audit row.

Facts are versioned: an edit adds a version and never rewrites one, so a review that
cited the old wording still shows what it was checked against.
"""

import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.models import Asset as AssetRow
from app.admin.models import Fact as FactRow
from app.admin.models import Term as TermRow
from app.admin.rulebook import current_rulebook_version
from app.auth.models import User
from app.content import storage
from app.contracts import Asset, AssetKind, DataClass, Fact, Term
from app.workflow.models import AuditLog

HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
IMAGE_KINDS = {AssetKind.logo, AssetKind.image}


class FactIn(BaseModel):
    statement: str = Field(min_length=1)
    value: str = Field(min_length=1, max_length=255)
    source_doc: str = Field(min_length=1, max_length=255)
    owner: str = Field(min_length=1, max_length=255)
    valid_until: date | None = None
    data_class: DataClass


class TermIn(BaseModel):
    preferred: str = Field(min_length=1, max_length=255)
    banned: list[str] = Field(default_factory=list)
    renamed_from: str | None = None
    rule_id: str | None = None
    rule_version: int | None = None

    @field_validator("banned")
    @classmethod
    def _clean(cls, banned: list[str]) -> list[str]:
        return [word.strip() for word in banned if word.strip()]


class PaletteIn(BaseModel):
    colours: list[str] = Field(min_length=1)

    @field_validator("colours")
    @classmethod
    def _hex(cls, colours: list[str]) -> list[str]:
        bad = [colour for colour in colours if not HEX.match(colour)]
        if bad:
            raise ValueError(f"not a #RRGGBB colour: {', '.join(bad)}")
        return [colour.upper() for colour in colours]


def _audit(
    session: Session,
    actor: User,
    action: str,
    target_type: str,
    target_id: str,
    before: dict | None,
    after: dict | None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor.id,
            role=actor.role,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            rulebook_version=current_rulebook_version(session),
        )
    )


def _next_id(session: Session, model: type, prefix: str) -> str:
    ids = session.scalars(select(model.id).where(model.id.like(f"{prefix}%")))
    numbers = [
        int(value[len(prefix) :]) for value in ids if value[len(prefix) :].isdigit()
    ]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _latest_fact(session: Session, fact_id: str) -> FactRow | None:
    return session.scalar(
        select(FactRow)
        .where(FactRow.id == fact_id)
        .order_by(FactRow.version.desc())
        .limit(1)
    )


def _fact(row: FactRow) -> Fact:
    return Fact.model_validate(row, from_attributes=True)


def create_fact(session: Session, body: FactIn, actor: User) -> Fact:
    """Adds a fact. The caller commits."""
    row = FactRow(
        id=_next_id(session, FactRow, "F-"),
        version=1,
        **{**body.model_dump(), "data_class": body.data_class.value},
    )
    session.add(row)
    session.flush()
    fact = _fact(row)
    _audit(
        session,
        actor,
        "fact:create",
        "fact",
        row.id,
        None,
        fact.model_dump(mode="json"),
    )
    return fact


def update_fact(session: Session, fact_id: str, body: FactIn, actor: User) -> Fact:
    """Adds a new version of a fact. The caller commits."""
    latest = _latest_fact(session, fact_id)
    if latest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fact not found")
    before = _fact(latest)
    changes = {**body.model_dump(), "data_class": body.data_class}
    if all(getattr(before, key) == value for key, value in changes.items()):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing changed.")
    row = FactRow(
        id=fact_id,
        version=latest.version + 1,
        **{**body.model_dump(), "data_class": body.data_class.value},
    )
    session.add(row)
    session.flush()
    after = _fact(row)
    _audit(
        session,
        actor,
        "fact:edit",
        "fact",
        fact_id,
        before.model_dump(mode="json"),
        after.model_dump(mode="json"),
    )
    return after


def _term(row: TermRow) -> Term:
    return Term.model_validate(row, from_attributes=True)


def create_term(session: Session, body: TermIn, actor: User) -> Term:
    row = TermRow(id=_next_id(session, TermRow, "T-"), **body.model_dump())
    session.add(row)
    session.flush()
    term = _term(row)
    _audit(
        session,
        actor,
        "term:create",
        "term",
        row.id,
        None,
        term.model_dump(mode="json"),
    )
    return term


def update_term(session: Session, term_id: str, body: TermIn, actor: User) -> Term:
    row = session.get(TermRow, term_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")
    before = _term(row).model_dump(mode="json")
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    session.flush()
    term = _term(row)
    _audit(
        session,
        actor,
        "term:edit",
        "term",
        term_id,
        before,
        term.model_dump(mode="json"),
    )
    return term


def _asset(row: AssetRow) -> Asset:
    return Asset.model_validate(row, from_attributes=True)


def add_palette(session: Session, body: PaletteIn, actor: User) -> Asset:
    row = AssetRow(
        id=_next_id(session, AssetRow, "A-"),
        kind=AssetKind.palette.value,
        file_ref="",
        meta={"colours": body.colours},
    )
    session.add(row)
    session.flush()
    asset = _asset(row)
    _audit(
        session,
        actor,
        "asset:create",
        "asset",
        row.id,
        None,
        asset.model_dump(mode="json"),
    )
    return asset


def add_image_asset(
    session: Session, kind: AssetKind, file_name: str, data: bytes, actor: User
) -> Asset:
    """Stores an approved logo or image. Only PNG and JPEG, which the Visual agent reads."""
    if kind not in IMAGE_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Upload logos and images here."
        )
    try:
        checked = storage.check_upload(file_name, data)
    except storage.UploadTooLarge as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from None
    except storage.UploadRejected as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    if not storage.is_image(file_name):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Logos and images must be PNG or JPEG.",
        )

    asset_id = _next_id(session, AssetRow, "A-")
    file_ref = f"assets/{uuid.uuid4().hex}{Path(file_name).suffix.lower()}"
    target = storage.stored_path(file_ref)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(checked.data)
    row = AssetRow(
        id=asset_id, kind=kind.value, file_ref=file_ref, meta={"name": file_name}
    )
    session.add(row)
    session.flush()
    asset = _asset(row)
    _audit(
        session,
        actor,
        "asset:create",
        "asset",
        asset_id,
        None,
        asset.model_dump(mode="json"),
    )
    return asset
