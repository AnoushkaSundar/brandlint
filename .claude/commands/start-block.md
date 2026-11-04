---
description: Start a BrandLint build block for Alapan or Anoushka
argument-hint: <alapan|anoushka> <block number>
---

You are starting a BrandLint build block. Arguments: $ARGUMENTS (person, then block number).

1. If either the person or the block number is missing, ask for it before doing anything else.
2. Read `CLAUDE.md`, `docs/timeline.md` (that block's row), `docs/tasks/<person>.md`, and `docs/contracts.md`.
3. Run `git checkout main && git pull --rebase`, then create the branch named in the timeline for this block (one branch per feature).
4. List the tasks for this person in this block and confirm the plan in three to six lines. Then build them, editing **only** that person's folders as listed in CLAUDE.md.
5. Write or update tests as you go, and run them.
6. If a task needs a change to a shared file or to the other person's folder, stop and explain what's needed. Don't make the change.
7. When done, push, open the PR (draft first, ready by the merge window), and report: what works, what's still mocked, what's left, and any contract change needed.
