import assert from "node:assert/strict";
import test from "node:test";

import { asId } from "../src/ids.ts";
import {
  assertPlanMatchesCase,
  assertUniqueCaseMembers,
  assertUniqueFindingParticipants,
} from "../src/invariants.ts";
import type {
  CaseMember,
  FindingParticipant,
  ReviewCase,
  ReviewPlan,
} from "../src/model.ts";
import { ScenarioRegistry } from "../src/scenario-registry.ts";

const organizationId = asId<ReviewPlan["organizationId"]>("org-demo");
const creatorId = asId<ReviewPlan["createdBy"]>("user-owner");
const planId = asId<ReviewPlan["id"]>("plan-001");
const caseId = asId<ReviewCase["id"]>("case-001");

const plan: ReviewPlan = {
  id: planId,
  organizationId,
  scenarioKey: "process-review",
  title: "2026 Q3 process review",
  plannedStartAt: null,
  plannedEndAt: null,
  createdBy: creatorId,
};

const reviewCase: ReviewCase = {
  id: caseId,
  organizationId,
  planId,
  scenarioKey: "process-review",
  scenarioVersion: 1,
  title: "Assembly process review",
  lifecycle: "draft",
  createdBy: creatorId,
  createdAt: "2026-08-21T00:00:00.000Z",
};

test("a planned case must share organization and scenario with its plan", () => {
  assert.doesNotThrow(() => assertPlanMatchesCase(plan, reviewCase));
  assert.throws(
    () => assertPlanMatchesCase(plan, { ...reviewCase, scenarioKey: "supplier-review" }),
    /same scenario/,
  );
});

test("the same user can hold different business roles without changing platform role", () => {
  const base = {
    caseId,
    userId: creatorId,
    joinedAt: "2026-08-21T00:00:00.000Z",
  };
  const members: readonly CaseMember[] = [
    { ...base, roleKey: "lead" },
    { ...base, roleKey: "reviewer" },
  ];

  assert.doesNotThrow(() => assertUniqueCaseMembers(members));
  assert.throws(() => assertUniqueCaseMembers([...members, members[0]!]), /Duplicate CaseMember/);
});

test("finding participants are unique per finding, user and role", () => {
  const participant: FindingParticipant = {
    findingId: asId("finding-001"),
    userId: creatorId,
    roleKey: "rectification_owner",
    assignedAt: "2026-08-21T00:00:00.000Z",
  };
  assert.throws(
    () => assertUniqueFindingParticipants([participant, participant]),
    /Duplicate FindingParticipant/,
  );
});

test("scenario extensions are registered by policy instead of core conditionals", () => {
  const registry = new ScenarioRegistry();
  registry.register({
    scenario: { key: "process-review", version: 1, name: "过程审查", enabled: true },
    caseRoleKeys: ["lead", "reviewer"],
    findingParticipantRoleKeys: ["rectification_owner", "verifier"],
    validateCaseInput: () => [],
  });

  assert.equal(registry.get("process-review").scenario.version, 1);
  assert.throws(() => registry.get("unknown"), /not available/);
});

test("identifiers reject ambiguous or unsafe values", () => {
  assert.equal(asId("case-001"), "case-001");
  assert.throws(() => asId(" x "), /Invalid identifier/);
});
