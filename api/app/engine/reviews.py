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

from app.admin.gaps import save_gaps
from app.checks import run_product_checks
from app.contracts import Chunk, ContentSource, Finding, Gap
from app.db import get_sessionmaker
from app.engine import graph, models
from app.engine.agents.claims import ClaimUnit
from app.engine.brand import BrandData, load_brand
from app.engine.cache import VerdictCache
from app.engine.checks import CheckContext
from app.engine.chunking import ParsedChunk, chunk_document
from app.engine.parsers import parse
from app.gateway import policy
from app.tenancy import org_sessions

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


def _gap_log(session_factory: SessionFactory) -> GapSink:
    def sink(gaps: list[Gap]) -> None:
        with session_factory() as session:
            save_gaps(session, gaps)
            session.commit()

    return sink


def _rulebook(session_factory: SessionFactory) -> BrandLoader:
    def loader(rulebook_version: int) -> BrandData:
        with session_factory() as session:
            return load_brand(session, rulebook_version)

    return loader


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


class UnreadableContent(ValueError):
    """A document that claims a format it can't be opened as."""


def check_readable(source: ContentSource) -> None:
    """Opens a document before a review starts, so a corrupt file is refused rather
    than left in review. Images are left out, because OCR is too slow to do twice."""
    data, fmt, _ = formats(source)
    if fmt not in _DOCUMENT_SUFFIXES:
        return
    try:
        parse(data, fmt)
    except Exception as exc:
        raise UnreadableContent(source.file_name) from exc


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


def _claim_log(session_factory: SessionFactory, run: ReviewRun) -> graph.ClaimSink:
    def sink(units: list[ClaimUnit]) -> None:
        with session_factory() as session:
            for unit in units:
                session.add(
                    models.ClaimUnit(
                        id=str(uuid.uuid4()),
                        review_id=run.review_id,
                        content_version_id=run.content_version_id,
                        normalized_claim=unit.text,
                        span_refs=unit.spans,
                        depends_on=unit.depends_on,
                    )
                )
            session.commit()

    return sink


def _save_findings(
    session_factory: SessionFactory,
    findings: list[Finding],
    base: dict,
    manifests: dict[str, dict],
) -> None:
    with session_factory() as session:
        for finding in findings:
            session.merge(
                models.Finding(
                    **finding.model_dump(mode="json"),
                    manifest={**base, **manifests.get(finding.id, {})},
                )
            )
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
        manifests: dict[str, dict] = {}
        model = policy.model_for(source.data_class)

        def product_checks(
            chunks: list[ParsedChunk], ctx: CheckContext, flagged: bool
        ) -> list[Finding]:
            return run_product_checks(
                data,
                check_format,
                chunks,
                ctx,
                data_class=source.data_class.value,
                session_factory=session_factory,
                classify=classify,
                model=model,
                flagged=flagged,
            )

        findings, _ = graph.run_review(
            chunks,
            ctx,
            check_format,
            classify,
            gap_sink=gap_sink,
            on_finding=lambda f: run.add("finding", f.model_dump(mode="json")),
            cache=VerdictCache(session_factory),
            manifests=manifests,
            claim_sink=_claim_log(session_factory, run),
            model=model,
            product_checks=product_checks,
        )
        base = {
            "fmt": check_format,
            "channel": channel,
            "rulebook_version": rulebook_version,
            "as_of": ctx.as_of.isoformat(),
            "facts": [{"id": f.id, "version": f.version} for f in brand.facts],
        }
        _save_findings(session_factory, findings, base, manifests)
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
    brand_loader: BrandLoader | None = None,
    gap_sink: GapSink | None = None,
    org_id: str | None = None,
) -> str:
    # Every session the review opens belongs to the org that started it.
    session_factory = org_sessions(session_factory or get_sessionmaker(), org_id)
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
        brand_loader or _rulebook(session_factory),
        gap_sink or _gap_log(session_factory),
    )
    return run.review_id


def get_run(review_id: str) -> ReviewRun | None:
    return _runs.get(review_id)


def review_status(review_id: str, session: Session) -> str:
    """running, done, failed or unknown. Only `done` means every check finished.

    A review that was running when the process stopped comes back as unknown,
    because the findings saved so far can't show that the checks completed.
    """
    run = get_run(review_id)
    if run is not None:
        if not run.finished.is_set():
            return "running"
        return "done" if run.events[-1][0] == "done" else "failed"
    return "done" if stored_events(review_id, session) else "unknown"


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


def list_findings(review_id: str, session: Session) -> list[Finding]:
    """The findings so far. Saved rows are the critic's final word once a review
    has finished; while it runs, or if it failed, these are what has been streamed."""
    run = get_run(review_id)
    stored = None
    if run is None or run.finished.is_set():
        stored = stored_events(review_id, session)
    events = stored or (run.events if run else [])
    return [Finding.model_validate(body) for name, body in events if name == "finding"]


def list_chunks(review_id: str, session: Session) -> list[Chunk]:
    run = get_run(review_id)
    if run is not None and run.chunks is not None:
        return [Chunk.model_validate(chunk.as_dict()) for chunk in run.chunks]
    version = session.scalar(
        select(models.Finding.content_version_id)
        .where(models.Finding.review_id == review_id)
        .limit(1)
    )
    if version is None:
        return []
    rows = session.scalars(
        select(models.Chunk)
        .where(models.Chunk.content_version_id == version)
        .order_by(models.Chunk.ordinal)
    ).all()
    return [
        Chunk.model_validate({name: getattr(row, name) for name in Chunk.model_fields})
        for row in rows
    ]
