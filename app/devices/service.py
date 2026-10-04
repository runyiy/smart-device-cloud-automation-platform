"""Device queries, write transactions and framework-independent domain errors."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.audit.service import record_audit_event
from app.db.transaction import transaction
from app.devices.model import Device
from app.devices.repository import DeviceRepository
from app.devices.schema import DeviceCreate, DeviceListQuery, DeviceUpdate


class DeviceNotFoundError(Exception):
    """The requested UUID does not identify a stored device."""


class DuplicateSerialNumberError(Exception):
    """The database rejected an already registered serial number."""


def create_device(
    session: Session,
    data: DeviceCreate,
    *,
    actor_id: UUID,
) -> Device:
    """Create through the write boundary; translate only exact serial conflicts."""

    device = Device(
        serial_number=data.serial_number,
        name=data.name,
        model=data.model,
        firmware_version=data.firmware_version,
    )
    repo = DeviceRepository(session)

    try:
        with transaction(session):
            repo.add(device)

            # Materialize the target UUID before staging its atomic audit event.
            session.flush()

            record_audit_event(
                session=session,
                actor_id=actor_id,
                action="device.created",
                resource_type="device",
                resource_id=device.id,
                event_metadata={},
            )

    except IntegrityError as exc:
        # The write boundary has already rolled back before error translation.
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

    try:
        repo.refresh(device)

    except SQLAlchemyError:
        # Only the failed read-back is cleaned up; the write is already committed.
        session.rollback()
        raise

    return device


def get_device(session: Session, device_id: UUID) -> Device:
    """Return one device or raise DeviceNotFoundError; never commit a read."""
    repo = DeviceRepository(session)
    device = repo.get(device_id, for_update=False)

    if device is None:
        raise DeviceNotFoundError(
            "Device not found",
        )

    return device


class InvalidDeviceStateError(Exception):
    """An inactive device cannot be reactivated."""


def list_devices(session: Session, query: DeviceListQuery) -> tuple[list[Device], int]:
    """Return a filtered, stably ordered page and its unpaginated total."""
    repo = DeviceRepository(session)
    devices, total = repo.list_page(query)

    return devices, total


def update_device(
    session: Session,
    device_id: UUID,
    data: DeviceUpdate,
    *,
    actor_id: UUID,
) -> Device:
    """Lock the row, validate transitions, and atomically persist supplied fields."""

    repo = DeviceRepository(session)
    with transaction(session):
        device = repo.get(device_id, for_update=True)

        if device is None:
            raise DeviceNotFoundError(
                "Device not found",
            )

        updates = data.model_dump(exclude_unset=True)

        fields = sorted(updates.keys())

        changed = any(getattr(device, field) != updates[field] for field in fields)

        if "status" in updates:
            new_status = updates["status"]

            if device.status == "inactive" and new_status == "active":
                raise InvalidDeviceStateError("Inactive device cannot be reactivated")

        for field in ("name", "model", "firmware_version"):
            if field in updates:
                setattr(device, field, updates[field])

        if "status" in updates:
            device.status = updates["status"]

        record_audit_event(
            session=session,
            actor_id=actor_id,
            action="device.updated",
            resource_type="device",
            resource_id=device.id,
            event_metadata={
                "fields": fields,
                "changed": changed,
            },
        )

    try:
        repo.refresh(device)

    except SQLAlchemyError:
        # Only the failed read-back is cleaned up; the write is already committed.
        session.rollback()
        raise

    return device
