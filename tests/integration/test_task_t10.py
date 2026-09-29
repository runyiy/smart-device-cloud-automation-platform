"""Guarded T10 persistence, atomicity and observed-lock-wait acceptance."""

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.config import Settings
from app.devices.model import Device, DeviceStatus
from app.devices.schema import DeviceUpdate
from app.devices.service import DeviceNotFoundError, update_device
from app.main import create_app
from app.test_tasks.model import TestTask as Task
from app.test_tasks.model import TestTaskStatus as State
from app.test_tasks.schema import TestTaskCreate as Create
from app.test_tasks.schema import TestTaskUpdate as Update
from app.test_tasks.service import (
    InactiveDeviceError,
    InvalidTestTaskStateError,
    create_test_task,
    get_test_task,
    update_test_task,
)
from app.test_tasks.service import TestTaskNotFoundError as TaskNotFoundError
from tests.integration.test_devices import device_engine as device_engine

STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def seed(engine: Engine, state: State = State.PENDING) -> tuple[UUID, UUID]:
    with Session(engine) as session:
        device = Device(
            serial_number="T10", name="Device", model="M1", firmware_version="v1"
        )
        session.add(device)
        session.flush()
        task = Task(
            device_id=device.id,
            name="Task",
            status=state,
            requested_at=STAMP,
            started_at=STAMP if state is State.RUNNING else None,
            summary="Original",
        )
        session.add(task)
        session.commit()
        return device.id, task.id


def test_creation_details_and_rejection(device_engine: Engine) -> None:
    device_id, _ = seed(device_engine)
    with Session(device_engine) as session:
        data = Create(device_id=device_id, name="Task")
        first = create_test_task(session, data)
        first_id = first.id
        second = create_test_task(session, data)
        assert first_id != second.id
        assert second.status is State.PENDING
        assert second.started_at is None and second.finished_at is None
        assert second.summary is None
    with Session(device_engine) as observer:
        assert get_test_task(observer, first_id).status is State.PENDING
        assert observer.scalar(select(func.count()).select_from(Task)) == 3
        device = observer.get(Device, device_id)
        assert device is not None and device.last_seen_at is None
        device.status = DeviceStatus.INACTIVE
        observer.commit()
    with Session(device_engine) as session:
        with pytest.raises(InactiveDeviceError):
            create_test_task(session, data)
        assert not session.in_transaction()
        with pytest.raises(DeviceNotFoundError):
            create_test_task(session, Create(device_id=uuid4(), name="Task"))
        with pytest.raises(TaskNotFoundError):
            get_test_task(session, uuid4())
        assert get_test_task(session, first_id).id == first_id
        update_test_task(session, first_id, Update.model_validate({"summary": None}))


@pytest.mark.parametrize(
    "source,target",
    [
        (State.PENDING, State.RUNNING),
        (State.PENDING, State.CANCELLED),
        (State.RUNNING, State.PASSED),
        (State.RUNNING, State.FAILED),
        (State.RUNNING, State.CANCELLED),
    ],
)
@pytest.mark.parametrize("future", [False, True])
def test_real_transitions_and_time_bounds(
    device_engine: Engine,
    source: State,
    target: State,
    future: bool,
) -> None:
    _, task_id = seed(device_engine, source)
    lower_bound = datetime.now(UTC) + timedelta(days=1) if future else STAMP
    with Session(device_engine) as session:
        row = session.get(Task, task_id)
        assert row is not None
        row.requested_at = lower_bound
        if source is State.RUNNING:
            row.started_at = lower_bound + timedelta(hours=1)
        session.commit()
    with Session(device_engine) as session:
        # Include summary to expose transition defects separately from validation.
        data = Update.model_validate({"status": target.value, "summary": "Done"})
        update_test_task(session, task_id, data)
    with Session(device_engine) as observer:
        row = observer.get(Task, task_id)
        assert row is not None and row.status is target
        assert row.summary == "Done"
        if target is State.RUNNING:
            assert row.started_at is not None and row.started_at >= lower_bound
            assert row.finished_at is None
        else:
            assert row.finished_at is not None and row.finished_at >= lower_bound
            if source is State.PENDING:
                assert row.started_at is None
            else:
                assert row.started_at is not None and row.finished_at >= row.started_at
        before = (row.requested_at, row.started_at, row.finished_at)
        update_test_task(observer, task_id, data)
        assert (row.requested_at, row.started_at, row.finished_at) == before


@pytest.mark.parametrize("operation", ["create", "update"])
def test_failed_commit_and_invalid_transition_are_atomic(
    device_engine: Engine, operation: str
) -> None:
    device_id, task_id = seed(device_engine)
    with Session(device_engine) as session:
        with pytest.raises(InvalidTestTaskStateError):
            update_test_task(
                session,
                task_id,
                Update.model_validate(
                    {"status": "passed", "summary": "Must not persist"}
                ),
            )
        assert not session.in_transaction()

        def corrupt(current: Session, context: object, instances: object) -> None:
            for obj in list(current.new) + list(current.dirty):
                if isinstance(obj, Task):
                    obj.name = ""  # Force a real database CHECK failure at commit.

        event.listen(session, "before_flush", corrupt)
        with pytest.raises(IntegrityError):
            if operation == "create":
                create_test_task(session, Create(device_id=device_id, name="New"))
            else:
                update_test_task(
                    session, task_id, Update.model_validate({"summary": "New"})
                )
        assert not session.in_transaction()
    with Session(device_engine) as observer:
        row = observer.get(Task, task_id)
        assert row is not None and row.status is State.PENDING
        assert row.name == "Task" and row.summary == "Original"
        assert observer.scalar(select(func.count()).select_from(Task)) == 1


