import pytest

from easyaudit_next.notifications.copy import _LEGACY_ENGLISH, COPY, display_copy
from easyaudit_next.notifications.models import NotificationKind

KINDS = list(NotificationKind)


def test_every_kind_has_chinese_copy_and_legacy_template() -> None:
    assert set(COPY) == set(KINDS)
    assert set(_LEGACY_ENGLISH) == set(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_legacy_english_row_displays_chinese(kind: NotificationKind) -> None:
    title, body = _LEGACY_ENGLISH[kind]
    assert display_copy(kind, title, body) == (COPY[kind].title, COPY[kind].body)


@pytest.mark.parametrize("kind", KINDS)
def test_chinese_copy_passes_through(kind: NotificationKind) -> None:
    assert display_copy(kind, COPY[kind].title, COPY[kind].body) == (
        COPY[kind].title,
        COPY[kind].body,
    )


@pytest.mark.parametrize("kind", KINDS)
def test_partial_legacy_match_is_not_replaced(kind: NotificationKind) -> None:
    title, body = _LEGACY_ENGLISH[kind]
    assert display_copy(kind, title, "custom") == (title, "custom")
    assert display_copy(kind, "custom", body) == ("custom", body)


def test_legacy_template_of_another_kind_is_not_replaced() -> None:
    title, body = _LEGACY_ENGLISH[NotificationKind.MANUAL_FINDING_NUDGE]
    assert display_copy(NotificationKind.MANUAL_ACTION_NUDGE, title, body) == (title, body)


def test_chinese_copy_has_no_implementation_terms() -> None:
    for copy in COPY.values():
        text = copy.title + copy.body
        assert not any(w in text for w in ("ReviewCase", "ActionItem", "Finding", "你"))
