"""T9 metadata and guarded PostgreSQL constraints/migration acceptance."""

from datetime import UTC, datetime, timedelta, timezone
from itertools import product
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Table, inspect, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import Session, joinedload

from alembic import command
from app.alerts.model import Alert, AlertSeverity
from app.db.base import Base
from app.devices.model import Device, DeviceStatus
from app.telemetry.model import Telemetry
from app.test_tasks.model import TestTask as DeviceTestTask
from app.test_tasks.model import TestTaskStatus as TaskStatus
from tests.integration.test_devices import device_engine as device_engine

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
CHECKS = {
    "ck_test_tasks_name_non_empty",
    "ck_test_tasks_status_valid",
    "ck_test_tasks_summary_non_empty",
    "ck_test_tasks_lifecycle_state",
    "ck_test_tasks_started_time",
    "ck_test_tasks_finished_time",
}
INSERT = text(
    "INSERT INTO test_tasks "
    "(id, device_id, name, status, requested_at, started_at, finished_at, summary) "
    "VALUES (:id, :device_id, :name, :status, :requested_at, :started_at, "
    ":finished_at, :summary)"
)


def seed(engine: Engine) -> UUID:
    with Session(engine) as session:
        device = Device(
            serial_number="T9-1",
            name="Sensor",
            model="M1",
            firmware_version="v1",
            status=DeviceStatus.INACTIVE,
        )
        session.add(device)
        session.commit()
        return device.id


def values(target_device_id: UUID, **overrides: object) -> dict[str, object]:
    return {
        "id": uuid4(),
        "device_id": target_device_id,
        "name": "Manual check",
        "status": "pending",
        "requested_at": STAMP,
        "started_at": None,
        "finished_at": None,
        "summary": None,
        **overrides,
    }


def test_model_contract() -> None:
    table = DeviceTestTask.__table__
    assert isinstance(table, Table) and table.metadata is Base.metadata
    assert list(table.columns.keys()) == [
        "id",
        "device_id",
        "name",
        "status",
        "requested_at",
        "started_at",
        "finished_at",
        "summary",
    ]
    assert {c.name for c in table.columns if c.nullable} == {
        "started_at",
        "finished_at",
        "summary",
    }
    assert all(c.onupdate is None for c in table.columns)
    assert table.c.id.default is not None and table.c.id.default.is_callable
    assert table.c.id.server_default is None
    assert table.c.status.default is not None
    assert getattr(table.c.status.default, "arg", None) is TaskStatus.PENDING
    assert table.c.status.server_default is not None
    assert str(getattr(table.c.status.server_default, "arg", None)) == "pending"
    assert table.c.requested_at.default is None
    assert table.c.requested_at.server_default is not None
    assert (
        str(getattr(table.c.requested_at.server_default, "arg", None))
        == "CURRENT_TIMESTAMP"
    )
    for name in ("device_id", "name", "started_at", "finished_at", "summary"):
        assert table.c[name].default is None and table.c[name].server_default is None
    assert {state.value for state in TaskStatus} == {
        "pending",
        "running",
        "passed",
        "failed",
        "cancelled",
    }
    assert {i.name: tuple(c.name for c in i.columns) for i in table.indexes} == {
        "ix_test_tasks_device_id_requested_at": ("device_id", "requested_at"),
        "ix_test_tasks_status_requested_at": ("status", "requested_at"),
    }
    assert all(not i.unique for i in table.indexes)
    rel = inspect(DeviceTestTask).relationships["device"]
    assert rel.lazy == "raise" and not rel.uselist
    assert "delete" not in rel.cascade and "delete-orphan" not in rel.cascade
    assert not inspect(Device).relationships


