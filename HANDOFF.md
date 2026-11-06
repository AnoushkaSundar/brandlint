# BrandLint — handoff note (Alapan)

_Snapshot: 2026-11-06. Written for a fresh Claude session or Alapan picking this up on another machine. Source of truth is always GitHub + `CLAUDE.md` + `docs/`; this is just a fast-start._

## Who / where
- Repo: `AnoushkaSundar/brandlint` (public github.com). Alapan commits as **AlapanSen / senalapan62@gmail.com** (repo-local git config).
- `gh`/git push use the github.com keychain token; the SAP GitHub MCP **cannot** touch github.com — use `GH_HOST=github.com gh ...`.
- Alapan owns `api/app/engine|gateway|memory|governance/`, `requirements/engine.txt`, `docker-compose.yml`, `.github/`. Anoushka owns `web/`, `api/app/auth|content|workflow|admin|insights/`, `api/app/checks/*`, `api/mocks/`, `demo/`, `requirements/product.txt`. Shared (both approve): `api/app/contracts/`, `api/app/main.py`, `api/migrations/`, `docs/`, `CLAUDE.md`.

## State of main (HEAD `5234eae`, tagged `v0.1`)
Merged and live: repo/CI/compose, Next.js shell, gateway `llm.call` stub + `gateway_log`, API skeleton (`main.py` router auto-discovery) + engine/memory/governance tables, **contracts v1 + v2**, auth + 5 roles + product tables, mocks (serve `/engine|/gateway|/memory` from demo brand, flag-gated via `api/app/clients/`), Tarnhollow demo brand, parsers.
- **Single Alembic head: `anoushka_0001`** (chain: `alapan_0001` → `alapan_0002` → `anoushka_0001`). Keep it single.

## Open PRs
| PR | Branch | Owner | Status | Next |
|----|--------|-------|--------|------|
| **#16** | `feat/alapan-tier0` | me | tier-0 checks + router, all 5 review fixes vs contracts/v2; CI green; **awaiting Anoushka** | she reviews → **I merge = block 3 done** |
| **#15** | `chore/alapan-uploads-volume` | me | compose `uploads` volume + `UPLOAD_DIR`; **awaiting Anoushka** | she reviews → I merge |
| **#13** | `feat/anoushka-content` | hers | I approved | she merges |
| **#14** | `feat/anoushka-review-screen` | hers | draft | she rebases after #13 |
| ~~#11~~ | — | me | **closed** — superseded by #16 | — |

## Next: block 4 (Alapan) — Gate v0.2
Branches `feat/alapan-language-agent`, `feat/alapan-findings-stream`:
- **LangGraph fixed graph**, four parallel tracks: tier-0 code checks, chunk checks (Language), claims, document pass. No free-form planning.
- **Language agent**: per chunk × applicable judgment rule, `llm.call(purpose="classify")`. Output schema `{rule_id, verdict, span, confidence, explanation}` only; temp 0; pinned model; 2–3 anchored examples; content in a delimited "material to judge" block; one control question whose answer code knows (wrong answer → verdicts UNSURE); if an injection detector fired on the chunk, PASS → UNSURE.
- **Critic (code)**: uncited findings → `POST /admin/gaps`; dedupe overlapping spans; lower confidence on specialist conflict.
- **Findings stream**: `GET /engine/reviews/{id}/findings` as SSE, tier-0 first (<1s), rest as each track finishes.
- **Gateway masking**: Presidio + a confidential deny-list (from `/admin/facts` confidential + codenames) + our numbered tokens (`[PRODUCT_1]`) in `token_vault`, unmask after the call. (`token_vault` table still to be created — gateway-owned.)
- At the end: set `USE_MOCK_ENGINE=false` for text, test one real piece together.

## Deferred engine TODOs (carry into block 4)
- Real `GET /engine/reviews/{id}/chunks` (needs review orchestration to persist chunks; mock serves it now). Contract + mock already exist (contracts/v2 + #13).
- When real `/engine` endpoints land, the real engine router must **stand down while `USE_MOCK_ENGINE=true`** (else it collides with the mock mounted via `app/clients/router.py`). Suggested: guard with `not use_mock("ENGINE")`.
- Commit **explicitly** in engine write routes — `app/db.get_session` commits after the response, so a read-straight-after-write can miss it (Anoushka's note on #13).

## Workflow gotchas
- Never push `main`. One branch per feature (`feat/alapan-<task>`). Squash-merge + delete. Both approve shared files.
- Rebase before generating migrations; prefix `alapan_`; keep one Alembic head (whoever merges second re-chains `down_revision` or runs `alembic merge heads`).
- A rebase/force-push **sometimes** dismisses an approval (stale-review) and sometimes not — always check `reviewDecision` before merging; never self-approve your own PR.
- Branch protection on `main` is live (1 non-author approval, status checks `guard`/`python`/`web`, no bypass). **Code-owner auto-request is OFF** — request each other by hand.

## Verifying locally (no project venv committed)
- Lint: `uvx ruff check api` (keep committed code clean; CI enforces at least `RUF100` — avoid stray `# noqa`).
- Guard: `./scripts/check_llm_imports.sh` (no LLM provider SDK outside `api/app/gateway/`).
- Tests (code uses `X | None` → **needs Python 3.11+**):
  ```
  cd api && uv run --python 3.11 \
    --with pydantic --with 'sqlalchemy>=2' --with fastapi --with httpx \
    --with pyjwt --with argon2-cffi --with alembic --with 'psycopg[binary]' \
    --with python-docx --with pymupdf --with beautifulsoup4 --with pytesseract --with pillow \
    --with pytest pytest -q
  ```
  (OCR test skips without the `tesseract` binary. Full suite was 185 passed / 1 skipped.)

## Moving machines
- All work is pushed; `git clone` is cleaner than a zip. In a fresh clone re-set repo git identity (above) and `gh auth login --hostname github.com && gh auth setup-git`.
- This chat transcript + memory live in `~/.claude/projects/-Users-I740416-brandlint/` (not the repo). To resume the same chat, copy that dir to the new `~/.claude/projects/` under the key matching the repo's absolute path.
