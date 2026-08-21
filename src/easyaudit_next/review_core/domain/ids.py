from typing import NewType
from uuid import UUID

from easyaudit_next.platform.domain.ids import DepartmentId, OrganizationId, UserId

__all__ = ["DepartmentId", "OrganizationId", "UserId"]

ReviewPlanId = NewType("ReviewPlanId", UUID)
ReviewCaseId = NewType("ReviewCaseId", UUID)
FindingId = NewType("FindingId", UUID)
ActionItemId = NewType("ActionItemId", UUID)
ActivityId = NewType("ActivityId", UUID)
SubmissionId = NewType("SubmissionId", UUID)
ScenarioDefinitionId = NewType("ScenarioDefinitionId", UUID)
ScenarioVersionId = NewType("ScenarioVersionId", UUID)
