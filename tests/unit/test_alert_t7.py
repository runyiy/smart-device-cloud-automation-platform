"""T7 exact threshold boundaries and transient Alert construction."""

from uuid import uuid4

import pytest
from sqlalchemy import inspect

from app.alerts.model import AlertSeverity, AlertStatus
from app.alerts.service import build_threshold_alert


@pytest.mark.parametrize(
    "metric,unit,value,expected",
    [
        ("temperature", "°C", 79.9, False),
        ("temperature", "°C", 80.0, False),
        ("temperature", "°C", 80.1, True),
        ("battery", "%", 19.9, True),
        ("battery", "%", 20.0, False),
        ("battery", "%", 20.1, False),
        ("signal_strength", "dBm", -80.1, True),
        ("signal_strength", "dBm", -80.0, False),
        ("signal_strength", "dBm", -79.9, False),
        ("battery", "%", -1.0, True),
        ("Temperature", "°C", 100.0, False),
        ("temperature", "C", 100.0, False),
        ("temperature", "celsius", 100.0, False),
        ("battery_level", "%", 1.0, False),
        ("battery", "percent", 1.0, False),
        ("signal_strength", "dbm", -100.0, False),
        ("unknown", "°C", 100.0, False),
    ],
)
def test_rule_boundaries(metric: str, unit: str, value: float, expected: bool) -> None:
    assert (build_threshold_alert(uuid4(), metric, value, unit) is not None) is expected


@pytest.mark.parametrize(
    "metric,unit,value,kind,severity,message",
    [
        (
            "temperature",
            "°C",
            90.0,
            "temperature_high",
            AlertSeverity.CRITICAL,
            "Temperature exceeds 80 °C.",
        ),
        (
            "battery",
            "%",
            10.0,
            "battery_low",
            AlertSeverity.WARNING,
            "Battery is below 20%.",
        ),
        (
            "signal_strength",
            "dBm",
            -90.0,
            "signal_weak",
            AlertSeverity.WARNING,
            "Signal strength is below -80 dBm.",
        ),
    ],
)
def test_return_fields_and_defaults(
    metric: str,
    unit: str,
    value: float,
    kind: str,
    severity: AlertSeverity,
    message: str,
) -> None:
    device_id = uuid4()
    alert = build_threshold_alert(device_id, metric, value, unit)
    assert alert is not None
    assert inspect(alert).transient
    assert alert.device_id == device_id
    assert (alert.type, alert.severity, alert.message) == (kind, severity, message)
    assert alert.status is AlertStatus.OPEN and alert.resolved_at is None
    assert alert.id is None and alert.triggered_at is None
    assert "device" not in alert.__dict__
    repeated = build_threshold_alert(device_id, metric, value, unit)
    assert repeated is not None and repeated is not alert
