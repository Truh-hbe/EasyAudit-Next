from collections.abc import Iterable, Mapping
from typing import Any, NoReturn

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from easyaudit_next.infrastructure.observability import APP_LOGGER, describe_exception
from easyaudit_next.rules import (
    FieldError,
    FieldErrorCode,
    ParamValue,
    RuleCode,
    RuleViolation,
)

DATABASE_CONFLICT_DETAIL = "Request conflicts with existing data"


def raise_database_conflict(exc: IntegrityError) -> NoReturn:
    """`str(IntegrityError)` embeds the SQL statement and bound parameters; never return it."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=DATABASE_CONFLICT_DETAIL,
    ) from None


# --- Structured rule/validation errors -------------------------------------------------------
#
# Every 422 (and any coded error) has one body shape. `detail` is English, for logs and
# troubleshooting; clients must not show it. `code`/`params`/`errors` are the stable contract.


class FieldErrorResponse(BaseModel):
    field: str
    code: FieldErrorCode
    params: dict[str, object] = Field(default_factory=dict)


class RuleErrorResponse(BaseModel):
    detail: str
    code: RuleCode
    params: dict[str, object] = Field(default_factory=dict)
    errors: list[FieldErrorResponse] = Field(default_factory=list)


RULE_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": RuleErrorResponse,
        "description": (
            "Request or business rule rejected. `code` is stable; `detail` is English text for "
            "logs only."
        ),
    }
}


def _json_params(params: Mapping[str, ParamValue]) -> dict[str, object]:
    return {
        key: list(value) if isinstance(value, tuple) else value for key, value in params.items()
    }


def rule_error_body(
    code: RuleCode,
    detail: str,
    params: Mapping[str, ParamValue] | None = None,
    errors: Iterable[FieldError] = (),
) -> dict[str, object]:
    return {
        "detail": detail,
        "code": code.value,
        "params": _json_params(params or {}),
        "errors": [
            {
                "field": error.field,
                "code": error.code.value,
                "params": _json_params(error.params),
            }
            for error in errors
        ],
    }


class CodedHTTPException(HTTPException):
    """A non-422 error that still carries the stable `code` (e.g. a wrong current password)."""

    def __init__(
        self,
        status_code: int,
        code: RuleCode,
        detail: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.code = code
        self.params: Mapping[str, ParamValue] = params or {}


async def coded_http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CodedHTTPException)
    return JSONResponse(
        status_code=exc.status_code,
        content=rule_error_body(exc.code, str(exc.detail), exc.params),
        headers=exc.headers,
    )


async def rule_violation_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RuleViolation)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=rule_error_body(exc.code, str(exc), exc.params, exc.errors),
    )


def raise_unclassified_rule_violation(exc: ValueError) -> NoReturn:
    """A bare `ValueError` that reached the edge: still 422, but logged so it can be found."""
    APP_LOGGER.warning(
        "unclassified_rule_violation",
        extra={"exception_details": describe_exception(exc)},
    )
    raise CodedHTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, RuleCode.RULE_UNSPECIFIED, str(exc)
    ) from exc


_PYDANTIC_FIELD_CODES: dict[str, FieldErrorCode] = {
    "missing": FieldErrorCode.REQUIRED,
    "string_too_short": FieldErrorCode.TOO_SHORT,
    "string_too_long": FieldErrorCode.TOO_LONG,
    "enum": FieldErrorCode.INVALID_CHOICE,
    "literal_error": FieldErrorCode.INVALID_CHOICE,
    "datetime_parsing": FieldErrorCode.INVALID_DATETIME,
    "datetime_from_date_parsing": FieldErrorCode.INVALID_DATETIME,
    "datetime_type": FieldErrorCode.INVALID_DATETIME,
    "timezone_aware": FieldErrorCode.INVALID_DATETIME,
    "greater_than": FieldErrorCode.RANGE,
    "greater_than_equal": FieldErrorCode.RANGE,
    "less_than": FieldErrorCode.RANGE,
    "less_than_equal": FieldErrorCode.RANGE,
}
_PYDANTIC_CONSTRAINT_PARAMS = {
    "string_too_short": ("min_length", "min"),
    "string_too_long": ("max_length", "max"),
    "greater_than": ("gt", "min"),
    "greater_than_equal": ("ge", "min"),
    "less_than": ("lt", "max"),
    "less_than_equal": ("le", "max"),
}


def _field_error(error: Mapping[str, Any]) -> FieldError:
    names = [
        part
        for part in error.get("loc", ())
        if isinstance(part, str) and part not in {"body", "query", "header", "path"}
    ]
    kind = str(error.get("type", ""))
    params: dict[str, ParamValue] = {}
    constraint = _PYDANTIC_CONSTRAINT_PARAMS.get(kind)
    ctx = error.get("ctx")
    if constraint is not None and isinstance(ctx, Mapping):
        value = ctx.get(constraint[0])
        if isinstance(value, int):
            params[constraint[1]] = value
    return FieldError(
        names[-1] if names else "",
        _PYDANTIC_FIELD_CODES.get(kind, FieldErrorCode.INVALID),
        params,
    )


async def request_validation_handler(_request: Request, exc: Exception) -> JSONResponse:
    # Default 422 bodies echo the offending input, which would leak submitted passwords. Only
    # field names, stable codes and numeric limits leave this function.
    assert isinstance(exc, RequestValidationError)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=rule_error_body(
            RuleCode.REQUEST_INVALID,
            "Request validation failed",
            errors=[_field_error(error) for error in exc.errors()],
        ),
    )
