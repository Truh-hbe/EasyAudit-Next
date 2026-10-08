"""Stable, language-neutral codes for rule violations and validation errors.

Domain, Scenario and application code raise `RuleViolation` with a `RuleCode` and parameters
(keys and numbers only, never display text). The API layer serializes them; the web client maps
codes to Chinese copy. `message` stays English and is for logs and troubleshooting only.

Codes are append-only once released: the web mapping depends on them. Standard library only, so
domain and Scenario code may import this module.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum

ParamValue = str | int | tuple[str, ...]


class RuleCode(StrEnum):
    """Page-level codes: `<entity>.<snake_case_reason>`; describe the fact, not the UI."""

    REQUEST_INVALID = "request.invalid"
    RULE_UNSPECIFIED = "rule.unspecified"

    WORKFLOW_INVALID_TRANSITION = "workflow.invalid_transition"
    WORKFLOW_UNKNOWN_ACTION = "workflow.unknown_action"
    WORKFLOW_MISSING_CONTEXT = "workflow.missing_context"

    CASE_CLOSE_BLOCKED_BY_OPEN_FINDINGS = "case.close_blocked_by_open_findings"

    FINDING_MISSING_PARTICIPANT_ROLES = "finding.missing_participant_roles"
    FINDING_ISSUE_REQUIRES_NONCONFORMITY = "finding.issue_requires_nonconformity"
    FINDING_ACCEPT_REQUIRES_OBSERVATION = "finding.accept_requires_observation"
    FINDING_REQUIRES_OPEN = "finding.requires_open"
    FINDING_INVALID_CASE_LIFECYCLE = "finding.invalid_case_lifecycle"
    FINDING_PARTICIPANTS_LOCKED = "finding.participants_locked"
    FINDING_INVALID_TYPE = "finding.invalid_type"
    FINDING_VERIFICATION_REQUIRES_ACTIONS = "finding.verification_requires_actions"
    FINDING_VERIFICATION_REQUIRES_ACTIONS_DONE = "finding.verification_requires_actions_done"
    FINDING_REOPEN_AFTER_CASE_CLOSURE = "finding.reopen_after_case_closure"

    SUBMISSION_PLAN_REQUIRES_RECTIFYING = "submission.plan_requires_rectifying"
    SUBMISSION_MISMATCH = "submission.mismatch"
    VERIFICATION_CASE_CLOSED = "verification.case_closed"

    ACTION_REQUIRES_RECTIFYING_FINDING = "action.requires_rectifying_finding"
    ACTION_REQUIRES_ACTIVE_CASE = "action.requires_active_case"
    ACTION_ALREADY_EXISTS = "action.already_exists"
    ACTION_MISSING = "action.missing"
    ACTION_ASSIGNEES_LOCKED = "action.assignees_locked"
    ACTION_EVIDENCE_ON_CANCELLED = "action.evidence_on_cancelled"
    ACTION_TRANSFER_REQUIRES_DONE = "action.transfer_requires_done"
    ACTION_EXECUTOR_STILL_ACTIVE = "action.executor_still_active"

    ROLE_NOT_ALLOWED_FOR_ACTOR = "role.not_allowed_for_actor"

    NUDGE_NO_ELIGIBLE_RECIPIENTS = "nudge.no_eligible_recipients"
    EXPORT_ROW_LIMIT_EXCEEDED = "export.row_limit_exceeded"

    EVIDENCE_FILE_EMPTY = "evidence.file_empty"
    EVIDENCE_FILENAME_INVALID = "evidence.filename_invalid"

    PASSWORD_TOO_SHORT = "password.too_short"
    PASSWORD_TOO_LONG = "password.too_long"
    PASSWORD_REUSED = "password.reused"
    PASSWORD_CURRENT_INVALID = "password.current_invalid"


class FieldErrorCode(StrEnum):
    """Field-level codes carried in `errors[]`; generic so that one message per code suffices."""

    REQUIRED = "required"
    PADDED = "padded"
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"
    INVALID_CHOICE = "invalid_choice"
    INVALID_DATETIME = "invalid_datetime"
    RANGE = "range"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    code: FieldErrorCode
    params: Mapping[str, ParamValue] = dataclass_field(default_factory=dict)
    # English, for `detail` only; never serialized into `errors[]`.
    message: str = ""


class RuleViolation(ValueError):
    """A request was understood but rejected by a validation or business rule (HTTP 422)."""

    def __init__(
        self,
        code: RuleCode,
        message: str,
        *,
        params: Mapping[str, ParamValue] | None = None,
        errors: Iterable[FieldError] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.params: Mapping[str, ParamValue] = dict(params or {})
        self.errors: tuple[FieldError, ...] = tuple(errors)


def request_invalid[V: RuleViolation](errors: Iterable[FieldError], cls: type[V]) -> V:
    """Field errors as a violation of type `cls`; `detail` joins their English messages."""
    collected = tuple(errors)
    return cls(
        RuleCode.REQUEST_INVALID,
        "; ".join(error.message for error in collected),
        errors=collected,
    )


def reason_required[V: RuleViolation](cls: type[V], message: str) -> V:
    """The operation needs a `reason` and none was given."""
    return request_invalid((FieldError("reason", FieldErrorCode.REQUIRED, message=message),), cls)


def field_violation[V: RuleViolation](
    field_name: str,
    code: FieldErrorCode,
    message: str,
    *,
    params: Mapping[str, ParamValue] | None = None,
    cls: type[V],
) -> V:
    """One field rejected for `code`."""
    return request_invalid((FieldError(field_name, code, params or {}, message),), cls)


def require_clean_text(value: str, field_name: str) -> None:
    """Non-blank, no surrounding whitespace."""
    message = f"{field_name} must be a non-blank, unpadded string"
    if not value.strip():
        raise field_violation(field_name, FieldErrorCode.REQUIRED, message, cls=RuleViolation)
    if value != value.strip():
        raise field_violation(field_name, FieldErrorCode.PADDED, message, cls=RuleViolation)
