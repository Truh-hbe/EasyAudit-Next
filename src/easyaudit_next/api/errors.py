from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

DATABASE_CONFLICT_DETAIL = "Request conflicts with existing data"


def raise_database_conflict(exc: IntegrityError) -> NoReturn:
    """`str(IntegrityError)` embeds the SQL statement and bound parameters; never return it."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DATABASE_CONFLICT_DETAIL,
    ) from None
