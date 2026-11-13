"""The CI/CD integration's routes. Off until CI_INTEGRATION_ENABLED=true."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.admin.edits import _audit
from app.admin.rulebook import RulebookNotFound, rulebook_at
from app.auth.defaults import utc_now
from app.auth.dependencies import SessionDep, require_roles
from app.auth.models import User
from app.ci import auth, runs
from app.ci.auth import CIPrincipal
from app.ci.models import CIPolicySetting, CIRun, ServiceToken
from app.contracts import CIRunRequest, CIRunStatus, Role, Severity
from app.tenancy import scoped, scoped_get

router = APIRouter(
    prefix="/ci", tags=["ci"], dependencies=[Depends(auth.require_enabled)]
)

Admin = Annotated[User, Depends(require_roles(Role.admin))]


class Whoami(BaseModel):
    kind: str
    name: str
    role: str | None = None


@router.get("/whoami", response_model=Whoami)
def whoami(principal: CIPrincipal) -> Whoami:
    """Who the caller is, so a CI job can check its token before it sends anything."""
    return Whoami(
        kind=principal.kind,
        name=principal.name,
        role=principal.user.role if principal.user else None,
    )


# --- Tokens: an admin manages their own workspace's ----------------------------------------


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class TokenOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class TokenCreated(TokenOut):
    # The only time the token is shown.
    token: str


def _out(row: ServiceToken) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
    }


@router.get("/tokens", response_model=list[TokenOut])
def list_tokens(admin: Admin, session: SessionDep) -> list[dict]:
    rows = session.scalars(
        scoped(session, ServiceToken).order_by(ServiceToken.created_at.desc())
    )
    return [_out(row) for row in rows]


@router.post(
    "/tokens", response_model=TokenCreated, status_code=status.HTTP_201_CREATED
)
def create_token(body: TokenIn, admin: Admin, session: SessionDep) -> dict:
    raw, digest = auth.new_token()
    row = ServiceToken(
        name=body.name.strip(),
        token_hash=digest,
        prefix=raw[:8],
        created_by=admin.id,
        expires_at=utc_now() + timedelta(days=body.expires_in_days)
        if body.expires_in_days
        else None,
    )
    session.add(row)
    session.flush()
    _audit(
        session,
        admin,
        "ci_token_created",
        "service_token",
        row.id,
        None,
        {"name": row.name, "prefix": row.prefix},
    )
    session.commit()
    return {**_out(row), "token": raw}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: str, admin: Admin, session: SessionDep) -> Response:
    row = scoped_get(session, ServiceToken, token_id)
    if row is None:
        # Another workspace's token and a missing one are the same answer.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token not found")
    if row.revoked_at is None:
        row.revoked_at = utc_now()
        _audit(
            session,
            admin,
            "ci_token_revoked",
            "service_token",
            row.id,
            {"name": row.name},
            None,
        )
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Runs: a CI job submits files and reads the verdict ------------------------------------


@router.post("/runs", response_model=CIRunStatus, status_code=status.HTTP_201_CREATED)
def create_run(
    body: CIRunRequest, principal: CIPrincipal, session: SessionDep, response: Response
) -> CIRunStatus:
    """Sends copy files through review. Sending the same thing again returns the same run."""
    if principal.user is not None and principal.user.role not in (
        Role.admin.value,
        Role.creator.value,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
    run, created = runs.submit(session, principal, body)
    if not created:
        response.status_code = status.HTTP_200_OK
    return runs.build_status(session, run)


@router.get("/runs/{run_id}", response_model=CIRunStatus)
def get_run(run_id: str, principal: CIPrincipal, session: SessionDep) -> CIRunStatus:
    run = scoped_get(session, CIRun, run_id)
    if run is None:
        # Another workspace's run and a missing one are the same answer.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return runs.build_status(session, run)


# --- Policy: what counts as a failure ------------------------------------------------------


class PolicySettings(BaseModel):
    severity_threshold: Severity = Severity.medium
    fail_on_unsure: bool = True
    # Approved rules whose findings never fail a run.
    ignore_rules: list[str] = Field(default_factory=list, max_length=100)
    # A review that takes longer than this is an error, never a pass.
    max_waiting_minutes: int = Field(default=15, ge=1, le=120)


def _settings(session: SessionDep) -> PolicySettings:
    policy = runs.load_policy(session)
    return PolicySettings(
        severity_threshold=policy.severity_threshold,
        fail_on_unsure=policy.fail_on_unsure,
        ignore_rules=sorted(policy.ignore_rules),
        max_waiting_minutes=policy.max_waiting_minutes,
    )


@router.get("/policy", response_model=PolicySettings)
def get_policy(principal: CIPrincipal, session: SessionDep) -> PolicySettings:
    """The workspace's policy. A CI job can read it, to say what will fail."""
    return _settings(session)


@router.put("/policy", response_model=PolicySettings)
def put_policy(
    body: PolicySettings, admin: Admin, session: SessionDep
) -> PolicySettings:
    if body.ignore_rules:
        try:
            approved = {rule.id for rule in rulebook_at(session)}
        except RulebookNotFound:
            approved = set()
        unknown = sorted(set(body.ignore_rules) - approved)
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Only approved rules can be ignored: {', '.join(unknown)} isn't one.",
            )
    row = session.scalar(scoped(session, CIPolicySetting))
    if row is None:
        row = CIPolicySetting()
        session.add(row)
    row.severity_threshold = body.severity_threshold.value
    row.fail_on_unsure = body.fail_on_unsure
    row.ignore_rules = sorted(set(body.ignore_rules))
    row.max_waiting_minutes = body.max_waiting_minutes
    row.updated_by = admin.id
    row.updated_at = utc_now()
    _audit(
        session,
        admin,
        "ci_policy_changed",
        "ci_policy",
        admin.org_id,
        None,
        body.model_dump(mode="json"),
    )
    session.commit()
    return _settings(session)
