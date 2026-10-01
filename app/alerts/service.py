"""Pure threshold evaluation, Alert queries and transactional state transitions."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.alerts.repository import AlertRepository
from app.alerts.schema import AlertListQuery
from app.db.transaction import transaction


def build_threshold_alert(
    device_id: UUID, metric: str, value: float, unit: str
) -> Alert | None:
    """Return one unsaved Alert for validated inputs; the caller owns persistence."""
    if metric == "temperature" and unit == "°C" and value > 80.0:
        return Alert(
            device_id=device_id,
            type="temperature_high",
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.OPEN,
            message="Temperature exceeds 80 °C.",
            resolved_at=None,
        )
    if metric == "battery" and unit == "%" and value < 20.0:
        return Alert(
            device_id=device_id,
            type="battery_low",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.OPEN,
            message="Battery is below 20%.",
            resolved_at=None,
        )
    if metric == "signal_strength" and unit == "dBm" and value < -80.0:
        return Alert(
            device_id=device_id,
            type="signal_weak",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.OPEN,
            message="Signal strength is below -80 dBm.",
            resolved_at=None,
        )
    return None


class AlertNotFoundError(Exception):
    """The requested UUID does not identify a stored alert."""


class InvalidAlertStateError(Exception):
    """A resolved alert cannot be acknowledged or reopened."""


def list_alerts(session: Session, query: AlertListQuery) -> tuple[list[Alert], int]:
    """Return a filtered, stably ordered page and total without committing."""
    repo_alert = AlertRepository(session)
    alerts, total = repo_alert.list_page(query)

    return alerts, total


def acknowledge_alert(session: Session, alert_id: UUID) -> Alert:
    """Lock before checking state; acknowledge idempotently or reject resolution."""
    repo_alert = AlertRepository(session)

    with transaction(session):
        alert = repo_alert.get(alert_id, for_update=True)

        if alert is None:
            raise AlertNotFoundError("Alert not found")

        if alert.status == AlertStatus.OPEN:
            alert.status = AlertStatus.ACKNOWLEDGED
        elif alert.status == AlertStatus.RESOLVED:
            raise InvalidAlertStateError("Alert state is invalid")

    try:
        repo_alert.refresh(alert)

    except SQLAlchemyError:
        # Clean up failed read-back; the successful write is already committed.
        session.rollback()
        raise

    return alert


def resolve_alert(session: Session, alert_id: UUID) -> Alert:
    """Lock and resolve once, preserving the timestamp on repeated calls."""
    repo_alert = AlertRepository(session)

    with transaction(session):
        alert = repo_alert.get(alert_id, for_update=True)

        if alert is None:
            raise AlertNotFoundError("Alert not found")

        if alert.status in (
            AlertStatus.OPEN,
            AlertStatus.ACKNOWLEDGED,
        ):
            now_utc = datetime.now(UTC)

            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = max(
                now_utc,
                alert.triggered_at,
            )

    try:
        repo_alert.refresh(alert)

    except SQLAlchemyError:
        # Clean up failed read-back; the successful write is already committed.
        session.rollback()
        raise

    return alert
