"""T6 metadata registration and guarded PostgreSQL migration acceptance."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import Engine, Table, inspect, select, text
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import Session, joinedload

from alembic import command
from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.devices.model import Device
from app.telemetry.model import Telemetry
from tests.integration.test_devices import device_engine as device_engine

ROOT = Path(__file__).resolve().parents[2]


def test_alembic_registers_alert_without_test_imports() -> None:
    # A separate interpreter prevents tests' imports from hiding a missing env import.
    script = """
import json
import runpy
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from alembic import context
from alembic.config import Config
from pydantic import SecretStr
with (
    patch.object(context, "config", Config(), create=True),
    patch.object(context, "is_offline_mode", return_value=True),
    patch.object(context, "configure") as configure,
    patch.object(context, "begin_transaction", return_value=nullcontext()),
    patch.object(context, "run_migrations"),
    patch("app.core.config.get_settings", return_value=SimpleNamespace(
        database_url=SecretStr("postgresql+psycopg://localhost/unused"))),
):
    runpy.run_path("alembic/env.py")
    print(json.dumps(sorted(configure.call_args.kwargs["target_metadata"].tables)))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    assert json.loads(result.stdout) == [
        "alerts",
        "devices",
        "telemetry",
        "test_tasks",
        "users",
    ]


def test_alert_metadata_contract() -> None:
    table = Alert.__table__
    assert isinstance(table, Table)
    assert table.metadata is Device.metadata
    assert list(table.columns.keys()) == [
        "id",
        "device_id",
        "type",
        "severity",
        "status",
        "message",
        "triggered_at",
        "resolved_at",
    ]
    assert {c.name for c in table.columns if c.nullable} == {"resolved_at"}
    assert all(c.onupdate is None for c in table.columns)
    assert {v.value for v in AlertSeverity} == {"info", "warning", "critical"}
    assert {v.value for v in AlertStatus} == {"open", "acknowledged", "resolved"}
    assert table.c.id.default is not None and table.c.id.default.is_callable
    assert {i.name: tuple(c.name for c in i.columns) for i in table.indexes} == {
        "ix_alerts_device_id_triggered_at": ("device_id", "triggered_at"),
        "ix_alerts_status_triggered_at": ("status", "triggered_at"),
    }
    assert all(not i.unique for i in table.indexes)
    rel = inspect(Alert).relationships["device"]
    assert rel.lazy == "raise" and not rel.uselist
    assert "delete" not in rel.cascade and "delete-orphan" not in rel.cascade
    assert not inspect(Device).relationships


