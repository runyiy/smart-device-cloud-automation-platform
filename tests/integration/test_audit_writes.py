"""V2-T8 guarded PostgreSQL mappings, rollback and fresh-state acceptance."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from threading import Barrier
from typing import cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.alerts.service import acknowledge_alert, resolve_alert
from app.audit.model import AuditLog
from app.audit.repository import AuditLogRepository
from app.core.config import Settings
from app.devices.model import Device
from app.devices.schema import DeviceCreate, DeviceUpdate
from app.devices.service import create_device, update_device
from app.main import create_app
from app.telemetry.model import Telemetry
from app.telemetry.schema import TelemetryCreate
from app.telemetry.service import ingest_telemetry
from app.test_tasks.model import TestTask as Task
from app.test_tasks.schema import TestTaskCreate as Create
from app.test_tasks.schema import TestTaskUpdate as Update
from app.test_tasks.service import create_test_task, update_test_task
from app.users.model import User
from tests.api.test_rbac import CASES, Case, request_case
from tests.integration.test_devices import device_engine as device_engine
from tests.rbac_support import admin_test_client

OPERATIONS = [
    "device.created",
    "device.updated",
    "telemetry.ingested",
    "alert.acknowledged",
    "alert.resolved",
    "test_task.created",
    "test_task.updated",
]
STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def seed(engine: Engine) -> tuple[UUID, UUID, UUID, UUID]:
    with Session(engine) as session:
        actor = User(email="t8@example.test", password_hash="opaque")
        device = Device(
            serial_number="AUDIT-SEED",
            name="Original",
            model="M",
            firmware_version="v1",
        )
        session.add_all([actor, device])
        session.flush()
        alert = Alert(
            device_id=device.id,
            type="test",
            severity=AlertSeverity.WARNING,
            message="Private alert",
            triggered_at=STAMP,
        )
        task = Task(
            device_id=device.id,
            name="Private task",
            summary="Private summary",
            requested_at=STAMP,
        )
        session.add_all([alert, task])
        session.flush()
        session.add(
            AuditLog(
                actor_id=actor.id,
                action="device.created",
                resource_type="device",
                resource_id=device.id,
                event_metadata={},
            )
        )
        session.commit()
        return actor.id, device.id, alert.id, task.id


def invoke(
    action: str,
    session: Session,
    ids: tuple[UUID, UUID, UUID, UUID],
    *,
    actor_id: UUID | None = None,
) -> Device | Telemetry | Alert | Task:
    actor, device, alert, task = ids
    actor = actor if actor_id is None else actor_id
    if action == "device.created":
        return create_device(
            session,
            DeviceCreate(
                serial_number="AUDIT-NEW",
                name="Private new",
                model="M",
                firmware_version="v1",
            ),
            actor_id=actor,
        )
    if action == "device.updated":
        return update_device(
            session, device, DeviceUpdate(name="Private renamed"), actor_id=actor
        )
    if action == "telemetry.ingested":
        return ingest_telemetry(
            session,
            device,
            TelemetryCreate(
                metric="temperature", value=90, unit="°C", recorded_at=STAMP
            ),
            actor_id=actor,
        )
    if action == "alert.acknowledged":
        return acknowledge_alert(session, alert, actor_id=actor)
    if action == "alert.resolved":
        return resolve_alert(session, alert, actor_id=actor)
    if action == "test_task.created":
        return create_test_task(
            session, Create(device_id=device, name="Private new task"), actor_id=actor
        )
    if action == "test_task.updated":
        return update_test_task(
            session, task, Update.model_validate({"summary": None}), actor_id=actor
        )
    raise AssertionError(action)


def snapshot(engine: Engine) -> list[list[str]]:
    with engine.connect() as connection:
        return [
            sorted(
                repr(tuple(row)) for row in connection.execute(select(model.__table__))
            )
            for model in (User, Device, Telemetry, Alert, Task, AuditLog)
        ]


@pytest.mark.parametrize("action", OPERATIONS)
def test_seven_exact_durable_event_mappings(device_engine: Engine, action: str) -> None:
    ids = seed(device_engine)
    with Session(device_engine) as session:
        with patch.object(session, "commit", wraps=session.commit) as commit:
            row = invoke(action, session, ids)
        commit.assert_called_once_with()
        resource_id = row.id
    with Session(device_engine) as observer:
        rows = list(observer.scalars(select(AuditLog)))
        assert len(rows) == 2
        audit = next(
            r
            for r in rows
            if r.resource_id == resource_id
            and (r.action != "device.created" or resource_id != ids[1])
        )
        expected: dict[str, dict[str, object]] = {
            "device.created": {},
            "device.updated": {"fields": ["name"], "changed": True},
            "telemetry.ingested": {"device_id": str(ids[1]), "alert_generated": True},
            "alert.acknowledged": {
                "from_status": "open",
                "to_status": "acknowledged",
                "changed": True,
            },
            "alert.resolved": {
                "from_status": "open",
                "to_status": "resolved",
                "changed": True,
            },
            "test_task.created": {"device_id": str(ids[1])},
            "test_task.updated": {
                "fields": ["summary"],
                "from_status": "pending",
                "to_status": "pending",
                "changed": True,
            },
        }
        assert audit.actor_id == ids[0] and audit.action == action
        assert audit.resource_type == action.split(".")[0]
        assert audit.event_metadata == expected[action]
        assert resource_id is not None
        if action == "telemetry.ingested":
            assert resource_id != ids[1]
            assert len(list(observer.scalars(select(Alert)))) == 2
            device = observer.get(Device, ids[1])
            assert device is not None and device.last_seen_at == STAMP


@pytest.mark.parametrize("action", OPERATIONS)
@pytest.mark.parametrize("failure", ["add", "serialization", "fk", "flush", "commit"])
def test_precommit_failure_rolls_back_all_effects_and_preserves_history(
    device_engine: Engine,
    action: str,
    failure: str,
) -> None:
    ids = seed(device_engine)
    before = snapshot(device_engine)
    original = AuditLogRepository.add

    def bad_metadata(repo: AuditLogRepository, row: AuditLog) -> None:
        row.event_metadata = {"bad": object()}
        original(repo, row)

    with Session(device_engine) as session:
        seam: AbstractContextManager[object]
        if failure == "add":
            seam = patch.object(
                AuditLogRepository, "add", side_effect=RuntimeError("private audit")
            )
        elif failure == "serialization":
            seam = patch.object(AuditLogRepository, "add", new=bad_metadata)
        elif failure in {"flush", "commit"}:
            seam = patch.object(
                session, failure, side_effect=SQLAlchemyError("private database")
            )
        else:
            seam = patch.object(AuditLogRepository, "add", new=original)
        with seam, pytest.raises((RuntimeError, SQLAlchemyError, TypeError)):
            invoke(action, session, ids, actor_id=uuid4() if failure == "fk" else None)
        assert not session.in_transaction()
        assert session.scalar(select(User.id)) == ids[0]
    assert snapshot(device_engine) == before


@pytest.mark.parametrize("action", OPERATIONS)
def test_refresh_failure_keeps_committed_business_and_audit(
    device_engine: Engine,
    action: str,
) -> None:
    ids = seed(device_engine)
    before = snapshot(device_engine)
    with Session(device_engine) as session:
        with patch.object(
            session, "refresh", side_effect=SQLAlchemyError("readback private")
        ):
            with pytest.raises(SQLAlchemyError):
                invoke(action, session, ids)
        assert not session.in_transaction()
    with Session(device_engine) as observer:
        assert len(list(observer.scalars(select(AuditLog)))) == 2
    assert snapshot(device_engine)[:-1] != before[:-1]


def test_noop_patches_and_idempotent_alerts_record_every_invocation(
    device_engine: Engine,
) -> None:
    ids = seed(device_engine)
    with Session(device_engine) as session:
        update_device(session, ids[1], DeviceUpdate(name="Original"), actor_id=ids[0])
        update_test_task(
            session, ids[3], Update(summary="Private summary"), actor_id=ids[0]
        )
        acknowledge_alert(session, ids[2], actor_id=ids[0])
        acknowledge_alert(session, ids[2], actor_id=ids[0])
        resolve_alert(session, ids[2], actor_id=ids[0])
        first = session.get(Alert, ids[2])
        assert first is not None
        timestamp = first.resolved_at
        resolve_alert(session, ids[2], actor_id=ids[0])
        assert first.resolved_at == timestamp
    with Session(device_engine) as observer:
        rows = list(observer.scalars(select(AuditLog).order_by(AuditLog.created_at)))
        assert len(rows) == 7
        assert [r.event_metadata.get("changed") for r in rows[1:]] == [
            False,
            False,
            True,
            False,
            True,
            False,
        ]
        assert rows[-1].action == rows[-2].action == "alert.resolved"


def test_concurrent_acknowledge_metadata_uses_fresh_locked_state(
    device_engine: Engine,
) -> None:
    ids = seed(device_engine)
    barrier = Barrier(2, timeout=10)

    def worker() -> None:
        with Session(device_engine, expire_on_commit=False) as session:
            cached = session.get(Alert, ids[2])
            assert cached is not None and cached.status is AlertStatus.OPEN
            barrier.wait()
            acknowledge_alert(session, ids[2], actor_id=ids[0])

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=20)
    with Session(device_engine) as observer:
        rows = list(
            observer.scalars(
                select(AuditLog).where(AuditLog.action == "alert.acknowledged")
            )
        )
        assert len(rows) == 2
        assert sorted(cast(bool, r.event_metadata["changed"]) for r in rows) == [
            False,
            True,
        ]
        assert sorted(cast(str, r.event_metadata["from_status"]) for r in rows) == [
            "acknowledged",
            "open",
        ]


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if c.method != "GET"],
    ids=lambda case: case.method + case.path,
)
def test_real_jwt_http_write_attribution_and_unchanged_response(
    device_engine: Engine,
    case: Case,
) -> None:
    ids = seed(device_engine)
    settings = Settings(
        _env_file=None,
        database_url=device_engine.url.render_as_string(hide_password=False),
    )
    app = create_app(settings)
    with admin_test_client(app, device_engine, raise_server_exceptions=False) as client:
        response = request_case(
            client,
            case,
            ids={
                "device_id": str(ids[1]),
                "alert_id": str(ids[2]),
                "task_id": str(ids[3]),
            },
        )
    assert response.status_code == case.success
    resource_id = UUID(response.json()["id"])
    with Session(device_engine) as observer:
        actor = observer.scalar(
            select(User).where(User.email == "legacy-admin@example.test")
        )
        assert actor is not None
        events = list(
            observer.scalars(select(AuditLog).where(AuditLog.actor_id == actor.id))
        )
        assert len(events) == 1
        event = events[0]
        assert event.resource_id == resource_id
        action = {
            ("POST", "/devices"): "device.created",
            ("PATCH", "/devices/{device_id}"): "device.updated",
            ("POST", "/devices/{device_id}/telemetry"): "telemetry.ingested",
            ("POST", "/alerts/{alert_id}/acknowledge"): "alert.acknowledged",
            ("POST", "/alerts/{alert_id}/resolve"): "alert.resolved",
            ("POST", "/test-tasks"): "test_task.created",
            ("PATCH", "/test-tasks/{task_id}"): "test_task.updated",
        }[(case.method, case.path)]
        assert event.action == action
        assert (
            "event_metadata" not in response.json()
            and "actor_id" not in response.json()
        )


def test_http_validation_domain_and_read_paths_produce_no_audit(
    device_engine: Engine,
) -> None:
    ids = seed(device_engine)
    settings = Settings(
        _env_file=None,
        database_url=device_engine.url.render_as_string(hide_password=False),
    )
    app = create_app(settings)
    with admin_test_client(app, device_engine, raise_server_exceptions=False) as client:
        before = snapshot(device_engine)
        assert client.get("/api/v1/devices").status_code == 200
        assert client.get("/api/v1/alerts").status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 200
        assert (
            client.post(
                "/api/v1/devices",
                json={
                    "serial_number": "AUDIT-SEED",
                    "name": "Private duplicate",
                    "model": "M",
                    "firmware_version": "v1",
                },
            ).status_code
            == 409
        )
        assert (
            client.patch(
                "/api/v1/devices/" + str(uuid4()), json={"name": "Missing"}
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/api/v1/devices/" + str(ids[1]),
                json={
                    "name": "Spoof",
                    "actor_id": str(ids[1]),
                },
            ).status_code
            == 422
        )
    assert snapshot(device_engine) == before


@pytest.mark.parametrize("value", [80.0, 79.0])
def test_nonthreshold_ingestion_has_one_event_and_no_extra_alert(
    device_engine: Engine,
    value: float,
) -> None:
    ids = seed(device_engine)
    with Session(device_engine) as session:
        row = ingest_telemetry(
            session,
            ids[1],
            TelemetryCreate(
                metric="temperature",
                value=value,
                unit="°C",
                recorded_at=STAMP,
            ),
            actor_id=ids[0],
        )
        resource_id = row.id
    with Session(device_engine) as observer:
        rows = list(
            observer.scalars(
                select(AuditLog).where(AuditLog.action == "telemetry.ingested")
            )
        )
        assert len(rows) == 1
        assert rows[0].resource_id == resource_id
        assert rows[0].event_metadata == {
            "device_id": str(ids[1]),
            "alert_generated": False,
        }
        assert len(list(observer.scalars(select(Alert)))) == 1


def test_mixed_supplied_fields_and_repeated_null_clearing_metadata(
    device_engine: Engine,
) -> None:
    ids = seed(device_engine)
    with Session(device_engine) as session:
        device_patch = DeviceUpdate.model_validate(
            {
                "status": "active",
                "name": "Original",
                "firmware_version": "Private firmware",
            }
        )
        task_patch = Update.model_validate({"status": "pending", "summary": None})
        for _ in range(2):
            update_device(session, ids[1], device_patch, actor_id=ids[0])
            update_test_task(session, ids[3], task_patch, actor_id=ids[0])
    with Session(device_engine) as observer:
        rows = list(
            observer.scalars(
                select(AuditLog)
                .where(AuditLog.action.in_(["device.updated", "test_task.updated"]))
                .order_by(AuditLog.created_at)
            )
        )
        assert len(rows) == 4
        for row, changed in zip(rows, [True, True, False, False], strict=True):
            expected: dict[str, object]
            if row.action == "device.updated":
                expected = {
                    "fields": ["firmware_version", "name", "status"],
                    "changed": changed,
                }
            else:
                expected = {
                    "fields": ["status", "summary"],
                    "changed": changed,
                    "from_status": "pending",
                    "to_status": "pending",
                }
            assert row.event_metadata == expected
