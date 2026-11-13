"""Block 3: the server's answer to "may this merge?", as one pure function and a policy."""

from __future__ import annotations

import itertools

import pytest
from app.ci.verdict import Policy, blocks, judge
from app.contracts import CIFileResult, CIFinding, FindingStatus, Severity, Verdict

SEVERITIES = list(Severity)
STATUSES = list(FindingStatus)
VERDICTS = list(Verdict)
# The only standings a person can leave a finding in that let it through.
PASSED = {FindingStatus.override_confirmed, FindingStatus.resolved}
ORDER = {Severity.low: 0, Severity.medium: 1, Severity.high: 2, Severity.critical: 3}


def finding(verdict=Verdict.VIOLATION, severity=Severity.high, status=FindingStatus.open, rule="R-1"):
    return CIFinding(
        id="f1",
        rule_id=rule,
        severity=severity,
        verdict=verdict,
        status=status,
        span="x",
        title="A finding",
        url="https://app.example/ci/runs/r#finding-f1",
    )


def policy(threshold=Severity.medium, unsure=True, ignore=()):
    return Policy(threshold, unsure, frozenset(ignore), 15)


# --- Every verdict x status x severity x policy ------------------------------------------


@pytest.mark.parametrize(
    "verdict, status, severity, threshold, unsure",
    list(itertools.product(VERDICTS, STATUSES, SEVERITIES, SEVERITIES, [True, False])),
)
def test_a_finding_blocks_exactly_when_the_policy_says(verdict, status, severity, threshold, unsure):
    """The whole table, written out the long way so the rule isn't tested against itself."""
    if verdict is Verdict.PASS or status in PASSED:
        expected = False
    elif verdict is Verdict.UNSURE:
        expected = unsure
    else:
        expected = ORDER[severity] >= ORDER[threshold]
    assert blocks(finding(verdict, severity, status), policy(threshold, unsure)) is expected


def test_unsure_fails_by_default_and_passes_when_the_policy_says():
    unsure = finding(Verdict.UNSURE, Severity.low)
    assert blocks(unsure, policy()) is True
    assert blocks(unsure, policy(unsure=False)) is False


def test_a_creators_override_at_low_severity_still_needs_a_reviewers_confirmation():
    low = finding(Verdict.VIOLATION, Severity.low, FindingStatus.override_pending)
    # Below the default threshold it never blocks, so tighten the threshold to see the rule.
    assert blocks(low, policy(Severity.low)) is True
    assert blocks(finding(Verdict.VIOLATION, Severity.low, FindingStatus.override_confirmed), policy(Severity.low)) is False


def test_an_ignored_rule_never_blocks_but_a_finding_without_a_rule_is_not_ignored():
    assert blocks(finding(rule="R-9"), policy(ignore={"R-9"})) is False
    assert blocks(finding(rule=None), policy(ignore={"R-9"})) is True


# --- The result ------------------------------------------------------------------------


def file_result(path, *findings, state="done"):
    return CIFileResult(path=path, content_id="c", review_id="r", state=state, findings=list(findings))


def test_a_run_with_nothing_that_blocks_passes():
    result, reasons = judge(
        [file_result("a.md", finding(Verdict.PASS), finding(status=FindingStatus.resolved))],
        policy(),
    )
    assert (result, reasons) == ("pass", [])


def test_a_run_fails_with_reasons_that_say_where_and_why_without_quoting_the_draft():
    bad = finding(severity=Severity.critical)
    bad.line = 4
    result, reasons = judge([file_result("docs/a.md", bad), file_result("docs/b.md")], policy())
    assert result == "fail"
    assert reasons[0] == "1 finding blocks this run."
    assert "docs/a.md:4" in reasons[1] and "R-1" in reasons[1] and "critical" in reasons[1]
    assert bad.blocking is True


def test_the_reasons_are_capped():
    many = [finding(rule=f"R-{n}") for n in range(30)]
    result, reasons = judge([file_result("a.md", *many)], policy())
    assert result == "fail" and len(reasons) <= 12 and "more" in reasons[-1]
