# Add BrandLint to your repo in 5 minutes

You need a BrandLint workspace with approved rules, and admin rights to make a token.

**1. Make a token.** In BrandLint, open **CI settings** and create a service token. Copy it: it is shown once. In your GitHub repo, add it as a secret named `BRANDLINT_TOKEN`.

**2. Say where your copy lives.** Add `.brandlint.yml` to the repo:

```yaml
server: https://your-brandlint.example/api
channels:
  - glob: "docs/**/*.md"
    channel: blog
```

**3. Add the workflow.** Copy `integrations/github-action/example-workflow.yml` to `.github/workflows/brandlint.yml`, set `server`, and **replace `COMMIT_SHA` with the commit of the action you trust** (not a tag).

**4. Require the check.** In the repo's branch protection, require the **BrandLint** status check. This is what blocks a merge: the action itself only reports.

**5. Try it.** Open a pull request that uses a retired product name. The check fails, the line is annotated, and one comment lists the findings with links. Open a link, and a reviewer can override or resolve the finding. Re-run the check: it now passes.

At your desk, `pip install ./cli`, set `BRANDLINT_TOKEN`, and run `brandlint check --staged` before you commit, or add the pre-commit hook (see `cli/README.md`). The hook warns and lets a slow commit through, and `--no-verify` skips it: the Action is the real gate.

More: [the guide](ci-integration.md).
