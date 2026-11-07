"""Voting: a split never decides, and a code check is never overruled."""

from __future__ import annotations

import pytest
from app.contracts import DataClass, Rule
from app.engine import graph as review_graph
from app.engine import voting
from app.engine.agents import language
from app.engine.cache import cache_key
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, sha256_text
from app.gateway import llm, masking, policy
from app.gateway.models import GatewayLog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

CLAIM = Rule(
    id="R-CLAIM-03", version=1, type="judgment", text="Do not promise outcomes.",
    clause_ref="§4.3", severity="high", channel_scope=[], status="approved",
)
TONE = Rule(
    id="R-TONE-09", version=1, type="judgment", text="Never be rude.", clause_ref="§2.9",
    severity="high", channel_scope=[], status="approved",
)
MILD = Rule(
    id="R-TONE-02", version=1, type="judgment", text="Stay calm.", clause_ref="§2.2",
    severity="medium", channel_scope=[], status="approved",
)
TEXT = "We guarantee you double your retention."


def chunk(text=TEXT, data_class="public"):
    return ParsedChunk(
        id="cv:0", content_version_id="cv", ordinal=0, kind="paragraph", text=text,
        content_hash=sha256_text(text), data_class=data_class, style=None,
    )


def context(*rules):
    return CheckContext(
        review_id="rev", content_version_id="cv", channel="blog", rules=list(rules),
    )


def reply(payload, rule_ids, verdict):
    prompt = payload["messages"][-1]["content"]
    text = prompt.split("\n")[-2]
    return {
        "control_answer": language._WORD.findall(text)[0],
        "verdicts": [{
            "rule_id": rule_ids[0], "verdict": verdict, "span": None, "confidence": 0.9,
            "explanation": "x",
        }],
    }


def model(*verdicts):
    """Answers each prompt in turn: the first judge, then each rubric, in rubric order."""

    def classify(data_class, rule_ids, payload, review_id):
        prompt = payload["messages"][-1]["content"]
        if "Judge the wording" in prompt:
            return reply(payload, rule_ids, verdicts[1])
        if "Judge the effect" in prompt:
            return reply(payload, rule_ids, verdicts[2])
        return reply(payload, rule_ids, verdicts[0])

    return classify


def second(verdict):
    return lambda data_class, rule_ids, payload, review_id: reply(payload, rule_ids, verdict)


def never(*args):
    raise AssertionError("must not be called")


def down(*args):
    raise TimeoutError


def judged(rule=CLAIM, verdicts=("VIOLATION",) * 3, *, data_class="public", second_voter=None):
    text = chunk(data_class=data_class)
    ctx = context(rule)
    classify = model(*verdicts)
    found = language.judge(text, rule, ctx, classify, flagged=(), model="m")
    voting.apply(
        [found], [text], ctx, classify, second=second_voter, flagged=(), model="m"
    )
    return found


def test_a_unanimous_vote_keeps_the_violation():
    found = judged()
    assert found.verdict == "VIOLATION"
    assert (found.vote.variants, found.vote.agree, found.vote.split) == (3, 3, False)
    assert found.fix_available


@pytest.mark.parametrize(
    "verdicts",
    [
        ("VIOLATION", "PASS", "VIOLATION"),
        ("VIOLATION", "VIOLATION", "PASS"),
        ("VIOLATION", "PASS", "PASS"),
        ("VIOLATION", "UNSURE", "VIOLATION"),
    ],
)
def test_any_split_goes_to_a_reviewer(verdicts):
    found = judged(verdicts=verdicts)
    assert found.verdict == "UNSURE"
    assert found.vote.split
    assert not found.fix_available
    assert "disagreed" in found.explanation


def test_a_rubric_that_fails_counts_against_the_finding():
    text, ctx = chunk(), context(CLAIM)
    good = model("VIOLATION", "VIOLATION", "VIOLATION")

    def flaky(data_class, rule_ids, payload, review_id):
        if "Judge the effect" in payload["messages"][-1]["content"]:
            raise TimeoutError
        return good(data_class, rule_ids, payload, review_id)

    found = language.judge(text, CLAIM, ctx, flaky, flagged=(), model="m")
    voting.apply([found], [text], ctx, flaky, second=None, flagged=(), model="m")
    assert found.verdict == "UNSURE"


