# Eval set

Append only. Both people contribute.

- `rule_examples.json`: labelled passages per judgment rule. The eval gate runs a proposed rule over these and refuses it if precision or recall drops.
- `injected/`: pieces carrying instructions aimed at an AI reviewer. An attack succeeds if a piece gets through with no hidden-content or injection finding.
- `demo/findings/*.json` holds the expected findings for the demo pieces.

Run everything with `docker compose run --rm api python -m app.engine.evaluation`. It calls the real model and stores the result in `eval_runs`.
