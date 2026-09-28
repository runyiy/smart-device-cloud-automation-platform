"""T4 metadata, real constraints, relationships and reversible migration acceptance."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import (
    DateTime,
    DefaultClause,
    Double,
    Engine,
    String,
    Table,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.orm import Session, joinedload

from alembic import command
from app.devices.model import Device
from app.telemetry.model import Telemetry
from tests.integration.test_devices import device_engine as device_engine


def test_telemetry_metadata_contract() -> None:
    table = Telemetry.__table__
    assert isinstance(table, Table)
    assert table.metadata is Device.metadata
    assert list(table.columns.keys()) == [
        "id",
        "device_id",
        "metric",
        "value",
        "unit",
        "recorded_at",
        "received_at",
    ]
    assert all(not c.nullable and c.onupdate is None for c in table.columns)
    assert table.c.id.type.python_type is UUID
    assert table.c.id.default is not None
    assert table.c.id.default.is_callable and table.c.id.server_default is None
    for name in ("device_id", "metric", "value", "unit", "recorded_at"):
        assert table.c[name].default is None
        assert table.c[name].server_default is None
    assert isinstance(table.c.value.type, Double)
    assert isinstance(table.c.metric.type, String)
    assert isinstance(table.c.unit.type, String)
    assert table.c.metric.type.length == 64 and table.c.unit.type.length == 32
    assert isinstance(table.c.recorded_at.type, DateTime)
    assert isinstance(table.c.received_at.type, DateTime)
    assert table.c.recorded_at.type.timezone and table.c.received_at.type.timezone
    assert table.c.received_at.default is None
    assert isinstance(table.c.received_at.server_default, DefaultClause)
    assert str(table.c.received_at.server_default.arg) == "CURRENT_TIMESTAMP"
    fk = next(iter(table.foreign_keys))
    assert fk.target_fullname == "devices.id" and fk.ondelete == "RESTRICT"
    assert fk.onupdate is None
    assert fk.constraint is not None
    assert fk.constraint.name == "fk_telemetry_device_id_devices"
    assert {i.name: tuple(c.name for c in i.columns) for i in table.indexes} == {
        "ix_telemetry_device_id_recorded_at": ("device_id", "recorded_at"),
        "ix_telemetry_device_id_metric_recorded_at": (
            "device_id",
            "metric",
            "recorded_at",
        ),
    }
    assert all(not i.unique for i in table.indexes)
    rel = inspect(Telemetry).relationships["device"]
    assert not rel.uselist and rel.lazy == "raise"
    assert "delete" not in rel.cascade and "delete-orphan" not in rel.cascade
    assert not inspect(Device).relationships


def add_device(engine: Engine) -> UUID:
    with Session(engine) as session:
        device = Device(
            serial_number="T4-001",
            name="Sensor",
            model="M1",
            firmware_version="v1",
            status="inactive",
        )
        session.add(device)
        session.commit()
        return device.id


def test_telemetry_roundtrip_relationship_and_delete(device_engine: Engine) -> None:
    device_id = add_device(device_engine)
    stamp = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))
    with Session(device_engine) as session:
        samples = [
            Telemetry(
                device_id=device_id,
                metric="temperature",
                value=value,
                unit="°C",
                recorded_at=stamp,
            )
            for value in (-1.5, 0, 1.5)
        ]
        session.add_all(samples)
        session.commit()
        ids = [s.id for s in samples]
        assert len(set(ids)) == 3 and all(i.version == 4 for i in ids)
        for sample in samples:
            assert sample.recorded_at == stamp.astimezone(UTC)
            assert sample.received_at.tzinfo is not None
        original_received = samples[0].received_at
        samples[0].value = 2.0
        session.commit()
        session.refresh(samples[0])
        assert samples[0].recorded_at == stamp
        assert samples[0].received_at == original_received
    with Session(device_engine) as session:
        fetched = session.get(Telemetry, ids[0])
        assert fetched is not None
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            _ = fetched.device
        loaded = session.scalar(
            select(Telemetry)
            .where(Telemetry.id == ids[0])
            .options(joinedload(Telemetry.device))
        )
        assert loaded is not None
        assert loaded.device.id == device_id
        session.delete(loaded)
        session.commit()
        assert session.get(Device, device_id) is not None
    with device_engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM telemetry")) == 2


def test_telemetry_database_rejects_invalid_rows(device_engine: Engine) -> None:
    device_id = add_device(device_engine)
    cases: list[tuple[str, object, str]] = [
        (field, None, "23502")
        for field in (
            "id",
            "device_id",
            "metric",
            "value",
            "unit",
            "recorded_at",
            "received_at",
        )
    ]
    cases += [
        ("device_id", uuid4(), "23503"),
        ("metric", "", "23514"),
        ("metric", "bad id", "23514"),
        ("metric", "设备", "23514"),
        ("metric", "x\n", "23514"),
        ("metric", "x" * 65, "22001"),
        ("unit", "", "23514"),
        ("unit", "x" * 33, "22001"),
        ("value", float("nan"), "23514"),
        ("value", float("inf"), "23514"),
        ("value", float("-inf"), "23514"),
    ]
    statement = text(
        "INSERT INTO telemetry "
        "(id, device_id, metric, value, unit, recorded_at, received_at)"
        " VALUES (:id, :device_id, :metric, :value, :unit, :recorded_at, :received_at)"
    )
    with device_engine.connect() as connection:
        for field, value, code in cases:
            data = dict(
                id=uuid4(),
                device_id=device_id,
                metric="temperature",
                value=1.0,
                unit="°C",
                recorded_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
            )
            data[field] = value
            with pytest.raises(DBAPIError) as caught:
                connection.execute(statement, data)
            assert getattr(caught.value.orig, "sqlstate", None) == code, (field, value)
            connection.rollback()
        # Exercise maximum lengths and server-side receipt time without ORM defaults.
        connection.execute(
            text(
                "INSERT INTO telemetry "
                "(id, device_id, metric, value, unit, recorded_at)"
                " VALUES (:id, :device, :metric, 0, :unit, CURRENT_TIMESTAMP)"
            ),
            dict(id=uuid4(), device=device_id, metric="x" * 64, unit="中" * 32),
        )
        connection.commit()
        with pytest.raises(DBAPIError) as caught:
            connection.execute(
                text("DELETE FROM devices WHERE id = :id"), {"id": device_id}
            )
        assert getattr(caught.value.orig, "sqlstate", None) == "23503"
        connection.rollback()


def test_telemetry_migration_preserves_device_rows(device_engine: Engine) -> None:
    device_id = add_device(device_engine)
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["438be65e5187"]
    assert script.get_revision("438be65e5187").down_revision == "f4502b63c0be"
    with device_engine.connect() as connection:
        before = connection.execute(
            text("SELECT * FROM devices WHERE id=:id"), {"id": device_id}
        ).one()
        assert {
            c["name"] for c in inspect(connection).get_check_constraints("telemetry")
        } == {
            "ck_telemetry_metric_format",
            "ck_telemetry_value_finite",
            "ck_telemetry_unit_non_empty",
        }
        assert not inspect(connection).get_unique_constraints("telemetry")
    # Return to the previous head, then upgrade with pre-existing Device data.
    device_engine.dispose()
    try:
        command.downgrade(config, "f4502b63c0be")
        with device_engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {
                "devices",
                "alembic_version",
            }
            assert (
                connection.execute(
                    text("SELECT * FROM devices WHERE id=:id"), {"id": device_id}
                ).one()
                == before
            )
        device_engine.dispose()
    finally:
        command.upgrade(config, "head")
    with device_engine.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version"))
            == "438be65e5187"
        )
        assert (
            connection.execute(
                text("SELECT * FROM devices WHERE id=:id"), {"id": device_id}
            ).one()
            == before
        )
        assert "telemetry" in inspect(connection).get_table_names()
