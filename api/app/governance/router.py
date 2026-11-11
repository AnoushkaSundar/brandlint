"""Governance router. These routes exist only while USE_MOCK_ENGINE is false, the
flag the governance mock is mounted under.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.admin.ingest import draft_from_proposal
from app.auth.dependencies import CurrentUser, SessionDep, current_user, require_roles
from app.clients.flags import use_mock
from app.contracts import Proposal, ProposalKind, ProposalStatus, Role
from app.db import get_sessionmaker
from app.engine import evaluation, graph
from app.governance import agent, spot_checks
from app.governance.models import Proposal as ProposalRow
from app.tenancy import bound_org, org_sessions, scoped_get


class ProposalDecision(BaseModel):
    status: Literal["approved", "rejected"]


def _routes() -> APIRouter:
    routes = APIRouter(dependencies=[Depends(current_user)])

    @routes.post(
        "/run",
        response_model=list[Proposal],
        dependencies=[Depends(require_roles(Role.admin))],
    )
    def run(session: SessionDep) -> list[Proposal]:
        classify = graph.gateway_classify(
            org_sessions(get_sessionmaker(), bound_org(session))
        )

        def gate(proposal, rule):
            return evaluation.gate(
                proposal, rule, session, classify, model=graph.PINNED_MODEL
            )

        return agent.run(session, agent.gateway_draft(session), gate)

    @routes.get(
        "/proposals",
        response_model=list[Proposal],
        dependencies=[Depends(require_roles(Role.admin))],
    )
    def list_proposals(session: SessionDep) -> list[Proposal]:
        return agent.pending(session)

    @routes.get(
        "/spot-checks",
        dependencies=[
            Depends(require_roles(Role.reviewer, Role.manager, Role.legal, Role.admin))
        ],
    )
    def list_spot_checks(session: SessionDep) -> list[dict]:
        return spot_checks.sample(session)

    @routes.post(
        "/proposals/{proposal_id}",
        response_model=list[Proposal],
        dependencies=[Depends(require_roles(Role.admin))],
    )
    def decide(
        proposal_id: str,
        body: ProposalDecision,
        user: CurrentUser,
        session: SessionDep,
    ) -> list[Proposal]:
        """Only a person's decision moves a proposal, and it doesn't change the rule.

        An approved rewrite becomes a draft, which an admin approves in the rulebook.
        """
        row = scoped_get(session, ProposalRow, proposal_id)
        if row is None or row.status != ProposalStatus.pending.value:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such pending proposal")
        row.status = body.status
        rewrites = {ProposalKind.amendment.value, ProposalKind.term.value}
        if body.status == "approved" and row.kind in rewrites:
            draft_from_proposal(session, row.rule_id, row.suggested, user)
        session.commit()
        return agent.pending(session)

    return routes


def build_router() -> APIRouter:
    built = APIRouter(prefix="/governance", tags=["governance"])
    if not use_mock("ENGINE"):
        built.include_router(_routes())
    return built


router = build_router()
