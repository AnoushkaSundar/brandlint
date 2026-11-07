# Handoff to Alapan: Saturday 7 November 2026, evening

Anoushka built blocks 7–10 on her side, merged your open PRs during your handover, and ran the full demo with every `USE_MOCK_*=false` against the real model. This page covers the current state, what changed in your folders, how to run and check the demo, and what's left.

## Where things stand

- `main` is green. All features are merged, so the code freeze applies: bug-fix PRs only, reviewed by both of you.
- Demo steps 1–10 pass end to end against the real services on a fresh stack. `demo/check_demo.py` proves it (see below).
- Not done yet: two dry runs in the browser, the `v1.0` tag and the pitch.
- Open: **#40** (voting with a second provider). It isn't in the demo path, needs `GEMINI_API_KEY` in `.env.litellm`, and conflicts with `main`. Merge it only if there's time to rebase and rerun the demo check, otherwise leave it.
- Leftover branches you can delete: `chore/alapan-handoff`, `handover/alapan`.

## Merged since your handover

| PR | What | Demo step |
|---|---|---|
| #36–#39, #41 | Your fixer, gateway, memory, governance, damaged-file PRs, reviewed and approved under Anoushka's account | — |
| #34 | Restart failed reviews, recover dropped streams, keep hidden text visible | 2 |
| #35 | Accessibility checks and the Visual agent, as a "product" track in the graph | 2 |
| #43 | Guideline ingest, rule approval, brand admin screens | 1 |
| #44 | Impact view and re-review queue; null characters refused with a 422 | 7 |
| #45 | Proposals screen, disclosure panel, masking preview | 8, 9 |
| #46 | Insights signals and dashboard, memory graph view | 8, 10 |
| #47 | Ingest: stable rule ids, skipped clauses asked for again, separate conflict check | 1 |
| #48 | A real UNSURE item, and demo history so governance has evidence | 6, 8 |

## What changed in your folders

You handed these over, so they were changed without your review. Worth a read:

- **`api/app/engine/graph.py`, `reviews.py`, `replay.py` (#35):** a fourth track, `product`, runs `app.checks.run_product_checks` (accessibility, plus the Visual agent for images). Its candidates carry the manifest `{"kind": "product"}` and go through the critic with `PRODUCT_RULE_IDS` in `known_rule_ids`. Replay raises `NotReplayable` for them, because they need the original file.
- **`api/app/governance/router.py` (#45):** `GET /governance/proposals` lists pending proposals (admin). `POST /governance/proposals/{id}` with `approved` now also calls `app.admin.ingest.draft_from_proposal`, which creates a **draft** of the rule. An admin still approves it in the rulebook, so no proposal changes a rule in force.
- **`api/mocks/governance.py` (#45):** lists proposals and remembers decisions for the life of the process.
- **`api/mocks/gateway.py` (#43):** the mock ingest returns rule ids and `required_text`.
- **`docker-compose.yml`:** unchanged. The key file was `env.litellm` (not ignored by git). It's now `.env.litellm`, and it was never committed.

## Things the real run taught us

- **Rule ids come from the guideline, not the model.** The model invented `R-NEW-xx` ids, so terms and the visual checks (`R-TERM-03`, `R-VIS-01`) lost their findings, because the critic drops uncited ones. `app/admin/ingest.py` now builds ids from section headings and clause numbers (§3.3 under "3. Terminology" is `R-TERM-03`). The visual checks still hard-code `R-VIS-01` and `R-VIS-02` in `app/checks/visual/checks.py`.
- **Ingest makes up to three model calls:** the rules, once more for any numbered clause it skipped, then a separate conflict check over the drafted rules. A clause still missing, or a conflict check that failed, is shown on the Rulebook screen.
- **Borderline wording is fragile.** The blog's UNSURE item depends on the exact sentence "It is a risk worth taking seriously." Writing "It's" instead got a VIOLATION. Don't edit `BLOG` in `demo/build_demo.py` without probing again.
- **The real model varies on judgment rules.** For example, the LinkedIn post's §4.3 claim isn't always flagged, and the blog's tone finding is UNSURE where the mock says so. Every finding shown still cites a rule or fact. The verdict cache pins results once made.
- **The governance agent needs three confirmed overrides** of one judgment rule. `demo/seed_history.py` creates them through the real workflow, so it has to run after the rulebook is approved.

## Running the demo stack

Keys go in `.env.litellm` only (`ANTHROPIC_API_KEY`, optionally `GEMINI_API_KEY`). Your spending limit is already set. Set the three `USE_MOCK_*` flags to `false` in `.env`.

```bash
docker compose --profile local-llm up --build -d
docker compose --profile local-llm exec ollama ollama pull llama3.2:1b
docker compose exec api alembic upgrade head
docker compose exec api python -m app.auth.seed
docker compose exec api python -m app.admin.seed --without-rules   # the demo starts by ingesting
```

The Ollama image has a 3.2 GB layer. On a slow connection the first pull can fail with `unexpected EOF`. Run `docker compose --profile local-llm pull ollama` again and it resumes.

**To reset before a demo or dry run**, delete only the database volume. Keep the `ollama` volume, so the model doesn't download again:

```bash
docker compose stop api web && docker compose rm -f -s db
docker volume rm brandlint-repo_pgdata
```

Then run `up` and the four setup commands again.

**On the day:** right after step 1 (rulebook approved), run this while showing step 2:

```bash
docker compose exec api python /demo/seed_history.py
```

**To check every step without a browser:**

```bash
docker compose exec api python /demo/check_demo.py
```

- It runs steps 1–10 as each role and exits 1 if any check fails. The last run reported `PROBLEMS: none`.
- It calls the real model, so it costs a few cents.
- It adds content, so reset before presenting.

Every demo account uses the password `brandlint-demo`: `admin@`, `agency@`, `reviewer@`, `manager@` and `legal@tarnhollow.example`.

## Known gaps

- **Insights:** there's no filter by AI tool, and reviewers can't yet mark missed issues on a spot-check. Neither is in the demo script.
- **Browser tests:** each spec passes on its own. Run with four workers, the full Playwright suite once timed out on a few shell tests under load, and passed on a rerun with two (`npx playwright test --workers=2`).
- **Hydration warning:** the Next.js dev overlay showed one, from a browser extension adding attributes to `<html>` or `<body>`. This PR adds `suppressHydrationWarning` to those two tags only.
- **`R-REQ-02`:** it comes out of ingest as `must_include` with no `required_text`, because the guideline doesn't quote the exact words. `app/engine/checks/required.py` skips such a rule, so nothing checks it. Give it a `required_text` on the Rulebook screen if it should count.
- **Neo4j:** sync isn't part of the demo. The graph view reads the Postgres edge table.

## Left to do

1. Two dry runs in the browser, following `docs/demo.md`, with a reset before each.
2. Tag `v1.0` on `main` once the dry runs pass: `git tag -a v1.0 -m "BrandLint v1.0" && git push origin v1.0`.
3. The pitch.
4. Optional: #40.

## Repo settings

- `main` protection: 1 approving review; required checks `guard`, `python` and `web`; strict; linear history; **Include administrators on**.
- Anoushka merged her own PRs by switching Include administrators off for the merge only, then back on and checking it. It's on now.
