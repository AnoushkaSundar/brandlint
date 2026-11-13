# BrandLint in CI and pre-commit

> **Superseded.** This page describes the first version, which signed in with an email and password. The current integration (service tokens, a policy, the `brandlint` command, the GitHub Action and the pre-commit hook) is in [`ci-integration.md`](ci-integration.md); start with [`ci-quickstart.md`](ci-quickstart.md). The script and action described below still work but are not the recommended way.

Review copy before it merges. A pull request that changes a copy file is sent through the
same review engine a creator uses. If a finding blocks, the check fails, and each finding
links to its review page, where a person can read why it was flagged and decide.

**A passing check means "no blocking findings". It is never an approval.** Nothing here
approves, fixes or overrides a finding. People do that in BrandLint.

## What blocks

| Finding | Default | Change it with |
|---|---|---|
| A violation at or above the threshold | Blocks. The threshold is `low`, so any violation | `fail-on`: `low`, `medium`, `high`, `critical` |
| A finding the AI wasn't sure about (UNSURE) | Blocks, because a person has to look and CI can't pretend one did | `unsure: warn` |
| A violation below the threshold | A warning annotation on the line | |
| BrandLint can't check a file (outage, timeout, a failed review) | Fails. It never counts as a pass | `--on-error warn` on the command line |
| More files than `max-files` | Fails, rather than checking only some | raise `max-files` |

Every finding cites a rule or an approved fact, as everywhere else in BrandLint.

## GitHub Action

1. Create a creator account for CI in BrandLint. A dedicated one keeps its submissions
   easy to find: they appear in the content list with source `ci`.
2. In the repository, add secrets `BRANDLINT_URL`, `BRANDLINT_EMAIL` and `BRANDLINT_PASSWORD`.
3. Add this workflow, for example `.github/workflows/brandlint.yml`:

```yaml
name: brandlint
on:
  pull_request:
    paths: ["**/*.md", "**/*.txt", "**/*.html", "**/*.docx"]
jobs:
  copy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: AnoushkaSundar/brandlint/.github/actions/brandlint@main
        with:
          url: ${{ secrets.BRANDLINT_URL }}
          email: ${{ secrets.BRANDLINT_EMAIL }}
          password: ${{ secrets.BRANDLINT_PASSWORD }}
          channel: blog
          fail-on: medium
```

4. To make it block the merge, make the `brandlint / copy` check **required** in the
   branch protection rules for `main`. Without that, a failing check is only a warning.

A ready-made version that only runs for a `copy/` folder, and says so loudly when the
secrets are missing, is in `docs/examples/brandlint-workflow.yml`.

Every input is optional except the three above: `paths`, `exclude`, `fail-on`, `unsure`,
`channel`, `data-class` (default `internal`) and `max-files`.

The job summary lists each file with its findings and a link to the review. Blocking
findings also appear as annotations on the changed line of the pull request.

**Pull requests from forks don't get repository secrets,** so the check can't sign in and
fails. Re-run it from a branch in the repository. Use `pull_request`, never
`pull_request_target`, so untrusted code never runs with the secrets.

## Pre-commit

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/AnoushkaSundar/brandlint
    rev: main
    hooks:
      - id: brandlint
```

Set `BRANDLINT_URL`, `BRANDLINT_EMAIL` and `BRANDLINT_PASSWORD` in your shell. The hook
checks the staged `.md`, `.txt`, `.html` and `.docx` files and prints the same links.
Reaching the server takes a few seconds per file, so it suits copy repositories more than
code repositories. Use `--no-verify` only for a commit you'll have reviewed another way.

## Command line

```bash
BRANDLINT_URL=https://brandlint.example.com \
BRANDLINT_EMAIL=ci@example.com BRANDLINT_PASSWORD=... \
python3 scripts/brandlint_ci.py README.md docs/launch-post.md --channel blog --fail-on medium
```

`--changed-since origin/main` checks what a branch changed. `--api-url` points at an API
that isn't under `<url>/api`. Exit codes: `0` passed, `1` blocked by a finding, `2` couldn't
check.

## Good to know

- **What's sent:** the file's text goes to the BrandLint server, which masks protected values
  and personal data before any model sees it, by the policy for its `data-class`.
- **Cost:** each file is a full review, a few cents with the real models. A repeat of the
  same text is answered from the verdict cache.
- **Line numbers** are found by locating the flagged words in the file. When they can't be
  found, for example in a `.docx`, the annotation goes on line 1.
- **The review links** open the review page. They need a signed-in reviewer or the creator
  account CI uses.
