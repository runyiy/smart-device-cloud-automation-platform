"""Real PostgreSQL acceptance for Device registration and separate requests."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import Engine, text
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.integration.test_devices import device_engine as device_engine


def test_registration_is_committed_and_visible_to_get(device_engine: Engine) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/devices",
            json={
                "serial_number": "http-001",
                "name": " Sensor ",
                "model": "M1",
                "firmware_version": "v1",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["name"] == "Sensor"
        assert body["status"] == "active"
        assert body["last_seen_at"] is None
        with device_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM devices WHERE serial_number = 'http-001'"
                    )
                )
                == 1
            )
        fetched = client.get(f"/api/v1/devices/{body['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == body


def test_concurrent_registration_returns_one_conflict(device_engine: Engine) -> None:
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    barrier = Barrier(2)
    with TestClient(app) as client:

        def register() -> int:
            barrier.wait(timeout=10)
            response = client.post(
                "/api/v1/devices",
                json={
                    "serial_number": "http-race",
                    "name": "Sensor",
                    "model": "M1",
                    "firmware_version": "v1",
                },
            )
            if response.status_code == 409:
                assert response.json()["error"]["code"] == "HTTP_409"
                assert (
                    response.json()["error"]["request_id"]
                    == response.headers["X-Request-ID"]
                )
            return response.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(register) for _ in range(2)]
            assert sorted(future.result(timeout=15) for future in futures) == [201, 409]
    with device_engine.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM devices WHERE serial_number = 'http-race'")
            )
            == 1
        )
