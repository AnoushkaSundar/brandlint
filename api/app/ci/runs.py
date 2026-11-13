"""A CI run: validating what a job sends, putting it through the review path, and reporting.

A file goes through exactly the path a creator's upload does (`content.reviewing`), as the
workspace's CI service user, so the rulebook, cache, limits and Replay are the web app's.
Nothing here approves, overrides or publishes anything: CI content stays in review.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.admin.rulebook import RulebookNotFound, rulebook_at
from app.auth.defaults import utc_now
from app.auth.models import User
from app.auth.security import hash_password
from app.ci.auth import Principal
from app.ci.models import CIPolicySetting, CIRun, CIRunFile
from app.ci.verdict import DEFAULT_POLICY, Policy, judge
from app.clients import engine as engine_client
from app.content import storage
from app.content.access import latest_review
from app.content.models import Content, ContentVersion
from app.content.reviewing import add_version, begin_review, versions
from app.contracts import (
    CIFile,
    CIFileResult,
    CIFinding,
    CIPolicy,
    CIRunRequest,
    CIRunStatus,
    ContentState,
    FindingStatus,
    Severity,
    Verdict,
)
from app.tenancy import limits, resolve_org, scoped, scoped_get
from app.workflow.decisions import finding_progress
from app.workflow.models import Review
from app.workflow.transitions import move_content

SERVICE_TAG = "ci"
EMPTY_RULEBOOK = (
    "This workspace has no approved rules yet, so nothing can be checked. Ask an admin to "
    "upload the brand guidelines and approve the rules, then run this again."
)


def _cap(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def not_a_ci_person(user_model: type = User):
    """A filter that leaves the workspace's CI service user out of a list of people."""
    return or_(user_model.tag.is_(None), user_model.tag != SERVICE_TAG)


# --- Validating what was sent ----------------------------------------------------------


@dataclass
class Prepared:
    file: CIFile
    text: str
    upload: storage.CheckedUpload | None
    digest: str
    size: int


def _refused(
    message: str, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT
) -> HTTPException:
    return HTTPException(code, message)


CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def check_path(path: str) -> None:
    """A path is relative to the repo, with forward slashes and nothing that climbs out."""
    if not path or len(path) > 512:
        raise _refused("A file needs a path of up to 512 characters.")
    if CONTROL.search(path):
        raise _refused(f"The path {path!r} contains a control character.")
    if path.startswith("/") or "\\" in path or re.match(r"^[A-Za-z]:", path):
        raise _refused(
            f"The path {path!r} must be relative to the repo, with forward slashes."
        )
    if any(part in ("..", "") for part in path.split("/")):
        raise _refused(f"The path {path!r} can't contain '..' or empty segments.")


def prepare(files: list[CIFile]) -> list[Prepared]:
    """Checks every file before anything is created, so a bad one leaves nothing behind."""
    limit = _cap("CI_MAX_FILE_BYTES", storage.MAX_UPLOAD_BYTES)
    seen: set[str] = set()
    prepared: list[Prepared] = []
    for item in files:
        check_path(item.path)
        if item.path in seen:
            raise _refused(f"The path {item.path!r} is in this run twice.")
        seen.add(item.path)
        if item.file_b64 is not None:
            try:
                data = base64.b64decode(item.file_b64, validate=True)
            except (binascii.Error, ValueError):
                raise _refused(f"{item.path}: the file isn't valid base64.") from None
            if len(data) > limit:
                raise _refused(
                    f"{item.path}: files can be up to {limit} bytes.",
                    status.HTTP_413_CONTENT_TOO_LARGE,
                )
            try:
                upload = storage.check_upload(item.path, data)
            except storage.UploadTooLarge as error:
                raise _refused(
                    f"{item.path}: {error}", status.HTTP_413_CONTENT_TOO_LARGE
                ) from None
            except storage.UploadRejected as error:
                raise _refused(f"{item.path}: {error}") from None
            prepared.append(
                Prepared(
                    item,
                    upload.text,
                    upload,
                    hashlib.sha256(data).hexdigest(),
                    len(data),
                )
            )
        else:
            text = item.text or ""
            if "\x00" in text:
                raise _refused(f"{item.path}: text can't contain a null character.")
            data = text.encode("utf-8")
            if len(data) > limit:
                raise _refused(
                    f"{item.path}: files can be up to {limit} bytes.",
                    status.HTTP_413_CONTENT_TOO_LARGE,
                )
            if not text.strip():
                raise _refused(f"{item.path}: there is no text to check.")
            prepared.append(
                Prepared(item, text, None, hashlib.sha256(data).hexdigest(), len(data))
            )
    return prepared


