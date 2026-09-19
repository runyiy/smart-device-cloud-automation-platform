"""Tests for JSON log privacy and repeated configuration."""

import json
import logging
from datetime import datetime, timedelta

from app.core.logging import JsonRequestFormatter, configure_request_logging


def test_json_formatter_allowlists_safe_fields() -> None:
    record = logging.LogRecord(
        "app.requests", logging.INFO, "", 0, "PRIVATE_SECRET", (), None
    )
    record.request_id = "id-123"
    record.method = "GET"
    record.route = "/devices/{device_id}"
    record.status_code = 200
    record.duration_ms = 1.25
    record.body = "PRIVATE_SECRET"
    rendered = JsonRequestFormatter().format(record)
    data = json.loads(rendered)
    assert set(data) == {
        "timestamp",
        "level",
        "event",
        "request_id",
        "method",
        "route",
        "status_code",
        "duration_ms",
    }
    assert data["event"] == "http_request"
    assert data["route"] == "/devices/{device_id}"
    assert data["request_id"] == "id-123"
    assert data["level"] == "INFO"
    assert data["status_code"] == 200
    assert data["duration_ms"] == 1.25
    assert datetime.fromisoformat(data["timestamp"]).utcoffset() == timedelta(0)
    assert "PRIVATE_SECRET" not in rendered


def test_logging_configuration_is_idempotent_and_local() -> None:
    names = ("app.requests", "app.request", "", "uvicorn", "uvicorn.access")
    loggers = [logging.getLogger(name) for name in names]
    saved = [
        (logger, logger.handlers[:], logger.level, logger.propagate)
        for logger in loggers
    ]
    try:
        loggers[0].handlers = []
        loggers[1].handlers = []
        configure_request_logging()
        handlers = loggers[0].handlers[:]
        configure_request_logging()
        assert len(handlers) == 1
        assert loggers[0].handlers == handlers
        assert isinstance(handlers[0], logging.StreamHandler)
        assert isinstance(handlers[0].formatter, JsonRequestFormatter)
        assert loggers[0].level == logging.INFO
        assert loggers[0].propagate is False
        for logger, original_handlers, level, propagate in saved[2:]:
            assert logger.handlers == original_handlers
            assert logger.level == level
            assert logger.propagate == propagate
    finally:
        for logger, original_handlers, level, propagate in saved:
            for handler in logger.handlers:
                if handler not in original_handlers:
                    handler.close()
            logger.handlers = original_handlers
            logger.setLevel(level)
            logger.propagate = propagate
