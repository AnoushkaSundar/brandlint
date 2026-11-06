"""Runs a review in the background and records what it finds.

`start_review` returns straight away. A worker parses the content, runs the fixed
graph, and appends events to the run as findings appear, so the stream can read
them at its own pace. A review that fails ends with an `error` event, never with
`done`: an empty result must always mean the checks ran.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import ContentSource, Finding, Gap
from app.db import get_sessionmaker
from app.engine import graph, models
from app.engine.brand import BrandData, load_brand
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, chunk_document
from app.engine.parsers import parse

logger = logging.getLogger(__name__)

WORKERS = 2
FAILED_MESSAGE = "The review could not finish. Please try again."

_TEXT_SUFFIXES = {"txt", "md", "markdown"}
_HTML_SUFFIXES = {"html", "htm"}
_DOCUMENT_SUFFIXES = {"docx", "pdf"}
_IMAGE_SUFFIXES = {"png", "jpg", "jpeg", "webp", "tiff"}

GapSink = Callable[[list[Gap]], None]
BrandLoader = Callable[[int], BrandData]
SessionFactory = Callable[[], Session]


def log_gaps(gaps: list[Gap]) -> None:
    """Stands in for POST /admin/gaps until the product's gap log exists."""
    logger.warning("%d guideline gaps have no gap log to go to yet", len(gaps))


@dataclass
class ReviewRun:
    review_id: str
    content_version_id: str
    chunks: list[ParsedChunk] | None = None
    events: list[tuple[str, dict]] = field(default_factory=list)
    finished: threading.Event = field(default_factory=threading.Event)

    def add(self, name: str, payload: dict) -> None:
        self.events.append((name, payload))

    def finish(self, name: str, payload: dict) -> None:
        self.add(name, payload)
        self.finished.set()


_runs: dict[str, ReviewRun] = {}
_pool = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="review")


def formats(source: ContentSource) -> tuple[str | bytes, str, str]:
    """(data, parser format, tier-0 format) for this content."""
    if not source.file_bytes:
        return source.text, "text", "text"
    suffix = Path(source.file_name or "").suffix.lower().lstrip(".")
    if suffix in _TEXT_SUFFIXES:
        return source.file_bytes, suffix, "text"
    if suffix in _HTML_SUFFIXES:
        return source.file_bytes, suffix, "html"
    if suffix in _DOCUMENT_SUFFIXES:
        return source.file_bytes, suffix, suffix
    if suffix in _IMAGE_SUFFIXES:
        return source.file_bytes, suffix, "image"
    raise ValueError(f"unsupported file type: {suffix!r}")


def _save_chunks(session_factory: SessionFactory, chunks: list[ParsedChunk]) -> None:
    with session_factory() as session:
        for chunk in chunks:
            session.merge(models.Chunk(**chunk.as_dict()))
        session.commit()


def _save_findings(session_factory: SessionFactory, findings: list[Finding]) -> None:
    with session_factory() as session:
        for finding in findings:
            session.merge(models.Finding(**finding.model_dump(mode="json")))
        session.commit()


def _execute(
    run: ReviewRun,
    channel: str,
    rulebook_version: int,
    source: ContentSource,
    classify: graph.ClassifyFn,
    session_factory: SessionFactory,
    brand_loader: BrandLoader,
    gap_sink: GapSink,
) -> None:
    try:
        data, parser_format, check_format = formats(source)
        chunks = chunk_document(
            parse(data, parser_format),
            run.content_version_id,
            data_class=source.data_class.value,
        )
        _save_chunks(session_factory, chunks)
        run.chunks = chunks

        brand = brand_loader(rulebook_version)
        ctx = CheckContext(
            review_id=run.review_id,
            content_version_id=run.content_version_id,
            channel=channel,
            rules=brand.rules,
            facts=brand.facts,
            terms=brand.terms,
            as_of=date.today(),
        )
        findings, _ = graph.run_review(
            chunks,
            ctx,
            check_format,
            classify,
            gap_sink=gap_sink,
            on_finding=lambda f: run.add("finding", f.model_dump(mode="json")),
        )
        _save_findings(session_factory, findings)
        run.finish("done", {"count": len(findings)})
    except Exception:
        logger.exception("review %s failed", run.review_id)
        run.finish("error", {"message": FAILED_MESSAGE})


def start_review(
    content_version_id: str,
    channel: str,
    rulebook_version: int,
    source: ContentSource,
    *,
    classify: graph.ClassifyFn | None = None,
    session_factory: SessionFactory | None = None,
    brand_loader: BrandLoader = load_brand,
    gap_sink: GapSink = log_gaps,
) -> str:
    session_factory = session_factory or get_sessionmaker()
    run = ReviewRun(
        review_id=f"rev-{uuid.uuid4()}", content_version_id=content_version_id
    )
    _runs[run.review_id] = run
    _pool.submit(
        _execute,
        run,
        channel,
        rulebook_version,
        source,
        classify or graph.gateway_classify(session_factory),
        session_factory,
        brand_loader,
        gap_sink,
    )
    return run.review_id


def get_run(review_id: str) -> ReviewRun | None:
    return _runs.get(review_id)


def stored_events(review_id: str, session: Session) -> list[tuple[str, dict]] | None:
    """The events of a review finished before this process started, if any."""
    rows = session.scalars(
        select(models.Finding)
        .where(models.Finding.review_id == review_id)
        .order_by(models.Finding.tier, models.Finding.id)
    ).all()
    if not rows:
        return None
    fields = Finding.model_fields
    events = [
        (
            "finding",
            Finding.model_validate(
                {name: getattr(row, name) for name in fields}
            ).model_dump(mode="json"),
        )
        for row in rows
    ]
    return [*events, ("done", {"count": len(events)})]
