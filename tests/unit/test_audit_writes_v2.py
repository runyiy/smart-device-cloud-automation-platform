"""V2-T8 trusted audit staging and mandatory internal actor contract."""

import inspect
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from app.alerts.service import acknowledge_alert, resolve_alert
from app.audit.model import AuditLog
from app.audit.service import record_audit_event
from app.devices.service import create_device, update_device
from app.telemetry.service import ingest_telemetry
from app.test_tasks.service import create_test_task, update_test_task


def test_helper_stages_exact_fields_without_database_work() -> None:
    session = MagicMock(spec=Session)
    actor_id, resource_id = uuid4(), uuid4()
    metadata: dict[str, object] = {"fields": ["name"], "changed": False}
    with patch("app.audit.service.AuditLogRepository") as constructor:
        record_audit_event(
            session,
            actor_id=actor_id,
            action="device.updated",
            resource_type="device",
            resource_id=resource_id,
            event_metadata=metadata,
        )
    constructor.assert_called_once_with(session)
    constructor.return_value.add.assert_called_once()
    row = constructor.return_value.add.call_args.args[0]
    assert isinstance(row, AuditLog)
    assert (row.actor_id, row.action, row.resource_type, row.resource_id) == (
        actor_id,
        "device.updated",
        "device",
        resource_id,
    )
    assert row.event_metadata is metadata
    assert session.mock_calls == []


def test_helper_propagates_repository_failure() -> None:
    session = MagicMock(spec=Session)
    failure = RuntimeError("audit staging failed")
    with patch("app.audit.service.AuditLogRepository") as constructor:
        constructor.return_value.add.side_effect = failure
        with pytest.raises(RuntimeError) as caught:
            record_audit_event(
                session,
                actor_id=uuid4(),
                action="device.created",
                resource_type="device",
                resource_id=uuid4(),
                event_metadata={},
            )
    assert caught.value is failure
    assert session.mock_calls == []


@pytest.mark.parametrize(
    "operation",
    [
        create_device,
        update_device,
        ingest_telemetry,
        acknowledge_alert,
        resolve_alert,
        create_test_task,
        update_test_task,
    ],
)
def test_write_actor_is_required_keyword_only(operation: object) -> None:
    signature = inspect.signature(operation)  # type: ignore[arg-type]
    actor = signature.parameters["actor_id"]
    assert actor.kind is inspect.Parameter.KEYWORD_ONLY
    assert actor.default is inspect.Parameter.empty
    assert actor.annotation is UUID
