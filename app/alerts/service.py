"""Exact threshold evaluation returning transient Alerts without database access."""

from uuid import UUID

from app.alerts.model import Alert, AlertSeverity, AlertStatus


def build_threshold_alert(
    device_id: UUID, metric: str, value: float, unit: str
) -> Alert | None:
    """Return one unsaved Alert for validated inputs; the caller owns persistence."""
    if metric == "temperature" and unit == "°C" and value > 80.0:
        return Alert(
            device_id=device_id,
            type="temperature_high",
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.OPEN,
            message="Temperature exceeds 80 °C.",
            resolved_at=None,
        )
    if metric == "battery" and unit == "%" and value < 20.0:
        return Alert(
            device_id=device_id,
            type="battery_low",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.OPEN,
            message="Battery is below 20%.",
            resolved_at=None,
        )
    if metric == "signal_strength" and unit == "dBm" and value < -80.0:
        return Alert(
            device_id=device_id,
            type="signal_weak",
            severity=AlertSeverity.WARNING,
            status=AlertStatus.OPEN,
            message="Signal strength is below -80 dBm.",
            resolved_at=None,
        )
    return None