def test_a_medium_finding_isnt_voted_on():
    found = judged(MILD)
    assert found.vote is None


def test_a_claim_gets_a_second_provider():
    found = judged(second_voter=second("VIOLATION"))
    assert (found.vote.variants, found.vote.agree) == (4, 4)
    assert policy.SECOND_MODEL in found.models_used


def test_the_second_provider_can_split_a_vote():
    found = judged(second_voter=second("PASS"))
    assert found.verdict == "UNSURE"
    assert (found.vote.variants, found.vote.agree, found.vote.split) == (4, 3, True)


def test_a_tone_finding_gets_no_second_provider():
    found = judged(TONE, second_voter=never)
    assert found.vote.variants == 3


def test_losing_the_second_provider_costs_one_ballot():
    found = judged(second_voter=down)
    assert found.verdict == "VIOLATION"
    assert found.vote.variants == 3
    assert policy.SECOND_MODEL not in found.models_used


@pytest.mark.parametrize("data_class", ["internal", "confidential"])
def test_the_free_tier_only_sees_public_data(data_class):
    found = judged(data_class=data_class, second_voter=never)
    assert found.vote.variants == 3


def test_restricted_text_is_not_voted_on():
    found = judged(data_class="restricted", second_voter=never)
    assert found.vote is None


def test_each_rubric_uses_its_own_examples():
    prompts = [
        language.build_payload(chunk(), CLAIM, "blog", "q", variant)["messages"][-1]["content"]
        for variant in (0, 1, 2)
    ]
    assert len(set(prompts)) == 3
    assert "How to judge" not in prompts[0]


def test_an_ordinary_prompt_is_unchanged_by_voting():
    assert language.build_payload(chunk(), CLAIM, "blog", "q") == language.build_payload(
        chunk(), CLAIM, "blog", "q", 0
    )


class Remembers:
    def __init__(self):
        self.keys = []

    def get(self, key, facts):
        self.keys.append(key)

    def put(self, key, **kwargs):
        pass


def test_variants_and_models_are_in_the_cache_key():
    cache = Remembers()
    text, ctx = chunk(), context(CLAIM)
    classify = model("VIOLATION", "VIOLATION", "VIOLATION")
    for variant in (0, 1, 2):
        language.judge(
            text, CLAIM, ctx, classify, flagged=(), model="m", cache=cache, variant=variant
        )
    language.judge(text, CLAIM, ctx, classify, flagged=(), model="other", cache=cache)
    assert len(set(cache.keys)) == 4
    assert cache_key("a", "b", "c", "d", "e", "f")


def test_a_split_stops_a_finding_ever_streaming_as_a_violation():
    text = chunk()
    ctx = context(CLAIM)
    streamed = []
    review_graph.run_review(
        [text], ctx, "text", model("VIOLATION", "PASS", "VIOLATION"),
        gap_sink=lambda gaps: None, on_finding=streamed.append, model="m",
    )
    claims = [f for f in streamed if f.rule_id == "R-CLAIM-03"]
    assert claims
    assert all(f.verdict == "UNSURE" and f.vote.split for f in claims)


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    GatewayLog.__table__.create(engine)
    with Session(engine) as s:
        yield s


@pytest.mark.parametrize("data_class", ["internal", "confidential"])
def test_the_gateway_itself_refuses_to_send_private_data_to_the_free_tier(
    monkeypatch, session, data_class
):
    """The policy table is the wall, in case a caller forgets to check."""
    monkeypatch.setattr(masking, "deny_list", lambda bind: masking.DenyList((), frozenset()))
    monkeypatch.setattr(llm, "_chat_completion", never)
    with pytest.raises(llm.PolicyBlocked):
        llm.call(
            "classify", data_class, [], {"messages": [{"role": "user", "content": "x"}]},
            session=session, model=policy.SECOND_MODEL,
        )


def test_public_data_may_reach_the_free_tier():
    assert policy.may_use_second_model(DataClass.public)
    assert not policy.may_use_second_model(DataClass.internal)
