type Brand<T, Name extends string> = T & { readonly __brand: Name };

export type OrganizationId = Brand<string, "OrganizationId">;
export type DepartmentId = Brand<string, "DepartmentId">;
export type UserId = Brand<string, "UserId">;
export type ReviewPlanId = Brand<string, "ReviewPlanId">;
export type ReviewCaseId = Brand<string, "ReviewCaseId">;
export type FindingId = Brand<string, "FindingId">;
export type ActionItemId = Brand<string, "ActionItemId">;
export type ActivityId = Brand<string, "ActivityId">;
export type SubmissionId = Brand<string, "SubmissionId">;

const idPattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$/;

export function asId<Id extends string>(value: string): Id {
  if (!idPattern.test(value)) {
    throw new Error(`Invalid identifier: ${value}`);
  }
  return value as Id;
}
