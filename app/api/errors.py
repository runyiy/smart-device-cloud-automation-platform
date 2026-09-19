"""V0-T5 error contracts and exception-handler boundaries."""

from http import HTTPStatus

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class ErrorBody(BaseModel):
    """Sanitized public error fields; internal details never belong here."""

    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    """Common envelope for framework and unexpected application errors."""

    error: ErrorBody


SAFE_PROTOCOL_HEADERS = {
    "www-authenticate",
    "allow",
    "retry-after",
}


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Preserve HTTP status and protocol headers with a generic public message."""
    assert isinstance(exc, HTTPException)

    request_id = getattr(
        request.state,
        "request_id",
        "unknown",
    )

    try:
        message = HTTPStatus(exc.status_code).phrase
    except ValueError:
        message = "HTTP error"

    body = ErrorResponse(
        error=ErrorBody(
            code=f"HTTP_{exc.status_code}",
            message=message,
            request_id=request_id,
        )
    )

    safe_headers = {}

    for name, value in (exc.headers or {}).items():
        if name.lower() in SAFE_PROTOCOL_HEADERS:
            safe_headers[name] = value

    response = JSONResponse(
        status_code=exc.status_code,
        content=body.model_dump(),
        headers=safe_headers,
    )

    response.headers["X-Request-ID"] = request_id

    return response


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Return a generic 422 without echoing input values or validation internals."""
    request_id = getattr(
        request.state,
        "request_id",
        "unknown",
    )
    assert isinstance(exc, RequestValidationError)

    body = ErrorResponse(
        error=ErrorBody(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            request_id=request_id,
        )
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=body.model_dump(),
    )
