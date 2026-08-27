from dataclasses import dataclass

from easyaudit_next.review_core.domain.scenario_capabilities import (
    ActorKind,
    AuthorizationContext,
    CollaborationRecipientIntent,
    PermissionSource,
    RoleGrant,
)
from easyaudit_next.scenarios.process_review import PROCESS_REVIEW_V1


def _case_context(role_key: str) -> AuthorizationContext:
    return AuthorizationContext(
        is_active_organization_user=True,
        case_role_grants=frozenset(
            {
                RoleGrant(
                    role_key=role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            }
        ),
    )


def _finding_context(role_key: str) -> AuthorizationContext:
    return AuthorizationContext(
        is_active_organization_user=True,
        finding_role_grants=frozenset(
            {
                RoleGrant(
                    role_key=role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            }
        ),
    )


def _action_context(role_key: str) -> AuthorizationContext:
    return AuthorizationContext(
        is_active_organization_user=True,
        action_role_grants=frozenset(
            {
                RoleGrant(
                    role_key=role_key,
                    actor_kind=ActorKind.USER,
                    source=PermissionSource.DIRECT,
                )
            }
        ),
    )


def test_process_review_v1_owns_current_recipient_mapping() -> None:
    recipients = PROCESS_REVIEW_V1.collaboration_recipients

    assert recipients.is_recipient(
        CollaborationRecipientIntent.FINDING_RECTIFICATION,
        _finding_context("owner"),
    )
    assert not recipients.is_recipient(
        CollaborationRecipientIntent.FINDING_RECTIFICATION,
        _finding_context("collaborator"),
    )

    assert recipients.is_recipient(
        CollaborationRecipientIntent.ACTION_EXECUTION,
        _action_context("primary"),
    )
    assert recipients.is_recipient(
        CollaborationRecipientIntent.ACTION_EXECUTION,
        _action_context("collaborator"),
    )

    assert recipients.is_recipient(
        CollaborationRecipientIntent.CASE_DEADLINE,
        _case_context("lead"),
    )
    assert not recipients.is_recipient(
        CollaborationRecipientIntent.CASE_DEADLINE,
        _case_context("auditor"),
    )


@dataclass(frozen=True, slots=True)
class DivergentAuthorization:
    def allows(self, permission: str, context: AuthorizationContext) -> bool:
        if permission != "transition_case":
            return False
        return any(
            grant.role_key in {"lead", "auditor"}
            for grant in context.case_role_grants
        )


@dataclass(frozen=True, slots=True)
class DivergentRecipients:
    def is_recipient(
        self,
        intent: CollaborationRecipientIntent,
        context: AuthorizationContext,
    ) -> bool:
        if intent is not CollaborationRecipientIntent.CASE_DEADLINE:
            return False
        return any(grant.role_key == "lead" for grant in context.case_role_grants)


def test_authorization_can_be_broader_than_case_deadline_responsibility() -> None:
    authorization = DivergentAuthorization()
    recipients = DivergentRecipients()
    auditor = _case_context("auditor")
    lead = _case_context("lead")

    assert authorization.allows("transition_case", auditor)
    assert authorization.allows("transition_case", lead)
    assert not recipients.is_recipient(CollaborationRecipientIntent.CASE_DEADLINE, auditor)
    assert recipients.is_recipient(CollaborationRecipientIntent.CASE_DEADLINE, lead)
