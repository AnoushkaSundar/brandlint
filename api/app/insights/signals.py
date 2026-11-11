"""Signals for governance, read from each piece's latest review.

Overrides count only once a reviewer confirmed them. These are signals about rules and
patterns, never a ranking of people.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.admin.models import Gap
from app.auth.models import User
from app.clients import engine as engine_client
from app.content.access import latest_review
from app.content.models import Content
from app.contracts import FindingStatus, Verdict
from app.tenancy import bound_org, scoped
from app.workflow.decisions import finding_progress
from app.workflow.models import Decision

UNCLEAR_RATE = 0.3
# A creator's rejected-override share only means something after a few attempts.
CREATOR_MIN_OVERRIDES = 3
CREATOR_SIGNAL_RATE = 0.5
GAP_LIMIT = 50


@dataclass
class _RuleCounts:
    findings: int = 0
    overridden: int = 0
    voted: int = 0
    split: int = 0


@dataclass
class _Tally:
    rules: dict[str, _RuleCounts] = field(
        default_factory=lambda: defaultdict(_RuleCounts)
    )
    by_day: Counter = field(default_factory=Counter)
    by_check: Counter = field(default_factory=Counter)
    unavailable: list[str] = field(default_factory=list)


def _pieces(session: Session, channel: str | None, source: str | None) -> list[Content]:
    query = scoped(session, Content).order_by(Content.created_at)
    if channel:
        query = query.where(Content.channel == channel)
    if source:
        query = query.where(Content.source == source)
    return list(session.scalars(query))


def _tally(session: Session, pieces: list[Content]) -> tuple[_Tally, dict[str, str]]:
    tally = _Tally()
    creator_of: dict[str, str] = {}
    for content in pieces:
        review = latest_review(session, content.id)
        if review is None:
            continue
        creator_of[review.id] = content.creator_id
        try:
            findings = engine_client.list_findings(review.engine_review_id, org_id=bound_org(session))
        except Exception:  # noqa: BLE001 - one piece mustn't hide the rest
            tally.unavailable.append(content.id)
            continue
        progress = finding_progress(session, review)
        for finding in findings:
            if finding.verdict is Verdict.PASS:
                continue
            tally.by_day[review.created_at.date().isoformat()] += 1
            tally.by_check[finding.check.value] += 1
            if not finding.rule_id:
                continue
            counts = tally.rules[finding.rule_id]
            counts.findings += 1
            standing = progress.get(finding.id)
            if standing and standing.status is FindingStatus.override_confirmed:
                counts.overridden += 1
            if finding.vote is not None:
                counts.voted += 1
                counts.split += int(finding.vote.split)
    return tally, creator_of


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 3) if whole else 0.0


def _creator_signals(session: Session, creator_of: dict[str, str]) -> list[dict]:
    """Creators whose overrides reviewers mostly reject: a sign they need guidance."""
    if not creator_of:
        return []
    decided = session.scalars(
        scoped(session, Decision).where(
            Decision.review_id.in_(list(creator_of)),
            Decision.status.in_(
                [
                    FindingStatus.override_confirmed.value,
                    FindingStatus.override_rejected.value,
                ]
            ),
        )
    )
    confirmed: Counter = Counter()
    rejected: Counter = Counter()
    for decision in decided:
        creator = creator_of[decision.review_id]
        if decision.status == FindingStatus.override_rejected.value:
            rejected[creator] += 1
        else:
            confirmed[creator] += 1

    names = {
        user.id: user.name
        for user in session.scalars(
            scoped(session, User).where(User.id.in_(list(creator_of.values())))
        )
    }
    signals = []
    for creator in set(confirmed) | set(rejected):
        total = confirmed[creator] + rejected[creator]
        rate = _rate(rejected[creator], total)
        if total >= CREATOR_MIN_OVERRIDES and rate > CREATOR_SIGNAL_RATE:
            signals.append(
                {
                    "creator": names.get(creator, creator),
                    "overrides": total,
                    "rejected_rate": rate,
                }
            )
    return sorted(signals, key=lambda signal: -signal["rejected_rate"])


def signals(
    session: Session, *, channel: str | None = None, source: str | None = None
) -> dict:
    pieces = _pieces(session, channel, source)
    tally, creator_of = _tally(session, pieces)
    rules = sorted(tally.rules.items(), key=lambda item: (-item[1].findings, item[0]))
    gaps = session.scalars(scoped(session, Gap).order_by(Gap.created_at.desc()).limit(GAP_LIMIT))
    return {
        "pieces": len(pieces),
        "reviewed": len(creator_of),
        "top_rules": [
            {"rule_id": rule_id, "findings": c.findings} for rule_id, c in rules
        ],
        "override_rate_by_rule": {
            rule_id: {
                "findings": c.findings,
                "overridden": c.overridden,
                "rate": _rate(c.overridden, c.findings),
                "may_be_unclear": _rate(c.overridden, c.findings) > UNCLEAR_RATE,
            }
            for rule_id, c in rules
        },
        "vote_split_by_rule": {
            rule_id: {
                "voted": c.voted,
                "split": c.split,
                "rate": _rate(c.split, c.voted),
            }
            for rule_id, c in rules
            if c.voted
        },
        "findings_by_day": [
            {"day": day, "findings": count}
            for day, count in sorted(tally.by_day.items())
        ],
        "findings_by_check": dict(tally.by_check.most_common()),
        "creator_signals": _creator_signals(session, creator_of),
        "gaps": [
            {
                "id": gap.id,
                "review_id": gap.review_id,
                "check": gap.check,
                "text": gap.text,
                "explanation": gap.explanation,
                "created_at": gap.created_at.isoformat(),
            }
            for gap in gaps
        ],
        "unavailable": tally.unavailable,
    }
