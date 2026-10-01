import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from easyaudit_next.platform.domain.ids import OrganizationId
from easyaudit_next.platform.settings import Settings
from easyaudit_next.review_core.application.evidence_policy import (
    MAX_FILENAME_CHARS,
    EvidenceUploadPolicy,
    InvalidEvidenceFilenameError,
    UnsupportedEvidenceTypeError,
    sanitize_filename,
)
from easyaudit_next.review_core.application.evidence_storage import (
    EvidenceTooLargeError,
    limit_stream,
    new_storage_key,
)

POLICY = EvidenceUploadPolicy.from_config(
    1024, "application/pdf,image/jpeg,text/plain,text/csv"
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("%E6%95%B4%E6%94%B9%E6%8A%A5%E5%91%8A.pdf", "整改报告.pdf"),
        ("..%2F..%2Fetc%2Fpasswd.txt", "passwd.txt"),
        ("C%3A%5CUsers%5Cme%5Cscan.pdf", "scan.pdf"),
        ("a%00b%0D%0Ac.txt", "abc.txt"),
        ("%E2%80%AEtxt.exe.pdf", "txt.exe.pdf"),  # right-to-left override removed
        ("  padded.txt  ", "padded.txt"),
        ("e%CC%81.txt", "é.txt"),  # NFC
    ],
)
def test_sanitize_filename_removes_paths_and_controls(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


@pytest.mark.parametrize("raw", ["", "%20%20", "..", "%2E%2E%2E", "a%2F", "%00%01", "%FF%FE",
     "report%GG.pdf", "report%.pdf", "report%2.pdf", "report.pdf%", "%zz", "a%2"])
def test_sanitize_filename_rejects_unusable_names(raw: str) -> None:
    with pytest.raises(InvalidEvidenceFilenameError):
        sanitize_filename(raw)


def test_sanitize_filename_limits_length_and_keeps_the_extension() -> None:
    name = sanitize_filename("x" * 400 + ".pdf")

    assert len(name) == MAX_FILENAME_CHARS
    assert name.endswith(".pdf")


def test_policy_accepts_matching_type_and_extension() -> None:
    validated = POLICY.validate("Application/PDF; charset=binary", "Scan.PDF")

    assert validated.content_type == "application/pdf"
    assert validated.original_name == "Scan.PDF"
    assert POLICY.validate("image/jpeg", "a.jpeg").content_type == "image/jpeg"


@pytest.mark.parametrize(
    ("content_type", "filename"),
    [
        (None, "a.pdf"),
        ("", "a.pdf"),
        ("application/octet-stream", "a.pdf"),
        ("application/x-msdownload", "a.exe"),
        ("image/png", "a.png"),  # real type, but not in this policy's allow-list
        ("application/pdf", "a.exe"),
        ("application/pdf", "a"),
        ("application/pdf", "a.pdf.exe"),
        ("text/plain", "a.csv"),
    ],
)
def test_policy_rejects_types_outside_the_list_and_mismatched_extensions(
    content_type: str | None, filename: str
) -> None:
    with pytest.raises(UnsupportedEvidenceTypeError):
        POLICY.validate(content_type, filename)


def test_policy_config_rejects_types_without_a_known_extension() -> None:
    with pytest.raises(ValueError):
        EvidenceUploadPolicy.from_config(1, "application/pdf,application/zip")
    with pytest.raises(ValueError):
        EvidenceUploadPolicy.from_config(1, " , ")


def test_default_settings_content_types_are_all_known() -> None:
    settings = Settings()
    policy = EvidenceUploadPolicy.from_config(
        settings.evidence_max_bytes, settings.evidence_allowed_content_types
    )

    assert len(policy.allowed_content_types) == 8


async def _chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


def test_limit_stream_passes_data_up_to_the_limit() -> None:
    async def run() -> list[bytes]:
        return [chunk async for chunk in limit_stream(_chunks(b"ab", b"cd"), 4)]

    assert asyncio.run(run()) == [b"ab", b"cd"]


def test_limit_stream_aborts_before_forwarding_the_offending_chunk() -> None:
    received: list[bytes] = []

    async def run() -> None:
        async for chunk in limit_stream(_chunks(b"ab", b"cde", b"never"), 4):
            received.append(chunk)

    with pytest.raises(EvidenceTooLargeError):
        asyncio.run(run())

    assert received == [b"ab"]


def test_storage_key_is_server_generated_and_never_reused() -> None:
    organization_id = OrganizationId(uuid4())
    first, second = new_storage_key(organization_id), new_storage_key(organization_id)

    assert first != second
    assert first.startswith(f"org/{organization_id}/evidence/")
    assert len(first.rsplit("/", 1)[1]) == 36
