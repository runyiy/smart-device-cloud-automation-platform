"""V1-T2 schema and service acceptance; no real database is needed here."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.devices.model import Device, DeviceStatus
from app.devices.schema import DeviceCreate, DeviceRead
from app.devices.service import (
    DeviceNotFoundError,
    DuplicateSerialNumberError,
    create_device,
    get_device,
)


def payload() -> dict[str, object]:
    return dict(
        serial_number="SN-001", name="Sensor", model="M1", firmware_version="v1"
    )


@pytest.mark.parametrize(
    "field", ["serial_number", "name", "model", "firmware_version"]
)
@pytest.mark.parametrize("value", [None, 1, True, [], {}])
def test_input_requires_strings(field: str, value: object) -> None:
    data = payload()
    data[field] = value
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate(data)


@pytest.mark.parametrize(
    "field", ["serial_number", "name", "model", "firmware_version"]
)
def test_input_requires_all_fields(field: str) -> None:
    data = payload()
    del data[field]
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate(data)


@pytest.mark.parametrize(
    "field", ["id", "status", "last_seen_at", "created_at", "extra"]
)
def test_input_forbids_extra_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate({**payload(), field: "client-value"})


@pytest.mark.parametrize(
    "serial", ["", "x" * 65, " SN", "SN ", "bad id", "设备", "x\n", "x/y", "x,y"]
)
def test_serial_rejects_invalid_values(serial: str) -> None:
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate({**payload(), "serial_number": serial})


@pytest.mark.parametrize("serial", ["a", "x" * 64, "device_A.2"])
def test_input_normalizes_only_display_fields(serial: str) -> None:
    data = DeviceCreate.model_validate(
        {
            **payload(),
            "serial_number": serial,
            "name": "  Sensor  A\t",
            "model": "\t" + "m" * 100 + " ",
            "firmware_version": " " + "v" * 64 + " ",
        }
    )
    assert data.serial_number == serial
    assert data.name == "Sensor  A"
    assert data.model == "m" * 100
    assert data.firmware_version == "v" * 64


@pytest.mark.parametrize(
    "field,limit", [("name", 100), ("model", 100), ("firmware_version", 64)]
)
@pytest.mark.parametrize("kind", ["empty", "whitespace", "overlong"])
def test_display_field_limits(field: str, limit: int, kind: str) -> None:
    value = {"empty": "", "whitespace": " \t\n", "overlong": "x" * (limit + 1)}[kind]
    with pytest.raises(ValidationError):
        DeviceCreate.model_validate({**payload(), field: value})


def test_output_normalizes_aware_timestamps_to_utc() -> None:
    stamp = datetime(2026, 1, 2, 10, tzinfo=timezone(timedelta(hours=8)))
    device = Device(
        id=uuid4(),
        serial_number="SN-001",
        name="Sensor",
        model="M1",
        firmware_version="v1",
        status=DeviceStatus.ACTIVE,
        created_at=stamp,
        last_seen_at=stamp,
    )
    output = DeviceRead.model_validate(device).model_dump(mode="json")
    assert len(output) == 8
    for field in ("created_at", "last_seen_at"):
        parsed = datetime.fromisoformat(output[field])
        assert parsed.utcoffset() == timedelta(0)
        assert parsed == stamp.astimezone(UTC)


class DriverError(Exception):
    def __init__(self, sqlstate: str, constraint: str) -> None:
        super().__init__("PRIVATE_SECRET")
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=constraint)


@pytest.mark.parametrize(
    "sqlstate,constraint,is_duplicate",
    [
        ("23505", "uq_devices_serial_number", True),
        ("23505", "pk_devices", False),
        ("23514", "uq_devices_serial_number", False),
    ],
)
def test_service_translates_only_exact_unique_violation(
    sqlstate: str,
    constraint: str,
    is_duplicate: bool,
) -> None:
    session = MagicMock(spec=Session)
    error = IntegrityError("INSERT", {}, DriverError(sqlstate, constraint))
    session.commit.side_effect = error
    expected = DuplicateSerialNumberError if is_duplicate else IntegrityError
    with pytest.raises(expected):
        create_device(session, DeviceCreate.model_validate(payload()))
    session.rollback.assert_called_once()
    session.close.assert_not_called()


def test_service_rolls_back_and_preserves_other_database_failures() -> None:
    session = MagicMock(spec=Session)
    error = OperationalError("INSERT", {}, Exception("PRIVATE_SECRET"))
    session.commit.side_effect = error
    with pytest.raises(OperationalError) as caught:
        create_device(session, DeviceCreate.model_validate(payload()))
    assert caught.value is error
    session.rollback.assert_called_once()


def test_service_success_commits_once_without_closing_session() -> None:
    session = MagicMock(spec=Session)
    device = create_device(session, DeviceCreate.model_validate(payload()))
    assert device.serial_number == "SN-001"
    session.add.assert_called_once_with(device)
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(device)
    session.close.assert_not_called()
    session.rollback.assert_not_called()


def test_missing_device_never_commits() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    session.get.return_value = None
    with pytest.raises(DeviceNotFoundError):
        get_device(session, uuid4())
    session.commit.assert_not_called()
    session.close.assert_not_called()
