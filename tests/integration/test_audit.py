"""V2-T7 audit constraints, atomicity, FK concurrency and migration acceptance."""

import json
from datetime import UTC, datetime
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, Table, func, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session

from alembic import command
from app.alerts.model import Alert, AlertSeverity
from app.audit.model import AuditLog
from app.audit.repository import AuditLogRepository
from app.db.base import Base
from app.db.transaction import transaction
from app.devices.model import Device
from app.telemetry.model import Telemetry
from app.test_tasks.model import TestTask as Task
from app.users.model import User, UserRole
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_task_t10 import STAMP, seed

HEAD = "585f640ecf98"
PARENT = "ba759824c979"
INSERT = text(
    "INSERT INTO audit_logs "
    "(id, actor_id, action, resource_type, resource_id, metadata, created_at) "
    "VALUES (:id, :actor_id, :action, :resource_type, :resource_id, "
    "CAST(:metadata AS jsonb), :created_at)"
)


@pytest.fixture
def actor_id(device_engine: Engine) -> UUID:
    # Persistence accepts a real actor regardless of application auth eligibility.
    with Session(device_engine) as session:
        user = User(
            email="audit@example.test",
            password_hash="opaque",
            role=UserRole.VIEWER,
            is_active=False,
        )
        session.add(user)
        session.commit()
        return user.id


def event(actor_id: UUID, resource_id: UUID | None = None) -> AuditLog:
    return AuditLog(
        actor_id=actor_id,
        action="Device.updated",
        resource_type="device",
        resource_id=resource_id if resource_id is not None else uuid4(),
    )


def audit_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(AuditLog)) or 0)


def test_migrated_audit_schema_matches_registered_metadata(
    device_engine: Engine,
) -> None:
    with device_engine.connect() as connection:
        inspector = inspect(connection)
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        )
        assert (
            compare_metadata(
                MigrationContext.configure(
                    connection, opts={"compare_server_default": True}
                ),
                Base.metadata,
            )
            == []
        )
        columns = inspector.get_columns("audit_logs")
        assert {c["name"] for c in columns} == {
            "id",
            "actor_id",
            "action",
            "resource_type",
            "resource_id",
            "metadata",
            "created_at",
        }
        assert all(not c["nullable"] for c in columns)
        assert {c["name"] for c in inspector.get_check_constraints("audit_logs")} == {
            "ck_audit_logs_action_valid",
            "ck_audit_logs_resource_type_valid",
            "ck_audit_logs_metadata_object",
        }
        (foreign_key,) = inspector.get_foreign_keys("audit_logs")
        assert foreign_key["name"] == "fk_audit_logs_actor_id_users"
        assert foreign_key["constrained_columns"] == ["actor_id"]
        assert foreign_key["referred_table"] == "users"
        assert foreign_key["referred_columns"] == ["id"]
        assert foreign_key["options"]["ondelete"] == "RESTRICT"
        (index,) = inspector.get_indexes("audit_logs")
        assert index["name"] == "ix_audit_logs_actor_id"
        assert index["column_names"] == ["actor_id"] and not index["unique"]
        assert not inspector.get_unique_constraints("audit_logs")


@pytest.mark.parametrize("resource_type", ["device", "telemetry", "alert", "test_task"])
def test_defaults_json_roundtrip_and_polymorphic_resource(
    device_engine: Engine,
    actor_id: UUID,
    resource_type: str,
) -> None:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "fields": ["name"],
        "nested": {"ok": True, "absent": None, "count": 3},
        "label": "温度",
    }
    with Session(device_engine, expire_on_commit=False) as session:
        repo = AuditLogRepository(session)
        first, second, nested = event(actor_id), event(actor_id), event(actor_id)
        nested.resource_type = resource_type
        nested.action = "A" * 64
        nested.event_metadata = payload
        with transaction(session):
            for row in (first, second, nested):
                repo.add(row)
        assert len({row.id for row in (first, second, nested)}) == 3
        assert all(row.id.version == 4 for row in (first, second, nested))
        assert first.action == "Device.updated"
        assert first.event_metadata == second.event_metadata == {}
        assert first.event_metadata is not second.event_metadata
        assert first.created_at.utcoffset() is not None
        assert now <= first.created_at <= datetime.now(UTC)
        first_id, nested_id = first.id, nested.id
    with Session(device_engine) as observer:
        persisted = observer.get(AuditLog, nested_id)
        assert persisted is not None and persisted.event_metadata == payload
        assert persisted.resource_type == resource_type
        assert observer.get(AuditLog, first_id) is not None
        # UUID snapshots need no corresponding row in any business table.
        for model in (Device, Telemetry, Alert, Task):
            assert observer.get(model, persisted.resource_id) is None
    raw_id = uuid4()
    with device_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO audit_logs "
                "(id, actor_id, action, resource_type, resource_id) "
                "VALUES (:id, :actor_id, 'x', :resource_type, :resource_id)"
            ),
            {
                "id": raw_id,
                "actor_id": actor_id,
                "resource_type": resource_type,
                "resource_id": uuid4(),
            },
        )
    with Session(device_engine) as observer:
        raw = observer.get(AuditLog, raw_id)
        assert raw is not None and raw.event_metadata == {}
        assert raw.created_at.utcoffset() is not None


