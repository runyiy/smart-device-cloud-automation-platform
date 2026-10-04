"""V2-T1 Device Service boundary and failure-cleanup contracts."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.devices.model import Device
from app.devices.repository import DeviceRepository
from app.devices.schema import DeviceCreate, DeviceUpdate
from app.devices.service import create_device, update_device


@pytest.mark.parametrize("operation", ["create", "update"])
def test_write_service_cleans_up_unexpected_commit_failure(operation: str) -> None:
    session = MagicMock(spec=Session)
    row = Device(id=uuid4(), name="Original", status="active")
    session.scalar.return_value = row
    error = RuntimeError("unexpected flush hook failure")
    session.commit.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        if operation == "create":
            create_device(
                session,
                DeviceCreate(
                    serial_number="TX-1",
                    name="Original",
                    model="M1",
                    firmware_version="v1",
                ),
                actor_id=uuid4(),
            )
        else:
            update_device(
                session, row.id, DeviceUpdate(name="Changed"), actor_id=uuid4()
            )
    assert caught.value is error
    session.commit.assert_called_once()
    session.rollback.assert_called_once()
    session.refresh.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "update"])
def test_write_service_delegates_readback_to_repository(operation: str) -> None:
    """Both use cases must share the agreed Repository persistence boundary."""
    session = MagicMock(spec=Session)
    row = Device(id=uuid4(), name="Original", status="active")
    session.scalar.return_value = row
    with patch.object(
        DeviceRepository,
        "refresh",
        autospec=True,
        side_effect=DeviceRepository.refresh,
    ) as refresh:
        if operation == "create":
            result = create_device(
                session,
                DeviceCreate(
                    serial_number="BOUNDARY-1",
                    name="Original",
                    model="M1",
                    firmware_version="v1",
                ),
                actor_id=uuid4(),
            )
        else:
            result = update_device(
                session, row.id, DeviceUpdate(name="Changed"), actor_id=uuid4()
            )
        refresh.assert_called_once()
        repository, refreshed = refresh.call_args.args
        assert repository.session is session
        assert refreshed is result
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(result)