@pytest.mark.parametrize(
    "first_action,second_action",
    [
        ("deactivate", "create"),
        ("create", "deactivate"),
        ("passed", "failed"),
        ("passed", "passed"),
        ("summary", "passed_only"),
        ("passed_only", "summary"),
        ("summary", "summary_second"),
    ],
)
def test_concurrent_writes_observe_locks(
    device_engine: Engine,
    first_action: str,
    second_action: str,
) -> None:
    device_id, task_id = seed(device_engine, State.RUNNING)
    pending: list[Future[str]] = []
    first_finished: list[datetime | None] = []

    def act(session: Session, action: str) -> str:
        try:
            if action == "create":
                create_test_task(session, Create(device_id=device_id, name="Created"))
            elif action == "deactivate":
                update_device(
                    session,
                    device_id,
                    DeviceUpdate.model_validate({"status": "inactive"}),
                )
            else:
                body = (
                    {"summary": "Concurrent"}
                    if action == "summary"
                    else {"summary": "Second"}
                    if action == "summary_second"
                    else {"status": "passed"}
                    if action == "passed_only"
                    else {"status": action, "summary": "Original"}
                )
                update_test_task(session, task_id, Update.model_validate(body))
            return "ok"
        except (InactiveDeviceError, InvalidTestTaskStateError):
            return "conflict"

    def compete() -> str:
        with Session(device_engine) as second:
            return act(second, second_action)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(device_engine) as first:
            pid = first.scalar(text("SELECT pg_backend_pid()"))

            def before_commit(current: Session) -> None:
                current.flush()
                row = current.get(Task, task_id)
                assert row is not None
                first_finished.append(row.finished_at)
                pending.append(executor.submit(compete))
                deadline = monotonic() + 3
                blocked = False
                with device_engine.connect() as observer:
                    while monotonic() < deadline:
                        # Surface validation failures instead of a lock timeout.
                        if pending[0].done():
                            pending[0].result()
                        blocked = bool(
                            observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE datname=current_database() "
                                    "AND :pid = ANY(pg_blocking_pids(pid))"
                                ),
                                {"pid": pid},
                            )
                        )
                        if blocked:
                            break
                        sleep(0.02)
                assert blocked, "Second operation did not wait for the target lock"

            event.listen(first, "before_commit", before_commit, once=True)
            try:
                assert act(first, first_action) == "ok"
            finally:
                first.rollback()
        result = pending[0].result(timeout=10)
    assert result == (
        "conflict"
        if (first_action, second_action)
        in {("deactivate", "create"), ("passed", "failed")}
        else "ok"
    )
    with Session(device_engine) as observer:
        if "create" in (first_action, second_action):
            count = observer.scalar(select(func.count()).select_from(Task))
            assert count == (1 if first_action == "deactivate" else 2)
        else:
            row = observer.get(Task, task_id)
            assert row is not None
            if second_action == "summary_second":
                assert row.status is State.RUNNING and row.finished_at is None
                assert row.summary == "Second"
                return
            assert row.status is State.PASSED and row.finished_at is not None
            if first_action in {"passed", "passed_only"}:
                assert row.finished_at == first_finished[0]
            if "summary" in (first_action, second_action):
                assert row.summary == "Concurrent"


def test_http_lifecycle_preserves_omitted_fields(device_engine: Engine) -> None:
    device_id, sibling_id = seed(device_engine)
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/api/v1/test-tasks",
            json={
                "device_id": str(device_id),
                "name": "  Manual check  ",
                "summary": "  Keep  ",
            },
        )
        assert created.status_code == 201
        initial = created.json()
        assert initial["name"] == "Manual check" and initial["summary"] == "Keep"
        assert initial["status"] == "pending"
        assert initial["started_at"] is None and initial["finished_at"] is None
        path = f"/api/v1/test-tasks/{initial['id']}"
        assert client.get(path).json() == initial
        with Session(device_engine) as session:
            update_device(
                session, device_id, DeviceUpdate.model_validate({"status": "inactive"})
            )
        running = client.patch(path, json={"status": "running"})
        assert running.status_code == 200
        assert running.json()["status"] == "running"
        assert running.json()["summary"] == "Keep"
        assert running.json()["started_at"].endswith("Z")
        completed = client.patch(path, json={"status": "passed"})
        assert completed.status_code == 200
        terminal = completed.json()
        assert terminal["status"] == "passed" and terminal["finished_at"].endswith("Z")
        assert terminal["started_at"] == running.json()["started_at"]
        assert client.patch(path, json={"status": "passed"}).json() == terminal
        cleared = client.patch(path, json={"summary": None})
        assert cleared.status_code == 200 and cleared.json() == {
            **terminal,
            "summary": None,
        }
        rejected = client.patch(
            path, json={"status": "failed", "summary": "Must not persist"}
        )
        assert rejected.status_code == 409
        assert client.get(path).json() == cleared.json()
        assert client.get(f"/api/v1/test-tasks/{uuid4()}").status_code == 404
        assert (
            client.patch(
                f"/api/v1/test-tasks/{uuid4()}", json={"summary": None}
            ).status_code
            == 404
        )
    with Session(device_engine) as observer:
        task = observer.get(Task, UUID(initial["id"]))
        sibling = observer.get(Task, sibling_id)
        assert task is not None and task.status is State.PASSED and task.summary is None
        assert sibling is not None and sibling.status is State.PENDING
        assert sibling.summary == "Original"
