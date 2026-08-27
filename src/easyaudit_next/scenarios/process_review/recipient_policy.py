from dataclasses import dataclass, field

from easyaudit_next.review_core.domain.scenario_capabilities import (
    AuthorizationContext,
    AuthorizationPolicy,
    CollaborationRecipientIntent,
    CollaborationRecipientPolicy,
)
from easyaudit_next.scenarios.process_review.v1 import (
    ProcessReviewAuthorizationPolicy,
    ProcessReviewPermission,
)


@dataclass(frozen=True, slots=True)
class ProcessReviewCollaborationRecipientPolicy(CollaborationRecipientPolicy):
    """process_review@1 mapping from collaboration intent to responsibility semantics."""

    authorization: AuthorizationPolicy = field(default_factory=ProcessReviewAuthorizationPolicy)

    def is_recipient(
        self,
        intent: CollaborationRecipientIntent,
        context: AuthorizationContext,
    ) -> bool:
        permission_by_intent = {
            CollaborationRecipientIntent.FINDING_RECTIFICATION: (
                ProcessReviewPermission.SUBMIT_RECTIFICATION
            ),
            CollaborationRecipientIntent.ACTION_EXECUTION: (
                ProcessReviewPermission.UPDATE_ASSIGNED_ACTION
            ),
            CollaborationRecipientIntent.CASE_DEADLINE: (
                ProcessReviewPermission.TRANSITION_CASE
            ),
        }
        return self.authorization.allows(permission_by_intent[intent], context)