def run_key(body: CIRunRequest, prepared: list[Prepared]) -> str:
    """What was sent: the same repo, PR and files with the same text give the same key."""
    parts = [body.repo, str(body.pr)] + sorted(
        f"{p.file.path}:{p.digest}" for p in prepared
    )
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


# --- Quotas ----------------------------------------------------------------------------


def check_quotas(
    session: Session, principal: Principal, prepared: list[Prepared]
) -> None:
    if len(prepared) > _cap("CI_MAX_FILES_PER_RUN", 50):
        raise limits.over(
            f"A run can hold up to {_cap('CI_MAX_FILES_PER_RUN', 50)} files."
        )
    total = sum(p.size for p in prepared)
    if total > _cap("CI_MAX_BYTES_PER_RUN", 20 * 1024 * 1024):
        raise limits.over(
            "This run is larger than a run can be. Send fewer or smaller files."
        )
    since = utc_now() - timedelta(days=1)
    runs_today = session.scalar(
        scoped(session, CIRun, func.count()).where(CIRun.created_at >= since)
    )
    if runs_today >= _cap("CI_MAX_RUNS_PER_DAY", 500):
        raise limits.over("This workspace has reached its CI runs for today.")
    if principal.token_id:
        by_token = session.scalar(
            scoped(session, CIRun, func.count()).where(
                CIRun.created_at >= since, CIRun.token_id == principal.token_id
            )
        )
        if by_token >= _cap("CI_MAX_RUNS_PER_TOKEN_PER_DAY", 200):
            raise limits.over("This token has reached its CI runs for today.")
    bytes_today = session.scalar(
        scoped(session, CIRunFile, func.coalesce(func.sum(CIRunFile.size), 0)).where(
            CIRunFile.created_at >= since
        )
    )
    if bytes_today + total > _cap("CI_MAX_BYTES_PER_DAY", 200 * 1024 * 1024):
        raise limits.over("This workspace has sent as much copy as it can for today.")


# --- Putting the files through review ----------------------------------------------------


