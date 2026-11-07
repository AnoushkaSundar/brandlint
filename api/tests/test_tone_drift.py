"""Tone drift: code decides what counts as a citable, located result."""

from __future__ import annotations

import pytest
from app.contracts import Rule
from app.engine.agents import document
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, sha256_text
from app.engine.critic import gate

CALM = Rule(
    id="R-TONE-02", version=1, type="judgment", text="Stay calm.", clause_ref="§2.2",
    severity="medium", channel_scope=[], status="approved",
)
CTX = CheckContext(review_id="rev", content_version_id="cv", channel="blog", rules=[CALM])


def chunk(ordinal, text="Plain calm words here", kind="paragraph"):
    return ParsedChunk(
        id=f"cv:{ordinal}", content_version_id="cv", ordinal=ordinal, kind=kind,
        text=text, content_hash=sha256_text(text + str(ordinal)), data_class="public",
        style=None,
    )


BODY = [chunk(0), chunk(1), chunk(2, "ACT NOW OR LOSE EVERYTHING")]


def reply(**over):
    base = {
        "control_answer": "Plain", "drift": True, "rule_id": "R-TONE-02", "blocks": [2],
        "explanation": "Block 2 starts shouting.",
    }
    return lambda *args: base | over


def run(classify, chunks=BODY, flagged=()):
    return document.tone_drift(chunks, CTX, classify, flagged=flagged, model="m")


def test_drift_names_the_chunks_that_disagree():
    found = run(reply())
    assert found.check == "tone_drift"
    assert found.verdict == "VIOLATION"
    assert found.unit_type == "document"
    assert [s["chunk_id"] for s in found.spans] == ["cv:2"]
    assert found.rule_id == "R-TONE-02"
    assert found.cited_text == CALM.text


def test_a_steady_voice_gives_no_finding():
    assert run(reply(drift=False, blocks=[], rule_id=None)) is None


def test_short_pieces_are_skipped():
    def never(*args):
        raise AssertionError("must not call the model")

    assert run(never, BODY[:2]) is None


def test_headings_and_flagged_text_stay_out():
    seen = []

    def spy(data_class, rule_ids, payload, review_id):
        seen.append(payload["messages"][1]["content"])
        return reply(drift=False, blocks=[], rule_id=None)()

    chunks = [*BODY, chunk(3, "Heading words", "heading"), chunk(4, "secret hidden text")]
    run(spy, chunks, flagged={"cv:4"})
    assert "Heading words" not in seen[0]
    assert "secret hidden text" not in seen[0]


@pytest.mark.parametrize(
    "bad",
    [{"blocks": [99]}, {"blocks": []}, {"rule_id": "R-INVENTED"}, {"rule_id": None}],
)
def test_drift_with_no_source_goes_to_the_gap_log(bad):
    found = run(reply(**bad))
    assert found.rule_id is None
    assert not found.fact_ids
    findings, gaps = gate([found], known_rule_ids={"R-TONE-02"}, known_fact_ids=set())
    assert findings == []
    assert len(gaps) == 1


@pytest.mark.parametrize("control", ["banana", "Plain words"])
def test_a_wrong_control_answer_goes_to_a_person(control):
    assert run(reply(control_answer=control)).verdict == "UNSURE"


@pytest.mark.parametrize("raw", [[], 7, None, {"drift": "maybe"}, {"content": "no"}])
def test_malformed_replies_fail_closed(raw):
    assert run(lambda *args: raw).verdict == "UNSURE"


def test_a_model_error_fails_closed():
    def down(*args):
        raise TimeoutError

    assert run(down).verdict == "UNSURE"


def test_a_failed_control_on_a_steady_reply_is_still_unsure():
    found = run(reply(drift=False, blocks=[], rule_id=None, control_answer="banana"))
    assert found.verdict == "UNSURE"


def test_no_tone_rule_means_no_call():
    ctx = CheckContext(review_id="r", content_version_id="cv", channel="blog", rules=[])

    def never(*args):
        raise AssertionError("must not call the model")

    assert document.tone_drift(BODY, ctx, never, model="m") is None
