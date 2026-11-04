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
            severity, channel_scope: [str], status: draft|approved|retired, supersedes? }
Fact      { id, statement, value, source_doc, owner, valid_until?, data_class, version }
Term      { id, preferred, banned: [str], renamed_from?: str }
Asset     { id, kind: logo|palette|image|font, file_ref, meta }
Decision  { id, finding_id, actor_id, role, action, reason?, created_at }
            action = accept_fix | edit_fix | override | confirm_override | reject_override | resolve
Gap       { id, review_id, check, text, explanation, created_at }
FixSuggestion { finding_id, original, suggested, diff, attempt: 1|2 }
Precedent { decision_id, rule_id, rule_version, channel, reason, reviewer, date }
Proposal  { id, rule_id, kind: amendment|anchor|term|severity, current, suggested,
            evidence: { count, examples: [span] }, eval?: { passed, precision, recall },
            status: pending|approved|rejected }
```

## Service interfaces

Alapan provides these. Anoushka mocks them under `api/mocks/` until they're built, and each one is switched with its own `USE_MOCK_*` flag.

| Call | Purpose |
|---|---|
| `POST /engine/reviews {content_version_id, channel, rulebook_version}` → `{review_id}` | start an AI review |
| `GET /engine/reviews/{id}/findings` (SSE) | stream findings; tier 0 first |
| `POST /engine/reviews/{id}/recheck {changed_chunk_ids}` | incremental re-review |
| `POST /engine/findings/{id}/fix` → `FixSuggestion` | lazy fix, max 2 attempts |
| `POST /engine/verdicts/{finding_id}/replay` → `{identical: bool, verdict, manifest}` | Replay |
| `POST /engine/eval/gate {proposal}` → `{passed, precision, recall}` | regression gate |
| `GET /memory/impact?fact_id=` → `[{content_id, state, claim_text}]` | impact analysis |
| `GET /memory/precedents?finding_id=` → `[Precedent]` | precedents |
| `GET /memory/graph?root=` → `{nodes, edges}` | graph view (Neo4j-backed) |
| `GET /gateway/reviews/{id}/disclosure` → `{models: [], masked: {entity: count}, routes: []}` | disclosure panel |
| `GET /gateway/reviews/{id}/masking-preview` → `{original, sent}` | masking preview |
| `POST /governance/run` → `[Proposal]` | run the governance agent |
| `GET /governance/spot-checks` → `[{content_id, review_id}]` | spot-check sample |

Anoushka provides these, and Alapan reads them:

| Call | Purpose |
|---|---|
| `GET /admin/rulebook?version=` → `[Rule]` | the approved rulebook at a given version |
| `GET /admin/facts`, `/admin/terms`, `/admin/assets` | brand data |
| `GET /workflow/decisions?since=` → `[Decision]` | decisions, for precedents and governance |
| `GET /insights/signals` → `{override_rate_by_rule, vote_split_by_rule, gaps}` | input for the governance agent |
| `POST /admin/gaps [Gap]` | the critic writes uncited findings to the guideline-gap log |

The Python function `llm.call(purpose, data_class, rule_ids, payload) -> dict` in `app.gateway` is the **only** way to call an LLM. Until the gateway is real, the mock returns canned JSON that matches the requested schema.

## Tables

- **Alapan:** `chunks`, `claim_units`, `findings`, `review_cache`, `edges`, `gateway_log`, `token_vault`, `proposals`, `spot_checks`, `eval_runs`
- **Anoushka:** `users`, `content`, `content_versions`, `reviews` (with the pinned `rulebook_version`), `review_state_log`, `decisions`, `comments`, `audit_log`, `rules`, `facts`, `terms`, `assets`, `ingest_jobs`, `gaps`

Each person reads the other's data through the API, never by querying the other's tables directly.
