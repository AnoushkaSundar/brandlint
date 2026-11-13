"""Insights for managers and admins."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import SessionDep, current_user, require_roles
from app.ci import auth as ci_auth
from app.ci.insights import summary as ci_summary
from app.contracts import Role
from app.insights.signals import signals

router = APIRouter(
    prefix="/insights",
    tags=["insights"],
    dependencies=[
        Depends(current_user),
        Depends(require_roles(Role.manager, Role.admin)),
    ],
)


@router.get("/signals")
def get_signals(
    session: SessionDep,
    channel: Annotated[str | None, Query(max_length=32)] = None,
    source: Annotated[str | None, Query(max_length=255)] = None,
) -> dict:
    return signals(session, channel=channel, source=source)


@router.get("/ci", dependencies=[Depends(ci_auth.require_enabled)])
def get_ci(session: SessionDep) -> dict:
    """CI runs over the last month: results, how long they took, why they errored, token use."""
    return ci_summary(session)
