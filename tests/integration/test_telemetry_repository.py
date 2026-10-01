"""V2-T2 real PostgreSQL Repository, atomicity and read-back acceptance."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.alerts.model import Alert
from app.alerts.repository import AlertRepository
from app.devices.model import Device
from app.devices.repository import DeviceRepository
from app.telemetry.model import Telemetry
from app.telemetry.repository import TelemetryRepository
from app.telemetry.schema import TelemetryListQuery
from app.telemetry.service import ingest_telemetry, list_telemetry
from tests.integration.test_devices import device_engine as device_engine
from tests.integration.test_telemetry_t5 import STAMP, sample, seed


def test_repository_preserves_device_filters_totals_and_time_ties(
    device_engine: Engine,
) -> None:
    device_id = seed(device_engine)
    other_id = seed(device_engine, "OTHER")
    with Session(device_engine) as session:
        repo = TelemetryRepository(session)
        for index, parent, metric, stamp in (
            (1, device_id, "temperature", STAMP),
            (2, device_id, "temperature", STAMP),
            (3, device_id, "battery", STAMP + timedelta(hours=1)),
            (4, other_id, "temperature", STAMP),
        ):
            repo.add(
                Telemetry(
                    id=UUID(int=index),
                    device_id=parent,
                    metric=metric,
                    value=90,
                    unit="°C",
                    recorded_at=stamp,
                )
            )
        session.commit()
        for direction, expected in (("asc", [1, 2]), ("desc", [2, 1])):
            for page in (1, 2, 3):
                rows, total = repo.list_page(
                    device_id,
                    TelemetryListQuery.model_validate(
                        {
                            "metric": "temperature",
                            "from": STAMP,
                            "to": STAMP,
                            "sort_order": direction,
                            "page": page,
                            "page_size": 1,
                        }
                    ),
                )
                assert [row.id.int for row in rows] == expected[page - 1 : page]
                assert total == 2
        assert repo.list_page(device_id, TelemetryListQuery(metric="Temperature")) == (
            [],
            0,
        )
        assert repo.list_page(UUID(int=999), TelemetryListQuery()) == ([], 0)
        assert session.scalar(select(func.count()).select_from(Alert)) == 0


@pytest.mark.parametrize("should_commit", [False, True])
def test_two_repositories_leave_visibility_and_finalization_to_caller(
    device_engine: Engine, should_commit: bool
) -> None:
    device_id = seed(device_engine)
    with Session(device_engine) as session:
        telemetry_repo = TelemetryRepository(session)
        alert_repo = AlertRepository(session)
        row = Telemetry(
            device_id=device_id,
            metric="temperature",
            value=90,
            unit="°C",
            recorded_at=STAMP,
        )
        alert = Alert(
            device_id=device_id,
            type="temperature_high",
            severity="critical",
            message="Test",
            status="open",
        )
        with (
            patch.object(session, "commit", wraps=session.commit) as commit,
            patch.object(session, "rollback", wraps=session.rollback) as rollback,
            patch.object(session, "close", wraps=session.close) as close,
        ):
            telemetry_repo.add(row)
            alert_repo.add(alert)
            session.flush()
            telemetry_repo.refresh(row)
            alert_repo.refresh(alert)
            assert alert_repo.get(alert.id) is alert
            commit.assert_not_called()
            rollback.assert_not_called()
            close.assert_not_called()
        with Session(device_engine) as observer:
            assert observer.get(Telemetry, row.id) is None
            assert observer.get(Alert, alert.id) is None
        if should_commit:
            session.commit()
        else:
            session.rollback()
        with Session(device_engine) as observer:
            assert observer.scalar(select(func.count()).select_from(Telemetry)) == int(
                should_commit
            )
            assert observer.scalar(select(func.count()).select_from(Alert)) == int(
                should_commit
            )


@pytest.mark.parametrize("failure_at", ["threshold", "alert_add"])
def test_flushed_ingestion_rolls_back_all_tables_and_reuses_session(
    device_engine: Engine, failure_at: str
) -> None:
    device_id = seed(device_engine)
    error = RuntimeError("after real flush")
    with Session(device_engine) as session:
        # Keep an existing read/autobegin transaction before entering the use case.
        assert DeviceRepository(session).get(device_id) is not None

        def fail_threshold(
            device_id: UUID, metric: str, value: float, unit: str
        ) -> Alert | None:
            session.flush()
            assert session.scalar(select(func.count()).select_from(Telemetry)) == 1
            raise error

        original_add = AlertRepository.add

        def fail_add(repo: AlertRepository, alert: Alert) -> None:
            original_add(repo, alert)
            repo.session.flush()
            assert repo.session.scalar(select(func.count()).select_from(Alert)) == 1
            assert (
                repo.session.scalar(
                    select(Device.last_seen_at).where(Device.id == device_id)
                )
                == STAMP
            )
            raise error

        target = (
            "app.telemetry.service.build_threshold_alert"
            if failure_at == "threshold"
            else "app.alerts.repository.AlertRepository.add"
        )
        with patch(
            target,
            autospec=failure_at == "alert_add",
            side_effect=fail_threshold if failure_at == "threshold" else fail_add,
        ):
            with pytest.raises(RuntimeError) as caught:
                ingest_telemetry(session, device_id, sample(value=90))
        assert caught.value is error
        assert not session.in_transaction()
        assert not session.new and not session.dirty
        with Session(device_engine) as observer:
            row = observer.get(Device, device_id)
            assert row is not None and row.last_seen_at is None
            for model in (Telemetry, Alert):
                assert observer.scalar(select(func.count()).select_from(model)) == 0
        ingest_telemetry(session, device_id, sample())
        with Session(device_engine) as observer:
            assert observer.scalar(select(func.count()).select_from(Telemetry)) == 1
            assert observer.scalar(select(func.count()).select_from(Alert)) == 0


def test_ingestion_readback_failure_keeps_all_three_committed_changes(
    device_engine: Engine,
) -> None:
    device_id = seed(device_engine)
    error = OperationalError("refresh", {}, Exception("injected"))
    with Session(device_engine) as session:

        def fail_refresh(instance: object) -> None:
            session.execute(text("SELECT 1"))
            raise error

        with patch.object(session, "refresh", side_effect=fail_refresh):
            with pytest.raises(OperationalError) as caught:
                ingest_telemetry(session, device_id, sample(value=90))
        assert caught.value is error
        assert not session.in_transaction()
        with Session(device_engine) as observer:
            row = observer.get(Device, device_id)
            assert row is not None and row.last_seen_at == STAMP
            for model in (Telemetry, Alert):
                assert observer.scalar(select(func.count()).select_from(model)) == 1
        assert session.scalar(text("SELECT 1")) == 1


def test_history_does_not_wait_for_a_device_writer(device_engine: Engine) -> None:
    device_id = seed(device_engine)
    with Session(device_engine) as writer, Session(device_engine) as reader:
        assert DeviceRepository(writer).get(device_id, for_update=True) is not None
        reader.execute(text("SET LOCAL lock_timeout = '200ms'"))
        # READ COMMITTED can inspect an existing row without waiting for its writer.
        assert list_telemetry(reader, device_id, TelemetryListQuery()) == ([], 0)


def test_contending_ingestions_keep_maximum_event_time(device_engine: Engine) -> None:
    """Force the newer report to commit first while the older report contends."""
    device_id = seed(device_engine)
    ready, release = Event(), Event()
    later = STAMP + timedelta(hours=1)

    def first_ingestion() -> None:
        with Session(device_engine) as session:

            def pause(current: Session) -> None:
                current.flush()
                ready.set()
                assert release.wait(10), "Owner transaction was not released"

            event.listen(session, "before_commit", pause, once=True)
            ingest_telemetry(session, device_id, sample(later, value=90))

    def second_ingestion() -> None:
        with Session(device_engine) as session:
            ingest_telemetry(session, device_id, sample(STAMP, value=90))

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_ingestion)
        try:
            assert ready.wait(5), "First ingestion never reached its flush"
            second = executor.submit(second_ingestion)
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
            assert blocked, "Competing ingestion never waited for the owner"
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    with Session(device_engine) as final_observer:
        row = final_observer.get(Device, device_id)
        assert row is not None and row.last_seen_at == later
        assert final_observer.scalar(select(func.count()).select_from(Telemetry)) == 2
        assert final_observer.scalar(select(func.count()).select_from(Alert)) == 2
