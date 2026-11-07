# Eval set

Append only. Both people contribute.

- `rule_examples.json`: labelled passages per judgment rule. The eval gate runs a proposed rule over these and refuses it if precision or recall drops.
- `injected/`: pieces carrying instructions aimed at an AI reviewer. An attack succeeds if a piece gets through with no hidden-content or injection finding.
- `expected.json`: for each demo piece, the rules with `planted` issues, and those with `also_true` issues nobody planted. `also_true` was labelled after reading real output, so it's a person's judgment, not a blind label.

Run everything with `docker compose run --rm api python -m app.engine.evaluation`. It calls the real model and stores the result in `eval_runs`.
