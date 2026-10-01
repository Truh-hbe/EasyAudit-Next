from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from easyaudit_next.cli import build_parser, default_occurrence_key
from easyaudit_next.platform.settings import Settings


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (datetime(2026, 10, 1, 16, 30, tzinfo=UTC), "daily:2026-10-02"),  # Shanghai 10-02 00:30
        (datetime(2026, 10, 1, 16, 0, tzinfo=UTC), "daily:2026-10-02"),  # exactly local midnight
        (datetime(2026, 10, 1, 15, 59, 59, tzinfo=UTC), "daily:2026-10-01"),
        (datetime(2026, 10, 2, 1, 0, tzinfo=UTC), "daily:2026-10-02"),  # the 09:00 run
        (datetime(2026, 12, 31, 16, 0, tzinfo=UTC), "daily:2027-01-01"),  # year boundary
    ],
)
def test_default_occurrence_key_uses_shanghai_date(as_of: datetime, expected: str) -> None:
    assert default_occurrence_key(as_of, "Asia/Shanghai") == expected


def test_same_local_day_gives_same_key_and_timezone_is_configurable() -> None:
    morning = datetime(2026, 10, 2, 1, 0, tzinfo=UTC)
    evening = datetime(2026, 10, 2, 14, 0, tzinfo=UTC)
    assert default_occurrence_key(morning, "Asia/Shanghai") == "daily:2026-10-02"
    assert default_occurrence_key(evening, "Asia/Shanghai") == "daily:2026-10-02"
    assert default_occurrence_key(evening, "America/New_York") == "daily:2026-10-02"
    assert default_occurrence_key(morning, "America/Los_Angeles") == "daily:2026-10-01"


def test_reminder_timezone_default_and_validation() -> None:
    assert Settings(_env_file=None).reminder_timezone == "Asia/Shanghai"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, reminder_timezone="Mars/Olympus")


@pytest.mark.parametrize("bad", ["2026-10-02T01:00:00", "yesterday"])
def test_as_of_must_be_iso_with_offset(bad: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run-reminder-sweep", "--as-of", bad])
    assert "as-of" in capsys.readouterr().err


def test_as_of_accepts_z_suffix_and_key_rejects_padding() -> None:
    args = build_parser().parse_args(
        ["run-reminder-sweep", "--as-of", "2026-10-01T16:30:00Z", "--occurrence-key", "manual-1"]
    )
    assert args.as_of == datetime(2026, 10, 1, 16, 30, tzinfo=UTC)
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run-reminder-sweep", "--occurrence-key", " padded"])
