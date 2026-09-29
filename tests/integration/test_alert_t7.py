"""T7 persistence, repeat-report and atomic failure acceptance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.alerts.service import build_threshold_alert
from app.core.config import Settings
from app.devices.model import Device
from app.main import create_app
from app.telemetry.model import Telemetry
from app.telemetry.service import ingest_telemetry
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_telemetry_t5 import STAMP, sample, seed


@pytest.mark.parametrize("old_status", list(AlertStatus))
def test_repeats_late_samples_and_normal_readings(
    device_engine: Engine, old_status: AlertStatus
) -> None:
    device_id = seed(device_engine)
    now = datetime.now(UTC)
    future = now + timedelta(days=1)
    with Session(device_engine) as session:
        old = Alert(
            device_id=device_id,
            type="temperature_high",
            severity=AlertSeverity.CRITICAL,
            status=old_status,
            message="Existing",
            triggered_at=STAMP,
            resolved_at=STAMP if old_status is AlertStatus.RESOLVED else None,
        )
        session.add(old)
        session.commit()
        old_id = old.id
        old_snapshot = (old.status, old.message, old.triggered_at, old.resolved_at)
        for stamp in (future, future, STAMP):
            ingest_telemetry(session, device_id, sample(stamp, 90.0))
        # Recovery and unknown units persist without altering any existing Alert.
        ingest_telemetry(session, device_id, sample(future, 80.0))
        mismatched = sample(future, 90.0).model_copy(update={"unit": "C"})
        ingest_telemetry(session, device_id, mismatched)
    with Session(device_engine) as session:
        alerts = list(session.scalars(select(Alert)).all())
        assert len(alerts) == 4 and len({a.id for a in alerts}) == 4
        original = session.get(Alert, old_id)
        assert original is not None
        assert (
            original.status,
            original.message,
            original.triggered_at,
            original.resolved_at,
        ) == old_snapshot
        for alert in alerts:
            if alert.id != old_id:
                assert alert.status is AlertStatus.OPEN and alert.resolved_at is None
                assert now <= alert.triggered_at <= datetime.now(UTC)
                assert alert.triggered_at != future and alert.triggered_at != STAMP
        device = session.get(Device, device_id)
        assert device is not None and device.last_seen_at == future
        assert session.scalar(select(func.count()).select_from(Telemetry)) == 5


def test_alert_insert_failure_is_atomic_and_sanitized(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    with Session(device_engine) as session:
        ingest_telemetry(session, device_id, sample(STAMP))
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )

    def invalid_alert(device_id: UUID, metric: str, value: float, unit: str) -> Alert:
        alert = build_threshold_alert(device_id, metric, value, unit)
        assert alert is not None
        alert.message = ""  # Force an actual PostgreSQL CHECK failure at flush.
        return alert

    with TestClient(app, raise_server_exceptions=False) as client:
        with patch(
            "app.telemetry.service.build_threshold_alert", side_effect=invalid_alert
        ) as helper:
            response = client.post(
                f"/api/v1/devices/{device_id}/telemetry",
                json={
                    "metric": "temperature",
                    "value": 90.0,
                    "unit": "°C",
                    "recorded_at": (STAMP + timedelta(hours=1)).isoformat(),
                },
            )
        helper.assert_called_once()
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert (
            response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
        )
        assert "ck_alerts" not in response.text and "INSERT" not in response.text
    with Session(device_engine) as session:
        assert session.scalar(select(func.count()).select_from(Telemetry)) == 1
        assert session.scalar(select(func.count()).select_from(Alert)) == 0
        device = session.get(Device, device_id)
        assert device is not None and device.last_seen_at == STAMP


@pytest.mark.parametrize(
    "metric,value,unit,kind",
    [
        ("temperature", 90.0, " °C ", "temperature_high"),
        ("battery", -1.0, "%", "battery_low"),
        ("signal_strength", -90.0, "dBm", "signal_weak"),
    ],
)
def test_http_breach_keeps_telemetry_response(
    device_engine: Engine, metric: str, value: float, unit: str, kind: str
) -> None:
    device_id = seed(device_engine)
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/devices/{device_id}/telemetry",
            json={
                "metric": metric,
                "value": value,
                "unit": unit,
                "recorded_at": STAMP.isoformat(),
            },
        )
        assert response.status_code == 201
        assert set(response.json()) == {
            "id",
            "device_id",
            "metric",
            "value",
            "unit",
            "recorded_at",
            "received_at",
        }
    with Session(device_engine) as session:
        alerts = list(session.scalars(select(Alert)).all())
        assert len(alerts) == 1 and alerts[0].type == kind
        assert alerts[0].device_id == device_id
