# brandlint-cli

Check the copy in a repo against your BrandLint rulebook, locally and in CI.

```bash
pip install ./cli                       # or: pip install brandlint-cli
export BRANDLINT_TOKEN=bl_...           # a service token from CI settings in BrandLint
brandlint check                         # every file .brandlint.yml says holds copy
brandlint check --changed-against origin/main
brandlint check --staged                # what you are about to commit
```

Exit codes: `0` passed, `1` a finding blocks, `2` a config or usage error, `3` BrandLint could not be reached or errored (`--on-error pass|warn` changes that to 0).

The token comes from `BRANDLINT_TOKEN` only, never a flag, and is masked in every message. The server decides pass or fail; this tool only sends the copy and reports. See `docs/ci-integration.md`.

## `.brandlint.yml`

```yaml
server: https://your-brandlint.example/api
channels:               # no file is checked unless a rule here matches it
  - glob: "docs/**/*.md"
    channel: blog       # blog, linkedin, email, ad, banner or document
ignore:
  - "docs/drafts/**"
```

## As a pre-commit hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/OWNER/brandlint
    rev: COMMIT_SHA        # pin by commit
    hooks:
      - id: brandlint      # checks staged copy at commit time
      # - id: brandlint-push   # or at push time, if commit time is too slow
```

Set `BRANDLINT_TOKEN` in your environment, and have a `.brandlint.yml` in the repo. If BrandLint is slow (20 seconds) or unreachable, the hook prints one line and lets the commit through; add `args: [--strict]` to block instead. A real finding always blocks. `git commit --no-verify` skips the hook, which is why the GitHub Action, not the hook, is the thing that enforces.
