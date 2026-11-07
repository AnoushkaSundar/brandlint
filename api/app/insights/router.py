"""Insights for managers and admins."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import SessionDep, current_user, require_roles
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