def test_alert_migration_and_constraints(device_engine: Engine) -> None:
    with device_engine.connect() as connection:
        assert "alerts" in inspect(connection).get_table_names(), (
            "head must create alerts"
        )
        assert {
            c["name"] for c in inspect(connection).get_check_constraints("alerts")
        } == {
            "ck_alerts_type_format",
            "ck_alerts_severity_valid",
            "ck_alerts_status_valid",
            "ck_alerts_message_non_empty",
            "ck_alerts_resolution_state",
            "ck_alerts_resolution_time",
        }
        assert not inspect(connection).get_unique_constraints("alerts")
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(device_engine) as session:
        device = Device(
            serial_number="T6-001", name="Sensor", model="M1", firmware_version="v1"
        )
        session.add(device)
        session.flush()
        device_id = device.id
        telemetry = Telemetry(
            device_id=device_id,
            metric="temperature",
            value=1,
            unit="C",
            recorded_at=stamp,
        )
        session.add(telemetry)
        session.commit()
        sample_id = telemetry.id
        alerts = [
            Alert(
                device_id=device_id,
                type="temperature_high",
                severity=severity,
                message="告警",
                triggered_at=stamp,
            )
            for severity in AlertSeverity
        ]
        session.add_all(alerts)
        session.commit()
        ids = [row.id for row in alerts]
        assert len(set(ids)) == 3
        assert all(
            row.status is AlertStatus.OPEN and row.resolved_at is None for row in alerts
        )
    with Session(device_engine) as session:
        row = session.get(Alert, ids[0])
        assert row is not None
        with pytest.raises(InvalidRequestError):
            _ = row.device
        loaded = session.scalar(
            select(Alert).where(Alert.id == ids[0]).options(joinedload(Alert.device))
        )
        assert loaded is not None and loaded.device.id == device_id
        session.delete(loaded)
        session.commit()
        assert session.get(Device, device_id) is not None
    statement = text(
        "INSERT INTO alerts "
        "(id, device_id, type, severity, status, message, triggered_at, resolved_at)"
        " VALUES (:id, :device_id, :type, :severity, :status, :message,"
        " :triggered_at, :resolved_at)"
    )
    invalid: list[dict[str, object]] = [
        {"severity": "INFO"},
        {"status": "bad"},
        {"type": "bad id"},
        {"message": ""},
        {"status": "resolved"},
        {"resolved_at": stamp},
        {"status": "acknowledged", "resolved_at": stamp},
        {"status": "resolved", "resolved_at": stamp - timedelta(seconds=1)},
        {"device_id": uuid4()},
        {"type": "x" * 65},
        {"message": "x" * 501},
    ]
    invalid += [
        {name: None}
        for name in (
            "id",
            "device_id",
            "type",
            "severity",
            "status",
            "message",
            "triggered_at",
        )
    ]
    with device_engine.connect() as connection:
        for changes in invalid:
            data: dict[str, object] = dict(
                id=uuid4(),
                device_id=device_id,
                type="temperature_high",
                severity="warning",
                status="open",
                message="Alert",
                triggered_at=stamp,
                resolved_at=None,
            )
            data.update(changes)
            with pytest.raises(DBAPIError):
                connection.execute(statement, data)
            connection.rollback()
        for state, resolved in (
            ("acknowledged", None),
            ("resolved", stamp),
            ("resolved", stamp + timedelta(seconds=1)),
        ):
            connection.execute(
                statement,
                dict(
                    id=uuid4(),
                    device_id=device_id,
                    type="temperature_high",
                    severity="critical",
                    status=state,
                    message="Alert",
                    triggered_at=stamp,
                    resolved_at=resolved,
                ),
            )
        connection.commit()
        with pytest.raises(DBAPIError) as caught:
            connection.execute(
                text("DELETE FROM devices WHERE id=:id"), {"id": device_id}
            )
        assert getattr(caught.value.orig, "sqlstate", None) == "23503"
        connection.rollback()
        device_before = connection.execute(
            text("SELECT * FROM devices WHERE id=:id"), {"id": device_id}
        ).one()
        sample_before = connection.execute(
            text("SELECT * FROM telemetry WHERE id=:id"), {"id": sample_id}
        ).one()
    config = Config("alembic.ini")
    device_engine.dispose()
    try:
        command.downgrade(config, "438be65e5187")
        with device_engine.connect() as connection:
            assert "alerts" not in inspect(connection).get_table_names()
            assert (
                connection.execute(
                    text("SELECT * FROM devices WHERE id=:id"), {"id": device_id}
                ).one()
                == device_before
            )
            assert (
                connection.execute(
                    text("SELECT * FROM telemetry WHERE id=:id"), {"id": sample_id}
                ).one()
                == sample_before
            )
        device_engine.dispose()
    finally:
        command.upgrade(config, "head")
    with device_engine.connect() as connection:
        assert "alerts" in inspect(connection).get_table_names()
        assert (
            connection.execute(
                text("SELECT * FROM devices WHERE id=:id"), {"id": device_id}
            ).one()
            == device_before
        )
        assert (
            connection.execute(
                text("SELECT * FROM telemetry WHERE id=:id"), {"id": sample_id}
            ).one()
            == sample_before
        )


def test_alert_defaults_times_and_independent_fk(device_engine: Engine) -> None:
    before = datetime.now(UTC)
    offset_time = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    with Session(device_engine) as session:
        device = Device(
            serial_number="T6-defaults",
            name="Sensor",
            model="M1",
            firmware_version="v1",
        )
        session.add(device)
        session.flush()
        device_id = device.id
        alert = Alert(
            device_id=device_id,
            type="battery_low",
            severity=AlertSeverity.WARNING,
            message="Low",
        )
        resolved = Alert(
            device_id=device_id,
            type="battery_low",
            severity=AlertSeverity.INFO,
            status=AlertStatus.RESOLVED,
            message="Resolved",
            triggered_at=offset_time,
            resolved_at=offset_time,
        )
        session.add_all([alert, resolved])
        session.commit()
        session.refresh(alert)
        session.refresh(resolved)
        assert before <= alert.triggered_at <= datetime.now(UTC)
        assert alert.status is AlertStatus.OPEN and alert.resolved_at is None
        assert resolved.triggered_at == datetime(2026, 1, 1, tzinfo=UTC)
        assert resolved.resolved_at == resolved.triggered_at
        original_time = alert.triggered_at
        alert.message = "Updated"
        session.commit()
        session.refresh(alert)
        assert alert.triggered_at == original_time and alert.resolved_at is None
    # This Device has no Telemetry children: only Alert can reject its deletion.
    with device_engine.connect() as connection:
        with pytest.raises(DBAPIError) as caught:
            connection.execute(
                text("DELETE FROM devices WHERE id=:id"), {"id": device_id}
            )
        assert getattr(caught.value.orig, "sqlstate", None) == "23503"
        assert getattr(
            getattr(caught.value.orig, "diag", None), "constraint_name", None
        ) == ("fk_alerts_device_id_devices")
        connection.rollback()
        raw = connection.execute(
            text(
                "INSERT INTO alerts (id, device_id, type, severity, message)"
                " VALUES (:id, :device_id, :type, 'critical', :message)"
                " RETURNING status, triggered_at, resolved_at"
            ),
            {
                "id": uuid4(),
                "device_id": device_id,
                "type": "x" * 64,
                "message": "中" * 500,
            },
        ).one()
        assert raw.status == "open" and raw.resolved_at is None
        assert raw.triggered_at.tzinfo is not None
        connection.rollback()
