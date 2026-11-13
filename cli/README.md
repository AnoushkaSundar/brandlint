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
