"""JSON formatting and configuration for application request logs."""

import json
import logging
from datetime import UTC, datetime


class JsonRequestFormatter(logging.Formatter):
    """Serialize allowlisted request fields as one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(
            record.created,
            tz=UTC,
        ).isoformat()

        log_record = {
            "timestamp": timestamp,
            "level": record.levelname,
            "event": "http_request",
            "request_id": getattr(record, "request_id", None),
            "method": getattr(record, "method", None),
            "route": getattr(record, "route", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }

        return json.dumps(log_record)


def configure_request_logging() -> None:
    """Configure the application request logger once without changing root logging."""
    logger = logging.getLogger("app.requests")

    if logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonRequestFormatter())

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
