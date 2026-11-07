# Handover from Alapan

Anoushka, Alapan is away and is handing his part to you. He'll confirm with you directly that you can work in his folders (`api/app/engine/`, `gateway/`, `memory/`, `governance/`, `docker-compose.yml`, `.github/`) and merge his PRs until he's back. `CLAUDE.md` assigns those folders to him, so that has to come from him and you, not from this file.

Everything is pushed. No work is only on Alapan's machine.

## 1. Merge order

All of Alapan's PRs need just your approval. CI is green on #33 to #40. Use squash merges. **Don't pass `--delete-branch` on a PR that another PR is stacked on:** last time that closed the child PR (#18) and lost its approval. The repo deletes branches by itself, and GitHub moves the child onto `main`.

| Order | PR | What | Notes |
|---|---|---|---|
| 1 | #33 | Tone-drift document pass | |
| 2 | #36 | Fixer: "Suggest fix" works on the real engine | Stacked on #33. Moves to `main` by itself when #33 merges |
| 3 | #37 | Gateway: policy, leak check, local route, disclosure, masking preview, access checks | Turns off the gateway mock |
| 4 | #38 | Memory: impact, precedents, graph | Turns off the memory mock. Impact and graph are staff-only |
| 5 | #39 | Governance agent, eval gate, spot-checks, eval set | Stacked on #38. Conflict below |
| 6 | #41 | Refuse a damaged DOCX or PDF before review | Conflict below |
| 7 | #40 | Voting with a second provider on claims | Draft, stacked. Rebase on `main` once 1–5 are in, then mark ready |
| 8 | #42 | README, contracts, design | Shared files. Merge last |

Merges need the branch up to date with `main`, so press "Update branch" before each one.

**Known conflicts.** Both are small, and both only need everything kept:
- **#39 after #37:** in `api/app/engine/router.py`, keep both import lines:
  ```python
  from app.admin.rulebook import rulebook_at
  from app.auth.dependencies import CurrentUser, SessionDep, current_user, require_roles
  ...
  from app.engine import evaluation, graph, models, replay, reviews
  from app.engine.access import require_review
  ```
- **#41 after #36:** in `api/app/clients/engine.py`, both add `from fastapi import HTTPException, status`. Keep one copy, and keep both functions.

**Your own PRs (#34, #35):** GitHub won't let you approve your own PR. Your admin role may let you merge anyway. If not, ask Alapan for an approval when he's back. #35 matters most: until it's in and connected, the banner gets no findings at all.

## 2. Keys

Model keys go in `.env.litellm` in the repo root, never `.env` and never git. Only the LiteLLM container reads that file.

```
ANTHROPIC_API_KEY=...   # required. Your own, or ask Alapan privately; never in chat history or git
GEMINI_API_KEY=...      # optional: the second voter in #40. Free key from Google AI Studio
```

Never give the `litellm` service `.env`, because its `DATABASE_URL` makes LiteLLM rewrite our database. Never install LiteLLM 1.82.7 or 1.82.8.

## 3. What's been tested

All of this is with mocks off, real models, on a temporary branch combining all the PRs.

**Works:**
- **Demo path:** upload to published, with fixes, an override, and reviewer, manager and legal. Replay identical.
- **Speed:** first finding in under 0.2 seconds. A new blog takes about 12 seconds with voting, under 2 seconds from cache.
- **Eval:** 10 of 10 planted issues found, 0 of 7 attacks got through. Precision is 91%, because R-TONE-02 is flagged on the blog. Please decide whether that's a real issue, and check `also_true` in `eval/expected.json`.
- **Outages:** with the model proxy or Presidio down, or the API restarted mid-review, nothing passed silently and recovery worked.
- **Abuse:** another creator can't read your draft, workflow abuse is refused, and parallel fixes respect the 2-attempt limit.
- **Setup:** following the README from a fresh clone works.

**Re-run the tests:**
- `scripts/e2e/demo_path.py`: the demo over HTTP.
- `scripts/e2e/abuse.py`: bad uploads, wrong ids, access, workflow abuse.
- `scripts/e2e/stages.py memory|governance|outage <name>`: precedents, step 8, outages.

They call `http://localhost:8000` with the seeded demo users. Run them inside the API container, ideally against a separate database. They're throwaway scripts, not tests to keep.

## 4. What's left, most important first

**The demo can't show these yet. All are yours, apart from step 2:**
1. **#35 merged, then the banner connected to the engine:** add `run_product_checks` to the graph and `PRODUCT_RULE_IDS` to `known_rule_ids`. Ask your Claude Code to do it in `api/app/engine/graph.py`.
2. **Screens for APIs that already work:** the disclosure panel and masking preview (step 9), the impact view (step 7), the graph view (step 10), and proposals (step 8). Those pages are placeholders. The APIs are in `docs/contracts.md` and the PRs above.
3. **Step 7:** there's no route to edit a fact.
4. **Step 1:** guideline ingest and rule approval have no backend.
5. **Step 8:** insights, and applying an approved amendment to the rulebook. The governance agent counts overrides itself, so `/insights/signals` isn't strictly needed.
6. **Bug:** pasted text with a null character gives a 500 in `POST /content`.

**For the submission:**
7. Run the demo through the browser with every `USE_MOCK_*=false`, which has never been done.
8. Two dry runs, then tag `v1.0`. Run each demo piece once beforehand so the review comes from the cache.
9. The pitch deck. Numbers you can use: 10 of 10 planted issues, 0 of 7 attacks, first finding under 0.2 seconds, identical Replay. Don't quote precision until the labels are agreed.

**Optional:** the local model (it needs a server, too slow on a laptop), Neo4j (skipped, the graph reads Postgres), and `recheck` (not built, the cache covers it).

## 5. Things that will surprise you

- **Free-tier data:** the second voter uses Google's free tier, which may use submitted data, so only `public` data reaches it.
- **Fix attempts:** the count is held in memory, so restarting the API resets it.
- **Your mock gateway:** it has no responses for the purposes `fix` and `governance`. Real-engine tests on the mock gateway will 422 there.
- **Deadline:** `docs/timeline.md` says Saturday 7 November. Alapan thought it was a day later, so check with the organisers.
