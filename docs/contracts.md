# Shared contracts

These are implemented as Pydantic models in `api/app/contracts/` and mirrored as TypeScript types in `web/lib/contracts.ts`. They are **frozen after block 2**. Any change needs its own `contracts/vN` PR that both people approve, and both rebase straight after it merges.

## Enums

```
Role          = creator | reviewer | manager | legal | admin
Severity      = low | medium | high | critical
Verdict       = VIOLATION | UNSURE | PASS
CheckType     = tone | terminology | messaging | claim | visual | accessibility
                | hidden_content | required_element | tone_drift
UnitType      = chunk | claim | document
DataClass     = public | internal | confidential | restricted
ContentState  = draft | ai_review | resolving | reviewer_check
                | manager_approval | legal_signoff | published | rejected
FindingStatus = open | fix_accepted | fix_edited | override_pending
                | override_confirmed | override_rejected | resolved
```

## Models

```
Finding {
  id, review_id, content_version_id,
  unit_type: UnitType,
  spans: [{ chunk_id, start, end }],          # a claim can span several chunks
  check: CheckType,
  tier: 0 | 1 | 2,
  verdict: Verdict,
  severity: Severity,
  confidence: float,                           # 0–1
  rule_id?, rule_version?, fact_ids: [str],    # at least one of rule_id or fact_ids
  cited_text: str,                             # exact clause or fact cited
  explanation: str,
  trace: { steps: [{ tool, input_summary, output_summary }], sources: [str], model?: str },
  ai_generated: bool,
  models_used: [str],
  vote?: { variants: int, agree: int, split: bool },
  fix_available: bool,
  status: FindingStatus
}

Rule      { id, version, type: deterministic|judgment|must_include, text, clause_ref,
            severity, channel_scope: [str], status: draft|approved|retired, supersedes?,
            required_text? }   # v2: exact text a must_include rule requires
Fact      { id, statement, value, source_doc, owner, valid_until?: date, data_class, version }
Term      { id, preferred, banned: [str], renamed_from?: str, rule_id?, rule_version? }  # v2: governing rule
Asset     { id, kind: logo|palette|image|font, file_ref, meta }
Decision  { id, finding_id, actor_id, role, action, reason?, created_at }
            action = accept_fix | edit_fix | override | confirm_override | reject_override | resolve
Gap       { id, review_id, check, text, explanation, created_at }
FixSuggestion { finding_id, original, suggested, diff, attempt: 1|2 }
Precedent { decision_id, rule_id, rule_version, channel, reason, reviewer, date }
Proposal  { id, rule_id, kind: amendment|anchor|term|severity, current, suggested,
            evidence: { count, examples: [span] }, eval?: { passed, precision, recall },
            status: pending|approved|rejected }
Chunk     { id, content_version_id, ordinal, kind: heading|paragraph|image, text,
            content_hash, data_class, style? }   # v2: served to the review screen
ContentSource { data_class, text, file_name?, file_bytes? }  # v3: in-process only, never on the wire
```

### contracts/v2 changes

- `Rule.required_text?` — the exact text a `must_include` rule requires (the tier-0 required-element check looks for this, not the rule sentence).
- `Term.rule_id?` / `Term.rule_version?` — the terminology rule a term is governed by, so findings cite the right rule and severity per term.
- `Fact.valid_until` is a **date** (was datetime), matching the facts table.
- New `Chunk` model + engine endpoint (below) for the review screen.

### contracts/v3 changes

- New `ContentSource`: what the engine reviews. The product already holds this when it starts a review, so it hands the content over, and the engine never reads `content` or `content_versions`.
- `app.clients.engine.start_review(content_version_id, channel, rulebook_version, source)` is how a real review starts. It is a Python call inside the API process.
- `file_bytes` is set for uploads and is the file's raw bytes. `file_name` gives the format. For pasted text both are empty and the engine parses `text`.
- `ContentSource` is never sent over HTTP. Paths and file references stay out of it, so no client can point the engine at a file on the server.

## Service interfaces

Alapan provides these. Anoushka mocks them under `api/mocks/` until they're built, and each one is switched with its own `USE_MOCK_*` flag.

| Call | Purpose |
|---|---|
| `POST /engine/reviews {content_version_id, channel, rulebook_version}` → `{review_id}` | start an AI review; mock only from v3, the real engine starts through `app.clients.engine.start_review` |
| `GET /engine/reviews/{id}/findings` (SSE) | stream findings; tier 0 first |
| `POST /engine/reviews/{id}/recheck {changed_chunk_ids}` | incremental re-review; mock only, not built, because the verdict cache already reuses unchanged chunks |
| `GET /engine/reviews/{id}/chunks` → `[Chunk]` | parsed chunks for the review screen (v2) |
| `POST /engine/findings/{id}/fix` → `FixSuggestion` | lazy fix, max 2 attempts |
| `POST /engine/verdicts/{finding_id}/replay` → `{identical: bool, verdict, manifest}` | Replay |
| `POST /engine/eval/gate {proposal}` → `{passed, precision, recall}` | regression gate; admin only |
| `GET /memory/impact?fact_id=` → `[{content_id, state, claim_text}]` | impact analysis; staff only |
| `GET /memory/precedents?finding_id=` → `[Precedent]` | precedents |
| `GET /memory/graph?root=` → `{nodes, edges}` | graph view, read from the Postgres edge table; staff only |
| `GET /gateway/reviews/{id}/disclosure` → `{models: [], masked: {entity: count}, routes: []}` | disclosure panel |
| `GET /gateway/reviews/{id}/masking-preview` → `{original, sent}` | masking preview |
| `POST /governance/run` → `[Proposal]` | run the governance agent and return every pending proposal; admin only |
| `POST /governance/proposals/{id} {status: approved\|rejected}` → `[Proposal]` | an admin's decision; returns what's still pending and doesn't change the rule; admin only |
| `GET /governance/spot-checks` → `[{content_id, review_id}]` | spot-check sample; staff only |

Anoushka provides these, and Alapan reads them:

| Call | Purpose |
|---|---|
| `GET /admin/rulebook?version=` → `[Rule]` | the approved rulebook at a given version |
| `GET /admin/facts`, `/admin/terms`, `/admin/assets` | brand data |
| `GET /workflow/decisions?since=` → `[Decision]` | decisions, for precedents and governance |
| `GET /insights/signals` → `{override_rate_by_rule, vote_split_by_rule, gaps}` | input for the governance agent |
| `POST /admin/gaps [Gap]` | the critic writes uncited findings to the guideline-gap log |

Engine, gateway and Replay routes take the engine's review id and follow the content's read rule, so a person who can't open a piece gets a 404.

`app.clients.engine` also provides `review_status(review_id, session)`, which returns `running`, `done`, `failed` or `unknown`. Only `done` means every check finished. `start_review` refuses a DOCX or PDF it can't open with a 422.

The Python function `llm.call(purpose, data_class, rule_ids, payload) -> dict` in `app.gateway` is the **only** way to call an LLM. Until the gateway is real, the mock returns canned JSON that matches the requested schema.

## Tables

- **Alapan:** `chunks`, `claim_units`, `findings`, `review_cache`, `edges`, `gateway_log`, `token_vault`, `proposals`, `spot_checks`, `eval_runs`
- **Anoushka:** `users`, `content`, `content_versions`, `reviews` (with the pinned `rulebook_version`), `review_state_log`, `decisions`, `comments`, `audit_log`, `rules`, `facts`, `terms`, `assets`, `ingest_jobs`, `gaps`

Each person reads the other's data through the API, never by querying the other's tables directly.
