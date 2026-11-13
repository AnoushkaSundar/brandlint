"""The server's answer to "may this merge?": one pure function over findings and a policy.

A finding blocks when it is a VIOLATION at or above the policy's severity threshold, or
UNSURE when the policy fails UNSURE (the default, because an UNSURE finding blocks approval
everywhere else), and nobody has dealt with it. Only two standings count as dealt with:
`override_confirmed` (a reviewer let it through) and `resolved` (a reviewer settled it). An
override still waiting for a reviewer, an edited or accepted fix and a rejected override
don't, so the answer fails closed. A waiver is therefore just a reviewer's decision in the
web app: nothing new is needed to let a finding through.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.contracts import CIFileResult, CIFinding, FindingStatus, Severity, Verdict

SEVERITY_ORDER = {
    Severity.low: 0,
    Severity.medium: 1,
    Severity.high: 2,
    Severity.critical: 3,
}
PASSED = frozenset({FindingStatus.override_confirmed, FindingStatus.resolved})
# How many blocking findings the reasons list by name.
REASONS_SHOWN = 10


@dataclass(frozen=True)
class Policy:
    severity_threshold: Severity
    fail_on_unsure: bool
    ignore_rules: frozenset[str]
    max_waiting_minutes: int


DEFAULT_POLICY = Policy(Severity.medium, True, frozenset(), 15)


def blocks(finding: CIFinding, policy: Policy) -> bool:
    if finding.verdict is Verdict.PASS or finding.status in PASSED:
        return False
    if finding.rule_id is not None and finding.rule_id in policy.ignore_rules:
        return False
    if finding.verdict is Verdict.UNSURE:
        return policy.fail_on_unsure
    return SEVERITY_ORDER[finding.severity] >= SEVERITY_ORDER[policy.severity_threshold]


def _reason(path: str, finding: CIFinding) -> str:
    where = f"{path}:{finding.line}" if finding.line else path
    rule = finding.rule_id or "no rule"
    kind = "UNSURE" if finding.verdict is Verdict.UNSURE else finding.severity.value
    return f"{where} {finding.title} ({rule}, {kind})"


def judge(files: Sequence[CIFileResult], policy: Policy) -> tuple[str, list[str]]:
    """`pass` or `fail`, and why. Marks each finding that blocks. Titles and rule ids only:
    a reason never quotes the draft."""
    blocking: list[tuple[str, CIFinding]] = []
    for file in files:
        for finding in file.findings:
            finding.blocking = blocks(finding, policy)
            if finding.blocking:
                blocking.append((file.path, finding))
    if not blocking:
        return "pass", []
    noun = "finding blocks" if len(blocking) == 1 else "findings block"
    reasons = [f"{len(blocking)} {noun} this run."]
    reasons += [_reason(path, finding) for path, finding in blocking[:REASONS_SHOWN]]
    if len(blocking) > REASONS_SHOWN:
        reasons.append(f"…and {len(blocking) - REASONS_SHOWN} more.")
    return "fail", reasons
