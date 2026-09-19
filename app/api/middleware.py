"""V0-T5 request correlation, unexpected-error response, and access-log boundary."""

import logging
import re
from time import perf_counter
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")


def is_valid_request_id(value: str) -> bool:
    return REQUEST_ID_PATTERN.fullmatch(value) is not None


def get_route_template(request: Request) -> str:
    matched_route = request.scope.get("route")
    return matched_route.path if matched_route is not None else "<unmatched>"


def build_log_extra(
    *,
    request: Request,
    request_id: str,
    route: str,
    status_code: int,
    duration_ms: float,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "method": request.method,
        "route": route,
        "status_code": status_code,
        "duration_ms": duration_ms,
    }


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Keep each request ID on request.state and emit one sanitized request log."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming_ids = request.headers.getlist("X-Request-ID")

        if len(incoming_ids) == 1 and is_valid_request_id(incoming_ids[0]):
            request_id = incoming_ids[0]
        else:
            request_id = uuid4().hex

        request.state.request_id = request_id

        logger = logging.getLogger("app.requests")
        start_time = perf_counter()

        try:
            response = await call_next(request)

        except Exception:
            duration_ms = (perf_counter() - start_time) * 1000
            route = get_route_template(request)

            logger.error(
                "request_failed",
                extra=build_log_extra(
                    request=request,
                    request_id=request_id,
                    route=route,
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    duration_ms=duration_ms,
                ),
            )

            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Internal server error",
                        "request_id": request_id,
                    }
                },
            )

        else:
            duration_ms = (perf_counter() - start_time) * 1000
            route = get_route_template(request)

            logger.info(
                "request_completed",
                extra=build_log_extra(
                    request=request,
                    request_id=request_id,
                    route=route,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                ),
            )

        response.headers["X-Request-ID"] = request_id
        return response
