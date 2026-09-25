"""T3 persistence and row-lock acceptance on the guarded PostgreSQL test DB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from time import monotonic, sleep
from uuid import UUID

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.config import Settings
from app.devices.model import Device
from app.devices.schema import DeviceListQuery, DeviceUpdate
from app.devices.service import InvalidDeviceStateError, list_devices, update_device
from app.main import create_app
from tests.integration.test_devices import device_engine as device_engine


def seed(engine: Engine) -> list[UUID]:
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    with Session(engine) as session:
        rows = [
            Device(
                id=UUID(int=i),
                serial_number=f"SN-{i}",
                name="Original",
                model="M1" if i < 3 else "M2",
                firmware_version="v1",
                status="active" if i != 2 else "inactive",
                created_at=stamp,
                last_seen_at=stamp,
            )
            for i in range(1, 4)
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


def test_listing_filters_counts_and_order(device_engine: Engine) -> None:
    ids = seed(device_engine)
    with Session(device_engine) as session:
        for column in ("created_at", "serial_number"):
            for direction, expected in (("asc", ids), ("desc", ids[::-1])):
                rows, total = list_devices(
                    session,
                    DeviceListQuery(sort_by=column, sort_order=direction, page_size=2),
                )
                assert [row.id for row in rows] == expected[:2]
                assert total == 3
        rows, total = list_devices(session, DeviceListQuery(page=2, page_size=2))
        assert [row.id for row in rows] == [ids[0]] and total == 3
        rows, total = list_devices(session, DeviceListQuery(page=9, model="M1"))
        assert rows == [] and total == 2
        rows, total = list_devices(
            session,
            DeviceListQuery(model=" M1 ", status="inactive", serial_number="SN-2"),
        )
        assert [row.id for row in rows] == [ids[1]] and total == 1
        rows, total = list_devices(
            session, DeviceListQuery(model="M1", status="active", serial_number="SN-2")
        )
        assert rows == [] and total == 0
        rows, total = list_devices(session, DeviceListQuery(model="m1"))
        assert rows == [] and total == 0


def test_patch_persistence_states_and_atomic_rejection(device_engine: Engine) -> None:
    ids = seed(device_engine)
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    path = f"/api/v1/devices/{ids[0]}"
    with TestClient(app) as client:
        before = client.get(path).json()
        for body in (
            {"status": "active"},
            {"status": "inactive"},
            {"status": "inactive"},
        ):
            response = client.patch(path, json=body)
            assert response.status_code == 200
            assert response.json()["status"] == body["status"]
        response = client.patch(
            path, json={"name": " New ", "firmware_version": " v2 "}
        )
        assert response.status_code == 200
        after = response.json()
        assert after["name"] == "New" and after["firmware_version"] == "v2"
        for field in ("id", "serial_number", "model", "created_at", "last_seen_at"):
            assert after[field] == before[field]
        assert after["status"] == "inactive"
        response = client.patch(
            path, json={"name": "Must not persist", "status": "active"}
        )
        assert response.status_code == 409
        assert client.get(path).json() == after
        assert (
            client.patch(
                f"/api/v1/devices/{UUID(int=99)}", json={"name": "Missing"}
            ).status_code
            == 404
        )
    with Session(device_engine) as session:
        persisted = session.get(Device, ids[0])
        assert persisted is not None
        assert persisted.name == "New" and persisted.status == "inactive"
        assert session.scalar(select(text("count(*)")).select_from(Device)) == 3


@pytest.mark.parametrize("scenario", ["disjoint", "same_field", "deactivation"])
def test_row_lock_serializes_updates(device_engine: Engine, scenario: str) -> None:
    device_id = seed(device_engine)[0]

    def competing_update() -> str:
        with Session(device_engine) as session:
            body = {"firmware_version": "v2"}
            if scenario == "same_field":
                body = {"name": "Second"}
            elif scenario == "deactivation":
                body = {"name": "Must not persist", "status": "active"}
            try:
                update_device(session, device_id, DeviceUpdate.model_validate(body))
            except InvalidDeviceStateError:
                return "conflict"
            return "updated"

    # Keep one real transaction open; observe actual PostgreSQL lock contention
    # before releasing it. A timing delay alone would not prove serialization.
    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(device_engine) as first:
            row = first.scalar(
                select(Device).where(Device.id == device_id).with_for_update()
            )
            assert row is not None
            row.name = "First"
            if scenario == "deactivation":
                row.status = "inactive"
            first.flush()
            future = executor.submit(competing_update)
            try:
                deadline = monotonic() + 3
                blocked = False
                with device_engine.connect() as observer:
                    while monotonic() < deadline:
                        blocked = bool(
                            observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE datname = current_database() "
                                    "AND cardinality(pg_blocking_pids(pid)) > 0"
                                )
                            )
                        )
                        if blocked:
                            break
                        sleep(0.02)
                assert blocked, "Competing update never waited for the row lock"
                assert not future.done()
                first.commit()
            finally:
                first.rollback()
        assert future.result(timeout=10) == (
            "conflict" if scenario == "deactivation" else "updated"
        )
    with Session(device_engine) as session:
        result = session.get(Device, device_id)
        assert result is not None
        assert result.name == ("Second" if scenario == "same_field" else "First")
        assert result.firmware_version == ("v2" if scenario == "disjoint" else "v1")
        assert result.status == ("inactive" if scenario == "deactivation" else "active")
