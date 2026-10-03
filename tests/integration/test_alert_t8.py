"""T8 acceptance on the existing guarded, disposable PostgreSQL fixture."""

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertSeverity, AlertStatus
from app.alerts.schema import AlertListQuery, AlertRead
from app.alerts.service import (
    AlertNotFoundError,
    InvalidAlertStateError,
    acknowledge_alert,
    list_alerts,
    resolve_alert,
)
from app.core.config import Settings
from app.devices.model import Device, DeviceStatus
from app.main import create_app
from app.telemetry.model import Telemetry
from tests.integration.test_devices import device_engine as device_engine
from tests.rbac_support import admin_test_client

STAMP = datetime(2026, 1, 1, tzinfo=UTC)
ACTIONS = {"acknowledge": acknowledge_alert, "resolve": resolve_alert}


def seed(engine: Engine) -> list[UUID]:
    with Session(engine) as session:
        session.add_all(
            [
                Device(
                    id=UUID(int=i),
                    serial_number=f"T8-{i}",
                    name="Sensor",
                    model="M1",
                    firmware_version="v1",
                    status=DeviceStatus.INACTIVE if i == 1 else DeviceStatus.ACTIVE,
                )
                for i in (1, 2)
            ]
        )
        session.flush()
        rows = [
            Alert(
                id=UUID(int=i),
                device_id=UUID(int=1 if i < 3 else 2),
                type="temperature_high" if i < 3 else "custom_alert",
                severity=AlertSeverity.CRITICAL if i < 3 else AlertSeverity.WARNING,
                status=state,
                message=f"Alert {i}",
                triggered_at=STAMP,
                resolved_at=STAMP if state is AlertStatus.RESOLVED else None,
            )
            for i, state in enumerate(
                [
                    AlertStatus.OPEN,
                    AlertStatus.ACKNOWLEDGED,
                    AlertStatus.RESOLVED,
                    AlertStatus.OPEN,
                ],
                start=1,
            )
        ]
        session.add_all(rows)
        session.commit()
        return [row.id for row in rows]


def snapshot(session: Session, alert_id: UUID) -> dict[str, object]:
    row = session.get(Alert, alert_id)
    assert row is not None
    return dict(AlertRead.model_validate(row).model_dump())


def test_list_filters_count_and_stable_pagination(device_engine: Engine) -> None:
    ids = seed(device_engine)
    cases: list[tuple[dict[str, object], list[UUID]]] = [
        ({"device_id": UUID(int=1)}, ids[:2]),
        ({"device_id": uuid4()}, []),
        ({"status": "open"}, [ids[0], ids[3]]),
        ({"severity": "warning"}, ids[2:]),
        ({"type": "custom_alert"}, ids[2:]),
        ({"type": "CUSTOM_ALERT"}, []),
        (
            {
                "device_id": UUID(int=1),
                "status": "acknowledged",
                "severity": "critical",
                "type": "temperature_high",
            },
            [ids[1]],
        ),
        ({"device_id": UUID(int=1), "severity": "warning"}, []),
    ]
    with Session(device_engine) as session, patch.object(session, "commit") as commit:
        for direction, expected in [("asc", ids), ("desc", ids[::-1])]:
            for page, wanted in [(1, expected[:2]), (2, expected[2:]), (3, [])]:
                rows, total = list_alerts(
                    session,
                    AlertListQuery.model_validate(
                        {
                            "sort_order": direction,
                            "page": page,
                            "page_size": 2,
                        }
                    ),
                )
                assert [row.id for row in rows] == wanted and total == 4
        for filters, expected in cases:
            query = AlertListQuery.model_validate({**filters, "sort_order": "asc"})
            rows, total = list_alerts(session, query)
            assert [row.id for row in rows] == expected and total == len(expected)
        # A distinct timestamp must take priority over the UUID tie-breaker.
        oldest = session.get(Alert, ids[-1])
        assert oldest is not None
        oldest.triggered_at = STAMP - timedelta(days=1)
        session.flush()
        rows, _ = list_alerts(session, AlertListQuery(sort_order="asc"))
        assert [row.id for row in rows] == [ids[-1], *ids[:-1]]
        commit.assert_not_called()


@pytest.mark.parametrize("action", list(ACTIONS))
@pytest.mark.parametrize("state", list(AlertStatus))
def test_persisted_transition_matrix(
    device_engine: Engine,
    action: str,
    state: AlertStatus,
) -> None:
    ids = seed(device_engine)
    target = ids[
        {AlertStatus.OPEN: 0, AlertStatus.ACKNOWLEDGED: 1, AlertStatus.RESOLVED: 2}[
            state
        ]
    ]
    with Session(device_engine) as session:
        before = {i: snapshot(session, i) for i in ids}
    with Session(device_engine) as session:
        if action == "acknowledge" and state is AlertStatus.RESOLVED:
            with pytest.raises(InvalidAlertStateError):
                ACTIONS[action](session, target)
            assert not session.in_transaction()
        else:
            ACTIONS[action](session, target)
            # Independent visibility proves persistence, not just identity-map mutation.
    with Session(device_engine) as observer:
        after = {i: snapshot(observer, i) for i in ids}
        for i in ids:
            for key in before[i]:
                if i != target or key not in {"status", "resolved_at"}:
                    assert after[i][key] == before[i][key]
        if state is AlertStatus.RESOLVED:
            assert after[target] == before[target]
        elif action == "acknowledge":
            assert after[target]["status"] is AlertStatus.ACKNOWLEDGED
            assert after[target]["resolved_at"] is None
        else:
            assert after[target]["status"] is AlertStatus.RESOLVED
            resolved = after[target]["resolved_at"]
            assert isinstance(resolved, datetime) and STAMP <= resolved <= datetime.now(
                UTC
            )
        device = observer.get(Device, UUID(int=1))
        assert device is not None and device.status is DeviceStatus.INACTIVE
        assert device.last_seen_at is None
        assert observer.scalar(select(func.count()).select_from(Telemetry)) == 0


