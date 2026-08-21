import re
from typing import NewType
from uuid import UUID

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId

__all__ = ["DepartmentId", "OrganizationId", "UserId"]

ReviewPlanId = NewType("ReviewPlanId", str)
ReviewCaseId = NewType("ReviewCaseId", str)
FindingId = NewType("FindingId", str)
ActionItemId = NewType("ActionItemId", str)
ActivityId = NewType("ActivityId", str)
SubmissionId = NewType("SubmissionId", str)
ScenarioDefinitionId = NewType("ScenarioDefinitionId", UUID)
ScenarioVersionId = NewType("ScenarioVersionId", UUID)

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def validate_id(value: str) -> str:
    if not _ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid identifier: {value}")
    return value
