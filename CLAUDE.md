# BrandLint

Hackathon entry for Inkloom AI's brand-governance problem statement. Team **anoushkasundar**: Alapan Sen and Anoushka Sundar. **Deadline: Saturday 7 November 2026.**

BrandLint is a pre-publication brand-governance platform. It turns an organisation's brand guidelines, approved facts, terminology and assets into a versioned rulebook, then reviews every draft (text, DOCX, PDF, HTML, images) against it before publication.
- **Checks:** tone, terminology, messaging, unsupported claims, visual misuse and accessibility.
- **Every finding:** cites the rule or fact it breaks and offers a minimal fix that keeps the creator's intent.
- **Decisions:** people make every one.

## Before you do anything

1. **Find out who you are working for.** Ask "Am I working for Alapan or Anoushka, and which block?" unless the user has already said. Then read:
   - `docs/timeline.md`: what is due in each block
   - `docs/tasks/alapan.md` or `docs/tasks/anoushka.md`: that person's full build brief
   - `docs/contracts.md`: the shared data formats and service interfaces
   - `docs/design.md`: architecture and the reasons behind it
   - `docs/demo.md`: demo script, demo data and acceptance criteria
2. **Only edit files that person owns** (see Ownership below). If a task needs a change in the other person's folder or in a shared file, stop and tell the user. Don't make the change yourself.
3. **Rebase before starting:** `git checkout main && git pull --rebase`, then create the block's branch from `docs/timeline.md`.

## Non-negotiable principles

- **No source, no flag.** A finding shown to a user must cite a rule clause or an approved fact. Uncited findings go to the guideline-gap log, never to the creator.
- **Agents propose, people decide.** Never auto-publish, auto-approve or auto-apply a fix. No AI component can create, change or approve a rule.
- **Deterministic verdicts.**
  - Pass/fail comes from code (tier 0) or constrained AI classification (tier 1): a fixed verdict enum per given rule ID, temperature 0, pinned model, cached.
  - Generated text (tier 2, fixes and amendment drafts) never decides pass/fail.
- **Every LLM call goes through `llm.call()` in `api/app/gateway`.** Never import an LLM provider SDK (openai, anthropic, google-genai, litellm, etc.) anywhere else. CI fails if you do.
- **Severity-gated overrides:**
  - low/medium: the creator can override with a reason, and a reviewer confirms;
  - high/critical: only a reviewer can override.
  - UNSURE findings block approval until a reviewer resolves them.
- **Pin the rulebook version per review.** The fixer gets at most 2 attempts.

## Querying tenant data

Each organisation is an isolated workspace (see `docs/multitenancy.md`). A table that belongs to one org has an `org_id`, and it is queried **only** through `app.tenancy`, never with a hand-written `.where(org_id == ...)` or a plain `session.get`:

| Instead of | Use |
|---|---|
| `select(Model)` | `scoped(session, Model)`, then `.where(...)` as usual. Pass columns to select those: `scoped(session, Model, Model.id)` |
| `session.get(Model, id)` | `scoped_get(session, Model, id)`. Another org's row and a missing row both give `None`, so an id can't be used to find out whether it exists. A plain `get` ignores the org. |
| `.join(Other, on)` | `scoped_join(statement, session, Other, on)` |
| `update(Model)` / `delete(Model)` | `scoped_update(session, Model)` / `scoped_delete(session, Model)` |

- **The org comes only from the signed-in user.** Take `CurrentOrg` (`from app.tenancy.context import CurrentOrg`) in a route. It ties the session to the user's org, so the helpers need no `org_id`. A background job passes `org_id=` itself. Never read an org from a body, path, query, header or the token.
- **Safe by default.** The helpers raise `NotTenantModel` for a model without `org_id`, `NoOrg` when there is no org, and `OrgMismatch` when a query or a new row names a different org from the request's. A row added in a request is put in the caller's org.
- **The CI check** (`api/tests/tenancy/test_unscoped_queries.py`) fails when any file under `api/app` queries a tenant model without a helper. The baseline in `api/tests/tenancy/unscoped_baseline.json` is empty, so it only ever goes up through a decision to allow a query, and a new one needs `# unscoped-ok`. `python -m tests.tenancy.queries` lists every query it found.
- **A query that is right without a scope** (looking a user up by email to find their org) carries `# unscoped-ok: <reason>` on its line or alone on the line above.
- **A blind spot:** the check reads names, so it can't see a model passed around as a variable. Convert those by hand.
- `organizations` is the only shared table. It is queried directly.
- **The database is a second lock.** Row-Level Security refuses another org's rows even if a query forgets its filter (`docs/rls.md`). The API connects as `brandlint_app`, never as the owner or a superuser, which would bypass it. `users` has it too, with a way through for the two lookups made before the org is known (`auth_lookup`).