def service_user(session: Session) -> User:
    """The workspace's CI author: a creator nobody can sign in as. Made on first use."""
    user = session.scalar(scoped(session, User).where(User.tag == SERVICE_TAG))
    if user is None:
        org = resolve_org(session)
        user = User(
            email=f"ci-{org}@brandlint.invalid",
            name="BrandLint CI",
            role="creator",
            tag=SERVICE_TAG,
            # Never used: nobody knows it, and the address can't receive mail.
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        session.add(user)
        session.flush()
    return user


def _piece_for(session: Session, ci_user: User, repo: str, item: Prepared) -> Content:
    ref = f"{repo}:{item.file.path}"
    content = session.scalar(
        scoped(session, Content).where(Content.external_ref == ref)
    )
    if content is None:
        content = Content(
            title=item.file.path,
            channel=item.file.channel,
            source="ci",
            data_class=item.file.data_class.value,
            creator_id=ci_user.id,
            external_ref=ref,
        )
        session.add(content)
        session.flush()
    else:
        content.channel = item.file.channel
        content.data_class = item.file.data_class.value
    return content


def _review_the_file(
    session: Session, ci_user: User, content: Content, item: Prepared
) -> tuple[ContentVersion, Review]:
    latest_version = next(iter(versions(session, content.id)), None)
    last_sent = session.scalar(
        scoped(session, CIRunFile)
        .where(CIRunFile.content_id == content.id)
        .order_by(CIRunFile.created_at.desc())
        .limit(1)
    )
    if (
        latest_version is not None
        and last_sent is not None
        and last_sent.version_id == latest_version.id
        and last_sent.text_hash == item.digest
    ):
        # The same copy again: its review, and any decisions made on it, are still current.
        review = latest_review(session, content.id)
        if review is not None:
            return latest_version, review
    if content.state == ContentState.ai_review.value:
        # An older review of this file is superseded by the new text.
        move_content(session, content, ContentState.resolving, ci_user)
    version = add_version(
        session,
        content,
        ci_user,
        item.text,
        item.upload,
        item.file.path if item.upload else None,
    )
    return version, begin_review(session, content, ci_user)


def submit(
    session: Session, principal: Principal, body: CIRunRequest
) -> tuple[CIRun, bool]:
    """Creates the run for what was sent, or finds the one it already made. Returns the run
    and whether it is new."""
    prepared = prepare(body.files)
    key = run_key(body, prepared)
    existing = session.scalar(scoped(session, CIRun).where(CIRun.run_key == key))
    if existing is not None:
        return existing, False
    check_quotas(session, principal, prepared)

    run = CIRun(
        run_key=key,
        repo=body.repo,
        pr=body.pr,
        sha=body.sha,
        base_sha=body.base_sha,
        token_id=principal.token_id,
        created_by=principal.user.id if principal.user else None,
        policy=CIPolicy().model_dump(mode="json"),
    )
    try:
        rulebook_at(session)
    except RulebookNotFound:
        # Never a pass: a review against no rules would let everything through.
        run.state, run.reasons, run.finished_at = "error", [EMPTY_RULEBOOK], utc_now()
        session.add(run)
        session.commit()
        return run, True

    ci_user = service_user(session)
    session.add(run)
    session.flush()
    for item in prepared:
        content = _piece_for(session, ci_user, body.repo, item)
        version, review = _review_the_file(session, ci_user, content, item)
        session.add(
            CIRunFile(
                run_id=run.id,
                path=item.file.path,
                text_hash=item.digest,
                size=item.size,
                content_id=content.id,
                version_id=version.id,
                review_id=review.id,
            )
        )
    session.commit()
    return run, True


# --- Reading a run ---------------------------------------------------------------------


def base_url() -> str:
    return (
        os.getenv("CI_BASE_URL") or os.getenv("WEB_ORIGIN") or "http://localhost:3000"
    ).rstrip("/")


def _short(text: str, size: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[: size - 1] + "…"


def _line_of(version_text: str, chunk_text: str, offset: int) -> int | None:
    index = version_text.find(chunk_text[:80]) if chunk_text else -1
    return None if index < 0 else version_text.count("\n", 0, index + offset) + 1


def _finding(run: CIRun, finding, progress, chunks, version_text: str) -> CIFinding:
    span, line = "", None
    if finding.spans:
        where = finding.spans[0]
        chunk = chunks.get(where.chunk_id)
        if chunk is not None:
            span = _short(chunk.text[where.start : where.end] or chunk.text)
            line = _line_of(version_text, chunk.text, where.start)
    standing = progress.get(finding.id)
    return CIFinding(
        id=finding.id,
        rule_id=finding.rule_id,
        severity=finding.severity,
        verdict=finding.verdict,
        status=standing.status if standing else FindingStatus(finding.status),
        span=span,
        line=line,
        title=_short(finding.explanation.split(". ")[0], 120),
        url=f"{base_url()}/ci/runs/{run.id}#finding-{finding.id}",
        blocking=False,
    )


def load_policy(session: Session) -> Policy:
    """The workspace's policy, or the defaults until an admin has saved one."""
    row = session.scalar(scoped(session, CIPolicySetting))
    if row is None:
        return DEFAULT_POLICY
    return Policy(
        Severity(row.severity_threshold),
        row.fail_on_unsure,
        frozenset(row.ignore_rules or []),
        row.max_waiting_minutes,
    )


def _file_state(session: Session, review: Review) -> str:
    seen = engine_client.review_status(review.engine_review_id, session)
    return {"done": "done", "running": "running"}.get(seen, "error")


def build_status(session: Session, run: CIRun) -> CIRunStatus:
    """The run as it stands now. Findings and their standing are read fresh each time, so a
    decision made in the web app shows up on the next read."""
    rows = list(
        session.scalars(
            scoped(session, CIRunFile)
            .where(CIRunFile.run_id == run.id)
            .order_by(CIRunFile.path)
        )
    )
    files: list[CIFileResult] = []
    states: list[str] = []
    for row in rows:
        review = scoped_get(session, Review, row.review_id)
        content = scoped_get(session, Content, row.content_id)
        version = scoped_get(session, ContentVersion, row.version_id)
        state = _file_state(session, review) if review else "error"
        states.append(state)
        found: list[CIFinding] = []
        if state == "done" and review and content and version:
            if content.state == ContentState.ai_review.value:
                # The review is finished, so reviewers can now act on it: a waiver.
                move_content(
                    session, content, ContentState.resolving, service_user(session)
                )
            chunks = {
                c.id: c
                for c in engine_client.list_chunks(
                    review.engine_review_id, org_id=str(run.org_id)
                )
            }
            progress = finding_progress(session, review)
            found = [
                _finding(run, f, progress, chunks, version.text)
                for f in engine_client.list_findings(
                    review.engine_review_id, org_id=str(run.org_id)
                )
                if f.verdict is not Verdict.PASS
            ]
        files.append(
            CIFileResult(
                path=row.path,
                content_id=row.content_id,
                review_id=row.review_id,
                state=state,
                findings=found,
            )
        )

    policy = load_policy(session)
    state, reasons = run.state, list(run.reasons or [])
    if state not in ("done", "error"):
        if "error" in states:
            state = "error"
            reasons = [
                "A review didn't finish, so the run can't say whether this passes."
            ]
        elif states and all(s == "done" for s in states):
            state = "done"
        else:
            created = (
                run.created_at
                if run.created_at.tzinfo
                else run.created_at.replace(tzinfo=utc_now().tzinfo)
            )
            if utc_now() - created > timedelta(minutes=policy.max_waiting_minutes):
                state = "error"
                reasons = [
                    "The review took too long, so the run can't say whether this passes."
                ]
            else:
                state = "running"
    # The answer is worked out from the findings as they stand now and the policy as it is now,
    # so a decision in the web app, or a changed policy, shows on the next read.
    result = None
    if state == "done":
        result, reasons = judge(files, policy)
    elif state == "error":
        result = None
    snapshot = {
        "severity_threshold": policy.severity_threshold.value,
        "fail_on_unsure": policy.fail_on_unsure,
    }
    changed = (state, result, reasons, run.policy) != (
        run.state,
        run.result,
        list(run.reasons or []),
        snapshot,
    )
    if changed:
        run.state, run.result, run.reasons, run.policy = (
            state,
            result,
            reasons,
            snapshot,
        )
        if state in ("done", "error") and run.finished_at is None:
            run.finished_at = utc_now()
        session.commit()
    return CIRunStatus(
        id=run.id,
        state=state,
        result=result,
        reasons=reasons,
        files=files,
        url=f"{base_url()}/ci/runs/{run.id}",
        policy=CIPolicy(
            severity_threshold=policy.severity_threshold,
            fail_on_unsure=policy.fail_on_unsure,
        ),
    )
