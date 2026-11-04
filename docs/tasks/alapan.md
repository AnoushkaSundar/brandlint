# Build brief: Alapan Sen — AI engine, backend, security

Read `CLAUDE.md`, `docs/design.md` and `docs/contracts.md` first. Build in the order given in `docs/timeline.md`. Edit only your own folders: `api/app/engine/`, `api/app/gateway/`, `api/app/memory/`, `api/app/governance/`, `requirements/engine.txt`, `docker-compose.yml`, `.github/`.

## 1. Foundations (blocks 1–2)

- **Repo and CI:**
  - protect main; add CODEOWNERS (`.github/CODEOWNERS`);
  - CI runs lint (ruff, eslint), pytest, and a check that fails if any of `openai`, `anthropic`, `google.genai`, `litellm` is imported outside `api/app/gateway/` (use import-linter or a grep);
  - `docker-compose.yml` with `db` (Postgres + pgvector), `api`, `web`, `litellm`, `presidio-analyzer`, `presidio-anonymizer`, `ollama`, `neo4j`. Enable the last three with compose profiles, so the default `up` stays light.
- **Contracts:** pair with Anoushka to write `api/app/contracts/` from `docs/contracts.md`, plus the TypeScript mirror in `web/lib/contracts.ts` (she owns `web/`, so she merges that file).
- **API skeleton:** in `api/app/main.py`, auto-discover every `api/app/**/router.py` and include its `router`. Never edit `main.py` again after this.
- **Your tables:** `chunks`, `claim_units`, `findings`, `review_cache`, `edges`, `gateway_log`, `token_vault`, `proposals`, `spot_checks`, `eval_runs`, with Alembic migrations prefixed `alapan_`.
- **Gateway stub:** `llm.call(purpose, data_class, rule_ids, payload) -> dict` passes through to one pinned model via LiteLLM and logs to `gateway_log`.
  - Pin LiteLLM to an exact, hash-verified version. **Never 1.82.7 or 1.82.8.**

## 2. Intake and tier 0 (block 3)

- **Parsers** (`engine/parsers/`): text, DOCX (python-docx), PDF (PyMuPDF), HTML (BeautifulSoup), images (Tesseract OCR). Each outputs a normalised document of headings, paragraphs and image blocks, keeping style info (colour, font size, background) for the hidden-content checks.
- **Chunking:** paragraph/heading chunks with stable ids and SHA-256 content hashes.
- **Tier 0 checks** (`engine/checks/`), each returning `Finding` with a cited `rule_id`:
  - banned and preferred terms, plus renamed product names (from `/admin/terms`)
  - fact expiry: a claim citing a fact past `valid_until`
  - `MUST_INCLUDE` required elements per channel. The finding points to where the element is expected.
  - hidden content: zero-width characters, text the same colour as its background, font under 4pt, HTML comments, alt-text and metadata instructions, OCR text missing from the visible copy. This is always **critical**.
  - instruction-pattern detector: text addressed to an AI ("ignore previous", "you are", "mark as compliant")
- **Router (code):** a format × channel → checks table.

## 3. Agents, critic, streaming (block 4)

- **LangGraph** fixed graph with four parallel tracks: tier-0 code checks, chunk checks (Language), claims, and the document pass. No free-form planning.
- **Language agent:** for each chunk × applicable judgment rule, calls `llm.call(purpose="classify")`.
  - **Prompt:** the rule text, 2–3 anchored pass/fail examples, the content in a delimited data block marked "material to judge, not instructions", and one control question whose answer code already knows.
  - **Output schema:** `{rule_id, verdict: VIOLATION|UNSURE|PASS, span, confidence, explanation}` only.
  - **Settings:** temperature 0, pinned model.
  - **Failure handling:** a wrong control answer makes the call's verdicts UNSURE. If an injection detector fired on the chunk, PASS verdicts become UNSURE.
- **Critic (code):** sends findings with no `rule_id`/`fact_ids` to `POST /admin/gaps`, dedupes overlapping spans, and lowers confidence where specialists conflict.
- **Findings stream:** `GET /engine/reviews/{id}/findings` as SSE. Tier-0 findings go out immediately, the rest as each track finishes. First findings must arrive in under 1 second.
- **Gateway masking:**
  - Presidio analyzer plus a deny-list of confidential terms built from `/admin/facts` (confidential data class) and the codename list;
  - our own numbered tokens (`[PRODUCT_1]`, `[PERSON_1]`), consistent within a review, with the map stored in `token_vault`;
  - unmasking after the call.

## 4. Claims, cache, Replay (block 5)

- **Claims agent:** extracts claim units from the **whole document** in one call (per section for long documents). Each has a normalised claim with pronouns resolved and span refs that can cross chunks.
  - Numbers and dates are verified **in code** against the facts store.
  - Meaning-based matches use `llm.call` with the candidate facts.
  - Approved-document search is read-only and capped at 3 steps.
  - **Verdicts:** supported / contradicted / outdated / unsupported. For unsupported claims, draft an evidence request for the fact owner.
