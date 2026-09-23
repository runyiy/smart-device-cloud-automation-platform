"""Device persistence acceptance against the migrated, disposable PostgreSQL DB."""

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.devices.model import Device, DeviceStatus
from tests.integration.test_migrations import reset_test_database


@pytest.fixture
def device_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Use real migrations, never create_all; reset only the authorized test schema."""
    if os.getenv("RUN_MIGRATION_TESTS") != "1":
        pytest.skip("set RUN_MIGRATION_TESTS=1 for Device database acceptance")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("SETTINGS_FILE", ".env.test")
    get_settings.cache_clear()
    engine: Engine | None = None
    try:
        settings = Settings(_env_file=".env.test")
        url = reset_test_database(settings)
        command.upgrade(Config("alembic.ini"), "head")
        engine = create_engine(
            url,
            connect_args={
                "connect_timeout": 5,
                "options": "-c statement_timeout=5000 -c lock_timeout=5000",
            },
        )
        yield engine
    finally:
        if engine is not None:
            try:
                with engine.begin() as connection:
                    connection.execute(text("DELETE FROM devices"))
            finally:
                engine.dispose()
        get_settings.cache_clear()


def test_device_metadata_contract() -> None:
    """Fast checks still execute when PostgreSQL acceptance is not opted in."""
    table = Device.__table__
    assert Device.metadata is Base.metadata
    assert list(table.columns.keys()) == [
        "id",
        "serial_number",
        "name",
        "model",
        "firmware_version",
        "status",
        "last_seen_at",
        "created_at",
    ]
    assert {column.name for column in table.primary_key} == {"id"}
    assert {column.name for column in table.columns if column.nullable} == {
        "last_seen_at"
    }
    assert table.c.id.type.python_type is UUID
    assert table.c.id.default is not None and table.c.id.default.is_callable
    assert table.c.id.server_default is None
    assert table.c.last_seen_at.default is None
    assert table.c.last_seen_at.server_default is None
    assert all(column.onupdate is None for column in table.columns)
    assert not table.foreign_keys
    assert not inspect(Device).relationships
    assert {status.value for status in DeviceStatus} == {"active", "inactive"}


def test_migration_matches_device_metadata(device_engine: Engine) -> None:
    with device_engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_server_default": True}
        )
        assert compare_metadata(context, Base.metadata) == []
        inspector = inspect(connection)
        checks = inspector.get_check_constraints("devices")
        assert {item["name"] for item in checks} == {
            "check_devices_serial_number_format",
            "ck_devices_name_non_empty",
            "ck_devices_model_non_empty",
            "ck_devices_firmware_version_non_empty",
            "ck_devices_status_valid",
        }
        assert len(inspector.get_unique_constraints("devices")) == 1
        assert not [
            item
            for item in inspector.get_indexes("devices")
            if not item.get("duplicates_constraint")
        ]


def test_defaults_and_timezone_round_trip(device_engine: Engine) -> None:
    before = datetime.now(UTC)
    reported = datetime(2026, 1, 2, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    with Session(device_engine) as session:
        first = Device(
            serial_number="Case-01",
            name="温度计",
            model="TH-100",
            firmware_version="factory-build-17",
        )
        second = Device(
            serial_number="case-01",
            name="Second",
            model="TH-100",
            firmware_version="v2-beta",
            last_seen_at=reported,
            status=DeviceStatus.INACTIVE,
        )
        session.add_all([first, second])
        session.flush()
        ids = first.id, second.id
        assert all(isinstance(value, UUID) and value.version == 4 for value in ids)
        assert ids[0] != ids[1]
        session.expire_all()
        assert first.status is DeviceStatus.ACTIVE
        assert second.status is DeviceStatus.INACTIVE
        assert first.last_seen_at is None
        assert second.last_seen_at is not None
        assert second.last_seen_at.astimezone(UTC) == reported.astimezone(UTC)
        created = first.created_at
        assert created.tzinfo is not None
        assert before <= created.astimezone(UTC) <= datetime.now(UTC)
        first.name = "Renamed"
        session.flush()
        session.refresh(first)
        assert first.created_at == created
        assert first.last_seen_at is None
        session.rollback()

    with device_engine.connect() as connection:
        result = connection.execute(
            text(
                "INSERT INTO devices (id, serial_number, name, model, firmware_version)"
                " VALUES (:id, :serial, :name, :model, :firmware)"
                " RETURNING status, last_seen_at, created_at"
            ),
            {
                "id": uuid4(),
                "serial": "a" * 64,
                "name": "中" * 100,
                "model": "m" * 100,
                "firmware": "v" * 64,
            },
        ).one()
        assert result.status == "active"
        assert result.last_seen_at is None
        assert result.created_at.tzinfo is not None
        connection.rollback()


def test_database_rejects_invalid_values(device_engine: Engine) -> None:
    """Raw SQL bypasses ORM validation/defaults, testing the database itself."""
    cases: list[tuple[str, object, str]] = [
        ("serial_number", value, "23514")
        for value in ("", "bad id", "设备", "x\n", "x\ny", "x\t", "x/", "x,")
    ]
    cases += [
        ("serial_number", "x" * 65, "22001"),
        ("status", "ACTIVE", "23514"),
        ("status", "online", "23514"),
        ("status", "", "23514"),
    ]
    for field, limit in (("name", 100), ("model", 100), ("firmware_version", 64)):
        cases += [(field, "", "23514"), (field, "x" * (limit + 1), "22001")]
    for field in (
        "id",
        "serial_number",
        "name",
        "model",
        "firmware_version",
        "status",
        "created_at",
    ):
        cases.append((field, None, "23502"))
    statement = text(
        "INSERT INTO devices "
        "(id, serial_number, name, model, firmware_version, status, created_at)"
        " VALUES (:id, :serial_number, :name, :model, :firmware_version, "
        ":status, :created_at)"
    )
    with device_engine.connect() as connection:
        for field, value, sqlstate in cases:
            values: dict[str, object] = {
                "id": uuid4(),
                "serial_number": "valid-001",
                "name": "Sensor",
                "model": "M1",
                "firmware_version": "1.0",
                "status": "active",
                "created_at": datetime.now(UTC),
            }
            values[field] = value
            with pytest.raises(DBAPIError) as caught:
                connection.execute(statement, values)
            assert getattr(caught.value.orig, "sqlstate", None) == sqlstate, (
                field,
                value,
            )
            connection.rollback()


def test_concurrent_serial_uniqueness(device_engine: Engine) -> None:
    """Independent transactions race; exactly one may commit the serial number."""
    barrier = Barrier(2)

    def insert_device() -> str:
        with Session(device_engine) as session:
            session.add(
                Device(
                    serial_number="race-001",
                    name="Sensor",
                    model="M1",
                    firmware_version="1.0",
                )
            )
            barrier.wait(timeout=10)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                assert getattr(error.orig, "sqlstate", None) == "23505"
                return "duplicate"
            return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(insert_device) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(results) == ["committed", "duplicate"]
    with device_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM devices WHERE serial_number = 'race-001'")
            )
            == 1
        )
