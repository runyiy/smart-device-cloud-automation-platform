"""V2-T3 real PostgreSQL ownership, failure and cached-state concurrency checks."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.orm import Session

from app.devices.model import Device, DeviceStatus
from app.devices.schema import DeviceUpdate
from app.devices.service import update_device
from app.test_tasks.model import TestTask as Task
from app.test_tasks.model import TestTaskStatus as State
from app.test_tasks.repository import TestTaskRepository as TaskRepository
from app.test_tasks.schema import TestTaskCreate as Create
from app.test_tasks.schema import TestTaskUpdate as Update
from app.test_tasks.service import (
    InactiveDeviceError,
    InvalidTestTaskStateError,
    create_test_task,
    get_test_task,
    update_test_task,
)
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_task_t10 import seed


def test_repository_visibility_and_finalization_belong_to_caller(
    device_engine: Engine,
) -> None:
    device_id, _ = seed(device_engine)
    new_id = uuid4()
    with Session(device_engine) as owner:
        repo = TaskRepository(owner)
        assert repo.session is owner
        row = Task(id=new_id, device_id=device_id, name="Staged")
        repo.add(row)
        owner.flush()
        repo.refresh(row)
        assert row.status is State.PENDING
        assert row.requested_at.tzinfo is not None
        assert repo.get(new_id) is row
        assert repo.get(uuid4()) is None
        assert repo.get(uuid4(), for_update=True) is None
        with Session(device_engine) as observer:
            assert TaskRepository(observer).get(new_id) is None
        owner.rollback()
        with Session(device_engine) as observer:
            assert TaskRepository(observer).get(new_id) is None
        # A prerequisite read has already started the caller's next transaction.
        assert repo.get(new_id) is None
        row = Task(id=new_id, device_id=device_id, name="Persisted")
        repo.add(row)
        owner.commit()
        repo.refresh(row)
        assert repo.get(new_id) is row
        with Session(device_engine) as observer:
            stored = TaskRepository(observer).get(new_id)
            assert stored is not None and stored.name == "Persisted"
            with pytest.raises(InvalidRequestError):
                _ = stored.device


def test_repository_lock_lifetime_and_nonblocking_service_detail(
    device_engine: Engine,
) -> None:
    _, task_id = seed(device_engine)
    with Session(device_engine) as owner, Session(device_engine) as competitor:
        assert TaskRepository(owner).get(task_id, for_update=True) is not None
        competitor.execute(text("SET LOCAL lock_timeout = '200ms'"))
        assert get_test_task(competitor, task_id).id == task_id
        with pytest.raises(OperationalError) as caught:
            TaskRepository(competitor).get(task_id, for_update=True)
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        competitor.rollback()
        owner.rollback()
        assert TaskRepository(competitor).get(task_id, for_update=True) is not None


@pytest.mark.parametrize("operation", ["create", "update"])
def test_failure_after_real_flush_rolls_back_and_allows_session_reuse(
    device_engine: Engine, operation: str
) -> None:
    device_id, task_id = seed(device_engine)
    error = RuntimeError("injected after database write")
    with Session(device_engine) as session:
        # Failure at finalization occurs after the pending write actually reaches PG.
        def flush_then_fail() -> None:
            session.flush()
            if operation == "create":
                assert session.scalar(select(func.count()).select_from(Task)) == 2
            else:
                changed = session.get(Task, task_id)
                assert changed is not None and changed.status is State.RUNNING
                assert changed.summary == "Must roll back"
            raise error

        with patch.object(session, "commit", side_effect=flush_then_fail):
            with pytest.raises(RuntimeError) as caught:
                if operation == "create":
                    create_test_task(session, Create(device_id=device_id, name="New"))
                else:
                    update_test_task(
                        session,
                        task_id,
                        Update(status=State.RUNNING, summary="Must roll back"),
                    )
        assert caught.value is error
        assert not session.in_transaction()
        with Session(device_engine) as observer:
            stored = observer.get(Task, task_id)
            assert stored is not None and stored.status is State.PENDING
            assert stored.summary == "Original"
            assert stored.started_at is None and stored.finished_at is None
            assert observer.scalar(select(func.count()).select_from(Task)) == 1
        updated = update_test_task(session, task_id, Update(summary="Recovered"))
        assert updated.summary == "Recovered"


@pytest.mark.parametrize("operation", ["create", "update"])
def test_refresh_failure_cleans_read_transaction_but_keeps_committed_write(
    device_engine: Engine, operation: str
) -> None:
    device_id, task_id = seed(device_engine)
    error = OperationalError("refresh", {}, RuntimeError("injected"))
    with Session(device_engine) as session:
        assert TaskRepository(session).get(task_id) is not None

        def fail_refresh(row: object) -> None:
            session.execute(text("SELECT 1"))
            raise error

        with patch.object(session, "refresh", side_effect=fail_refresh):
            with pytest.raises(OperationalError) as caught:
                if operation == "create":
                    create_test_task(
                        session, Create(device_id=device_id, name="Durable")
                    )
                else:
                    update_test_task(
                        session,
                        task_id,
                        Update(status=State.RUNNING, summary="Durable"),
                    )
        assert caught.value is error
        assert not session.in_transaction()
        with Session(device_engine) as observer:
            if operation == "create":
                created = observer.scalar(select(Task).where(Task.name == "Durable"))
                assert created is not None and created.status is State.PENDING
                assert observer.scalar(select(func.count()).select_from(Task)) == 2
            else:
                updated = observer.get(Task, task_id)
                assert updated is not None and updated.status is State.RUNNING
                assert updated.summary == "Durable" and updated.started_at is not None
                started = updated.started_at
                repeated = update_test_task(
                    session, task_id, Update(status=State.RUNNING)
                )
                assert repeated.started_at == started
        assert get_test_task(session, task_id).id == task_id


def test_update_rechecks_state_after_lock_when_task_was_previously_read(
    device_engine: Engine,
) -> None:
    _, task_id = seed(device_engine, State.RUNNING)
    rejected = False
    with Session(device_engine) as stale:
        cached = get_test_task(stale, task_id)
        assert cached.status is State.RUNNING
        with Session(device_engine) as winner:
            completed = update_test_task(
                winner, task_id, Update(status=State.PASSED, summary="Winner")
            )
            finished = completed.finished_at
        # The accepted caller-owned Session/autobegin contract permits prior reads.
        try:
            update_test_task(
                stale, task_id, Update(status=State.FAILED, summary="Must not persist")
            )
        except InvalidTestTaskStateError:
            rejected = True
            assert not stale.in_transaction()
    # Observe durable data before asserting rejection, to expose any committed loss.
    with Session(device_engine) as observer:
        row = observer.get(Task, task_id)
        assert row is not None and row.status is State.PASSED
        assert row.summary == "Winner" and row.finished_at == finished
    assert rejected, "A terminal-state transition must be rejected after locking"


def test_create_rechecks_device_after_lock_when_device_was_previously_read(
    device_engine: Engine,
) -> None:
    device_id, _ = seed(device_engine)
    rejected = False
    with Session(device_engine) as stale:
        cached = stale.get(Device, device_id)
        assert cached is not None and cached.status is DeviceStatus.ACTIVE
        with Session(device_engine) as winner:
            update_device(winner, device_id, DeviceUpdate(status=DeviceStatus.INACTIVE))
        try:
            create_test_task(
                stale, Create(device_id=device_id, name="Must not persist")
            )
        except InactiveDeviceError:
            rejected = True
            assert not stale.in_transaction()
    with Session(device_engine) as observer:
        assert observer.scalar(select(func.count()).select_from(Task)) == 1
        device = observer.get(Device, device_id)
        assert device is not None and device.status is DeviceStatus.INACTIVE
    assert rejected, "Task creation must reject the locked current inactive state"
