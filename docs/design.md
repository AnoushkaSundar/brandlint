# BrandLint design

## Architecture (four layers)

1. **Intake**
   - Parsers turn text, DOCX, PDF, HTML and images (OCR) into stable chunks (paragraphs and headings) with content hashes.
   - Each chunk is tagged with a data class: public, internal, confidential or restricted.
   - The ingest agent turns guideline PDFs into atomic draft rules, flags conflicts, and waits for a person to approve them.
2. **Review engine** (a fixed LangGraph graph)
   - A code router picks the checks by format and channel.
   - Tier 0 code checks and the specialist agents run in parallel.
   - A code critic gates every finding.
   - The fixer runs only when a finding is opened.
3. **Brand memory** (Postgres + pgvector)
   - rulebook (versioned rules with clause references)
   - facts store (source, owner, expiry, version)
   - graph edges
   - verdict cache with input manifests
   - audit log
4. **Product** (Next.js)
   - review screen and diff view
   - workflow and approvals
   - brand admin
   - insights and governance
   - disclosure

## Tiers

| Tier | Checks | How | Determinism |
|---|---|---|---|
| 0 · Code | banned/preferred terms, renamed product names, fact expiry, hidden text, required elements (`MUST_INCLUDE`), contrast, alt text, headings, link text, logo aspect ratio, palette distance | plain functions | 100% |
| 1 · Constrained AI | tone, messaging, claim classification, tone drift | verdict enum per given rule ID, anchored pass/fail examples, temperature 0, pinned model, cached | reproducible via cache; vote on high severity |
| 2 · Generative AI | fix suggestions, amendment drafts | free text, re-checked by the specialist that raised the finding | never decides pass/fail |

## Review units (run in parallel)

| Unit | Boundaries | Used for | Cache key |
|---|---|---|---|
| Structural chunk | paragraphs/headings (deterministic) | tone, terms, accessibility, visuals | chunk text + channel + rule id@version + prompt version + model version + gateway policy version |
| Claim unit | extracted from the whole document; one claim can span several chunks | claim verification | normalised claim + the facts it depends on (position-independent) |
| Document | whole piece | `MUST_INCLUDE` rules (code), tone drift (one small-model call) | hash of all chunk hashes + channel |

- **Cache entry:** stores `depends_on` (fact ids + versions used) and `valid_until` (the earliest fact expiry). A hit is valid only if every dependency is unchanged and the current time is before `valid_until`.
- **Input manifest:** every verdict stores one (all versions and facts used, plus the as-of date). **Replay** re-runs a verdict from its manifest and must return an identical result.
- **Precedents:** never part of a cache key. They are context only and never change a verdict.
- **Re-review:** edits re-check only the chunks whose hash changed.

## Voting (high-severity findings)

- At temperature 0, re-running the same prompt is pointless, so votes vary the judge instead.
- **Default:** 3 pinned paraphrases of the rule's rubric, each with different anchor examples, on the same model.
- **Legal and claims findings:** add a second model from a different provider, called through the gateway. It's `gemini-3.5-flash-lite` on Google's free tier, so the policy table allows it for public data only.
- Only model judgments are voted on. A number checked against the facts store is code, and a majority can't overturn it.
- If the second model fails, voting continues without it. A rubric that fails counts against the finding.
- The majority wins. Any split makes the finding UNSURE, and it goes to a reviewer.
- Rubric variants and models are pinned and part of the cache key.
- Repeated splits on a rule count as an "unclear guideline" signal.

## Agents

| Agent | Owner | Job |
|---|---|---|
| Router (code) | Alapan | picks checks by format × channel |
| Language | Alapan | tone, messaging, terminology |
| Claims | Alapan | extracts claim units from the whole document; numbers and dates checked in code against facts; approved-document search capped at 3 steps; drafts an evidence request when a fact is missing |
| Critic (code) | Alapan | drops uncited findings into the gap log, dedupes, lowers confidence on conflicts |
| Fixer | Alapan | minimal intent-preserving fix, max 2 attempts; a diff check rejects new URLs, numbers or claims |
| Governance | Alapan (backend), Anoushka (UI) | mines confirmed overrides, vote splits and gaps (≥ 3 occurrences); drafts amendments, sends them through the eval gate; an admin approves |
| Ingest | Anoushka | guideline PDF to atomic draft rules, plus conflict detection |
| Visual | Anoushka | logo (feature match, aspect ratio, rotation, colour), off-palette colours (CIEDE2000), imagery rules via `llm.call`, OCR text through the term checks |
| Accessibility (code) | Anoushka | WCAG 2.x contrast (4.5:1 normal, 3:1 large), alt text, heading order, link text |

Every agent step is logged as a trace (tool calls, sources, model) and shown under "Why was this flagged?".

## Prompt-injection defence

| Layer | Detail |
|---|---|
| Hidden-content scan (tier 0) | zero-width characters, text matching its background, tiny fonts, HTML comments, metadata or alt-text instructions, OCR text missing from the visible copy. Raised as a **critical** finding. |
| Instruction-pattern detector | text addressed to an AI ("ignore previous", "mark as compliant") |
| Content isolation | content sits in a delimited data block, with a strict output schema |
| Suspicious PASS → UNSURE | if either detector fired on a chunk, AI PASS verdicts on it go to a reviewer |
| Control questions | each tier-1 call includes one check whose answer code already knows; a wrong answer makes the call's verdicts UNSURE |
| Least privilege | agents have no write tools; search is read-only on a fixed corpus |
| Fixer diff check | no new URLs, numbers or claims |
| Red-team eval | 5–10 injected pieces in `eval/`, with attack success rate reported |

