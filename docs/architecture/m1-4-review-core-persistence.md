# M1.4 — Review Core Persistence Foundation

M1.4 maps the M0 Review Core relationships into PostgreSQL without opening M2 business APIs.

- Core identities use application-generated PostgreSQL UUID values.
- `organization_id` is carried by every aggregate and participation relation.
- Composite foreign keys prevent ReviewCase, Finding, ActionItem, Submission, User, and Department
  references from crossing Organization boundaries.
- FindingParticipant and ActionAssignee use typed nullable foreign keys plus an exactly-one actor
  check; they do not use a generic actor reference.
- Submission uses a three-column foreign key so an optional Finding must belong to the same
  ReviewCase and Organization.
- Activity uses four typed nullable foreign keys with an exactly-one target check and PostgreSQL
  rejects every UPDATE or DELETE.

The stage exposes repositories and persistence integration tests only. ReviewCase, Finding,
ActionItem, Submission, and Activity workflow endpoints remain M2 scope.

Final Review evidence is recorded in `m1-final-review.md`.