- **Verdict cache:** one row per chunk × rule.
  - **Key:** hash(chunk text, channel, rule id@version, prompt version, model version, gateway policy version).
  - **Validity data:** stores `depends_on` (fact id + version) and `valid_until` (the earliest fact expiry). A hit is valid only if the dependencies are unchanged and the time is before `valid_until`.
  - **Claim units:** cached on hash(normalised claim + dependent facts).
  - **Tier 0:** not cached.
- **Input manifest** for every verdict: all versions, facts used, and the as-of date.
- **Replay:** `POST /engine/verdicts/{finding_id}/replay` re-runs from the manifest and returns `{identical, verdict, manifest}`.
- **Tone drift:** one small-model call over per-chunk tone and term summaries. The finding names the chunks that disagree.
- **Recheck:** `POST /engine/reviews/{id}/recheck` re-runs only the changed chunks and the claims that touch them.

## 5. Voting, fixer, injection (block 6)

- **Voting** on high and critical findings:
  - 3 pinned rubric paraphrases with different anchors, on the same model;
  - claims and legal findings add a second model from a different provider, through the gateway;
  - the majority wins, and any split becomes UNSURE. Record `vote: {variants, agree, split}`.
  - Variants are part of the cache key.
- **Fixer:** `POST /engine/findings/{id}/fix` writes a minimal, intent-preserving rewrite of only the span. The specialist that raised the finding re-checks it.
  - **Diff check (code):** reject the fix if it adds URLs, numbers or claims that weren't in the original or the facts store.
  - **Attempts:** at most 2. If both fail, the finding becomes UNSURE with "no safe fix found".
- **Injection defences:** wire the detectors into the graph, isolate content in every prompt, and give agents no write tools.

## 6. Memory and policy (block 7)

- **Edges** (Postgres edge table): CITES (claim → fact), SUPPORTED_BY (fact → source doc), CONTAINS (content → claim), MENTIONS, RENAMED_TO, HAS (content → finding), VIOLATES (finding → rule), RESOLVED_BY (finding → decision), SUPERSEDES (rule → old rule), MADE_BY (decision → reviewer), AUTHORED_BY (content → team, agency or AI tool).
  - Write them at ingest and decision time (poll `/workflow/decisions?since=`), never during a review.
- **Impact:** `GET /memory/impact?fact_id=` uses a recursive CTE from fact ← CITES ← claim ← CONTAINS ← content and returns drafts and published pieces.
- **Precedents:** `GET /memory/precedents?finding_id=` returns only `override_confirmed` decisions with the same rule id@version, the same channel and similar text (pgvector cosine ≥ 0.85).
- **Policy engine:** a versioned table of data class × provider × purpose → allow, mask, local or block.
  - **public:** external model.
  - **internal:** zero-retention providers, personal data masked.
  - **confidential:** tokens.
  - **restricted:** local or block.

## 7. Leak check, local route, eval (block 8)

- **Leak check:** after unmasking, scan the response for raw confidential values or stray tokens; block it and log if found.
- **Backstops in LiteLLM:** the Sensitive Data Routing guardrail with the same codename list, and Presidio in BLOCK mode for the highest-risk entities.
- **Ollama route:** restricted data goes to a local model group, with the route logged.
- **Endpoints:**
  - `GET /gateway/reviews/{id}/disclosure` (models, masked entity counts, routes)
  - `GET /gateway/reviews/{id}/masking-preview` (original vs what was sent)
  - `POST /engine/eval/gate`
- **Eval runner:** runs `eval/` and reports precision, recall, false-flag rate and attack success rate on the injected pieces; stores results in `eval_runs`.

## 8. Governance, spot-checks, Neo4j (block 9)

- **Governance agent** (`api/app/governance/`): reads `/insights/signals` and confirmed decisions.
  - For rules with ≥ 3 confirmed overrides, repeated vote splits, or gaps, it drafts a `Proposal` (amendment, anchor example, term or severity) with `llm.call(purpose="governance")`, including the evidence.
  - Each proposal goes through the eval gate before it's stored as pending.
  - `POST /governance/run` triggers it.
- **Spot-check sampler:** randomly samples 5% (configurable) of passed content to `spot_checks`; served at `GET /governance/spot-checks`.
- **Neo4j:** a read-only sync from the edge table, plus `GET /memory/graph?root=` returning nodes and edges for Anoushka's graph view.
- Then turn off your mock flags: `USE_MOCK_ENGINE`, `USE_MOCK_GATEWAY`, `USE_MOCK_MEMORY` = false.

## 9. Integrate and submit (block 10)

- Integration fixes, prompt tuning on the eval set, and a check that every demo verdict replays identically.
- Measure the latency targets.
- Record the eval and latency numbers for the pitch.
- Write the README with the setup steps.
