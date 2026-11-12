"""Voting on high and critical judgment findings.

At temperature 0 the same prompt gives the same answer, so a vote varies the judge:
two further rubrics with their own anchors, and for claims a second model from another
provider. A split never decides anything. It sends the finding to a reviewer as UNSURE.

Only model judgments are voted on. A number checked against the facts store is code,
and a majority can't overturn it. Findings are voted on inside their track, so a
finding never streams as a violation and then changes.
"""

from __future__ import annotations

from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor

from app.contracts import CheckType, DataClass, Rule, Severity, Verdict, Vote
from app.engine.agents import language
from app.engine.agents.anchors import VARIANTS
from app.engine.agents.language import ClassifyFn
from app.engine.cache import VerdictCache
from app.engine.checks.context import CheckContext
from app.engine.chunking import ParsedChunk
from app.engine.critic import Candidate
from app.gateway import policy

DEFAULT_WORKERS = 4
_VOTED_SEVERITIES = {Severity.high, Severity.critical}


def _due(candidate: Candidate) -> bool:
    return (
        candidate.tier == 1
        and candidate.verdict == Verdict.VIOLATION
        and candidate.severity in _VOTED_SEVERITIES
        and candidate.manifest.get("kind") == "language"
    )


def _unavailable(candidate: Candidate | None) -> bool:
    """The check never ran, as opposed to a model that couldn't decide."""
    return (
        candidate is not None
        and candidate.verdict == Verdict.UNSURE
        and candidate.confidence == 0.0
    )


def settle(
    candidate: Candidate,
    chunk: ParsedChunk,
    rule: Rule,
    ctx: CheckContext,
    classify: ClassifyFn,
    *,
    second: ClassifyFn | None,
    flagged: Collection[str],
    model: str,
    cache: VerdictCache | None = None,
) -> None:
    """Votes on a violation. A rubric that fails counts against it, because a failed
    check isn't agreement. The second model is extra, so losing it costs one ballot."""
    ballots = [Verdict.VIOLATION]
    for variant in VARIANTS:
        other = language.judge(
            chunk, rule, ctx, classify, flagged=flagged, model=model, cache=cache,
            variant=variant,
        )
        ballots.append(other.verdict if other else Verdict.PASS)

    second_used = False
    if (
        second is not None
        and candidate.check == CheckType.claim
        and policy.may_use_second_model(DataClass(chunk.data_class))
    ):
        other = language.judge(
            chunk, rule, ctx, second, flagged=flagged, model=policy.SECOND_MODEL,
            cache=cache,
        )
        if not _unavailable(other):
            ballots.append(other.verdict if other else Verdict.PASS)
            second_used = True

    agree = ballots.count(Verdict.VIOLATION)
    split = agree != len(ballots)
    candidate.vote = Vote(variants=len(ballots), agree=agree, split=split)
    candidate.manifest = {**candidate.manifest, "voted": True}
    if second_used:
        candidate.models_used = [*candidate.models_used, policy.SECOND_MODEL]
    if split:
        candidate.verdict = Verdict.UNSURE
        candidate.fix_available = False
        candidate.explanation = (
            f"{candidate.explanation} The checks disagreed ({agree} of {len(ballots)} "
            "found a violation), so a reviewer needs to decide."
        )


def apply(
    found: list[Candidate],
    chunks: list[ParsedChunk],
    ctx: CheckContext,
    classify: ClassifyFn,
    *,
    second: ClassifyFn | None,
    flagged: Collection[str],
    model: str,
    cache: VerdictCache | None = None,
    max_workers: int = DEFAULT_WORKERS,
) -> list[Candidate]:
    """Settles every finding that's due. Restricted text stays with one local vote."""
    by_id = {chunk.id: chunk for chunk in chunks}
    due = [
        candidate
        for candidate in found
        if _due(candidate)
        and not policy.stays_local(
            DataClass(by_id[candidate.manifest["chunk_id"]].data_class)
        )
    ]

    def run(candidate: Candidate) -> None:
        settle(
            candidate, by_id[candidate.manifest["chunk_id"]],
            Rule.model_validate(candidate.manifest["rule"]), ctx, classify,
            second=second, flagged=flagged, model=model, cache=cache,
        )

    if due:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(run, due))
    return found
