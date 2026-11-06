import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

TEXT_EXTENSIONS = {".txt", ".md", ".html", ".htm"}

# Signature each binary format starts with, so a renamed file can't get through.
BINARY_SIGNATURES = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class UploadRejected(ValueError):
    """The upload can't be accepted. The message is safe to show to the user."""


class UploadTooLarge(UploadRejected):
    pass


@dataclass
class CheckedUpload:
    extension: str
    data: bytes
    # Decoded text for text formats. Empty for the rest, which the engine parses.
    text: str


def check_upload(file_name: str, data: bytes) -> CheckedUpload:
    extension = Path(file_name).suffix.lower()
    if extension not in TEXT_EXTENSIONS and extension not in BINARY_SIGNATURES:
        raise UploadRejected("Upload a text, HTML, DOCX, PDF, PNG or JPEG file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadTooLarge("Files can be up to 10 MB.")
    if not data:
        raise UploadRejected("That file is empty.")

    if extension in TEXT_EXTENSIONS:
        try:
            return CheckedUpload(extension, data, data.decode("utf-8"))
        except UnicodeDecodeError:
            raise UploadRejected("Text files must be UTF-8.") from None

    if not data.startswith(BINARY_SIGNATURES[extension]):
        raise UploadRejected(f"That file isn't a valid {extension[1:].upper()}.")
    return CheckedUpload(extension, data, "")


def upload_dir() -> Path:
    default = Path(tempfile.gettempdir()) / "brandlint-uploads"
    path = Path(os.environ.get("UPLOAD_DIR", default))
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(version_id: str, upload: CheckedUpload) -> str:
    """Stores the file under a generated name, never the name the user supplied."""
    file_ref = f"{version_id}{upload.extension}"
    (upload_dir() / file_ref).write_bytes(upload.data)
    return file_ref


def stored_path(file_ref: str) -> Path:
    return upload_dir() / file_ref


def is_image(file_ref: str) -> bool:
    return Path(file_ref).suffix.lower() in IMAGE_MEDIA_TYPES


def media_type(file_ref: str) -> str:
    # Anything that isn't an image is served as a download, so an uploaded HTML file
    # can never run in the app's origin.
    return IMAGE_MEDIA_TYPES.get(
        Path(file_ref).suffix.lower(), "application/octet-stream"
    )
