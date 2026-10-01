"""V2-T2 Alert Repository queries, locks and post-commit read-back checks."""

from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertStatus
from app.alerts.repository import AlertRepository
from app.alerts.schema import AlertListQuery
from app.alerts.service import acknowledge_alert, resolve_alert
from tests.integration.test_alert_t8 import seed
from tests.integration.test_devices import device_engine as device_engine


def test_repository_filters_totals_ties_and_missing_targets(
    device_engine: Engine,
) -> None:
    ids = seed(device_engine)
    with Session(device_engine) as session:
        repo = AlertRepository(session)
        for direction, expected in (("asc", ids), ("desc", ids[::-1])):
            for page in (1, 2, 3):
                rows, total = repo.list_page(
                    AlertListQuery(
                        sort_order=direction,
                        page=page,
                        page_size=2,
                    )
                )
                start = (page - 1) * 2
                assert [row.id for row in rows] == expected[start : start + 2]
                assert total == 4
        rows, total = repo.list_page(
            AlertListQuery(
                device_id=UUID(int=1),
                status="open",
                severity="critical",
                type="temperature_high",
            )
        )
        assert [row.id for row in rows] == ids[:1] and total == 1
        assert repo.list_page(AlertListQuery(device_id=UUID(int=99))) == ([], 0)
        assert repo.list_page(AlertListQuery(type="Temperature_high")) == ([], 0)
        rows, total = repo.list_page(AlertListQuery(severity="critical", page=9))
        assert rows == [] and total == 2
        assert repo.get(UUID(int=99)) is None
        assert repo.get(UUID(int=99), for_update=True) is None


def test_alert_repository_lock_ends_only_with_caller_transaction(
    device_engine: Engine,
) -> None:
    alert_id = seed(device_engine)[0]
    with Session(device_engine) as owner, Session(device_engine) as competitor:
        assert AlertRepository(owner).get(alert_id, for_update=True) is not None
        assert AlertRepository(competitor).get(alert_id) is not None
        competitor.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as caught:
            AlertRepository(competitor).get(alert_id, for_update=True)
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        competitor.rollback()
        owner.rollback()
        assert AlertRepository(competitor).get(alert_id, for_update=True) is not None


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
def test_action_readback_failure_preserves_durable_state_and_retry_timestamp(
    device_engine: Engine, action: str
) -> None:
    alert_id = seed(device_engine)[0]
    operation = acknowledge_alert if action == "acknowledge" else resolve_alert
    error = OperationalError("refresh", {}, Exception("injected"))
    with Session(device_engine) as session:
        assert AlertRepository(session).get(alert_id) is not None

        def fail_refresh(instance: object) -> None:
            session.execute(text("SELECT 1"))
            raise error

        with patch.object(session, "refresh", side_effect=fail_refresh):
            with pytest.raises(OperationalError) as caught:
                operation(session, alert_id)
        assert caught.value is error
        assert not session.in_transaction()
        with Session(device_engine) as observer:
            row = observer.get(Alert, alert_id)
            assert row is not None
            assert row.status == (
                AlertStatus.ACKNOWLEDGED
                if action == "acknowledge"
                else AlertStatus.RESOLVED
            )
            stamp = row.resolved_at
        retried = operation(session, alert_id)
        assert retried.resolved_at == stamp
