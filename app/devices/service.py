"""Device registration transactions and framework-independent lookup errors."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.devices.model import Device
from app.devices.schema import DeviceCreate


class DeviceNotFoundError(Exception):
    """The requested UUID does not identify a stored device."""


class DuplicateSerialNumberError(Exception):
    """The database rejected an already registered serial number."""


def create_device(session: Session, data: DeviceCreate) -> Device:
    """Persist one device; own commit/rollback and translate only serial conflicts."""
    try:
        device = Device(
            serial_number=data.serial_number,
            name=data.name,
            model=data.model,
            firmware_version=data.firmware_version,
        )

        session.add(device)
        session.commit()
        session.refresh(device)
        return device

    except IntegrityError as exc:
        session.rollback()

        sqlstate = getattr(exc.orig, "sqlstate", None)

        constraint_name = getattr(
            getattr(exc.orig, "diag", None),
            "constraint_name",
            None,
        )

        if sqlstate == "23505" and constraint_name == "uq_devices_serial_number":
            raise DuplicateSerialNumberError(
                "Device serial number already exists"
            ) from exc

        raise

    except SQLAlchemyError:
        session.rollback()
        raise


def get_device(session: Session, device_id: UUID) -> Device:
    """Return one device or raise DeviceNotFoundError; never commit a read."""
    stmt = select(Device).where(Device.id == device_id)
    device = session.scalar(stmt)

    if device is None:
        raise DeviceNotFoundError(
            "Device not found",
        )

    return device
