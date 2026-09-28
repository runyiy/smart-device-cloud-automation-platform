"""T5 Service, HTTP and PostgreSQL transaction/concurrency acceptance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import UUID

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.core.config import Settings
from app.devices.model import Device
from app.devices.schema import DeviceUpdate
from app.devices.service import DeviceNotFoundError, update_device
from app.main import create_app
from app.telemetry.model import Telemetry
from app.telemetry.schema import TelemetryCreate, TelemetryListQuery
from app.telemetry.service import InactiveDeviceError, ingest_telemetry, list_telemetry
from tests.integration.test_devices import device_engine as device_engine

STAMP = datetime(2026, 9, 26, 10, tzinfo=UTC)


def seed(engine: Engine, serial: str = "T5-001") -> UUID:
    with Session(engine) as session:
        row = Device(
            serial_number=serial, name="Sensor", model="M1", firmware_version="v1"
        )
        session.add(row)
        session.commit()
        return row.id


def sample(stamp: datetime = STAMP) -> TelemetryCreate:
    return TelemetryCreate.model_validate(
        {"metric": "temperature", "value": 23.5, "unit": "°C", "recorded_at": stamp}
    )


def test_service_persists_duplicates_and_filters(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    other = seed(device_engine, "T5-002")
    with Session(device_engine) as session:
        for stamp in (STAMP, STAMP, STAMP - timedelta(hours=1)):
            ingest_telemetry(session, device_id, sample(stamp))
        ingest_telemetry(session, other, sample())
        row = session.get(Device, device_id)
        assert row is not None and row.last_seen_at == STAMP
        rows, total = list_telemetry(
            session,
            device_id,
            TelemetryListQuery.model_validate(
                {"from": STAMP, "to": STAMP, "metric": "temperature", "page_size": 1}
            ),
        )
        assert total == 2 and len(rows) == 1
        rows2, total2 = list_telemetry(
            session,
            device_id,
            TelemetryListQuery.model_validate(
                {
                    "from": STAMP,
                    "to": STAMP,
                    "metric": "temperature",
                    "page": 2,
                    "page_size": 1,
                }
            ),
        )
        assert total2 == 2 and len(rows2) == 1 and rows[0].id.int > rows2[0].id.int
        rows, total = list_telemetry(session, device_id, TelemetryListQuery(page=99))
        assert rows == [] and total == 3
        rows, total = list_telemetry(
            session, device_id, TelemetryListQuery(metric="Temperature")
        )
        assert rows == [] and total == 0
        update_device(session, device_id, DeviceUpdate(status="inactive"))
        assert list_telemetry(session, device_id, TelemetryListQuery())[1] == 3
        with pytest.raises(InactiveDeviceError):
            ingest_telemetry(session, device_id, sample())
        with pytest.raises(DeviceNotFoundError):
            list_telemetry(session, UUID(int=0), TelemetryListQuery())


def test_failed_insert_rolls_back_watermark(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    with Session(device_engine) as session:
        ingest_telemetry(session, device_id, sample())
        # Deliberately bypass input validation to exercise a database failure.
        invalid = sample(STAMP + timedelta(hours=1)).model_copy(update={"metric": ""})
        with pytest.raises(IntegrityError):
            ingest_telemetry(session, device_id, invalid)
    with Session(device_engine) as session:
        row = session.get(Device, device_id)
        assert row is not None and row.last_seen_at == STAMP
        assert session.scalar(select(func.count()).select_from(Telemetry)) == 1


def test_concurrent_ingestion_preserves_samples_and_max_time(
    device_engine: Engine,
) -> None:
    device_id = seed(device_engine)
    barrier = Barrier(2)

    def ingest(hour_offset: int) -> UUID:
        with Session(device_engine) as session:
            barrier.wait(timeout=5)
            return ingest_telemetry(
                session, device_id, sample(STAMP + timedelta(hours=hour_offset))
            ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(ingest, offset) for offset in (1, -1)]
        assert len({f.result(timeout=10) for f in futures}) == 2
    with Session(device_engine) as session:
        row = session.get(Device, device_id)
        assert row is not None and row.last_seen_at == STAMP + timedelta(hours=1)
        assert session.scalar(select(func.count()).select_from(Telemetry)) == 2


@pytest.mark.parametrize("ingest_first", [False, True])
def test_ingestion_and_deactivation_lock_order(
    device_engine: Engine, ingest_first: bool
) -> None:
    device_id = seed(device_engine)
    ready = Event()
    release = Event()

    def execute(is_ingest: bool, hold: bool) -> str:
        with Session(device_engine) as session:
            if hold:

                def pause_before_commit(current: Session) -> None:
                    ready.set()
                    assert release.wait(timeout=8), "Lock-holder release timed out"

                event.listen(session, "before_commit", pause_before_commit, once=True)
            if is_ingest:
                try:
                    ingest_telemetry(session, device_id, sample())
                except InactiveDeviceError:
                    return "rejected"
                return "ingested"
            update_device(session, device_id, DeviceUpdate(status="inactive"))
            return "deactivated"

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(execute, ingest_first, True)
        try:
            assert ready.wait(timeout=5)
            second = executor.submit(execute, not ingest_first, False)
            # Observe a real blocked backend rather than relying on thread timing.
            blocked = False
            deadline = monotonic() + 3
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
            assert blocked
            assert not second.done()
        finally:
            release.set()
        assert first.result(timeout=5) == (
            "ingested" if ingest_first else "deactivated"
        )
        assert second.result(timeout=5) == (
            "deactivated" if ingest_first else "rejected"
        )
    with Session(device_engine) as session:
        device = session.get(Device, device_id)
        assert device is not None and device.status == "inactive"
        assert device.last_seen_at == (STAMP if ingest_first else None)
        assert session.scalar(select(func.count()).select_from(Telemetry)) == int(
            ingest_first
        )


def test_http_ingestion_and_history_roundtrip(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    path = f"/api/v1/devices/{device_id}/telemetry"
    with TestClient(app) as client:
        body = {
            "metric": "temperature",
            "value": 0,
            "unit": " °C ",
            "recorded_at": "2026-09-26T18:00:00+08:00",
        }
        created = client.post(path, json=body)
        assert created.status_code == 201
        output = created.json()
        assert set(output) == {
            "id",
            "device_id",
            "metric",
            "value",
            "unit",
            "recorded_at",
            "received_at",
        }
        assert output["recorded_at"] == "2026-09-26T10:00:00Z"
        assert output["unit"] == "°C"
        assert client.get(path).json()["items"] == [output]
        device = client.get(f"/api/v1/devices/{device_id}").json()
        assert datetime.fromisoformat(device["last_seen_at"]) == STAMP
        assert (
            client.patch(
                f"/api/v1/devices/{device_id}", json={"status": "inactive"}
            ).status_code
            == 200
        )
        assert client.post(path, json=body).status_code == 409
        assert client.get(path).json()["items"] == [output]
        assert client.get(f"/api/v1/devices/{UUID(int=0)}/telemetry").status_code == 404
