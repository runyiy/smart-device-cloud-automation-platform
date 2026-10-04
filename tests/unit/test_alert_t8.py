"""T8 schema boundaries and service transaction contracts without database I/O."""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.alerts.schema import AlertListQuery, AlertRead
from app.alerts.service import (
    AlertNotFoundError,
    InvalidAlertStateError,
    acknowledge_alert,
    list_alerts,
    resolve_alert,
)


def stored_alert(status: AlertStatus = AlertStatus.OPEN) -> Alert:
    stamp = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    return Alert(
        id=uuid4(),
        device_id=uuid4(),
        type="temperature_high",
        severity=AlertSeverity.CRITICAL,
        status=status,
        message="Temperature high",
        triggered_at=stamp,
        resolved_at=stamp if status is AlertStatus.RESOLVED else None,
    )


def test_query_defaults_and_explicit_none() -> None:
    query = AlertListQuery()
    assert (query.page, query.page_size, query.sort_order) == (1, 20, "desc")
    assert (query.device_id, query.status, query.severity, query.type) == (None,) * 4
    assert (
        AlertListQuery.model_validate(
            dict.fromkeys(["device_id", "status", "severity", "type"])
        )
        == query
    )


@pytest.mark.parametrize(
    "data",
    [
        {"page": 0},
        {"page": "bad"},
        {"page_size": 0},
        {"page_size": 101},
        {"device_id": ""},
        {"device_id": "bad"},
        {"status": "OPEN"},
        {"status": ""},
        {"severity": "CRITICAL"},
        {"severity": ""},
        {"sort_order": "ASC"},
        {"type": ""},
        {"type": "x" * 65},
        {"type": " x"},
        {"type": "x "},
        {"type": "告警"},
        {"type": "x/y"},
        {"type": "x\n"},
        {"type": "x\r"},
        {"type": "x\x00"},
    ],
)
def test_bad_query(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AlertListQuery.model_validate(data)


@pytest.mark.parametrize("kind", ["a", "A.b_C-9", "x" * 64, "custom_alert"])
def test_query_parses_http_values_and_exact_type(kind: str) -> None:
    device_id = uuid4()
    query = AlertListQuery.model_validate(
        {
            "page": "2",
            "page_size": "100",
            "device_id": str(device_id),
            "status": "acknowledged",
            "severity": "warning",
            "type": kind,
            "sort_order": "asc",
        }
    )
    assert query.device_id == device_id and query.type == kind
    assert (query.page, query.page_size) == (2, 100)
    assert query.status is AlertStatus.ACKNOWLEDGED
    assert query.severity is AlertSeverity.WARNING


@pytest.mark.parametrize("state", list(AlertStatus))
def test_read_orm_and_utc(state: AlertStatus) -> None:
    alert = stored_alert(state)
    result = AlertRead.model_validate(alert).model_dump(mode="json")
    assert set(result) == {
        "id",
        "device_id",
        "type",
        "severity",
        "status",
        "message",
        "triggered_at",
        "resolved_at",
    }
    assert result["status"] == state.value and result["severity"] == "critical"
    assert result["triggered_at"] == "2025-12-31T16:00:00Z"
    assert result["resolved_at"] == (
        result["triggered_at"] if state is AlertStatus.RESOLVED else None
    )
    assert "device" not in alert.__dict__


def test_read_rejects_naive_time() -> None:
    alert = stored_alert()
    alert.triggered_at = datetime(2026, 1, 1)
    with pytest.raises(ValidationError):
        AlertRead.model_validate(alert)


def test_listing_never_commits_or_closes() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = 0
    session.scalars.return_value.all.return_value = []
    assert list_alerts(session, AlertListQuery()) == ([], 0)
    session.commit.assert_not_called()
    session.close.assert_not_called()
    assert "FOR UPDATE" not in str(session.scalars.call_args.args[0])


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
@pytest.mark.parametrize("state", list(AlertStatus))
def test_action_matrix_and_transaction(action: str, state: AlertStatus) -> None:
    session = MagicMock(spec=Session)
    alert = stored_alert(state)
    before = (
        alert.id,
        alert.device_id,
        alert.type,
        alert.severity,
        alert.message,
        alert.triggered_at,
    )
    prior_resolution = alert.resolved_at
    session.scalar.return_value = alert
    operation = acknowledge_alert if action == "acknowledge" else resolve_alert
    if action == "acknowledge" and state is AlertStatus.RESOLVED:
        with pytest.raises(InvalidAlertStateError):
            operation(session, alert.id, actor_id=uuid4())
        session.rollback.assert_called_once()
        session.commit.assert_not_called()
    else:
        assert operation(session, alert.id, actor_id=uuid4()) is alert
        session.commit.assert_called_once()
        session.refresh.assert_called_once_with(alert)
        session.rollback.assert_not_called()
        assert alert.status is (
            AlertStatus.ACKNOWLEDGED
            if action == "acknowledge"
            else AlertStatus.RESOLVED
        )
    assert "FOR UPDATE" in str(session.scalar.call_args.args[0])
    assert before == (
        alert.id,
        alert.device_id,
        alert.type,
        alert.severity,
        alert.message,
        alert.triggered_at,
    )
    if state is AlertStatus.RESOLVED:
        assert alert.resolved_at == prior_resolution
    elif action == "acknowledge":
        assert alert.resolved_at is None
    else:
        assert alert.resolved_at is not None
        assert alert.triggered_at <= alert.resolved_at <= datetime.now(UTC)


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
def test_missing_rolls_back(action: str) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    operation = acknowledge_alert if action == "acknowledge" else resolve_alert
    with pytest.raises(AlertNotFoundError):
        operation(session, uuid4(), actor_id=uuid4())
    session.rollback.assert_called_once()
    session.commit.assert_not_called()


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
@pytest.mark.parametrize("failure_at", ["scalar", "commit", "refresh"])
def test_database_errors_roll_back(action: str, failure_at: str) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = stored_alert()
    failure = OperationalError("PRIVATE_SQL", {}, RuntimeError("PRIVATE_SECRET"))
    getattr(session, failure_at).side_effect = failure
    operation = acknowledge_alert if action == "acknowledge" else resolve_alert
    with pytest.raises(OperationalError) as caught:
        operation(session, uuid4(), actor_id=uuid4())
    assert caught.value is failure
    session.rollback.assert_called_once()


def test_future_trigger_time_is_resolution_lower_bound() -> None:
    session = MagicMock(spec=Session)
    alert = stored_alert()
    alert.triggered_at = datetime.now(UTC) + timedelta(days=1)
    session.scalar.return_value = alert
    assert (
        resolve_alert(session, alert.id, actor_id=uuid4()).resolved_at
        == alert.triggered_at
    )