@pytest.mark.parametrize("action", list(ACTIONS))
def test_missing_and_failed_write_leave_database_unchanged(
    device_engine: Engine,
    action: str,
) -> None:
    target = seed(device_engine)[0]
    with Session(device_engine) as session:
        before = snapshot(session, target)
    with Session(device_engine) as session:
        with pytest.raises(AlertNotFoundError):
            ACTIONS[action](session, uuid4())
        assert not session.in_transaction()

        def corrupt_message(
            current: Session,
            flush_context: object,
            instances: object,
        ) -> None:
            for obj in current.dirty:
                if isinstance(obj, Alert):
                    obj.message = ""  # Trigger the real CHECK during service commit.

        event.listen(session, "before_flush", corrupt_message)
        with pytest.raises(IntegrityError):
            ACTIONS[action](session, target)
        assert not session.in_transaction()
    with Session(device_engine) as observer:
        assert snapshot(observer, target) == before


def test_future_timestamp_and_repeated_resolution(device_engine: Engine) -> None:
    target = seed(device_engine)[0]
    future = datetime.now(UTC) + timedelta(days=1)
    with Session(device_engine) as session:
        row = session.get(Alert, target)
        assert row is not None
        row.triggered_at = future
        session.commit()
        assert resolve_alert(session, target).resolved_at == future
    with Session(device_engine) as session:
        assert resolve_alert(session, target).resolved_at == future


@pytest.mark.parametrize(
    "first_action,second_action",
    [
        ("resolve", "resolve"),
        ("acknowledge", "resolve"),
        ("resolve", "acknowledge"),
    ],
)
def test_concurrent_actions_wait_for_target_lock(
    device_engine: Engine,
    first_action: str,
    second_action: str,
) -> None:
    target = seed(device_engine)[0]
    pending: list[Future[tuple[str, datetime | None]]] = []
    first_resolution: list[datetime | None] = []

    def compete() -> tuple[str, datetime | None]:
        with Session(device_engine) as second:
            try:
                row = ACTIONS[second_action](second, target)
                return "success", row.resolved_at
            except InvalidAlertStateError:
                return "conflict", None

    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(device_engine) as first:
            first_pid = first.scalar(text("SELECT pg_backend_pid()"))

            def before_commit(current: Session) -> None:
                # Pause an actual service transaction after it acquired the row lock.
                current.flush()
                row = current.get(Alert, target)
                assert row is not None
                first_resolution.append(row.resolved_at)
                pending.append(executor.submit(compete))
                deadline = monotonic() + 3
                blocked = False
                with device_engine.connect() as observer:
                    while monotonic() < deadline:
                        blocked = bool(
                            observer.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE datname = current_database() "
                                    "AND :pid = ANY(pg_blocking_pids(pid))"
                                ),
                                {"pid": first_pid},
                            )
                        )
                        if blocked:
                            break
                        sleep(0.02)
                assert blocked, "The competing action never waited for the Alert lock"
                assert not pending[0].done()

            event.listen(first, "before_commit", before_commit, once=True)
            try:
                ACTIONS[first_action](first, target)
            finally:
                first.rollback()
        outcome, second_resolution = pending[0].result(timeout=10)
    assert outcome == ("conflict" if second_action == "acknowledge" else "success")
    with Session(device_engine) as observer:
        final = observer.get(Alert, target)
        assert final is not None and final.status is AlertStatus.RESOLVED
        assert final.resolved_at is not None
        if first_action == "resolve":
            assert final.resolved_at == first_resolution[0]
        if second_action == "resolve":
            assert final.resolved_at == second_resolution


def test_http_persistence_and_inactive_parent(device_engine: Engine) -> None:
    target = seed(device_engine)[0]
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            database_url=device_engine.url.render_as_string(hide_password=False),
        )
    )
    with admin_test_client(app, device_engine, raise_server_exceptions=False) as client:
        listing = client.get("/api/v1/alerts", params={"device_id": str(UUID(int=1))})
        assert listing.status_code == 200 and listing.json()["total"] == 2
        assert client.post(f"/api/v1/alerts/{target}/acknowledge").status_code == 200
        resolved = client.post(f"/api/v1/alerts/{target}/resolve")
        assert resolved.status_code == 200 and resolved.json()["resolved_at"].endswith(
            "Z"
        )
        assert client.post(f"/api/v1/alerts/{target}/resolve").json() == resolved.json()
        assert client.post(f"/api/v1/alerts/{target}/acknowledge").status_code == 409
        assert client.post(f"/api/v1/alerts/{uuid4()}/resolve").status_code == 404
        missing = client.get("/api/v1/alerts", params={"device_id": str(uuid4())})
        assert missing.status_code == 200 and missing.json()["items"] == []
        assert missing.json()["total"] == 0
    with Session(device_engine) as observer:
        row = observer.get(Alert, target)
        assert row is not None and row.status is AlertStatus.RESOLVED