## AI gateway

Every model call goes through `llm.call(purpose, data_class, rule_ids, payload)`.

1. **Detect:** Presidio for personal data, plus a deny-list of confidential terms from brand memory (codenames, embargoed facts), plus upload labels.
2. **Decide:** a versioned policy maps data class × provider × purpose to allow, mask, route to local, or block.
3. **Transform:** values are replaced with our own numbered tokens (`[PRODUCT_1]`), kept in a vault scoped to the review.
   - Don't use LiteLLM's built-in unmasking: its tokens are per type, not per value, and it has open bugs.
4. **Call:** through the LiteLLM proxy, the only component that holds provider keys.
   - Backstops inside LiteLLM: the Sensitive Data Routing guardrail on the same codename list, and Presidio in BLOCK mode for the highest-risk entities.
5. **Inspect:** restore the tokens and scan the response for leaks.
6. **Log:** provider, model, what was masked, and the route. This feeds the disclosure panel and the audit log.

| Data class | Gateway action |
|---|---|
| public | approved external model |
| internal | zero-retention providers only; personal data masked |
| confidential | reversible numbered tokens; claims involving masked values checked in code |
| restricted | never leaves: Ollama (local) or code-only checks, otherwise a reviewer |

There is no LLM streaming: verdicts are structured output, and we stream findings ourselves.

## Brand memory graph

- **Nodes:** Fact, SourceDoc, Claim, Content, Term, Rule, Finding, Decision, Reviewer.
- **Edges:** CITES, SUPPORTED_BY, CONTAINS, MENTIONS, RENAMED_TO, HAS, VIOLATES, RESOLVED_BY, SUPERSEDES, MADE_BY, AUTHORED_BY.
- **Impact analysis:** a changed or expired fact is traced back through CITES → Claim and CONTAINS → Content to every affected draft and published piece.
- **Precedents:** only reviewer-confirmed overrides become precedents. Each is scoped to the same rule, the same channel and similar text, and expires when the rule's version changes.
- **Build timing:** the graph is built at ingest and decision time, never during a review.
- **Graph view:** read from the Postgres edge table. The planned Neo4j sync wasn't built, because the view needs nothing it adds.
- **Edges:** a projection, rebuilt from claims, findings and decisions when the graph is read. Only a piece's latest review counts.
- **Precedent similarity:** text matching for now, because no embedding model is available through the proxy.

## Workflow

```
draft → ai_review → resolving → reviewer_check → manager_approval → (legal_signoff →) published
resolving ← reviewer_check (changes requested)    ai_review ← resolving (edits re-checked)
any → rejected (with reason)
```

- Legal sign-off is required only when there is a claim finding with high or critical severity.
- A piece can't leave `resolving` while any VIOLATION or UNSURE finding is still open.
- Published versions are locked and stamped with the approvers and the rulebook version.
- **Abuse signal:** a creator whose overrides are often rejected is flagged in Insights, and their overrides go to a reviewer by default.

## Learning loop

- The system changes versioned artifacts (rubric anchor examples, terms, severities, rules), never model weights. Every change is a proposal a person approves.
- Only reviewer-confirmed signals count.
- A proposal must pass the eval gate (labelled set, no drop in precision or recall) before an admin sees it.
- **The gate fails closed outside the demo org.** The labelled examples were written for the Tarnhollow guideline, so any other organisation's rules have none. Its proposals report `passed: false` ("not enough labelled examples"), and an admin decides them by hand. A gap in the set is never a pass.
- **Spot-checks:** 5% of passed content is sampled for a reviewer, which is our only source of missed-issue labels.
- **Active learning:** UNSURE and split-vote items are routed to reviewers first.

## Workspaces

One database, many organisations. Every table that belongs to an org has an `org_id`, and `organizations` is the only shared table. The org comes only from the signed-in user's database row, never from the request. Queries go through `app.tenancy` (`scoped`, `scoped_get` and the rest), a CI check fails when one doesn't, and Postgres Row-Level Security is a second lock behind it: each transaction is told its org, and the policy on every tenant table returns nothing from another. The verdict cache key includes the org, so two orgs never share an answer; rulebook and fact versions are numbered per org. Another org's id is a 404, never a 403, so an id can't be used to find out whether it exists. Why each choice: [`multitenancy.md`](multitenancy.md) and [`rls.md`](rls.md).

A visitor's sandbox workspace is limited (people, content, uploads, reviews, model calls) and expires; an expired one is deleted with its data and files by the expiry job, which binds each org in turn instead of needing a role that bypasses RLS.

## Operational rules

- English only for now; non-English content goes to a person with a notice.
- Confidential visuals can't be masked, so they are treated as restricted.
- Audio and video are future scope: transcript and keyframe converters at intake, with findings pointing to timestamps.

## Cost

About $0.03 for the demo blog post on a first review, estimated from measured call costs; cached re-runs cost almost nothing.

- **Tier 1 and fixes:** `claude-haiku-4-5`, $1 in and $5 out per million tokens. It's pinned rather than Haiku 5.5 because Anthropic rejects `temperature` on 5.5, and verdicts need temperature 0.
- **Second voter:** `gemini-3.5-flash-lite`, free tier for the hackathon. On a paid tier it's $0.30 in and $2.50 out.
- All the software is open source.
