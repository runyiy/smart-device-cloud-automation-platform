"""V1 cross-module HTTP acceptance on the guarded migrated PostgreSQL database."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.alerts.model import Alert, AlertStatus
from app.core.config import Settings
from app.devices.model import Device
from app.main import create_app
from app.telemetry.model import Telemetry
from app.test_tasks.model import TestTask as Task
from app.test_tasks.model import TestTaskStatus as TaskStatus
from tests.integration.test_devices import device_engine as device_engine

STAMP = "2026-01-01T00:00:00Z"


@pytest.fixture
def v1_client(device_engine: Engine) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def exercise_v1_business_flow(client: TestClient) -> tuple[UUID, UUID, UUID, UUID]:
    serial = "V1-" + uuid4().hex
    created = client.post(
        "/api/v1/devices",
        json={
            "serial_number": serial,
            "name": "Lab sensor",
            "model": "M1",
            "firmware_version": "1.0",
        },
    )
    assert created.status_code == 201
    device = created.json()
    device_id = device["id"]
    assert device["status"] == "active"
    assert client.get(f"/api/v1/devices/{device_id}").json() == device
    listing = client.get("/api/v1/devices", params={"serial_number": serial})
    assert listing.status_code == 200
    assert listing.json()["total"] == 1 and listing.json()["items"] == [device]
    before = datetime.now(UTC)
    sample = client.post(
        f"/api/v1/devices/{device_id}/telemetry",
        json={
            "metric": "temperature",
            "value": 90.0,
            "unit": "°C",
            "recorded_at": STAMP,
        },
    )
    assert sample.status_code == 201
    samples = client.get(f"/api/v1/devices/{device_id}/telemetry")
    assert samples.status_code == 200 and samples.json()["items"] == [sample.json()]
    assert client.get(f"/api/v1/devices/{device_id}").json()["last_seen_at"] == STAMP
    alerts = client.get(
        "/api/v1/alerts", params={"device_id": device_id, "type": "temperature_high"}
    )
    assert alerts.status_code == 200 and alerts.json()["total"] == 1
    alert = alerts.json()["items"][0]
    assert (alert["status"], alert["severity"], alert["message"]) == (
        "open",
        "critical",
        "Temperature exceeds 80 °C.",
    )
    assert before <= datetime.fromisoformat(alert["triggered_at"]) <= datetime.now(UTC)
    assert alert["triggered_at"] != STAMP
    alert_path = f"/api/v1/alerts/{alert['id']}"
    ack = client.post(alert_path + "/acknowledge")
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    resolved = client.post(alert_path + "/resolve")
    assert resolved.status_code == 200 and resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"].endswith("Z")
    assert client.post(alert_path + "/resolve").json() == resolved.json()
    task = client.post(
        "/api/v1/test-tasks", json={"device_id": device_id, "name": "Manual check"}
    )
    assert task.status_code == 201 and task.json()["status"] == "pending"
    assert task.json()["started_at"] is None and task.json()["finished_at"] is None
    task_path = f"/api/v1/test-tasks/{task.json()['id']}"
    assert client.get(task_path).json() == task.json()
    running = client.patch(task_path, json={"status": "running"})
    assert running.status_code == 200 and running.json()["status"] == "running"
    passed = client.patch(
        task_path, json={"status": "passed", "summary": "Manual check recorded"}
    )
    assert passed.status_code == 200 and passed.json()["status"] == "passed"
    result = passed.json()
    assert result["device_id"] == device_id
    requested, started, finished = (
        datetime.fromisoformat(result[key])
        for key in ("requested_at", "started_at", "finished_at")
    )
    assert requested <= started <= finished
    assert client.patch(task_path, json={"status": "passed"}).json() == result
    return (
        UUID(device_id),
        UUID(sample.json()["id"]),
        UUID(alert["id"]),
        UUID(result["id"]),
    )


def test_complete_business_flow(v1_client: TestClient, device_engine: Engine) -> None:
    device_id, sample_id, alert_id, task_id = exercise_v1_business_flow(v1_client)
    with Session(device_engine) as observer:
        device = observer.get(Device, device_id)
        sample = observer.get(Telemetry, sample_id)
        alert = observer.get(Alert, alert_id)
        task = observer.get(Task, task_id)
        assert device is not None and device.last_seen_at == datetime.fromisoformat(
            STAMP
        )
        assert (
            sample is not None and sample.device_id == device_id and sample.value == 90
        )
        assert (
            alert is not None
            and alert.device_id == device_id
            and alert.status is AlertStatus.RESOLVED
        )
        assert (
            task is not None
            and task.device_id == device_id
            and task.status is TaskStatus.PASSED
        )
        assert task.summary == "Manual check recorded"
        for model in (Device, Telemetry, Alert, Task):
            assert observer.scalar(select(func.count()).select_from(model)) == 1


def test_error_boundaries_and_deactivation(
    v1_client: TestClient, device_engine: Engine
) -> None:
    client = v1_client
    device_id, _, alert_id, task_id = exercise_v1_business_flow(client)
    device_path = f"/api/v1/devices/{device_id}"
    task_path = f"/api/v1/test-tasks/{task_id}"
    device = client.get(device_path).json()
    task_before = client.get(task_path).json()
    cases = [
        (
            "POST",
            "/api/v1/devices",
            {
                key: device[key]
                for key in ("serial_number", "name", "model", "firmware_version")
            },
            409,
        ),
        ("GET", "/api/v1/devices/not-a-uuid", None, 422),
        ("GET", f"/api/v1/devices/{uuid4()}", None, 404),
        ("POST", f"/api/v1/alerts/{alert_id}/acknowledge", None, 409),
        ("PATCH", task_path, {"status": "failed", "summary": "Must not persist"}, 409),
    ]
    for method, path, body, expected in cases:
        response = client.request(
            method, path, json=body, headers={"X-Request-ID": "v1-rejected"}
        )
        assert response.status_code == expected
        assert response.json()["error"]["code"] == (
            "VALIDATION_ERROR" if expected == 422 else f"HTTP_{expected}"
        )
        assert (
            response.json()["error"]["request_id"]
            == response.headers["X-Request-ID"]
            == "v1-rejected"
        )
    assert client.get(task_path).json() == task_before
    pending = client.post(
        "/api/v1/test-tasks", json={"device_id": str(device_id), "name": "Existing"}
    )
    assert pending.status_code == 201
    deactivated = client.patch(device_path, json={"status": "inactive"})
    assert deactivated.status_code == 200
    assert (
        client.post(
            device_path + "/telemetry",
            json={
                "metric": "temperature",
                "value": 99,
                "unit": "°C",
                "recorded_at": "2026-01-02T00:00:00Z",
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/test-tasks", json={"device_id": str(device_id), "name": "Rejected"}
        ).status_code
        == 409
    )
    assert client.get(device_path).json()["last_seen_at"] == STAMP
    assert client.post(f"/api/v1/alerts/{alert_id}/resolve").status_code == 200
    existing_path = f"/api/v1/test-tasks/{pending.json()['id']}"
    assert client.get(existing_path).status_code == 200
    assert client.patch(existing_path, json={"status": "cancelled"}).status_code == 200
    with Session(device_engine) as observer:
        assert observer.scalar(select(func.count()).select_from(Device)) == 1
        assert observer.scalar(select(func.count()).select_from(Telemetry)) == 1
        assert observer.scalar(select(func.count()).select_from(Alert)) == 1
        assert observer.scalar(select(func.count()).select_from(Task)) == 2
        stored = observer.get(Task, task_id)
        assert stored is not None and stored.summary == task_before["summary"]
        assert stored.status is TaskStatus.PASSED
