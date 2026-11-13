# BrandLint GitHub Action

Checks the copy a pull request changed, annotates the lines, keeps one comment up to date, and fails the check when a finding blocks.

1. In BrandLint, open **CI settings** and make a service token. Put it in the repo's secrets as `BRANDLINT_TOKEN`.
2. Add a `.brandlint.yml` saying which files hold copy (see `cli/README.md`).
3. Copy `example-workflow.yml` to `.github/workflows/brandlint.yml`, and **pin the action by commit SHA**.
4. To block merges, require the **BrandLint** check in branch protection. **The action only reports: GitHub's branch protection does the blocking.**

It needs only `contents: read` and `pull-requests: write` (for the comment). The check fetches the base commit, so check out with `fetch-depth: 0`.

**Fork pull requests** get no secrets from GitHub, so the check cannot run. By default it fails with a clear message (never a pass). Set `on-fork: skip` to leave them unchecked. Never use `pull_request_target` to get around this: it would run with secrets on a stranger's change.

Dependencies are pinned by hash (`requirements.txt`, installed with `--require-hashes`). To bump one, update the pin in `requirements.txt` with all the file hashes PyPI lists for that version.
