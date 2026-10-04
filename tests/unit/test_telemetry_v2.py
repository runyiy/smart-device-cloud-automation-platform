"""V2-T2 Telemetry Service ownership, locking and failure contracts."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.alerts.repository import AlertRepository
from app.devices.model import Device
from app.devices.repository import DeviceRepository
from app.telemetry.repository import TelemetryRepository
from app.telemetry.schema import TelemetryCreate, TelemetryListQuery
from app.telemetry.service import ingest_telemetry, list_telemetry

STAMP = datetime(2026, 1, 1, tzinfo=UTC)


def sample(value: float = 90) -> TelemetryCreate:
    return TelemetryCreate(
        metric="temperature", value=value, unit="°C", recorded_at=STAMP
    )


@pytest.mark.parametrize("breached", [False, True])
def test_ingestion_shares_session_and_locks_before_staging(breached: bool) -> None:
    session = MagicMock(spec=Session)
    device = Device(id=uuid4(), status="active", last_seen_at=None)
    session.scalar.return_value = device
    with (
        patch.object(
            DeviceRepository, "get", autospec=True, side_effect=DeviceRepository.get
        ) as get,
        patch.object(
            TelemetryRepository,
            "add",
            autospec=True,
            side_effect=TelemetryRepository.add,
        ) as add_sample,
        patch.object(
            AlertRepository, "add", autospec=True, side_effect=AlertRepository.add
        ) as add_alert,
        patch.object(
            TelemetryRepository,
            "refresh",
            autospec=True,
            side_effect=TelemetryRepository.refresh,
        ) as refresh,
    ):
        result = ingest_telemetry(
            session, device.id, sample(90 if breached else 23), actor_id=uuid4()
        )
        get.assert_called_once()
        assert get.call_args.args[0].session is session
        assert get.call_args.kwargs == {"for_update": True}
        add_sample.assert_called_once()
        assert add_sample.call_args.args[0].session is session
        assert add_sample.call_args.args[1] is result
        assert add_alert.call_count == int(breached)
        if breached:
            assert add_alert.call_args.args[0].session is session
        refresh.assert_called_once()
        assert refresh.call_args.args[0].session is session
        assert refresh.call_args.args[1] is result
    assert device.last_seen_at == STAMP
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


def test_history_uses_nonlocking_read_and_repository_page() -> None:
    session = MagicMock(spec=Session)
    device = Device(id=uuid4(), status="inactive")
    session.scalar.return_value = device
    query = TelemetryListQuery()
    with (
        patch.object(
            DeviceRepository, "get", autospec=True, side_effect=DeviceRepository.get
        ) as get,
        patch.object(TelemetryRepository, "list_page", autospec=True) as page,
    ):
        page.return_value = ([], 0)
        assert list_telemetry(session, device.id, query) == ([], 0)
        get.assert_called_once()
        assert get.call_args.kwargs == {"for_update": False}
        page.assert_called_once()
        assert page.call_args.args[0].session is session
        assert page.call_args.args[1:] == (device.id, query)
    session.commit.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("failure_at", ["threshold", "commit"])
def test_unexpected_ingestion_failure_rolls_back_once(failure_at: str) -> None:
    session = MagicMock(spec=Session)
    device = Device(id=uuid4(), status="active", last_seen_at=None)
    session.scalar.return_value = device
    error = RuntimeError("injected")
    if failure_at == "commit":
        session.commit.side_effect = error
    with patch("app.telemetry.service.build_threshold_alert") as threshold:
        threshold.side_effect = error if failure_at == "threshold" else None
        threshold.return_value = None
        with pytest.raises(RuntimeError) as caught:
            ingest_telemetry(session, device.id, sample(), actor_id=uuid4())
    assert caught.value is error
    session.rollback.assert_called_once()
    session.refresh.assert_not_called()
    session.close.assert_not_called()
