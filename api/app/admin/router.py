from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.admin import edits, ingest
from app.admin.brand import list_assets, list_facts, list_terms, visible_facts
from app.admin.gaps import save_gaps
from app.admin.rulebook import RulebookNotFound, rulebook_at
from app.auth.dependencies import CurrentUser, SessionDep, current_user, require_roles
from app.auth.models import User
from app.content import rereview
from app.contracts import Asset, AssetKind, Fact, Gap, Role, Rule, Term
from app.memory import queries as memory

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(current_user)]
)

Admin = Annotated[User, Depends(require_roles(Role.admin))]


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


@router.post("/facts", response_model=Fact, status_code=status.HTTP_201_CREATED)
def post_fact(body: edits.FactIn, user: Admin, session: SessionDep) -> Fact:
    fact = edits.create_fact(session, body, user)
    session.commit()
    return fact


@router.put("/facts/{fact_id}")
def put_fact(
    fact_id: str, body: edits.FactIn, user: Admin, session: SessionDep
) -> dict:
    """Saves a new version and says which pieces cite this fact, for the impact view."""
    fact = edits.update_fact(session, fact_id, body, user)
    session.commit()
    return {
        "fact": fact.model_dump(mode="json"),
        "impact": memory.impact(fact_id, session),
    }


@router.post("/terms", response_model=Term, status_code=status.HTTP_201_CREATED)
def post_term(body: edits.TermIn, user: Admin, session: SessionDep) -> Term:
    term = edits.create_term(session, body, user)
    session.commit()
    return term


@router.put("/terms/{term_id}", response_model=Term)
def put_term(
    term_id: str, body: edits.TermIn, user: Admin, session: SessionDep
) -> Term:
    term = edits.update_term(session, term_id, body, user)
    session.commit()
    return term


@router.post(
    "/assets/palette", response_model=Asset, status_code=status.HTTP_201_CREATED
)
def post_palette(body: edits.PaletteIn, user: Admin, session: SessionDep) -> Asset:
    asset = edits.add_palette(session, body, user)
    session.commit()
    return asset


@router.post("/assets", response_model=Asset, status_code=status.HTTP_201_CREATED)
def post_asset(
    user: Admin,
    session: SessionDep,
    kind: Annotated[AssetKind, Form()],
    file: Annotated[UploadFile, File()],
) -> Asset:
    data = file.file.read(edits.storage.MAX_UPLOAD_BYTES + 1)
    asset = edits.add_image_asset(session, kind, file.filename or "", data, user)
    session.commit()
    return asset


class ApproveIn(edits.BaseModel):
    rule_ids: list[str]


@router.post("/ingest", status_code=status.HTTP_201_CREATED)
def post_ingest(
    user: Admin, session: SessionDep, file: Annotated[UploadFile, File()]
) -> dict:
    """Reads a guideline into draft rules. Nothing goes live until an admin approves."""
    data = file.file.read(edits.storage.MAX_UPLOAD_BYTES + 1)
    if len(data) > edits.storage.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "Files can be up to 10 MB."
        )
    job = ingest.ingest(session, file.filename or "", data, user)
    session.commit()
    return {
        "id": job.id,
        "status": job.status,
        "error": job.error,
        "result": job.result,
    }


@router.get("/rules/drafts", dependencies=[Depends(require_roles(Role.admin))])
def get_drafts(session: SessionDep) -> dict:
    return {
        "version": ingest.next_version(session),
        "drafts": [rule.model_dump(mode="json") for rule in ingest.drafts(session)],
        "conflicts": ingest.latest_conflicts(session),
    }


@router.put("/rules/{rule_id}/draft", response_model=Rule)
def put_draft(
    rule_id: str, body: ingest.DraftEdit, user: Admin, session: SessionDep
) -> Rule:
    rule = ingest.edit_draft(session, rule_id, body, user)
    session.commit()
    return rule


@router.delete("/rules/{rule_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(rule_id: str, user: Admin, session: SessionDep) -> None:
    ingest.reject_draft(session, rule_id, user)
    session.commit()


@router.post("/rules/approve")
def post_approve(body: ApproveIn, user: Admin, session: SessionDep) -> dict:
    version = ingest.approve(session, body.rule_ids, user)
    session.commit()
    return {"version": version}


class RereviewIn(edits.BaseModel):
    content_ids: list[str]


@router.post("/facts/{fact_id}/rereview")
def post_rereview(
    fact_id: str, body: RereviewIn, user: Admin, session: SessionDep
) -> dict:
    """Asks for another review of pieces that cite a fact. Only affected pieces."""
    affected = {item["content_id"] for item in memory.impact(fact_id, session)}
    outside = sorted(set(body.content_ids) - affected)
    if not body.content_ids or outside:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose pieces that cite this fact.",
        )
    queued = rereview.queue(session, fact_id, body.content_ids, user)
    session.commit()
    return {"queued": queued}
