# M2.2 transaction ownership

ReviewPlanningService does not call `commit()` or `rollback()`. Persistence methods may `flush()`
to surface PostgreSQL constraint failures, while the request-scoped SQLAlchemy Session owns the
transaction boundary. This lets ReviewCase creation, initial CaseMember creation, and the creation
Activity participate in one unit of work without teaching the domain or Scenario policy about
SQLAlchemy transactions.
