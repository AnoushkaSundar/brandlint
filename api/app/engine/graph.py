"""The review graph: a fixed LangGraph graph with four parallel tracks.

    START -> tier0, language, claims, document -> critic -> END

There is no planner: the edges below are the whole control flow. Tracks only add
to `candidates`, and the critic alone decides what becomes a finding.
"""

from __future__ import annotations

import operator
import os
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.clients.gateway import llm_call
from app.contracts import Finding, Gap
from app.engine import critic
from app.engine.agents import language
from app.engine.agents.language import ClassifyFn
from app.engine.checks import (
    SEC_CONFIDENTIAL,
    SEC_HIDDEN_CONTENT,
    SEC_INJECTION,
    CheckContext,
    check_hidden_content,
    detect_instructions,
    run_tier0,
)
from app.engine.chunking import ParsedChunk
from app.engine.critic import Candidate
from app.gateway.llm import PINNED_MODEL

# LangGraph ships with LangSmith. Tracing would send content to an outside
# service around the gateway, so it stays off whatever the environment says.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

GapSink = Callable[[list[Gap]], None]


class ReviewState(TypedDict, total=False):
    chunks: list[ParsedChunk]
    ctx: CheckContext
    fmt: str
    candidates: Annotated[list[Candidate], operator.add]
    findings: list[Finding]
    gaps: list[Gap]


def gateway_classify(session_factory: Callable[[], Session]) -> ClassifyFn:
    """A thread-safe classify: each call gets its own session for gateway_log."""

    def classify(
        data_class: str,
        rule_ids: list[str],
        payload: dict[str, Any],
        review_id: str,
    ) -> dict[str, Any]:
        with session_factory() as session:
            try:
                return llm_call(
                    "classify",
                    data_class,
                    rule_ids,
                    payload,
                    session=session,
                    review_id=review_id,
                )
            finally:
                # A failed call must stay in the log too.
                session.commit()

    return classify


def flagged_chunk_ids(chunks: list[ParsedChunk], ctx: CheckContext) -> set[str]:
    """Chunks where either injection detector fired."""
    return {
        span.chunk_id
        for finding in [
            *check_hidden_content(chunks, ctx),
            *detect_instructions(chunks, ctx),
        ]
        for span in finding.spans
    }


def known_rule_ids(ctx: CheckContext) -> set[str]:
    return {
        *(rule.id for rule in ctx.rules),
        SEC_CONFIDENTIAL,
        SEC_HIDDEN_CONTENT,
        SEC_INJECTION,
    }


def build_review_graph(
    classify: ClassifyFn,
    *,
    gap_sink: GapSink,
    model: str = PINNED_MODEL,
) -> Any:
    def tier0(state: ReviewState) -> dict:
        found = run_tier0(state["chunks"], state["ctx"], state["fmt"])
        return {"candidates": [Candidate.from_finding(f) for f in found]}

    def language_track(state: ReviewState) -> dict:
        chunks, ctx = state["chunks"], state["ctx"]
        found = language.review_chunks(
            chunks,
            ctx,
            classify,
            flagged=flagged_chunk_ids(chunks, ctx),
            model=model,
        )
        return {"candidates": found}

    def claims(state: ReviewState) -> dict:
        return {"candidates": []}  # Claims agent lands in block 5.

    def document(state: ReviewState) -> dict:
        return {"candidates": []}  # Tone-drift pass lands in block 5.

    def critic_node(state: ReviewState) -> dict:
        ctx = state["ctx"]
        findings, gaps = critic.gate(
            state["candidates"],
            known_rule_ids=known_rule_ids(ctx),
            known_fact_ids={fact.id for fact in ctx.facts},
        )
        if gaps:
            gap_sink(gaps)
        return {"findings": findings, "gaps": gaps}

    graph = StateGraph(ReviewState)
    graph.add_node("tier0", tier0)
    graph.add_node("language", language_track)
    graph.add_node("claims", claims)
    graph.add_node("document", document)
    graph.add_node("critic", critic_node)
    tracks = ["tier0", "language", "claims", "document"]
    for track in tracks:
        graph.add_edge(START, track)
    graph.add_edge(tracks, "critic")  # Waits for all four tracks.
    graph.add_edge("critic", END)
    return graph.compile()


def run_review(
    chunks: list[ParsedChunk],
    ctx: CheckContext,
    fmt: str,
    classify: ClassifyFn,
    *,
    gap_sink: GapSink,
    model: str = PINNED_MODEL,
    on_finding: Callable[[Finding], None] | None = None,
) -> tuple[list[Finding], list[Gap]]:
    """Runs the graph. `on_finding` gets each finding once, as soon as its track
    finishes, so code findings don't wait for the model. Tier 0 always goes first:
    a fast model's findings wait until the code checks have reported. Every one
    has passed the critic. The returned list is the final word."""
    graph = build_review_graph(classify, gap_sink=gap_sink, model=model)
    known_facts = {fact.id for fact in ctx.facts}
    collected: list[Candidate] = []
    published: set[str] = set()
    findings: list[Finding] = []
    gaps: list[Gap] = []
    tier0_reported = False

    def publish(ready: list[Finding]) -> None:
        for finding in ready:
            if finding.id not in published:
                published.add(finding.id)
                if on_finding:
                    on_finding(finding)

    for update in graph.stream(
        {"chunks": chunks, "ctx": ctx, "fmt": fmt, "candidates": []},
        stream_mode="updates",
    ):
        for node, change in update.items():
            if node == "critic":
                findings, gaps = change["findings"], change["gaps"]
                publish(findings)
                continue
            collected.extend((change or {}).get("candidates", []))
            tier0_reported = tier0_reported or node == "tier0"
            if not tier0_reported:
                continue
            ready, _ = critic.gate(
                collected,
                known_rule_ids=known_rule_ids(ctx),
                known_fact_ids=known_facts,
            )
            publish(ready)
    return findings, gaps