INVALID: list[tuple[str, object, str]] = [
    ("action", "", "23514"),
    ("action", " ", "23514"),
    ("action", "\t\n", "23514"),
    ("action", "valid\n", "23514"),
    ("action", "审计", "23514"),
    ("action", "x" * 65, "22001"),
    ("resource_type", "", "23514"),
    ("resource_type", "DEVICE", "23514"),
    ("resource_type", "unknown", "23514"),
    ("event_metadata", [], "23514"),
    ("event_metadata", "text", "23514"),
    ("event_metadata", 1, "23514"),
    ("event_metadata", True, "23514"),
    ("event_metadata", None, "23514"),
]


@pytest.mark.parametrize("mode", ["orm", "sql"])
@pytest.mark.parametrize("field,value,state", INVALID)
def test_object_action_resource_constraints(
    device_engine: Engine,
    actor_id: UUID,
    mode: str,
    field: str,
    value: object,
    state: str,
) -> None:
    with Session(device_engine) as session:
        with pytest.raises(DBAPIError) as caught:
            with transaction(session):
                if mode == "orm":
                    row = event(actor_id)
                    setattr(row, field, value)
                    AuditLogRepository(session).add(row)
                else:
                    values: dict[str, object] = {
                        "id": uuid4(),
                        "actor_id": actor_id,
                        "action": "device.updated",
                        "resource_type": "device",
                        "resource_id": uuid4(),
                        "metadata": "{}",
                        "created_at": STAMP,
                    }
                    if field == "event_metadata":
                        values["metadata"] = json.dumps(value)
                    else:
                        values[field] = value
                    session.execute(INSERT, values)
        assert getattr(caught.value.orig, "sqlstate", None) == state
        if state == "23514":
            expected = {
                "action": "ck_audit_logs_action_valid",
                "resource_type": "ck_audit_logs_resource_type_valid",
                "event_metadata": "ck_audit_logs_metadata_object",
            }[field]
            assert (
                getattr(
                    getattr(caught.value.orig, "diag", None), "constraint_name", None
                )
                == expected
            )
        assert not session.in_transaction()
        with Session(device_engine) as observer:
            assert audit_count(observer) == 0


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "actor_id",
        "action",
        "resource_type",
        "resource_id",
        "metadata",
        "created_at",
    ],
)
def test_raw_sql_not_null_contract(
    device_engine: Engine,
    actor_id: UUID,
    field: str,
) -> None:
    values: dict[str, object] = {
        "id": uuid4(),
        "actor_id": actor_id,
        "action": "device.updated",
        "resource_type": "device",
        "resource_id": uuid4(),
        "metadata": "{}",
        "created_at": STAMP,
    }
    values[field] = None
    with device_engine.connect() as connection:
        with pytest.raises(IntegrityError) as caught:
            connection.execute(INSERT, values)
        assert getattr(caught.value.orig, "sqlstate", None) == "23502"
        connection.rollback()


def test_unknown_actor_duplicate_id_and_delete_restrict(
    device_engine: Engine,
    actor_id: UUID,
) -> None:
    with Session(device_engine) as session:
        with pytest.raises(IntegrityError) as caught:
            with transaction(session):
                AuditLogRepository(session).add(event(uuid4()))
        assert getattr(caught.value.orig, "sqlstate", None) == "23503"
        row = event(actor_id)
        with transaction(session):
            AuditLogRepository(session).add(row)
        row_id = row.id
    with device_engine.begin() as connection:
        with pytest.raises(IntegrityError) as duplicate:
            connection.execute(
                INSERT,
                {
                    "id": row_id,
                    "actor_id": actor_id,
                    "action": "device.updated",
                    "resource_type": "device",
                    "resource_id": uuid4(),
                    "metadata": "{}",
                    "created_at": STAMP,
                },
            )
        assert getattr(duplicate.value.orig, "sqlstate", None) == "23505"
        connection.rollback()
    with device_engine.connect() as connection:
        with pytest.raises(IntegrityError) as restricted:
            connection.execute(text("DELETE FROM users WHERE id=:id"), {"id": actor_id})
        assert getattr(restricted.value.orig, "sqlstate", None) == "23503"
        connection.rollback()
    with Session(device_engine) as observer:
        assert observer.get(User, actor_id) is not None
        assert observer.get(AuditLog, row_id) is not None


