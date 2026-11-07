"""A file the engine can't open is refused at the door, not left in ai_review."""

from __future__ import annotations

import io
import zipfile

import docx
import fitz
import pytest
from app.clients import engine as engine_client
from app.contracts import ContentSource
from app.engine import reviews
from fastapi import HTTPException


def source(name, data):
    return ContentSource(data_class="public", file_name=name, file_bytes=data)


def real_docx():
    document = docx.Document()
    document.add_paragraph("Plain words.")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def real_pdf():
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Plain words.")
    return document.tobytes()


def zip_without_a_document():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("nothing.txt", "x")
    return buffer.getvalue()


@pytest.fixture()
def started(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "false")
    calls = []
    monkeypatch.setattr(
        reviews, "start_review", lambda *args: calls.append(args) or "rev-1"
    )
    return calls


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.docx", zip_without_a_document()),
        ("a.docx", b"not a document"),
        ("a.pdf", b"%PDF-1.4 broken"),
    ],
)
def test_an_unreadable_file_is_refused_before_a_review_starts(started, name, data):
    with pytest.raises(HTTPException) as refused:
        engine_client.start_review("cv", "blog", 1, source(name, data))
    assert refused.value.status_code == 422
    assert "couldn't be read" in refused.value.detail
    assert started == []


@pytest.mark.parametrize(
    ("name", "make"), [("a.docx", real_docx), ("a.pdf", real_pdf)]
)
def test_a_readable_file_starts_as_normal(started, name, make):
    assert engine_client.start_review("cv", "blog", 1, source(name, make())) == "rev-1"


def test_pasted_text_isnt_parsed_twice(started, monkeypatch):
    monkeypatch.setattr(reviews, "parse", None)
    text = ContentSource(data_class="public", text="Plain words.")
    assert engine_client.start_review("cv", "blog", 1, text) == "rev-1"


def test_the_mock_engine_is_untouched(monkeypatch):
    monkeypatch.setenv("USE_MOCK_ENGINE", "true")
    assert engine_client.start_review("cv", "blog", 1, source("a.pdf", b"broken"))
