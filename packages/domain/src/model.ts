import type {
  ActionItemId,
  ActivityId,
  DepartmentId,
  FindingId,
  OrganizationId,
  ReviewCaseId,
  ReviewPlanId,
  SubmissionId,
  UserId,
} from "./ids.ts";

export type IsoDateTime = string;
export type ScenarioKey = string;

export type PlatformRole = "system_admin" | "ordinary_user";

export interface Organization {
  readonly id: OrganizationId;
  readonly name: string;
}

export interface Department {
  readonly id: DepartmentId;
  readonly organizationId: OrganizationId;
  readonly name: string;
}

export interface User {
  readonly id: UserId;
  readonly organizationId: OrganizationId;
  readonly departmentId: DepartmentId | null;
  readonly displayName: string;
  readonly platformRole: PlatformRole;
}

export interface Scenario {
  readonly key: ScenarioKey;
  readonly version: number;
  readonly name: string;
  readonly enabled: boolean;
}

export interface ReviewPlan {
  readonly id: ReviewPlanId;
  readonly organizationId: OrganizationId;
  readonly scenarioKey: ScenarioKey;
  readonly title: string;
  readonly plannedStartAt: IsoDateTime | null;
  readonly plannedEndAt: IsoDateTime | null;
  readonly createdBy: UserId;
}

export type ReviewCaseLifecycle =
  | "draft"
  | "scheduled"
  | "in_progress"
  | "awaiting_closure"
  | "closed"
  | "cancelled";

export interface ReviewCase {
  readonly id: ReviewCaseId;
  readonly organizationId: OrganizationId;
  readonly planId: ReviewPlanId | null;
  readonly scenarioKey: ScenarioKey;
  readonly scenarioVersion: number;
  readonly title: string;
  readonly lifecycle: ReviewCaseLifecycle;
  readonly createdBy: UserId;
  readonly createdAt: IsoDateTime;
}

export type FindingLifecycle = "open" | "rectifying" | "verifying" | "closed" | "voided";
export type FindingSeverity = "low" | "medium" | "high" | "critical";

export interface Finding {
  readonly id: FindingId;
  readonly caseId: ReviewCaseId;
  readonly title: string;
  readonly description: string | null;
  readonly severity: FindingSeverity;
  readonly lifecycle: FindingLifecycle;
  readonly raisedBy: UserId;
  readonly raisedAt: IsoDateTime;
}

export type ActionItemLifecycle = "todo" | "in_progress" | "done" | "cancelled";

export interface ActionItem {
  readonly id: ActionItemId;
  readonly findingId: FindingId;
  readonly title: string;
  readonly lifecycle: ActionItemLifecycle;
  readonly dueAt: IsoDateTime | null;
  readonly ownerId: UserId | null;
}

export interface CaseMember {
  readonly caseId: ReviewCaseId;
  readonly userId: UserId;
  readonly roleKey: string;
  readonly joinedAt: IsoDateTime;
}

export interface FindingParticipant {
  readonly findingId: FindingId;
  readonly userId: UserId;
  readonly roleKey: string;
  readonly assignedAt: IsoDateTime;
}

export type ActivitySubjectType = "review_case" | "finding" | "action_item" | "submission";

export interface Activity {
  readonly id: ActivityId;
  readonly organizationId: OrganizationId;
  readonly subjectType: ActivitySubjectType;
  readonly subjectId: string;
  readonly eventType: string;
  readonly actorId: UserId | null;
  readonly occurredAt: IsoDateTime;
  readonly metadata: Readonly<Record<string, unknown>>;
}

export type SubmissionPurpose = "finding_report" | "rectification" | "verification" | "closure";

export interface Submission {
  readonly id: SubmissionId;
  readonly caseId: ReviewCaseId;
  readonly findingId: FindingId | null;
  readonly purpose: SubmissionPurpose;
  readonly submittedBy: UserId;
  readonly submittedAt: IsoDateTime;
  readonly payload: Readonly<Record<string, unknown>>;
}
