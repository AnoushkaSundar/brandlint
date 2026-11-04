# Build timeline (deadline: Saturday 7 November 2026)

There are 10 blocks of about 3–4 hours each, three a day: morning, afternoon and evening. Every block ends with a merge window. Every feature is merged by the end of block 9, and from the middle of block 10 only bug fixes are merged.

| Block | Slot | Alapan | Anoushka | Merge & sync |
|---|---|---|---|---|
| 1 | Wed 4 Nov, evening | Repo, branch protection, CODEOWNERS, CI (lint, tests, LLM-SDK import check), docker-compose · `chore/repo-setup` | Next.js shell in `web/`, Tailwind, shadcn/ui, layout and nav · `feat/anoushka-web-shell` | Pair for an hour on `api/app/contracts` in one PR (`contracts/v1`); Alapan merges it, both rebase |
| 2 | Thu 5 Nov, morning | FastAPI skeleton with router auto-discovery, engine tables + migration (`alapan_`), gateway stub `llm.call` · `feat/alapan-api-skeleton`, `feat/alapan-gateway-stub` | Login + 5 roles, her tables + migration (`anoushka_`), mocks under `api/mocks/`, demo brand files · `feat/anoushka-auth`, `feat/anoushka-mocks`, `feat/anoushka-demo-brand` | Alapan merges first, Anoushka rebases and merges. **Gate v0.1:** contracts frozen |
| 3 | Thu 5 Nov, afternoon | Parsers (text, DOCX, PDF, HTML, image OCR), stable chunking, hashes; tier-0 checks (terms, fact expiry, hidden text, required elements) · `feat/alapan-parsers`, `feat/alapan-tier0` | Content upload and versions; review screen layout against the mock stream · `feat/anoushka-content`, `feat/anoushka-review-screen` | Normal merge window |
| 4 | Thu 5 Nov, evening | Language agent, critic, findings stream (SSE), gateway masking · `feat/alapan-language-agent`, `feat/alapan-findings-stream` | Finding cards (cited source, trace, AI badge), diff view · `feat/anoushka-finding-cards`, `feat/anoushka-diff-view` | Set `USE_MOCK_ENGINE=false` for text and test one piece together. **Gate v0.2** |
| 5 | Fri 6 Nov, morning | Claims agent with claim units, verdict cache + Replay, tone-drift document pass · `feat/alapan-claims`, `feat/alapan-cache-replay` | Severity-gated overrides + state machine (server-enforced), role and override tests · `feat/anoushka-workflow` | Normal merge window |
| 6 | Fri 6 Nov, afternoon | Voting (3 rubrics, plus a second model for legal and claims), fixer with diff check (max 2), injection defences · `feat/alapan-voting`, `feat/alapan-fixer`, `feat/alapan-injection` | Reviewer queue (UNSURE items, pending overrides), comments, version history, audit view · `feat/anoushka-reviewer-queue`, `feat/anoushka-audit` | All 3 demo pieces through the workflow. **Gate v0.3** |
| 7 | Fri 6 Nov, evening | Graph edges, impact and precedent endpoints, gateway policy engine · `feat/alapan-graph-impact`, `feat/alapan-policy` | Accessibility checks; Visual agent (logo, palette, OCR text, AI imagery check) · `feat/anoushka-a11y-checks`, `feat/anoushka-visual-agent` | Normal merge window |
| 8 | Sat 7 Nov, morning | Leak check, Ollama route for restricted data, disclosure + masking-preview + eval-gate endpoints, eval runner · `feat/alapan-leak-check`, `feat/alapan-ollama-route`, `feat/alapan-eval` | Ingest agent with conflict detection + rule approval; facts, terms and assets admin · `feat/anoushka-ingest`, `feat/anoushka-brand-admin` | Normal merge window |
| 9 | Sat 7 Nov, afternoon | Governance agent (amendment drafts through the eval gate), spot-check sampler, Neo4j sync + graph endpoint; turn off his mock flags · `feat/alapan-governance`, `feat/alapan-neo4j` | Insights dashboard + proposal approval screen, spot-check queue, impact view, graph view, disclosure panel + masking preview · `feat/anoushka-insights`, `feat/anoushka-disclosure` | **All features merged.** Run the demo script end to end. **Gate v0.4** |
| 10 | Sat 7 Nov, evening | Integration fixes, prompt tuning on the eval set, Replay check, latency and eval numbers, README + setup steps · `fix/alapan-*` | Playwright E2E suite, UI polish, accessibility pass of the app itself, pitch deck, final demo data · `fix/anoushka-*` | **Code freeze from mid-block.** Two dry runs, submit with buffer, tag `v1.0` |

## Rhythm inside every block

1. **Sync up (10 minutes):** what merged, what's blocked, any contract question. Then `git checkout main && git pull --rebase && git checkout -b feat/<you>-<task>`.
2. **Build** in your own folders only. Commit often, push at least twice, open a draft PR early.
3. **Merge window (last hour):** mark the PR ready. The other person reviews, CI passes, then squash-merge. Alapan merges first when you both touch migrations.
4. **Check main:** pull, run `docker compose up` and the tests. At a gate, `git tag vX.Y && git push --tags`.

If a block slips, carry its work into the next block. Nothing is dropped, so blocks 8 and 9 are the ones to watch.
