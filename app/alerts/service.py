"""Pure threshold evaluation, Alert queries and transactional state transitions."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.alerts.schema import AlertListQuery


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
    filters = []

    if query.device_id is not None:
        filters.append(Alert.device_id == query.device_id)
    if query.status is not None:
        filters.append(Alert.status == query.status)
    if query.severity is not None:
        filters.append(Alert.severity == query.severity)
    if query.type is not None:
        filters.append(Alert.type == query.type)

    stmt = select(Alert).where(*filters)

    count_stmt = select(func.count()).select_from(Alert).where(*filters)

    total = int(session.scalar(count_stmt) or 0)

    if query.sort_order == "asc":
        stmt = stmt.order_by(
            Alert.triggered_at.asc(),
            Alert.id.asc(),
        )
    else:
        stmt = stmt.order_by(
            Alert.triggered_at.desc(),
            Alert.id.desc(),
        )

    offset = (query.page - 1) * query.page_size
    stmt = stmt.offset(offset).limit(query.page_size)

    alerts = list(session.scalars(stmt).all())

    return alerts, total


def acknowledge_alert(session: Session, alert_id: UUID) -> Alert:
    """Lock before checking state; acknowledge idempotently or reject resolution."""
    try:
        stmt = select(Alert).where(Alert.id == alert_id).with_for_update()

        alert = session.scalar(stmt)

        if alert is None:
            raise AlertNotFoundError("Alert not found")

        if alert.status == AlertStatus.OPEN:
            alert.status = AlertStatus.ACKNOWLEDGED
        elif alert.status == AlertStatus.RESOLVED:
            raise InvalidAlertStateError("Alert state is invalid")

        session.commit()
        session.refresh(alert)
        return alert

    except (AlertNotFoundError, InvalidAlertStateError):
        session.rollback()
        raise

    except SQLAlchemyError:
        session.rollback()
        raise


def resolve_alert(session: Session, alert_id: UUID) -> Alert:
    """Lock and resolve once, preserving the timestamp on repeated calls."""
    try:
        stmt = select(Alert).where(Alert.id == alert_id).with_for_update()

        alert = session.scalar(stmt)

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

        session.commit()
        session.refresh(alert)
        return alert

    except AlertNotFoundError:
        session.rollback()
        raise

    except SQLAlchemyError:
        session.rollback()
        raise