## Stack

- **Web:** Next.js (App Router, TypeScript), Tailwind CSS, shadcn/ui.
- **API:** FastAPI (Python 3.11+), SQLAlchemy 2, Alembic, Pydantic v2.
- **Agents:** LangGraph, as a fixed graph rather than a free-form planner.
- **Data:** PostgreSQL + pgvector. The graph is a Postgres edge table; Neo4j sync is for the graph view only.
- **AI gateway:**
  - our own policy layer plus Microsoft Presidio (masking with numbered tokens such as `[PRODUCT_1]`);
  - a LiteLLM proxy that holds all provider keys. **Pin its version and verify hashes; never install 1.82.7 or 1.82.8, which were malicious.**
  - Ollama for restricted data.
- **Parsing:** python-docx, PyMuPDF, BeautifulSoup, Tesseract OCR.
- **Local dev:** `docker compose up` (services: db, api, web).

## Ownership (also enforced by `.github/CODEOWNERS`)

**Alapan: AI engine, backend, security**
- `api/app/engine/`: parsers, chunking, tier-0 code checks, agents (Language, Claims), critic, cache + Replay, voting, fixer, injection defences
- `api/app/gateway/`: `llm.call`, masking, policy, routing, leak check, Ollama route
- `api/app/memory/`: graph edges, impact analysis, precedents, Neo4j sync
- `api/app/governance/`: governance agent, amendment drafts, spot-check sampler
- `requirements/engine.txt`, `docker-compose.yml`, `.github/`

**Anoushka: product, workflow, governance UI, visual checks**
- `web/`: the whole frontend, including `package.json` and the lockfile
- `api/app/auth/`, `api/app/content/`, `api/app/workflow/`, `api/app/admin/` (including the ingest agent), `api/app/insights/` (analytics)
- `api/app/checks/visual/`, `api/app/checks/accessibility/`
- `api/mocks/`, `demo/`, `requirements/product.txt`

**Shared: change only at a sync point, through a PR both approve**
- `api/app/contracts/`: frozen after block 2; changes go in their own `contracts/vN` PR
- `api/app/main.py`: written once in block 2. Routers are auto-discovered from `api/app/**/router.py`, so never edit it to add an endpoint.
- `api/migrations/`: add files only for your own tables, prefixed `alapan_` or `anoushka_`
- `eval/` (append-only), `.env.example`, `README.md`, `CLAUDE.md`, `docs/`

## Git rules

- Never push to `main`. One short-lived branch per feature: `feat/<person>-<task>`, never older than one block.
- Commit small and often, and push at least twice per block. Open a draft PR early.
- Merge window at the end of every block: the other person reviews, CI must pass, then squash-merge and delete the branch.
- Before generating a migration, rebase on main. If two Alembic heads appear, whoever merges second runs `alembic merge heads` in the same PR.
- Mocks: Anoushka's code calls Alapan's services through `api/app/clients/` and `web/lib/engineClient.ts`. Per-service flags (`USE_MOCK_ENGINE`, `USE_MOCK_GATEWAY`, `USE_MOCK_MEMORY`) switch between `api/mocks/` and the real services.
- **Code freeze:** every feature is merged by the end of block 9. From the middle of block 10, only bug-fix PRs, reviewed by both. The release tag is `v1.0`.

## Commands

```bash
docker compose up --build             # run everything
docker compose exec api pytest        # backend tests
docker compose exec api alembic upgrade head
cd web && npm run dev                 # frontend only
cd web && npx playwright test         # end-to-end tests
docker compose exec api pytest tests/tenancy      # isolation suite
RLS_TEST_DATABASE_URL=<superuser url> docker compose exec api pytest tests/test_rls.py  # RLS, needs Postgres
python demo/check_workspaces.py                   # two workspaces on a running stack (no model calls)
docker compose exec api python -m app.tenancy.expiry   # delete expired sandbox workspaces
```

Update this section when the real commands differ.

## Definition of done for any task

- It works against the contracts in `docs/contracts.md`, and the tests pass.
- Backend rules (permissions, overrides, state transitions) are enforced on the server, not only in the UI.
- No provider SDK is imported outside the gateway, and no secrets are committed.
- At the end of the block, report: what works, what's still mocked, what's left, and any contract change needed.
