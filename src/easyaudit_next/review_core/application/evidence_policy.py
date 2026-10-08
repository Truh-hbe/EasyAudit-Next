"""What an Evidence upload may be: type allow-list, extension agreement, file-name hygiene.

The file name is metadata only. It is cleaned here, stored in `original_name`, and never used
to build a storage key.
"""

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import unquote

from easyaudit_next.rules import RuleCode, RuleViolation

MAX_FILENAME_CHARS = 255
_MAX_EXTENSION_CHARS = 16
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})

EXTENSIONS_BY_CONTENT_TYPE: dict[str, frozenset[str]] = {
    "application/pdf": frozenset({".pdf"}),
    "image/png": frozenset({".png"}),
    "image/jpeg": frozenset({".jpg", ".jpeg"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": frozenset(
        {".docx"}
    ),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": frozenset({".xlsx"}),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": frozenset(
        {".pptx"}
    ),
    "text/plain": frozenset({".txt"}),
    "text/csv": frozenset({".csv"}),
}


def download_content_type(stored: str | None) -> str:
    """The stored type if it is one the upload policy can ever have accepted, else a
    type no browser will interpret. The stored value is data, not a promise."""
    if stored is not None and stored in EXTENSIONS_BY_CONTENT_TYPE:
        return stored
    return "application/octet-stream"


class UnsupportedEvidenceTypeError(Exception):
    """The declared type is not allowed, or the file extension does not match it."""


class InvalidEvidenceFilenameError(RuleViolation):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(RuleCode.EVIDENCE_FILENAME_INVALID, message, params={"reason": reason})


@dataclass(frozen=True, slots=True)
class ValidatedEvidenceFile:
    content_type: str
    original_name: str


def sanitize_filename(raw_header: str) -> str:
    """Percent-encoded UTF-8 header value -> a display-safe file name (no path, no controls)."""
    if _BAD_PERCENT.search(raw_header):  # `unquote` would silently keep these as literals
        raise InvalidEvidenceFilenameError("File name has an invalid percent-encoding", "encoding")
    try:
        decoded = unquote(raw_header, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidEvidenceFilenameError(
            "File name must be percent-encoded UTF-8", "encoding"
        ) from exc
    normalized = unicodedata.normalize("NFC", decoded).replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch) not in _REMOVED_CATEGORIES)
    name = name.strip()
    if not name or set(name) == {"."}:
        raise InvalidEvidenceFilenameError("File name is empty after sanitization", "empty")
    if len(name) > MAX_FILENAME_CHARS:
        stem, dot, extension = name.rpartition(".")
        if dot and 0 < len(extension) <= _MAX_EXTENSION_CHARS and stem:
            keep = MAX_FILENAME_CHARS - len(extension) - 1
            name = f"{stem[:keep].rstrip()}.{extension}"
        else:
            name = name[:MAX_FILENAME_CHARS].rstrip()
    return name


def _extension(name: str) -> str:
    _, dot, extension = name.rpartition(".")
    return f".{extension.lower()}" if dot else ""


@dataclass(frozen=True, slots=True)
class EvidenceUploadPolicy:
    max_bytes: int
    allowed_content_types: frozenset[str]

    @classmethod
    def from_config(cls, max_bytes: int, content_types_csv: str) -> "EvidenceUploadPolicy":
        configured = frozenset(
            item.strip().lower() for item in content_types_csv.split(",") if item.strip()
        )
        unknown = sorted(configured - EXTENSIONS_BY_CONTENT_TYPE.keys())
        if unknown or not configured:
            raise ValueError(f"Unsupported EVIDENCE_ALLOWED_CONTENT_TYPES entries: {unknown}")
        return cls(max_bytes, configured)

    def validate(
        self, content_type_header: str | None, filename_header: str
    ) -> ValidatedEvidenceFile:
        """Raises `InvalidEvidenceFilenameError` (422) or `UnsupportedEvidenceTypeError` (415)."""
        name = sanitize_filename(filename_header)
        content_type = (content_type_header or "").split(";", 1)[0].strip().lower()
        if content_type not in self.allowed_content_types:
            raise UnsupportedEvidenceTypeError("Content type is not allowed for Evidence")
        if _extension(name) not in EXTENSIONS_BY_CONTENT_TYPE[content_type]:
            raise UnsupportedEvidenceTypeError("File extension does not match the content type")
        return ValidatedEvidenceFile(content_type, name)
