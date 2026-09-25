"""T3 input acceptance checks independent of application startup or PostgreSQL."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.devices.model import Device
from app.devices.schema import DeviceListQuery, DeviceUpdate
from app.devices.service import (
    DeviceNotFoundError,
    InvalidDeviceStateError,
    list_devices,
    update_device,
)


@pytest.mark.parametrize(
    "field,limit", [("name", 100), ("model", 100), ("firmware_version", 64)]
)
@pytest.mark.parametrize("kind", ["empty", "whitespace", "overlong"])
def test_patch_rejects_invalid_display_values(
    field: str, limit: int, kind: str
) -> None:
    value = {"empty": "", "whitespace": " \t\n", "overlong": "x" * (limit + 1)}[kind]
    with pytest.raises(ValidationError):
        DeviceUpdate.model_validate({field: value})


@pytest.mark.parametrize(
    "field,limit", [("name", 100), ("model", 100), ("firmware_version", 64)]
)
def test_patch_strips_before_checking_length(field: str, limit: int) -> None:
    data = DeviceUpdate.model_validate({field: " " + "x" * limit + "\t"})
    assert data.model_dump(exclude_unset=True) == {field: "x" * limit}


@pytest.mark.parametrize("field", ["name", "model", "firmware_version", "status"])
@pytest.mark.parametrize("value", [None, 1, True, [], {}])
def test_patch_rejects_null_and_non_string_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        DeviceUpdate.model_validate({field: value})


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"id": "x"},
        {"serial_number": "x"},
        {"created_at": "x"},
        {"last_seen_at": "x"},
        {"extra": "x"},
    ],
)
def test_patch_rejects_empty_or_forbidden_fields(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        DeviceUpdate.model_validate(data)


@pytest.mark.parametrize("state", ["active", "inactive"])
def test_patch_preserves_omission(state: str) -> None:
    assert DeviceUpdate.model_validate({"status": state}).model_dump(
        exclude_unset=True
    ) == {"status": state}


def test_query_defaults() -> None:
    data = DeviceListQuery()
    assert (data.page, data.page_size) == (1, 20)
    assert (data.status, data.model, data.serial_number) == (None, None, None)
    assert (data.sort_by, data.sort_order) == ("created_at", "desc")


def test_listing_never_commits_or_closes_session() -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = 0
    session.scalars.return_value.all.return_value = []
    assert list_devices(session, DeviceListQuery()) == ([], 0)
    session.scalar.assert_called_once()
    session.scalars.assert_called_once()
    session.commit.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("failure_at", ["scalar", "commit", "refresh"])
def test_update_rolls_back_database_errors(failure_at: str) -> None:
    session = MagicMock(spec=Session)
    device = Device(id=uuid4(), name="Original", status="active")
    session.scalar.return_value = device
    error = OperationalError("UPDATE", {}, Exception("PRIVATE_SECRET"))
    getattr(session, failure_at).side_effect = error
    with pytest.raises(OperationalError) as caught:
        update_device(session, device.id, DeviceUpdate(name="New"))
    assert caught.value is error
    session.rollback.assert_called_once()
    session.close.assert_not_called()


def test_update_success_commits_once_and_refreshes() -> None:
    session = MagicMock(spec=Session)
    device = Device(id=uuid4(), name="Original", status="active")
    session.scalar.return_value = device
    assert update_device(session, device.id, DeviceUpdate(name="New")) is device
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(device)
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
def test_update_domain_rejection_rolls_back_before_mutation(missing: bool) -> None:
    session = MagicMock(spec=Session)
    device = Device(id=uuid4(), name="Original", status="inactive")
    session.scalar.return_value = None if missing else device
    expected = DeviceNotFoundError if missing else InvalidDeviceStateError
    with pytest.raises(expected):
        update_device(session, device.id, DeviceUpdate(name="New", status="active"))
    assert device.name == "Original"
    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("field", ["model", "serial_number"])
def test_query_accepts_none_for_absent_optional_filters(field: str) -> None:
    assert getattr(DeviceListQuery.model_validate({field: None}), field) is None


@pytest.mark.parametrize(
    "data",
    [
        {"page": "0"},
        {"page_size": "101"},
        {"model": "  "},
        {"serial_number": "bad id"},
        {"status": ""},
        {"sort_by": "name"},
        {"sort_order": "invalid"},
    ],
)
def test_query_rejects_invalid_values(data: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        DeviceListQuery.model_validate(data)


def test_query_accepts_url_integer_strings_and_normalizes_model() -> None:
    data = DeviceListQuery.model_validate(
        {"page": "2", "page_size": "100", "model": " M1 "}
    )
    assert (data.page, data.page_size, data.model) == (2, 100, "M1")
