"""Telemetry queries and atomic ingestion with a monotonic Device watermark."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.devices.model import Device, DeviceStatus
from app.devices.service import DeviceNotFoundError
from app.telemetry.model import Telemetry
from app.telemetry.schema import TelemetryCreate, TelemetryListQuery


class InactiveDeviceError(Exception):
    """Telemetry ingestion is forbidden after a Device is deactivated."""


def ingest_telemetry(
    session: Session, device_id: UUID, data: TelemetryCreate
) -> Telemetry:
    """Persist one sample and advance the Device watermark in one transaction."""
    try:
        stmt = select(Device).where(Device.id == device_id).with_for_update()

        device = session.scalar(stmt)

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

        session.add(telemetry)

        if device.last_seen_at is None or data.recorded_at > device.last_seen_at:
            device.last_seen_at = data.recorded_at

        session.commit()
        session.refresh(telemetry)
        return telemetry

    except (DeviceNotFoundError, InactiveDeviceError):
        session.rollback()
        raise

    except SQLAlchemyError:
        session.rollback()
        raise


def list_telemetry(
    session: Session, device_id: UUID, query: TelemetryListQuery
) -> tuple[list[Telemetry], int]:
    """Return a Device's filtered page and total without committing."""
    device = session.scalar(select(Device).where(Device.id == device_id))

    if device is None:
        raise DeviceNotFoundError("Device not found")

    filters = [
        Telemetry.device_id == device_id,
    ]

    if query.metric is not None:
        filters.append(Telemetry.metric == query.metric)

    if query.from_time is not None:
        filters.append(Telemetry.recorded_at >= query.from_time)

    if query.to_time is not None:
        filters.append(Telemetry.recorded_at <= query.to_time)

    stmt = select(Telemetry).where(*filters)

    count_stmt = select(func.count()).select_from(Telemetry).where(*filters)

    total = int(session.scalar(count_stmt) or 0)

    if query.sort_order == "asc":
        stmt = stmt.order_by(
            Telemetry.recorded_at.asc(),
            Telemetry.id.asc(),
        )
    else:
        stmt = stmt.order_by(
            Telemetry.recorded_at.desc(),
            Telemetry.id.desc(),
        )

    offset = (query.page - 1) * query.page_size
    stmt = stmt.offset(offset).limit(query.page_size)

    telemetries = list(session.scalars(stmt).all())

    return telemetries, total
