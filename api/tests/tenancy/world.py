"""Two organisations with data in every tenant table, for the isolation tests.

Every piece of text an org owns carries its sentinel (`marker`), so a response that
contains org A's sentinel while org B is asking is a leak, whatever route it came from.

The `org_id` plumbing is isolated in `make_org` and `org_kwargs`. Before Block 1 there
is no organizations table and no org_id column, so both do nothing and the two orgs
share one database, which is exactly the state the tests are meant to show failing.
Once the columns exist, rows get their org without any change to the builders.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from app.admin import models as admin
from app.auth.models import User
from app.auth.security import create_token
from app.ci.models import CIPolicySetting, CIRun, CIRunFile, ServiceToken
from app.content import storage
from app.content.models import Content, ContentVersion
from app.db import Base
from app.engine import models as engine
from app.engine.chunking import ParsedChunk
from app.engine.reviews import ReviewRun
from app.gateway.models import GatewayLog, TokenVault
from app.governance import models as governance
from app.memory.models import Edge
from app.workflow import models as workflow
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Org:
    id: str
    name: str


@dataclass(frozen=True)
class Person:
    id: str
    email: str
    role: str
    token: str


@dataclass
class OrgWorld:
    org: Org
    tag: str
    marker: str
    admin: Person
    reviewer: Person
    creator: Person
    # What a request can name: path parameters, query parameters and body fields.
    ids: dict = field(default_factory=dict)
    # Every identifier that belongs to this org, for spotting rows that refer to it.
    owned_ids: set[str] = field(default_factory=set)
    run: ReviewRun | None = None

    @property
    def people(self) -> tuple[Person, Person, Person]:
        return self.admin, self.reviewer, self.creator


@dataclass
class World:
    a: OrgWorld
    b: OrgWorld


def org_kwargs(model, org: Org) -> dict:
    """The org column for a row, once the model has one."""
    return {"org_id": org.id} if hasattr(model, "org_id") else {}


def make_org(session: Session, tag: str) -> Org:
    """Creates the organisation row if the organizations table exists yet."""
    org = Org(id=str(uuid.uuid4()), name=f"Org {tag}")
    table = Base.metadata.tables.get("organizations")
    if table is not None:
        values = {
            "id": org.id,
            "name": org.name,
            "slug": f"org-{tag.lower()}",
            "kind": "sandbox",
            "status": "active",
        }
        columns = {column.name for column in table.columns}
        session.execute(
            table.insert().values(**{k: v for k, v in values.items() if k in columns})
        )
        session.flush()
    return org


def _edge_id(kind: str, src_id: str, dst_id: str) -> str:
    return hashlib.sha256(f"{kind}|{src_id}|{dst_id}".encode()).hexdigest()


def _person(session: Session, org: Org, tag: str, role: str) -> Person:
    user = User(
        id=f"u-{tag}-{role}",
        email=f"{role}-{tag.lower()}@tenancy.test",
        name=f"{role.title()} {tag}",
        password_hash="not-used",
        role=role,
        **org_kwargs(User, org),
    )
    session.add(user)
    session.flush()
    return Person(id=user.id, email=user.email, role=role, token=create_token(user))


def build_org(session: Session, tag: str) -> OrgWorld:
    """Adds one organisation's users, content, review, findings, rules and the rest."""
    marker = f"ORG{tag}-SENTINEL-{uuid.uuid4().hex[:8]}"
    org = make_org(session, tag)

    def add(row_type, /, **fields):
        # Positional-only, because some tables have a column called "model".
        row = row_type(**fields, **org_kwargs(row_type, org))
        session.add(row)
        session.flush()
        return row

    admin_user = _person(session, org, tag, "admin")
    reviewer = _person(session, org, tag, "reviewer")
    creator = _person(session, org, tag, "creator")

    # Content: one piece waiting on a reviewer, one already published.
    text = f"{marker} Customers cut onboarding time by 80% on average."
    c1, c2 = f"c-{tag}-1", f"c-{tag}-2"
    v1, v2 = f"v-{tag}-1", f"v-{tag}-2"
    r1, r2 = f"r-{tag}-1", f"r-{tag}-2"
    eng1, eng2 = f"eng-{tag}-1", f"eng-{tag}-2"
    for content_id, state, label in (
        (c1, "reviewer_check", "Launch post"),
        (c2, "published", "Case study"),
    ):
        add(
            Content,
            id=content_id,
            title=f"{marker} {label}",
            channel="blog",
            source="in-house",
            data_class="public",
            state=state,
            creator_id=creator.id,
        )
    file_ref = f"{org.id}/{tag}-draft.txt"
    path = storage.stored_path(file_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    add(
        ContentVersion,
        id=v1,
        content_id=c1,
        version=1,
        text=text,
        file_ref=file_ref,
        file_name="draft.txt",
        created_by=creator.id,
    )
    add(
        ContentVersion,
        id=v2,
        content_id=c2,
        version=1,
        text=f"{marker} Published.",
        created_by=creator.id,
    )
    add(
        workflow.Review,
        id=r1,
        content_version_id=v1,
        engine_review_id=eng1,
        channel="blog",
        rulebook_version=1,
    )
    add(
        workflow.Review,
        id=r2,
        content_version_id=v2,
        engine_review_id=eng2,
        channel="blog",
        rulebook_version=1,
    )
    add(
        workflow.ReviewStateLog,
        id=f"sl-{tag}-1",
        content_id=c1,
        from_state="resolving",
        to_state="reviewer_check",
        actor_id=creator.id,
        reason=f"{marker} ready",
    )

    # The brand: an approved rule, a draft of another, a fact, a term and an asset.
    rule, draft, fact, term = f"R-{tag}-1", f"R-{tag}-D", f"F-{tag}-1", f"T-{tag}-1"
    add(
        admin.Rule,
        id=rule,
        version=1,
        type="judgment",
        text=f"{marker} Stay calm and helpful.",
        clause_ref="§2.2",
        severity="medium",
        channel_scope=[],
        status="approved",
    )
    add(
        admin.Rule,
        id=draft,
        version=2,
        type="judgment",
        text=f"{marker} A draft rule.",
        clause_ref="§9.9",
        severity="low",
        channel_scope=[],
        status="draft",
    )
    add(
        admin.Fact,
        id=fact,
        version=1,
        statement=f"{marker} Customers cut onboarding time by 38%.",
        value="38%",
        source_doc=f"{marker} Study",
        owner="Insights",
        valid_until=None,
        data_class="public",
    )
    add(
        admin.Term,
        id=term,
        preferred=f"{marker} new hire",
        banned=["newbie"],
        renamed_from=None,
        rule_id=rule,
        rule_version=1,
    )
    add(
        admin.Asset,
        id=f"A-{tag}-1",
        kind="palette",
        file_ref="",
        meta={"colours": ["#112233"], "name": f"{marker} palette"},
    )
    add(
        admin.IngestJob,
        id=f"j-{tag}-1",
        file_ref=f"{marker}.pdf",
        status="done",
        result={"version": 1, "rules": [rule], "conflicts": []},
        error=None,
        created_by=admin_user.id,
    )
    add(
        admin.Gap,
        id=f"g-{tag}-1",
        review_id=eng1,
        check="tone",
        text=f"{marker} Too breezy",
        explanation=f"{marker} No rule covers this.",
    )

    # The engine's side of review 1: the chunk, two findings and a claim that cites the fact.
    chunk_id = f"{v1}:0"
    add(
        engine.Chunk,
        id=chunk_id,
        content_version_id=v1,
        ordinal=0,
        kind="paragraph",
        text=text,
        content_hash=f"hash-{tag}",
        data_class="public",
        style=None,
    )
    f1, f2 = f"fnd-{tag}-1", f"fnd-{tag}-2"
    for finding_id, verdict, tier, severity, status in (
        (f1, "UNSURE", 1, "medium", "open"),
        (f2, "VIOLATION", 0, "low", "override_confirmed"),
    ):
        add(
            engine.Finding,
            id=finding_id,
            review_id=eng1,
            content_version_id=v1,
            unit_type="chunk",
            spans=[{"chunk_id": chunk_id, "start": 0, "end": len(text)}],
            check="tone",
            tier=tier,
            verdict=verdict,
            severity=severity,
            confidence=0.9,
            rule_id=rule,
            rule_version=1,
            fact_ids=[],
            cited_text=f"{marker} Stay calm and helpful.",
            explanation=f"{marker} This may be pushy.",
            trace={
                "steps": [
                    {
                        "tool": "classify",
                        "input_summary": "rule",
                        "output_summary": "hit",
                    }
                ],
                "sources": [rule],
                "model": None,
            },
            ai_generated=tier == 1,
            models_used=[],
            vote=None,
            fix_available=False,
            status=status,
            manifest={
                "kind": "language",
                "channel": "blog",
                "rulebook_version": 1,
                "chunk_id": chunk_id,
                "content_hash": f"hash-{tag}",
                "rule": {
                    "id": rule,
                    "version": 1,
                    "type": "judgment",
                    "text": f"{marker} Stay calm and helpful.",
                    "clause_ref": "§2.2",
                    "severity": "medium",
                    "channel_scope": [],
                    "status": "approved",
                },
                "flagged": False,
                "model": "claude-haiku-4-5",
            },
        )
    add(
        engine.ClaimUnit,
        id=f"cu-{tag}-1",
        review_id=eng1,
        content_version_id=v1,
        normalized_claim=f"{marker} onboarding time cut by 80%",
        span_refs=[],
        depends_on=[{"fact_id": fact, "version": 1}],
    )
    add(
        engine.ReviewCache,
        id=f"rc-{tag}-1",
        cache_key=f"cache-key-{tag}",
        unit_type="chunk",
        verdict="VIOLATION",
        payload={"note": marker},
        depends_on=[],
        manifest={},
    )

    # Decisions: a creator's override that a reviewer confirmed. It is the precedent for f1.
    add(
        workflow.Decision,
        id=f"d-{tag}-1",
        review_id=r1,
        finding_id=f2,
        actor_id=creator.id,
        role="creator",
        action="override",
        status="override_pending",
        reason=f"{marker} A direct quote.",
    )
    add(
        workflow.Decision,
        id=f"d-{tag}-2",
        review_id=r1,
        finding_id=f2,
        actor_id=reviewer.id,
        role="reviewer",
        action="confirm_override",
        status="override_confirmed",
        reason=None,
    )
    add(
        workflow.FixOffer,
        id=f"fo-{tag}-1",
        review_id=r1,
        finding_id=f1,
        attempt=1,
        original=f"{marker} before",
        suggested=f"{marker} after",
        diff=f"{marker} diff",
    )
    add(
        workflow.Comment,
        id=f"cm-{tag}-1",
        content_version_id=v1,
        finding_id=f1,
        span=None,
        parent_id=None,
        author_id=creator.id,
        body=f"{marker} Please check this.",
        mentions=[],
    )
    add(
        workflow.AuditLog,
        id=f"au-{tag}-1",
        actor_id=admin_user.id,
        role="admin",
        action="fact:edit",
        target_type="fact",
        target_id=fact,
        before={"value": f"{marker} old"},
        after={"value": f"{marker} new"},
        rulebook_version=1,
    )

    # Memory, gateway and governance.
    add(
        Edge,
        id=_edge_id("CITES", f"cu-{tag}-1", fact),
        type="CITES",
        src_type="Claim",
        src_id=f"cu-{tag}-1",
        dst_type="Fact",
        dst_id=fact,
        meta={"src_label": f"{marker} claim", "dst_label": fact},
    )
    add(
        GatewayLog,
        id=f"gl-{tag}-1",
        purpose="classify",
        data_class="public",
        rule_ids=[rule],
        provider="anthropic",
        model="claude-haiku-4-5",
        route="litellm",
        masked={"PRODUCT": 1},
        review_id=eng1,
        status="ok",
        latency_ms=12,
        error=None,
    )
    add(
        TokenVault,
        id=f"tv-{tag}-1",
        scope=eng1,
        token="[PRODUCT_1]",
        value=f"{marker}-codename",
        entity="PRODUCT",
    )
    add(
        governance.Proposal,
        id=f"p-{tag}-1",
        rule_id=rule,
        kind="amendment",
        current=f"{marker} Stay calm.",
        suggested=f"{marker} Stay calm, unless stating a fact.",
        evidence={"count": 3, "examples": []},
        eval={"passed": True, "precision": 1.0, "recall": 1.0},
        status="pending",
    )
    add(governance.SpotCheck, id=f"sc-{tag}-1", content_id=c2, review_id=eng2)
    add(
        governance.EvalRun,
        id=f"ev-{tag}-1",
        kind="gate",
        precision=1.0,
        recall=1.0,
        false_flag_rate=0.0,
        attack_success_rate=0.0,
        passed=True,
        details={"note": marker},
    )

    # A finished review the engine still holds in memory, which is where /chunks reads from.
    run = ReviewRun(
        review_id=eng1,
        content_version_id=v1,
        chunks=[
            ParsedChunk(
                chunk_id, v1, 0, "paragraph", text, f"hash-{tag}", "public", None
            )
        ],
    )
    run.finish("done", {"count": 2})

    token = add(
        ServiceToken,
        id=f"tok-{tag}-1",
        name=f"{marker} token",
        token_hash=hashlib.sha256(f"bl_unused-{tag}".encode()).hexdigest(),
        prefix="bl_unuse",
        created_by=admin_user.id,
    )

    ci_run = add(
        CIRun,
        id=f"run-{tag}-1",
        run_key=hashlib.sha256(f"key-{tag}".encode()).hexdigest(),
        repo=f"{tag.lower()}/repo",
        pr=1,
        sha="abc",
        state="done",
        result="pass",
        reasons=[],
        policy={},
    )
    add(
        CIRunFile,
        id=f"runfile-{tag}-1",
        run_id=ci_run.id,
        path=f"{marker}.md",
        text_hash=hashlib.sha256(f"text-{tag}".encode()).hexdigest(),
        size=10,
        content_id=c1,
        version_id=v1,
        review_id=r1,
    )

    add(CIPolicySetting, id=f"pol-{tag}-1", ignore_rules=[])

    ids = {
        "run_id": ci_run.id,
        "token_id": token.id,
        "content_id": c1,
        "version_id": v1,
        "content_version_id": v1,
        "review_id": eng1,
        "finding_id": f1,
        "fact_id": fact,
        "user_id": creator.id,
        "root": fact,
        "rule_id": draft,
        "approved_rule_id": rule,
        "term_id": term,
        "proposal_id": f"p-{tag}-1",
        "content_ids": [c1],
        "rule_ids": [draft],
    }
    owned = {
        c1,
        c2,
        v1,
        v2,
        r1,
        r2,
        eng1,
        eng2,
        f1,
        f2,
        fact,
        rule,
        draft,
        term,
        f"p-{tag}-1",
        f"A-{tag}-1",
        f"j-{tag}-1",
        f"g-{tag}-1",
        f"cm-{tag}-1",
        token.id,
        ci_run.id,
    }
    return OrgWorld(
        org=org,
        tag=tag,
        marker=marker,
        admin=admin_user,
        reviewer=reviewer,
        creator=creator,
        ids=ids,
        owned_ids=owned,
        run=run,
    )


def build_world(session: Session) -> World:
    world = World(a=build_org(session, "A"), b=build_org(session, "B"))
    session.commit()
    return world