def test_actual_schema_and_defaults(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    with device_engine.connect() as connection:
        inspector = inspect(connection)
        assert {
            c["name"] for c in inspector.get_check_constraints("test_tasks")
        } == CHECKS
        assert inspector.get_pk_constraint("test_tasks")["name"] == "pk_test_tasks"
        assert not inspector.get_unique_constraints("test_tasks")
        fk = inspector.get_foreign_keys("test_tasks")
        assert len(fk) == 1 and fk[0]["name"] == "fk_test_tasks_device_id_devices"
        assert fk[0]["referred_table"] == "devices"
        assert fk[0]["options"]["ondelete"] == "RESTRICT"
        assert not connection.scalar(
            text(
                "SELECT count(*) FROM pg_type WHERE typname = 'testtaskstatus' "
                "AND typtype = 'e'"
            )
        )
        transaction_time = connection.scalar(text("SELECT CURRENT_TIMESTAMP"))
        raw = connection.execute(
            text(
                "INSERT INTO test_tasks (id, device_id, name) "
                "VALUES (:id, :device_id, 'Raw') RETURNING *"
            ),
            {"id": uuid4(), "device_id": device_id},
        ).one()
        assert raw.status == "pending" and raw.requested_at == transaction_time
        assert (
            raw.started_at is None and raw.finished_at is None and raw.summary is None
        )
        connection.rollback()
    with Session(device_engine) as session:
        # Duplicates and simultaneous running tasks are intentionally legal.
        rows = [DeviceTestTask(device_id=device_id, name="Same") for _ in range(2)]
        for state in TaskStatus:
            for _ in range(2):
                rows.append(
                    DeviceTestTask(
                        device_id=device_id,
                        name="Same",
                        status=state,
                        requested_at=STAMP,
                        started_at=STAMP if state is not TaskStatus.PENDING else None,
                        finished_at=STAMP
                        if state
                        in {TaskStatus.PASSED, TaskStatus.FAILED, TaskStatus.CANCELLED}
                        else None,
                    )
                )
        session.add_all(rows)
        session.commit()
        assert len({row.id for row in rows}) == len(rows)
        assert rows[0].status is TaskStatus.PENDING and rows[0].summary is None
        for row in rows:
            assert isinstance(row.status, TaskStatus)
            assert row.requested_at.utcoffset() is not None


def test_lifecycle_matrix_and_raw_sql_rejections(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    with device_engine.connect() as connection:
        for state, started, finished in product(
            TaskStatus, (False, True), (False, True)
        ):
            allowed = (
                (state is TaskStatus.PENDING and not started and not finished)
                or (state is TaskStatus.RUNNING and started and not finished)
                or (
                    state in {TaskStatus.PASSED, TaskStatus.FAILED}
                    and started
                    and finished
                )
                or (state is TaskStatus.CANCELLED and finished)
            )
            data = values(
                device_id,
                status=state.value,
                started_at=STAMP if started else None,
                finished_at=STAMP if finished else None,
            )
            if allowed:
                connection.execute(INSERT, data)
            else:
                with pytest.raises(DBAPIError) as caught:
                    connection.execute(INSERT, data)
                assert getattr(caught.value.orig, "sqlstate", None) == "23514"
                assert getattr(
                    getattr(caught.value.orig, "diag", None), "constraint_name", None
                ) == ("ck_test_tasks_lifecycle_state")
            connection.rollback()
        bad: list[tuple[dict[str, object], str]] = [
            ({"status": "PENDING"}, "23514"),
            ({"status": "unknown"}, "23514"),
            ({"status": ""}, "23514"),
            ({"name": ""}, "23514"),
            ({"name": "x" * 101}, "22001"),
            ({"summary": ""}, "23514"),
            ({"summary": "x" * 1001}, "22001"),
            ({"device_id": uuid4()}, "23503"),
            (
                {"status": "running", "started_at": STAMP - timedelta(seconds=1)},
                "23514",
            ),
            (
                {"status": "cancelled", "finished_at": STAMP - timedelta(seconds=1)},
                "23514",
            ),
            (
                {
                    "status": "passed",
                    "started_at": STAMP + timedelta(seconds=1),
                    "finished_at": STAMP,
                },
                "23514",
            ),
        ]
        bad.extend(
            ({field: None}, "23502")
            for field in ("id", "device_id", "name", "status", "requested_at")
        )
        for overrides, code in bad:
            with pytest.raises(DBAPIError) as caught:
                connection.execute(INSERT, values(device_id, **overrides))
            assert getattr(caught.value.orig, "sqlstate", None) == code
            connection.rollback()
        for name, summary in [("x", None), ("中" * 100, "文" * 1000), (" ", " ")]:
            connection.execute(INSERT, values(device_id, name=name, summary=summary))
        connection.rollback()
        duplicate = values(device_id)
        connection.execute(INSERT, duplicate)
        connection.commit()
        with pytest.raises(DBAPIError) as caught:
            connection.execute(INSERT, duplicate)
        assert getattr(caught.value.orig, "sqlstate", None) == "23505"
        connection.rollback()


def test_times_relationship_and_independent_fk(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    offset = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    with Session(device_engine) as session:
        row = DeviceTestTask(
            device_id=device_id,
            name="Task",
            status=TaskStatus.PASSED,
            requested_at=offset,
            started_at=offset,
            finished_at=offset,
            summary=None,
        )
        sibling = DeviceTestTask(device_id=device_id, name="Task")
        session.add_all([row, sibling])
        session.commit()
        row_id, sibling_id = row.id, sibling.id
        assert (row.requested_at, row.started_at, row.finished_at) == (STAMP,) * 3
        row.summary = "Updated"
        session.commit()
        session.refresh(row)
        assert (row.requested_at, row.started_at, row.finished_at) == (STAMP,) * 3
        with pytest.raises(InvalidRequestError):
            _ = row.device
        loaded = session.scalar(
            select(DeviceTestTask)
            .where(DeviceTestTask.id == row_id)
            .options(joinedload(DeviceTestTask.device))
        )
        assert loaded is not None and loaded.device.id == device_id
    # No Alert/Telemetry children exist: this FK must independently protect Device.
    with device_engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            connection.execute(
                text("DELETE FROM devices WHERE id=:id"), {"id": device_id}
            )
        assert getattr(caught.value.orig, "sqlstate", None) == "23503"
        assert getattr(
            getattr(caught.value.orig, "diag", None), "constraint_name", None
        ) == ("fk_test_tasks_device_id_devices")
        connection.rollback()
    with Session(device_engine) as session:
        target = session.get(DeviceTestTask, row_id)
        assert target is not None
        session.delete(target)
        session.commit()
        assert session.get(Device, device_id) is not None
        assert session.get(DeviceTestTask, sibling_id) is not None


def test_new_migration_round_trip_preserves_previous_data(
    device_engine: Engine,
) -> None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1
    revision = script.get_revision("237c5f37c6c2")
    assert revision is not None and revision.down_revision == "68cc8b7ce48b"
    device_id = seed(device_engine)
    with Session(device_engine) as session:
        session.add(
            Telemetry(
                device_id=device_id,
                metric="temperature",
                value=90,
                unit="°C",
                recorded_at=STAMP,
            )
        )
        session.add(
            Alert(
                device_id=device_id,
                type="temperature_high",
                severity=AlertSeverity.CRITICAL,
                message="Existing",
            )
        )
        session.commit()
    tables = ("devices", "telemetry", "alerts")
    with device_engine.connect() as connection:
        before = {
            table: connection.execute(text(f"SELECT * FROM {table}")).all()
            for table in tables
        }
    device_engine.dispose()
    try:
        command.downgrade(config, "68cc8b7ce48b")
        command.upgrade(config, "head")
        with Session(device_engine) as session:
            session.add(
                DeviceTestTask(device_id=device_id, name="Discard on downgrade")
            )
            session.commit()
        device_engine.dispose()
        command.downgrade(config, "68cc8b7ce48b")
        with device_engine.connect() as connection:
            assert "test_tasks" not in inspect(connection).get_table_names()
            for table in tables:
                assert (
                    connection.execute(text(f"SELECT * FROM {table}")).all()
                    == before[table]
                )
        device_engine.dispose()
    finally:
        command.upgrade(config, "head")
    with device_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == script.get_current_head()
        )
        assert connection.scalar(text("SELECT count(*) FROM test_tasks")) == 0
        for table in tables:
            assert (
                connection.execute(text(f"SELECT * FROM {table}")).all()
                == before[table]
            )
