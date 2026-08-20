import type { CaseMember, Finding, FindingParticipant, ReviewCase, ReviewPlan } from "./model.ts";

export function assertPlanMatchesCase(plan: ReviewPlan, reviewCase: ReviewCase): void {
  if (reviewCase.planId !== plan.id) {
    throw new Error("ReviewCase does not belong to ReviewPlan");
  }
  if (reviewCase.organizationId !== plan.organizationId) {
    throw new Error("ReviewPlan and ReviewCase must belong to the same organization");
  }
  if (reviewCase.scenarioKey !== plan.scenarioKey) {
    throw new Error("ReviewPlan and ReviewCase must use the same scenario");
  }
}

export function assertFindingBelongsToCase(finding: Finding, reviewCase: ReviewCase): void {
  if (finding.caseId !== reviewCase.id) {
    throw new Error("Finding does not belong to ReviewCase");
  }
}

export function assertUniqueCaseMembers(members: readonly CaseMember[]): void {
  const keys = new Set<string>();
  for (const member of members) {
    const key = `${member.caseId}:${member.userId}:${member.roleKey}`;
    if (keys.has(key)) {
      throw new Error(`Duplicate CaseMember: ${key}`);
    }
    keys.add(key);
  }
}

export function assertUniqueFindingParticipants(participants: readonly FindingParticipant[]): void {
  const keys = new Set<string>();
  for (const participant of participants) {
    const key = `${participant.findingId}:${participant.userId}:${participant.roleKey}`;
    if (keys.has(key)) {
      throw new Error(`Duplicate FindingParticipant: ${key}`);
    }
    keys.add(key);
  }
}
