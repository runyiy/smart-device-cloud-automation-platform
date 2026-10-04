"""V2-T3 Task Repository delegation and use-case finalization contracts."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.devices.repository import DeviceRepository
from app.test_tasks.repository import TestTaskRepository as TaskRepository
from app.test_tasks.schema import TestTaskCreate as Create
from app.test_tasks.schema import TestTaskUpdate as Update
from app.test_tasks.service import create_test_task, get_test_task, update_test_task
from tests.api.test_devices import stored_device
from tests.unit.test_task_t10 import stored_task


def test_creation_shares_session_and_delegates_staging_and_readback() -> None:
    session = MagicMock(spec=Session)
    device = stored_device()
    session.scalar.return_value = device
    with (
        patch.object(
            DeviceRepository, "get", autospec=True, side_effect=DeviceRepository.get
        ) as get,
        patch.object(
            TaskRepository, "add", autospec=True, side_effect=TaskRepository.add
        ) as add,
        patch.object(
            TaskRepository, "refresh", autospec=True, side_effect=TaskRepository.refresh
        ) as refresh,
    ):
        row = create_test_task(
            session, Create(device_id=device.id, name="Task"), actor_id=uuid4()
        )
        assert get.call_args.args[0].session is session
        assert get.call_args.args[1] == device.id
        assert get.call_args.kwargs == {"for_update": True}
        add.assert_called_once()
        refresh.assert_called_once()
        assert add.call_args.args[0] is refresh.call_args.args[0]
        assert add.call_args.args[0].session is session
        assert add.call_args.args[1] is row
        assert refresh.call_args.args[1] is row
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("operation", ["read", "update"])
def test_task_lookup_lock_and_readback_contract(operation: str) -> None:
    session = MagicMock(spec=Session)
    row = stored_task()
    session.scalar.return_value = row
    with (
        patch.object(
            TaskRepository, "get", autospec=True, side_effect=TaskRepository.get
        ) as get,
        patch.object(
            TaskRepository, "refresh", autospec=True, side_effect=TaskRepository.refresh
        ) as refresh,
    ):
        result = (
            get_test_task(session, row.id)
            if operation == "read"
            else update_test_task(
                session, row.id, Update(summary=None), actor_id=uuid4()
            )
        )
        assert result is row
        get.assert_called_once()
        assert get.call_args.args[0].session is session
        assert get.call_args.args[1] == row.id
        assert get.call_args.kwargs == {"for_update": operation == "update"}
        if operation == "read":
            refresh.assert_not_called()
            session.commit.assert_not_called()
        else:
            refresh.assert_called_once()
            assert refresh.call_args.args[0] is get.call_args.args[0]
            assert refresh.call_args.args[1] is row
            session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("failure_at", ["lookup", "commit"])
def test_unexpected_write_failure_rolls_back_once_and_propagates(
    operation: str, failure_at: str
) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = (
        stored_device() if operation == "create" else stored_task()
    )
    error = RuntimeError("injected")
    getattr(
        session, "scalar" if failure_at == "lookup" else "commit"
    ).side_effect = error
    with pytest.raises(RuntimeError) as caught:
        if operation == "create":
            create_test_task(
                session, Create(device_id=uuid4(), name="Task"), actor_id=uuid4()
            )
        else:
            update_test_task(session, uuid4(), Update(summary=None), actor_id=uuid4())
    assert caught.value is error
    session.rollback.assert_called_once()
    session.refresh.assert_not_called()
    session.close.assert_not_called()
    if failure_at == "lookup":
        session.add.assert_not_called()
        session.commit.assert_not_called()
