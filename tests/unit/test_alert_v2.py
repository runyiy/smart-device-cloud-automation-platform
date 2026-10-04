"""V2-T2 Alert Service Repository and transaction boundary contracts."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.alerts.model import Alert, AlertStatus
from app.alerts.repository import AlertRepository
from app.alerts.schema import AlertListQuery
from app.alerts.service import acknowledge_alert, list_alerts, resolve_alert


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
def test_actions_lock_and_refresh_through_same_repository_session(action: str) -> None:
    session = MagicMock(spec=Session)
    row = Alert(
        id=uuid4(),
        status=AlertStatus.OPEN,
        triggered_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.scalar.return_value = row
    operation = acknowledge_alert if action == "acknowledge" else resolve_alert
    with (
        patch.object(
            AlertRepository, "get", autospec=True, side_effect=AlertRepository.get
        ) as get,
        patch.object(
            AlertRepository,
            "refresh",
            autospec=True,
            side_effect=AlertRepository.refresh,
        ) as refresh,
    ):
        assert operation(session, row.id, actor_id=uuid4()) is row
        get.assert_called_once()
        assert get.call_args.kwargs == {"for_update": True}
        assert get.call_args.args[0].session is session
        refresh.assert_called_once()
        assert refresh.call_args.args[0].session is session
        assert refresh.call_args.args[1] is row
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("action", ["acknowledge", "resolve"])
@pytest.mark.parametrize("failure_at", ["query", "commit"])
def test_actions_clean_up_unexpected_failures(action: str, failure_at: str) -> None:
    session = MagicMock(spec=Session)
    row = Alert(
        id=uuid4(),
        status=AlertStatus.OPEN,
        triggered_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    session.scalar.return_value = row
    error = RuntimeError("injected")
    getattr(
        session, "scalar" if failure_at == "query" else "commit"
    ).side_effect = error
    operation = acknowledge_alert if action == "acknowledge" else resolve_alert
    with pytest.raises(RuntimeError) as caught:
        operation(session, row.id, actor_id=uuid4())
    assert caught.value is error
    session.rollback.assert_called_once()
    session.refresh.assert_not_called()
    session.close.assert_not_called()


def test_alert_collection_delegates_without_committing() -> None:
    session = MagicMock(spec=Session)
    query = AlertListQuery(device_id=uuid4())
    with patch.object(AlertRepository, "list_page", autospec=True) as page:
        page.return_value = ([], 0)
        assert list_alerts(session, query) == ([], 0)
        assert page.call_args.args[0].session is session
        assert page.call_args.args[1] is query
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()