def test_successful_caller_transaction_commits_business_and_event_once(
    device_engine: Engine,
    actor_id: UUID,
) -> None:
    device_id, _ = seed(device_engine)
    with Session(device_engine) as owner:
        device = owner.get(Device, device_id)
        assert device is not None
        row = event(actor_id, device_id)
        with (
            patch.object(owner, "commit", wraps=owner.commit) as commits,
            patch.object(owner, "rollback", wraps=owner.rollback) as rollbacks,
        ):
            with transaction(owner):
                device.name = "Committed"
                AuditLogRepository(owner).add(row)
                owner.flush()
                with Session(device_engine) as observer:
                    visible = observer.get(Device, device_id)
                    assert visible is not None and visible.name == "Device"
                    assert audit_count(observer) == 0
            assert commits.call_count == 1 and rollbacks.call_count == 0
    with Session(device_engine) as observer:
        visible = observer.get(Device, device_id)
        assert visible is not None and visible.name == "Committed"
        persisted = observer.scalar(select(AuditLog))
        assert persisted is not None and persisted.resource_id == device_id


@pytest.mark.parametrize("failure", ["body", "flush", "commit", "serialization"])
def test_failure_rolls_back_business_and_audit_and_session_recovers(
    device_engine: Engine,
    actor_id: UUID,
    failure: str,
) -> None:
    device_id, _ = seed(device_engine)
    with Session(device_engine) as owner:
        device = owner.get(Device, device_id)
        assert device is not None
        row = event(actor_id, device_id)
        if failure in {"flush", "commit"}:
            row.action = ""
        elif failure == "serialization":
            row.event_metadata = {"invalid": object()}
        expected = {"body": RuntimeError, "serialization": TypeError}.get(
            failure, IntegrityError
        )
        with (
            patch.object(owner, "commit", wraps=owner.commit) as commits,
            patch.object(owner, "rollback", wraps=owner.rollback) as rollbacks,
        ):
            with pytest.raises(expected):
                with transaction(owner):
                    device.name = "Must roll back"
                    AuditLogRepository(owner).add(row)
                    if failure != "commit":
                        owner.flush()
                    if failure == "body":
                        raise RuntimeError("injected body failure")
            assert commits.call_count == (1 if failure == "commit" else 0)
            assert rollbacks.call_count == 1 and not owner.in_transaction()
        with Session(device_engine) as observer:
            visible = observer.get(Device, device_id)
            assert visible is not None and visible.name == "Device"
            assert audit_count(observer) == 0
        with transaction(owner):
            AuditLogRepository(owner).add(event(actor_id, device_id))
    with Session(device_engine) as observer:
        assert audit_count(observer) == 1


def test_actor_delete_contends_with_pending_event_then_remains_restricted(
    device_engine: Engine,
    actor_id: UUID,
) -> None:
    with Session(device_engine) as owner, Session(device_engine) as contender:
        row = event(actor_id)
        AuditLogRepository(owner).add(row)
        owner.flush()
        contender.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as blocked:
            contender.execute(text("DELETE FROM users WHERE id=:id"), {"id": actor_id})
        assert getattr(blocked.value.orig, "sqlstate", None) == "55P03"
        contender.rollback()
        owner.commit()
        with pytest.raises(IntegrityError) as restricted:
            contender.execute(text("DELETE FROM users WHERE id=:id"), {"id": actor_id})
        assert getattr(restricted.value.orig, "sqlstate", None) == "23503"
        contender.rollback()
    with Session(device_engine) as observer:
        assert observer.get(User, actor_id) is not None and audit_count(observer) == 1


def test_additive_migration_preserves_users_and_all_business_rows(
    device_engine: Engine,
    actor_id: UUID,
) -> None:
    device_id, _ = seed(device_engine)
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
        AuditLogRepository(session).add(event(actor_id, device_id))
        session.commit()
    tables = [
        cast(Table, model.__table__) for model in (User, Device, Telemetry, Alert, Task)
    ]

    def snapshot() -> dict[str, list[tuple[object, ...]]]:
        with device_engine.connect() as connection:
            return {
                table.name: [
                    tuple(row)
                    for row in connection.execute(select(table).order_by(table.c.id))
                ]
                for table in tables
            }

    before = snapshot()
    config = Config("alembic.ini")
    device_engine.dispose()
    try:
        command.downgrade(config, PARENT)
        with device_engine.connect() as connection:
            assert not inspect(connection).has_table("audit_logs")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == PARENT
            )
        assert snapshot() == before
        device_engine.dispose()
    finally:
        command.upgrade(config, "head")
    assert snapshot() == before
    with device_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        )
        assert connection.scalar(text("SELECT count(*) FROM audit_logs")) == 0
        assert (
            compare_metadata(
                MigrationContext.configure(
                    connection, opts={"compare_server_default": True}
                ),
                Base.metadata,
            )
            == []
        )
