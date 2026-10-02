from dataclasses import dataclass

from easyaudit_next.notifications.models import NotificationKind


@dataclass(frozen=True, slots=True)
class NotificationCopy:
    title: str
    body: str


COPY: dict[NotificationKind, NotificationCopy] = {
    NotificationKind.CASE_MEMBERSHIP_ADDED: NotificationCopy(
        "加入审查活动", "您已被加入一个审查活动。"
    ),
    NotificationKind.FINDING_PARTICIPANT_ADDED: NotificationCopy(
        "参与发现项", "您已被添加为一个发现项的参与方。"
    ),
    NotificationKind.ACTION_ASSIGNEE_ADDED: NotificationCopy(
        "指派整改项", "您已被指派处理一个整改项。"
    ),
    NotificationKind.FINDING_SUBMITTED_FOR_VERIFICATION: NotificationCopy(
        "验证发现项", "一个发现项的整改已提交，等待您验证。"
    ),
    NotificationKind.MANUAL_FINDING_NUDGE: NotificationCopy(
        "催办发现项", "有一个发现项需要您尽快处理。"
    ),
    NotificationKind.MANUAL_ACTION_NUDGE: NotificationCopy(
        "催办整改项", "有一个整改项需要您尽快处理。"
    ),
    NotificationKind.AUTOMATIC_CASE_REMINDER: NotificationCopy(
        "审查活动已逾期", "一个审查活动已超过计划结束时间。"
    ),
    NotificationKind.AUTOMATIC_ACTION_REMINDER: NotificationCopy(
        "整改项已逾期", "一个整改项已超过截止时间。"
    ),
}

# Only for rows written before the Chinese copy shipped. Delivered title/body are immutable
# (trg_notifications_immutable), so the read side maps them instead of migrating. Remove this
# table once no English legacy rows remain.
_LEGACY_ENGLISH: dict[NotificationKind, tuple[str, str]] = {
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


def display_copy(kind: NotificationKind, title: str, body: str) -> tuple[str, str]:
    """Return stored title/body, upgrading an exact legacy English template to Chinese."""
    if _LEGACY_ENGLISH.get(kind) == (title, body):
        copy = COPY[kind]
        return copy.title, copy.body
    return title, body
