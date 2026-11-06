from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.admin.brand import list_assets, list_facts, list_terms, visible_facts
from app.admin.gaps import save_gaps
from app.admin.rulebook import RulebookNotFound, rulebook_at
from app.auth.dependencies import CurrentUser, SessionDep, current_user, require_roles
from app.contracts import Asset, Fact, Gap, Role, Rule, Term

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(current_user)]
)


@router.get("/rulebook", response_model=list[Rule])
def get_rulebook(
    session: SessionDep, version: Annotated[int | None, Query(ge=1)] = None
) -> list[Rule]:
    try:
        return rulebook_at(session, version)
    except RulebookNotFound:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "There's no approved rulebook at that version."
        ) from None


@router.get("/facts", response_model=list[Fact])
def get_facts(session: SessionDep, user: CurrentUser) -> list[Fact]:
    return visible_facts(list_facts(session), user.role)


@router.get("/terms", response_model=list[Term])
def get_terms(session: SessionDep) -> list[Term]:
    return list_terms(session)


@router.get("/assets", response_model=list[Asset])
def get_assets(session: SessionDep) -> list[Asset]:
    return list_assets(session)


@router.post("/gaps", dependencies=[Depends(require_roles(Role.admin))])
def post_gaps(gaps: list[Gap], session: SessionDep) -> dict[str, int]:
    saved = save_gaps(session, gaps)
    session.commit()
    return {"saved": saved}
