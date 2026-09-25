"""V1-T2 HTTP contracts with isolated Service results, not database writes."""

from collections.abc import Iterator
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.api.dependencies import get_db_session
from app.core.config import Settings
from app.devices.model import Device, DeviceStatus
from app.devices.service import DeviceNotFoundError, DuplicateSerialNumberError
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(
        Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:")
    )
    app.dependency_overrides[get_db_session] = lambda: MagicMock(spec=Session)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def stored_device() -> Device:
    return Device(
        id=uuid4(),
        serial_number="SN-001",
        name="Sensor",
        model="M1",
        firmware_version="v1",
        status=DeviceStatus.ACTIVE,
        last_seen_at=None,
        created_at=datetime.now(UTC),
    )


def test_post_contract(client: TestClient) -> None:
    device = stored_device()
    with patch("app.devices.router.create_device", return_value=device):
        response = client.post(
            "/api/v1/devices",
            json={
                "serial_number": "SN-001",
                "name": "Sensor",
                "model": "M1",
                "firmware_version": "v1",
            },
        )
    assert response.status_code == 201
    assert response.json()["id"] == str(device.id)
    assert response.json()["status"] == "active"
    assert response.json()["last_seen_at"] is None


def test_get_returns_device(client: TestClient) -> None:
    device = stored_device()
    with patch("app.devices.router.get_device", return_value=device) as service:
        response = client.get(f"/api/v1/devices/{device.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(device.id)
    service.assert_called_once()


@pytest.mark.parametrize("missing", [False, True])
def test_get_bad_or_missing_id(client: TestClient, missing: bool) -> None:
    device_id = str(uuid4()) if missing else "not-a-uuid"
    with patch("app.devices.router.get_device", side_effect=DeviceNotFoundError):
        response = client.get(f"/api/v1/devices/{device_id}")
    assert response.status_code == (404 if missing else 422)
    assert response.json()["error"]["code"] == (
        "HTTP_404" if missing else "VALIDATION_ERROR"
    )
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


@pytest.mark.parametrize(
    "error,status,code",
    [
        (DuplicateSerialNumberError("PRIVATE_SECRET"), 409, "HTTP_409"),
        (RuntimeError("PRIVATE_SECRET"), 500, "INTERNAL_ERROR"),
    ],
)
def test_post_errors_are_safe(
    client: TestClient,
    error: Exception,
    status: int,
    code: str,
) -> None:
    with patch("app.devices.router.create_device", side_effect=error):
        response = client.post(
            "/api/v1/devices",
            json={
                "serial_number": "SN-001",
                "name": "Sensor",
                "model": "M1",
                "firmware_version": "v1",
            },
        )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "PRIVATE_SECRET" not in response.text


def test_openapi_documents_device_operations(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    post = schema["paths"]["/api/v1/devices"]["post"]
    assert "201" in post["responses"]
    assert "409" in post["responses"]
    get = schema["paths"]["/api/v1/devices/{device_id}"]["get"]
    for operation, codes in [(post, ("409", "422")), (get, ("404", "422"))]:
        for code in codes:
            assert operation["responses"][code]["content"]["application/json"][
                "schema"
            ]["$ref"].endswith("/ErrorResponse")
    body = post["requestBody"]["content"]["application/json"]
    create_schema = schema["components"]["schemas"]["DeviceCreate"]
    assert body.get("example") or body.get("examples") or create_schema.get("examples")
