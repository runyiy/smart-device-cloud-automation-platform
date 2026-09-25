"""Device queries, write transactions and framework-independent domain errors."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.devices.model import Device
from app.devices.schema import DeviceCreate, DeviceListQuery, DeviceUpdate


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


class InvalidDeviceStateError(Exception):
    """An inactive device cannot be reactivated within V1-T3."""


def list_devices(session: Session, query: DeviceListQuery) -> tuple[list[Device], int]:
    """Return a filtered, stably ordered page and its unpaginated total."""
    filters = []

    if query.status is not None:
        filters.append(Device.status == query.status)

    if query.model is not None:
        filters.append(Device.model == query.model)

    if query.serial_number is not None:
        filters.append(Device.serial_number == query.serial_number)

    stmt = select(Device).where(*filters)

    count_stmt = select(func.count()).select_from(Device).where(*filters)

    total = int(session.scalar(count_stmt) or 0)

    sort_columns = {
        "created_at": Device.created_at,
        "serial_number": Device.serial_number,
    }

    sort_column = sort_columns[query.sort_by]

    if query.sort_order == "asc":
        stmt = stmt.order_by(
            sort_column.asc(),
            Device.id.asc(),
        )
    else:
        stmt = stmt.order_by(
            sort_column.desc(),
            Device.id.desc(),
        )

    offset = (query.page - 1) * query.page_size
    stmt = stmt.offset(offset).limit(query.page_size)

    devices = list(session.scalars(stmt).all())

    return devices, total


def update_device(session: Session, device_id: UUID, data: DeviceUpdate) -> Device:
    """Lock the row, validate transitions, and atomically persist supplied fields."""
    try:
        stmt = select(Device).where(Device.id == device_id).with_for_update()

        device = session.scalar(stmt)

        if device is None:
            raise DeviceNotFoundError(
                "Device not found",
            )

        updates = data.model_dump(exclude_unset=True)

        if "status" in updates:
            new_status = updates["status"]

            if device.status == "inactive" and new_status == "active":
                raise InvalidDeviceStateError("Inactive device cannot be reactivated")

        for field in ("name", "model", "firmware_version"):
            if field in updates:
                setattr(device, field, updates[field])

        if "status" in updates:
            device.status = updates["status"]

        session.commit()
        session.refresh(device)
        return device

    except (DeviceNotFoundError, InvalidDeviceStateError):
        session.rollback()
        raise

    except SQLAlchemyError:
        session.rollback()
        raise
