"""Turns accepted fixes into a new version of the content."""

from collections import defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.content.models import Content, ContentVersion
from app.contracts import Chunk, Finding
from app.workflow.decisions import FindingProgress


def text_with_fixes(
    chunks: Sequence[Chunk],
    findings: Sequence[Finding],
    progress: Mapping[str, FindingProgress],
) -> str:
    """Rebuilds the text with each fix in place. Spans are offsets within a chunk."""
    edits: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    additions: list[str] = []
    for finding in findings:
        fix_text = progress.get(finding.id, FindingProgress()).fix_text
        if fix_text is None:
            continue
        if finding.spans:
            # A claim can span several places. The fix rewrites the last of them.
            span = finding.spans[-1]
            edits[span.chunk_id].append((span.start, span.end, fix_text))
        else:
            # A document-level fix has nowhere to go, such as a missing disclaimer.
            additions.append(fix_text)

    parts = []
    for chunk in sorted(chunks, key=lambda item: item.ordinal):
        if chunk.kind == "image":
            continue
        text = chunk.text
        limit = len(text)
        # Right to left, so one edit never shifts the offsets of the next.
        for start, end, fix_text in sorted(edits[chunk.id], reverse=True):
            if end <= limit:
                text = text[:start] + fix_text + text[end:]
                limit = start
        parts.append(text)
    return "\n\n".join([*parts, *additions])


def save_fixed_version(
    session: Session, content: Content, text: str, actor: User
) -> ContentVersion | None:
    """Adds a version with the fixes applied, unless the newest already has this text."""
    latest = session.scalar(
        select(ContentVersion)
        .where(ContentVersion.content_id == content.id)
        .order_by(ContentVersion.version.desc())
        .limit(1)
    )
    if latest is not None and latest.text == text:
        return None
    version = ContentVersion(
        content_id=content.id,
        version=(latest.version if latest else 0) + 1,
        text=text,
        created_by=actor.id,
    )
    session.add(version)
    return version
