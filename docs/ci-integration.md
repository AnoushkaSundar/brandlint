# BrandLint in CI

BrandLint can check the copy in a pull request before it merges. A GitHub Action (or a pre-commit hook, or the `brandlint` command on its own) sends the copy files a change touched to your BrandLint workspace, the server says whether any finding blocks the change, and every finding links to its card in BrandLint, where a reviewer can read it, decide, and waive it. **Five minutes to set up: [ci-quickstart.md](ci-quickstart.md).**

This page is the guide. The build plan it was made from is further down.

## How it works

1. **A service token** (made by an admin in **CI settings**) lets a CI job send copy for checking, and do nothing else. It belongs to one workspace, is shown once, and can be revoked.
2. **`.brandlint.yml`** in your repo says which files hold copy, and how to read them. No file is checked unless a rule matches it.
3. **The check** sends only the files a pull request changed. Each goes through the same review as an upload in the web app: the same rulebook, cache and Replay, so a verdict is the same in CI as on screen.
4. **The server decides.** The result is `pass` or `fail`, with reasons. The client only reports it.
5. **Branch protection blocks the merge.** Require the **BrandLint** check in GitHub's branch protection. The Action itself only reports.

A pass means no finding blocks the run. It is not an approval: people approve content in BrandLint.

## The config, `.brandlint.yml`

```yaml
server: https://your-brandlint.example/api     # or BRANDLINT_SERVER, or --server
channels:                                      # no file is checked unless a rule matches it
  - glob: "docs/**/*.md"
    channel: blog            # blog, linkedin, email, ad, banner or document
  - glob: "i18n/*.json"
    channel: email
    extract: json-i18n       # plain (default), json-i18n, yaml-i18n, po, properties, html-text
    data_class: public       # public (default), internal, confidential or restricted
ignore:
  - "docs/drafts/**"
```

**Extractors.** `plain` sends the file as it is. The others find the copy inside a file that also holds code: they send each string value (never the keys, numbers or URLs), and the report points at the right `path:line` and key. Placeholders (`{name}`, `{{name}}`, `%s`, ICU groups) are replaced with `[placeholder]` before sending, so they aren't read as product terms. **Use `plain` for HTML if hidden text matters**: only then does the server see text hidden with CSS, which it flags as a critical hidden-content finding. `html-text` sends only visible text and ignores scripts and styles.

## The command line

```bash
pip install ./cli
export BRANDLINT_TOKEN=bl_...
brandlint check                              # everything the config matches
brandlint check --changed-against origin/main
brandlint check --staged
brandlint check --format json|github|sarif|short
```

| Exit code | Meaning |
|---|---|
| 0 | Passed (or nothing to check) |
| 1 | A finding blocks |
| 2 | A config or usage error (the message says what to change) |
| 3 | BrandLint couldn't be reached or errored. `--on-error pass` or `warn` turns this into 0, with a warning; a real failure is never let through |

The token comes only from `BRANDLINT_TOKEN`, never a flag, and is masked in all output.

## What fails a run: the policy

An admin sets it in **CI settings** (and a job can read it at `GET /ci/policy`):

- **Severity threshold** (default `medium`): a VIOLATION at or above it blocks.
- **Fail on UNSURE** (default on): a finding the AI was unsure about blocks, because it blocks approval everywhere else.
- **Rules to ignore:** approved rule ids whose findings never block.
- **How long to wait** (default 15 minutes): a review that takes longer is an **error**, never a pass.

A finding stops blocking when a reviewer **overrides** or **resolves** it in BrandLint. Nothing else counts: an override still waiting for a reviewer, an edited or accepted fix, and a rejected override all still block, so the answer fails closed. An empty rulebook is an error with a helpful message, never a pass.

## Waiving a finding

There is no separate waiver. A reviewer opens the finding from the link in the check (or from **CI runs**), and overrides or resolves it with a reason, under the usual rules (high and critical findings are for reviewers). Re-run the check: the same copy finds the same review and reads the new standing, so the run now passes. Changed copy is a new version and a new review.

## The GitHub Action

See `integrations/github-action/README.md` and its `example-workflow.yml`. It needs only `contents: read` and `pull-requests: write`, annotates the changed lines, writes a job summary and keeps **one** comment up to date. **Pin it by commit SHA.** Fork pull requests get no secrets, so the check can't run: by default it fails with a clear message (never a pass), and `on-fork: skip` leaves them unchecked. Never use `pull_request_target` to get around that.

## The pre-commit hook

See `cli/README.md`. It warns and lets the commit through when BrandLint is slow or unreachable (`--strict` blocks), and `git commit --no-verify` skips it, so the Action is the thing that enforces.

## Turning it on (admins)

The integration ships off. Set `CI_INTEGRATION_ENABLED=true` on the API and build the web app with `NEXT_PUBLIC_CI_ENABLED=true`; rollout steps and rollback are in `deploy/README.md`. Limits are environment settings: `CI_MAX_FILES_PER_RUN` (50), `CI_MAX_BYTES_PER_RUN`, `CI_MAX_FILE_BYTES`, `CI_MAX_RUNS_PER_DAY` (500), `CI_MAX_RUNS_PER_TOKEN_PER_DAY` (200), `CI_MAX_BYTES_PER_DAY`. Over a limit is a 429 with a message.

## Troubleshooting

| You see | What to do |
|---|---|
| `set BRANDLINT_TOKEN` | Put a service token in the environment or the repo's secrets |
| `answered 401` | The token is wrong, revoked or expired: make a new one in CI settings |
| `answered 403` | The workspace is suspended or expired |
| `answered 404` on `/ci/...` | The integration is off on the server |
| `could not compare with 'origin/main'` | Check out with `fetch-depth: 0`, or `git fetch origin main` |
| `No approved rules yet` | An admin has to upload the guidelines and approve the rules |
| `reached its CI runs for today` | A daily limit: ask an admin, or wait |
| `SKIPPED path: ...` | A file wasn't checked, and the reason is given: too large, not UTF-8, a symlink out of the repo, or no copy in it |
| The check says it could not run on a fork | Expected: forks have no secrets. A maintainer can run it from a branch in the repo |

---

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
