"""The eval set: the gate a proposed rule must pass, and the full run for the pitch.

The gate judges labelled passages with the current rule and the proposed one, and
refuses the proposal if precision or recall drops. It decides from counts, so a model
that drafts an amendment can't argue it through.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.contracts import ContentSource, DataClass, Proposal, Rule, Verdict
from app.engine.agents import language
from app.engine.agents.language import ClassifyFn
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, sha256_text
from app.governance.models import EvalRun

logger = logging.getLogger(__name__)

EVAL_DIR = pathlib.Path(os.getenv("EVAL_DIR", "/eval"))
DEMO_DIR = pathlib.Path(os.getenv("DEMO_DIR", "/demo"))
MIN_EXAMPLES = 4
WORKERS = 8
# A check that proves an attack was caught.
CAUGHT = {"hidden_content", "injection"}
DEMO_PIECES = (("agency-blog", "agency-blog.docx", "blog"),
               ("linkedin-post", "linkedin-post.html", "linkedin"))


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    true_positives: int
    false_positives: int
    false_negatives: int


def score(pairs: list[tuple[bool, bool]]) -> Score:
    """`pairs` are (expected a flag, got a flag)."""
    tp = sum(1 for expected, got in pairs if expected and got)
    fp = sum(1 for expected, got in pairs if not expected and got)
    fn = sum(1 for expected, got in pairs if expected and not got)
    return Score(
        precision=tp / (tp + fp) if tp + fp else 1.0,
        recall=tp / (tp + fn) if tp + fn else 1.0,
        true_positives=tp, false_positives=fp, false_negatives=fn,
    )


def load_examples(rule_id: str) -> list[dict[str, str]]:
    path = EVAL_DIR / "rule_examples.json"
    if not path.exists():
        return []
    return [e for e in json.loads(path.read_text("utf8")) if e["rule_id"] == rule_id]


def _chunk(number: int, text: str) -> ParsedChunk:
    return ParsedChunk(
        id=f"eval:{number}", content_version_id="eval", ordinal=number, kind="paragraph",
        text=text, content_hash=sha256_text(text), data_class=DataClass.public.value,
        style=None,
    )


def judge_examples(
    rule: Rule, examples: list[dict[str, str]], classify: ClassifyFn, model: str
) -> Score:
    """UNSURE counts as a flag, because it stops a piece just as a violation does."""

    def flagged(pair: tuple[int, dict[str, str]]) -> tuple[bool, bool]:
        number, example = pair
        ctx = CheckContext(
            review_id="eval-gate", content_version_id="eval",
            channel=example["channel"], rules=[rule], facts=[], terms=[],
            as_of=date.today(),
        )
        found = language.judge(
            _chunk(number, example["text"]), rule, ctx, classify, flagged=(), model=model
        )
        return example["verdict"] == Verdict.VIOLATION.value, found is not None

    with ThreadPoolExecutor(WORKERS) as pool:
        return score(list(pool.map(flagged, enumerate(examples))))


def gate(
    proposal: Proposal,
    rule: Rule,
    session: Session,
    classify: ClassifyFn,
    *,
    model: str,
) -> dict[str, Any]:
    """Refuses a proposal it can't measure, so a gap in the set isn't a pass."""
    examples = load_examples(rule.id)
    if len(examples) < MIN_EXAMPLES:
        result = {"passed": False, "precision": 0.0, "recall": 0.0}
        details: dict[str, Any] = {"reason": "not enough labelled examples"}
    else:
        amended = rule.model_copy(
            update={"text": proposal.suggested, "version": rule.version + 1}
        )
        before = judge_examples(rule, examples, classify, model)
        after = judge_examples(amended, examples, classify, model)
        result = {
            "passed": after.precision >= before.precision and after.recall >= before.recall,
            "precision": round(after.precision, 3),
            "recall": round(after.recall, 3),
        }
        details = {"before": before.__dict__, "after": after.__dict__}
    session.add(
        EvalRun(
            id=str(uuid.uuid4()), kind="gate", precision=result["precision"],
            recall=result["recall"], passed=result["passed"],
            details={"proposal": proposal.id, "rule_id": rule.id, **details},
        )
    )
    session.commit()
    return result


Run = Callable[[str, bytes, str, str], list[dict[str, Any]]]


def _expected(name: str) -> set[str]:
    found = json.loads((DEMO_DIR / "findings" / f"{name}.json").read_text("utf8"))
    return {f["rule_id"] for f in found if f.get("rule_id")}


def piece_scores(run: Run) -> dict[str, Any]:
    """Expected rule ids against the rule ids a real review raised, per demo piece."""
    pairs: list[tuple[bool, bool]] = []
    pieces = {}
    for name, file_name, channel in DEMO_PIECES:
        data = (DEMO_DIR / "pieces" / file_name).read_bytes()
        expected = _expected(name)
        got = {f["rule_id"] for f in run(file_name, data, channel, "public") if f["rule_id"]}
        pairs += [(rule in expected, rule in got) for rule in expected | got]
        pieces[name] = {
            "missed": sorted(expected - got), "extra": sorted(got - expected),
        }
    total = score(pairs)
    flagged = total.true_positives + total.false_positives
    return {
        "precision": total.precision,
        "recall": total.recall,
        "false_flag_rate": total.false_positives / flagged if flagged else 0.0,
        "pieces": pieces,
    }


def attack_scores(run: Run) -> dict[str, Any]:
    """An attack succeeds if the piece raises no hidden-content or injection finding."""
    paths = sorted((EVAL_DIR / "injected").iterdir())
    survived = []
    for path in paths:
        found = run(path.name, path.read_bytes(), "blog", "public")
        if not any(f["check"] in CAUGHT for f in found):
            survived.append(path.name)
    return {
        "attacks": len(paths),
        "survived": survived,
        "attack_success_rate": len(survived) / len(paths) if paths else 0.0,
    }


def full_run(session: Session, run: Run) -> dict[str, Any]:
    pieces, attacks = piece_scores(run), attack_scores(run)
    session.add(
        EvalRun(
            id=str(uuid.uuid4()), kind="full", precision=pieces["precision"],
            recall=pieces["recall"], false_flag_rate=pieces["false_flag_rate"],
            attack_success_rate=attacks["attack_success_rate"],
            passed=not attacks["survived"],
            details={"pieces": pieces["pieces"], "survived": attacks["survived"]},
        )
    )
    session.commit()
    return {**pieces, **attacks}


def _real_run(file_name: str, data: bytes, channel: str, data_class: str) -> list[dict]:
    from app.clients import engine as engine_client
    from app.engine import reviews

    source = ContentSource(
        data_class=DataClass(data_class), file_name=file_name, file_bytes=data
    )
    version = f"eval-{uuid.uuid4().hex[:8]}"
    review_id = engine_client.start_review(version, channel, 1, source)
    run = reviews.get_run(review_id)
    if run is None or not run.finished.wait(180):
        raise TimeoutError(f"{file_name} didn't finish")
    return [payload for name, payload in run.events if name == "finding"]


if __name__ == "__main__":
    from app.db import get_sessionmaker

    with get_sessionmaker()() as session:
        print(json.dumps(full_run(session, _real_run), indent=2))
