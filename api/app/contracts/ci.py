"""The CI/CD integration contract (contracts/v4), mirrored in web/lib/contracts.ts.

A CI job (the GitHub Action, the pre-commit hook, or `brandlint check`) submits the copy
files it found as a run, and reads back the server's verdict. The server decides pass or
fail, never the client. See docs/ci-integration.md.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .enums import DataClass, FindingStatus, Severity, Verdict

# The same channels a creator can pick in the web app.
CIChannel = Literal["blog", "linkedin", "email", "ad", "banner", "document"]
CIRunState = Literal["queued", "running", "done", "error"]
CIResult = Literal["pass", "fail"]


class CIFile(BaseModel):
    """One file's copy: its text, or a binary file (DOCX, PDF, an image) as base64."""

    path: str = Field(min_length=1, max_length=512)
    channel: CIChannel
    text: str | None = None
    file_b64: str | None = None
    data_class: DataClass = DataClass.public

    @model_validator(mode="after")
    def _text_or_file(self) -> CIFile:
        if (self.text is None) == (self.file_b64 is None):
            raise ValueError("send exactly one of text and file_b64")
        return self


class CIRunRequest(BaseModel):
    repo: str = Field(min_length=1, max_length=255)
    pr: int | None = None
    sha: str = Field(min_length=1, max_length=64)
    base_sha: str | None = Field(default=None, max_length=64)
    files: list[CIFile] = Field(min_length=1)


class CIPolicy(BaseModel):
    """What counts as a failure. A workspace setting; the server applies it."""

    severity_threshold: Severity = Severity.medium
    fail_on_unsure: bool = True


class CIFinding(BaseModel):
    id: str
    rule_id: str | None = None
    severity: Severity
    verdict: Verdict
    status: FindingStatus
    # A short quote of the flagged text, never more than a sentence or so.
    span: str
    # 1-based line in the text that was submitted, when the server can tell.
    line: int | None = None
    title: str
    # Opens the finding in BrandLint. Needs sign-in to the same workspace.
    url: str
    # True when this finding is why the run fails.
    blocking: bool = False


class CIFileResult(BaseModel):
    path: str
    content_id: str
    review_id: str
    state: CIRunState
    findings: list[CIFinding] = Field(default_factory=list)


class CIRunStatus(BaseModel):
    id: str
    state: CIRunState
    # Set once the run is done. An error run has no result, and never counts as a pass.
    result: CIResult | None = None
    reasons: list[str] = Field(default_factory=list)
    files: list[CIFileResult] = Field(default_factory=list)
    url: str
    policy: CIPolicy
