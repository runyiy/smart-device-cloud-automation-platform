"""T10 input, response and transition contracts independent of PostgreSQL."""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.test_tasks.model import TestTask as Task
from app.test_tasks.model import TestTaskStatus as State
from app.test_tasks.schema import TestTaskCreate as Create
from app.test_tasks.schema import TestTaskRead as Read
from app.test_tasks.schema import TestTaskUpdate as Update
from app.test_tasks.service import (
    InvalidTestTaskStateError,
    create_test_task,
    get_test_task,
    update_test_task,
)
from app.test_tasks.service import (
    TestTaskNotFoundError as TaskNotFoundError,
)
from tests.api.test_devices import stored_device

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
ALLOWED = {
    State.PENDING: {State.RUNNING, State.CANCELLED},
    State.RUNNING: {State.PASSED, State.FAILED, State.CANCELLED},
    State.PASSED: set(),
    State.FAILED: set(),
    State.CANCELLED: set(),
}


def stored_task(state: State = State.PENDING) -> Task:
    return Task(
        id=uuid4(),
        device_id=uuid4(),
        name="Original",
        status=state,
        requested_at=STAMP,
        started_at=STAMP if state != State.PENDING else None,
        finished_at=STAMP
        if state in {State.PASSED, State.FAILED, State.CANCELLED}
        else None,
        summary="Original summary",
    )


@pytest.mark.parametrize("state", list(State))
def test_status_only_patch_can_omit_summary(state: State) -> None:
    data = Update.model_validate({"status": state.value})
    assert data.model_dump(exclude_unset=True) == {"status": state}


def test_summary_omission_and_clear() -> None:
    assert Update.model_validate({"summary": None}).model_dump(exclude_unset=True) == {
        "summary": None
    }
    assert Update.model_validate({"summary": "  New  "}).summary == "New"
    for summary in (None, " x "):
        data = Create.model_validate(
            {"device_id": str(uuid4()), "name": " Lab ", "summary": summary}
        )
        assert data.name == "Lab" and data.summary == (None if summary is None else "x")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"status": None, "summary": None},
        {"status": "RUNNING", "summary": None},
        {"status": 1, "summary": None},
        {"summary": " "},
        {"summary": 1},
        {"summary": True},
        {"summary": []},
        {"summary": "x" * 1001},
        {"name": "Rename", "summary": None},
        {"finished_at": "2026-01-01", "summary": None},
    ],
)
def test_invalid_patch(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Update.model_validate(body)


@pytest.mark.parametrize(
    "overrides",
    [
        {"device_id": None},
        {"device_id": "bad"},
        {"name": None},
        {"name": " "},
        {"name": 5},
        {"name": "x" * 101},
        {"summary": ""},
        {"summary": False},
        {"summary": "x" * 1001},
        {"status": "pending"},
        {"requested_at": "2026-01-01"},
    ],
)
def test_invalid_create(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Create.model_validate({"device_id": str(uuid4()), "name": "Task", **overrides})


def test_text_boundaries() -> None:
    data = Create.model_validate(
        {"device_id": uuid4(), "name": " " + "中" * 100, "summary": "文" * 1000 + " "}
    )
    assert data.name == "中" * 100 and data.summary == "文" * 1000
    assert Update.model_validate({"summary": "文" * 1000}).summary == "文" * 1000


@pytest.mark.parametrize("source", list(State))
@pytest.mark.parametrize("target", list(State))
def test_all_transitions(source: State, target: State) -> None:
    session = MagicMock(spec=Session)
    row = stored_task(source)
    session.scalar.return_value = row
    before = (
        row.status,
        row.requested_at,
        row.started_at,
        row.finished_at,
        row.summary,
    )
    # Include summary to test the service independently of the optional-field defect.
    data = Update.model_validate({"status": target.value, "summary": "Changed"})
    if source != target and target not in ALLOWED[source]:
        with pytest.raises(InvalidTestTaskStateError):
            update_test_task(session, row.id, data)
        assert (
            row.status,
            row.requested_at,
            row.started_at,
            row.finished_at,
            row.summary,
        ) == before
        session.rollback.assert_called_once()
        session.commit.assert_not_called()
        return
    result = update_test_task(session, row.id, data)
    assert result.status is target
    assert result.summary == "Changed" and result.requested_at == STAMP
    if source == target:
        assert (result.started_at, result.finished_at) == before[2:4]
    elif target is State.RUNNING:
        assert result.started_at is not None and result.started_at >= STAMP
        assert result.finished_at is None
    else:
        assert result.finished_at is not None and result.finished_at >= STAMP
        assert result.started_at == before[2]
    assert "FOR UPDATE" in str(session.scalar.call_args.args[0])
    session.commit.assert_called_once()
    session.refresh.assert_called_once_with(row)


@pytest.mark.parametrize("state", list(State))
def test_summary_only_preserves_lifecycle(state: State) -> None:
    row = stored_task(state)
    before = (row.status, row.requested_at, row.started_at, row.finished_at)
    session = MagicMock(spec=Session)
    session.scalar.return_value = row
    update_test_task(session, row.id, Update.model_validate({"summary": None}))
    assert row.summary is None
    assert (row.status, row.requested_at, row.started_at, row.finished_at) == before


def test_read_orm_utc_and_missing() -> None:
    row = stored_task()
    row.requested_at = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    result = Read.model_validate(row).model_dump(mode="json")
    assert result["requested_at"] == "2026-01-01T00:00:00Z"
    assert result["started_at"] is None and result["finished_at"] is None
    assert set(result) == {
        "id",
        "device_id",
        "name",
        "status",
        "requested_at",
        "started_at",
        "finished_at",
        "summary",
    }
    assert "device" not in row.__dict__
    row.requested_at = datetime(2026, 1, 1)
    with pytest.raises(ValidationError):
        Read.model_validate(row)
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    with pytest.raises(TaskNotFoundError):
        get_test_task(session, uuid4())
    session.commit.assert_not_called()
    assert "FOR UPDATE" not in str(session.scalar.call_args.args[0])


@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("failure_at", ["scalar", "commit", "refresh"])
def test_write_rolls_back_sql_errors(operation: str, failure_at: str) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = (
        stored_device() if operation == "create" else stored_task()
    )
    failure = OperationalError("PRIVATE_SQL", {}, RuntimeError("PRIVATE_SECRET"))
    getattr(session, failure_at).side_effect = failure
    with pytest.raises(OperationalError):
        if operation == "create":
            create_test_task(session, Create(device_id=uuid4(), name="Task"))
        else:
            update_test_task(session, uuid4(), Update.model_validate({"summary": None}))
    session.rollback.assert_called_once()
