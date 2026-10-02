import unicodedata

import pytest

from easyaudit_next.notifications.copy import COPY, display_copy
from easyaudit_next.notifications.models import NotificationKind

# Historical English templates exactly as written on main 2a70e42. Deliberately duplicated here,
# not imported: these literals are the compatibility contract with rows already in the database.
HISTORICAL_ENGLISH: dict[NotificationKind, tuple[str, str]] = {
    NotificationKind.CASE_MEMBERSHIP_ADDED: (
        "ReviewCase membership added",
        "You were added to a ReviewCase.",
    ),
    NotificationKind.FINDING_PARTICIPANT_ADDED: (
        "Finding participant assigned",
        "You were added as a Finding participant.",
    ),
    NotificationKind.ACTION_ASSIGNEE_ADDED: (
        "ActionItem assigned",
        "You were assigned to an ActionItem.",
    ),
    NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION: (
        "Finding awaiting verification",
        "A Finding is ready for verification.",
    ),
    NotificationKind.MANUAL_FINDING_NUDGE: (
        "Finding nudge",
        "A Finding needs your attention.",
    ),
    NotificationKind.MANUAL_ACTION_NUDGE: (
        "ActionItem nudge",
        "An ActionItem needs your attention.",
    ),
    NotificationKind.AUTOMATIC_CASE_REMINDER: (
        "ReviewCase deadline reminder",
        "A ReviewCase deadline is overdue.",
    ),
    NotificationKind.AUTOMATIC_ACTION_REMINDER: (
        "ActionItem deadline reminder",
        "An ActionItem deadline is overdue.",
    ),
}

KINDS = list(NotificationKind)


def test_historical_literals_cover_every_kind() -> None:
    assert set(HISTORICAL_ENGLISH) == set(KINDS)
    assert set(COPY) == set(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_historical_english_row_displays_chinese(kind: NotificationKind) -> None:
    title, body = HISTORICAL_ENGLISH[kind]
    assert display_copy(kind, title, body) == (COPY[kind].title, COPY[kind].body)


@pytest.mark.parametrize("kind", KINDS)
def test_chinese_copy_passes_through(kind: NotificationKind) -> None:
    assert display_copy(kind, COPY[kind].title, COPY[kind].body) == (
        COPY[kind].title,
        COPY[kind].body,
    )


@pytest.mark.parametrize("kind", KINDS)
def test_partial_match_is_not_replaced(kind: NotificationKind) -> None:
    title, body = HISTORICAL_ENGLISH[kind]
    assert display_copy(kind, title, "custom") == (title, "custom")
    assert display_copy(kind, "custom", body) == ("custom", body)


@pytest.mark.parametrize("kind", KINDS)
def test_near_miss_templates_pass_through(kind: NotificationKind) -> None:
    title, body = HISTORICAL_ENGLISH[kind]
    variants = {
        "leading/trailing whitespace": (f" {title}", f"{body} "),
        "trailing newline": (f"{title}\n", body),
        "case": (title.lower(), body.lower()),
        "fullwidth period": (title, body.replace(".", "．")),
        "fullwidth letter": (chr(ord(title[0]) + 0xFEE0) + title[1:], body),
        "nfd-decomposed": (unicodedata.normalize("NFD", title + "\u00e9"), body),
        "nbsp": (title.replace(" ", "\u00a0"), body),
    }
    for name, (t, b) in variants.items():
        assert (t, b) != (title, body), name
        assert display_copy(kind, t, b) == (t, b), name


@pytest.mark.parametrize("kind", KINDS)
def test_other_kinds_historical_templates_are_not_replaced(kind: NotificationKind) -> None:
    for other, (title, body) in HISTORICAL_ENGLISH.items():
        if other is not kind:
            assert display_copy(kind, title, body) == (title, body)


def test_chinese_copy_has_no_implementation_terms() -> None:
    for copy in COPY.values():
        text = copy.title + copy.body
        assert not any(w in text for w in ("ReviewCase", "ActionItem", "Finding", "你"))
