# M2.2 Acceptance Gates

M2.2 is ready for architecture review only when all of the following are true:

- ReviewPlan creation uses the Core planning authorization policy.
- ReviewCase creation resolves an organization-published exact ScenarioVersion.
- Scenario-specific Case data is validated by that versioned policy.
- Case creation persists ReviewCase + creator lead + `review_case.created` Activity atomically.
- A PostgreSQL failure in the third write rolls the first two writes back.
- Review Core reads require organization scope; UUID alone is not an authorization boundary.
- CaseMember roles are validated against Scenario RoleSpecification.
- Case transitions are invoked through the Scenario workflow and append Activity.
- `lifecycle` is not writable through ordinary create/update payloads; state changes use transitions.
- local users with `must_change_password=true` cannot enter Review business APIs.
- Review Core contains no direct import from `easyaudit_next.scenarios`.
- M2.2 does not implement Finding, Action, Submission, Evidence, notifications, dashboard, or Case
  closure orchestration.
