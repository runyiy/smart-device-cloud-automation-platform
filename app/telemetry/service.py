"""Telemetry queries and atomic ingestion with a monotonic Device watermark."""

from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository
from app.alerts.service import build_threshold_alert
from app.audit.service import record_audit_event
from app.db.transaction import transaction
from app.devices.model import DeviceStatus
from app.devices.repository import DeviceRepository
from app.devices.service import DeviceNotFoundError
from app.telemetry.model import Telemetry
from app.telemetry.repository import TelemetryRepository
from app.telemetry.schema import TelemetryCreate, TelemetryListQuery


class InactiveDeviceError(Exception):
    """Telemetry ingestion is forbidden after a Device is deactivated."""


def ingest_telemetry(
    session: Session,
    device_id: UUID,
    data: TelemetryCreate,
    *,
    actor_id: UUID,
) -> Telemetry:
    """Persist one sample and advance the Device watermark in one transaction."""
    repo_device = DeviceRepository(session)
    repo_telemetry = TelemetryRepository(session)
    repo_alert = AlertRepository(session)
    with transaction(session):
        # Serialize status and watermark decisions with other Device writers.
        device = repo_device.get(device_id, for_update=True)

        if device is None:
            raise DeviceNotFoundError(
                "Device not found",
            )

        if device.status == DeviceStatus.INACTIVE:
            raise InactiveDeviceError(
                "Device is inactive",
            )

        telemetry = Telemetry(
            device_id=device_id,
            metric=data.metric,
            value=data.value,
            unit=data.unit,
            recorded_at=data.recorded_at,
        )

        repo_telemetry.add(telemetry)

        if device.last_seen_at is None or data.recorded_at > device.last_seen_at:
            device.last_seen_at = data.recorded_at

        alert = build_threshold_alert(
            device_id=device_id, metric=data.metric, value=data.value, unit=data.unit
        )

        alert_generated = False

        if alert is not None:
            repo_alert.add(alert)
            alert_generated = True

        # Materialize the target UUID; business and audit still share one commit.
        session.flush()

        record_audit_event(
            session=session,
            actor_id=actor_id,
            action="telemetry.ingested",
            resource_type="telemetry",
            resource_id=telemetry.id,
            event_metadata={
                "device_id": str(device_id),
                "alert_generated": alert_generated,
            },
        )
        # Sample, optional Alert, watermark and audit succeed or roll back together.

    try:
        repo_telemetry.refresh(telemetry)

    except SQLAlchemyError:
        # Clean up failed read-back; the successful write is already committed.
        session.rollback()
        raise

    return telemetry


def list_telemetry(
    session: Session, device_id: UUID, query: TelemetryListQuery
) -> tuple[list[Telemetry], int]:
    """Return a Device's filtered page and total without committing."""
    repo_device = DeviceRepository(session)
    repo_telemetry = TelemetryRepository(session)

    # This existence check is read-only and must not hold a Device write lock.
    device = repo_device.get(device_id, for_update=False)

    if device is None:
        raise DeviceNotFoundError("Device not found")

    telemetries, total = repo_telemetry.list_page(device_id, query)

    return telemetries, total
