# CI/CD integration: build plan

Goal: a GitHub Action and a pre-commit hook that run BrandLint on every file containing copy before a PR merges. Violations fail the check, which blocks the merge when it is a required status check, and each one links to its finding in BrandLint.

Owner: Anoushka, for every block. The plan is built to stay inside her folders. The engine is only called through the existing review path, and never changed. If a block seems to need an engine, gateway or `.github/` change, stop and say what's needed (see "Files outside your folders").

## Design decisions (locked, don't re-open inside a block)

1. **The check calls a BrandLint server.** The Action and hook are thin clients. No review logic runs in CI, so verdicts stay deterministic and identical to the web app (same rulebook, same cache, same Replay).
2. **Machine access uses a service token, not a password.** One token belongs to one organisation, is shown once, stored only as a hash, can be revoked, and can do only CI things (create runs, read runs). It can't approve, override, edit rules or read other content.
3. **Org comes from the token's row,** exactly as users get theirs from `users.org_id`. Never from a request field. Uses the multi-tenancy helpers (`scoped`, `CurrentOrg`).
4. **A run is keyed by repo + PR + file path + text hash.** Re-running identical text returns the existing review, so a reviewer's decisions in the web app apply to the next CI run. Changed text creates a new version and a new review. This is how a violation gets waived without any new override mechanism.
5. **The server decides pass or fail,** never the client. The result is `pass` or `fail` plus a reason list. Default policy: a finding with verdict `VIOLATION` at or above a severity threshold fails (default `medium`), and `UNSURE` also fails, because UNSURE blocks approval everywhere else. A confirmed override counts as passed. The threshold and the UNSURE rule are workspace settings.
6. **Fail closed.** If BrandLint is unreachable or times out, the Action fails (setting `on-error: pass` exists, defaults to `fail`). The pre-commit hook defaults the other way (warn, don't block) because it can be bypassed anyway with `--no-verify`. **The Action is the enforcement point.**
7. **"Contains copy" is decided by config, not guessed.** `.brandlint.yml` in the repo maps path globs to a channel and says how to extract copy. No file is scanned unless a rule matches it.
8. **Scan only what changed.** On a PR, only files changed against the base. Unchanged text would hit the cache anyway, but sending less is faster and cheaper.
9. **Repo content is untrusted input.** It goes through the same injection defences as any upload. Hidden-content findings are critical, and the Action never runs repo code.
10. **Links need sign-in.** The link in a failing check opens a run page in BrandLint. Findings quote the draft, so the page requires login to the same org, and returns 404 otherwise. The CI log and PR comment show finding titles and rule ids, never a quoted draft beyond a short span.
11. **Secrets rules:** the token lives in a repo secret and is masked in logs. PRs from forks don't get secrets, so the Action detects that and gives a clear "can't run on fork PRs" result instead of failing mysteriously. Never use `pull_request_target` to work around it.
12. **Ship behind a flag.** `CI_INTEGRATION_ENABLED=false` until Block 9.

## Files outside your folders

- New server code goes in a new `api/app/ci/` folder. Routers are auto-discovered, so don't edit `main.py`.
- New contract models need a `contracts/vN` PR that Alapan approves (Block 0 only).
- `.github/` (including the dogfood workflow in Block 9) and `.github/CODEOWNERS` belong to Alapan. The Action goes in `integrations/github-action/` and the hook in the repo root. The one workflow that runs the check on this repo itself needs a small PR from Alapan.
- The CLI lives in `cli/` with its own `pyproject.toml`. It must not import anything from `api/`, and must not import an LLM SDK (the guard still applies).

## Rules for every block

- One branch and one PR per block: `feat/anoushka-ci-<n>-<name>`.
- Write the failing tests first, then the code. Show them failing, then passing.
- Each migration has an upgrade and a downgrade, covered by `test_migrations.py`, prefixed `anoushka_`. Take a database backup note in the PR description.
- Run `ruff`, the full `pytest`, the LLM-import guard and the isolation suite in `api/tests/tenancy/` before opening the PR. The isolation suite must stay green.
- Tests never call a real model or the real GitHub. Use the existing mock gateway and the fake GitHub fixture from Block 0.
- End every block with a report: what works, what's left, what could still leak or be abused.
- Don't deploy until the block's gate passes.

## Blocks

**Block 0: Contract, fixtures and test harness.** The `contracts/v4` models (`CIRunRequest`, `CIFile`, `CIRunStatus`, `CIFileResult`, `CIFinding`, `CIPolicy`), mirrored in `web/lib/contracts.ts`. Fixtures in `integrations/fixtures/`: a fake repo tree with clean, violating, UNSURE and hidden-content copy in markdown, HTML, JSON i18n, YAML i18n, PO and properties; DOCX and PNG builders; a fake GitHub (records PR comments, check runs and annotations); a fake BrandLint server for CLI tests.

**Block 1: Service tokens.** Table `service_tokens` (`id`, `org_id`, `name`, `token_hash`, `prefix`, `scopes`, `created_by`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`). Token format `bl_<32 random bytes, base64url>`, shown once, SHA-256 hashed, compared in constant time. Admin-only create, list and revoke, inside the admin's own org. A service token works only on `/ci/*`; anywhere else it is a 401. Revoked, expired and suspended-org tokens are refused at once. `last_used_at` is updated at most once a minute.

**Block 2: CI run API.** Tables `ci_runs` and `ci_run_files`. `POST /ci/runs` validates every file (size, extension and signature, a relative path with no `..`, file and byte caps), creates or finds the content for `(repo, path)`, adds a version only if the text hash changed, starts a review through the existing content path, and returns the run. Idempotent. `GET /ci/runs/{id}` is poll-friendly. CI content is authored by a per-org service user, hidden from creators' lists, and never published. Quotas per token and per org return 429.

**Block 3: Verdict, policy and waivers.** A per-org policy (`severity_threshold`, `fail_on_unsure`, `ignore_rules`, `max_waiting_minutes`). One pure function computes the result: `override_confirmed` and `resolved` count as passed; `open`, `override_pending` and `fix_edited` do not. A review that doesn't finish in time is `error`, never `pass`. An empty rulebook is an `error` with a helpful reason. Waivers are the existing overrides: re-running identical text reads the new status.

**Block 4: Web.** The run page `/ci/runs/[id]`, a runs list, settings (the policy form and token management, with example workflow YAML), and a CI filter on the content list.

**Block 5: CLI core.** `cli/` (`brandlint-cli`, depends only on `httpx` and `pyyaml`; Python 3.9+): `brandlint check [paths…] [--changed-against <ref>] [--staged] [--format text|json|github|sarif] [--on-error fail|pass]`. Exit codes: 0 pass, 1 violations, 2 config or usage error, 3 BrandLint unreachable or errored. The token comes from `BRANDLINT_TOKEN` only, never a flag.

**Block 6: Copy extraction and line mapping.** Extractors `plain`, `json-i18n`, `yaml-i18n`, `po`, `properties`, `html-text`, each keeping a map back to path, key and line. Placeholders are masked. Output formats `github`, `sarif`, `text`, `json` use the mapping.

**Block 7: GitHub Action.** `integrations/github-action/`: annotations, a job summary, one PR comment updated in place, fork-PR handling, concurrency, pinned dependencies. Blocking the merge is done by GitHub's branch protection, not the Action.

**Block 8: Pre-commit hook.** `.pre-commit-hooks.yaml` at the repo root. Warns and lets the commit through when the server is slow or unreachable; `--strict` blocks. `--no-verify` bypasses it, which is why the Action is the real gate.

**Block 9: Hardening, docs and rollout.** Red-team pass, observability, audit entries for token create and revoke, the user guide, rollout steps in `deploy/README.md`, and the dogfood workflow.

## Order and dependencies

0 → 1 → 2 → 3 → (4, and 5 in parallel; they share nothing but the contract) → 6 → 7 → 8 → 9. Needs multi-tenancy merged first (tokens and runs belong to an org).
