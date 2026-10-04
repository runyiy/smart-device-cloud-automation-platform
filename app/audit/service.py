"""Trusted audit staging contract; business Services own atomic write outcomes.

Business Services call this helper before their existing transaction commits.
They own metadata allowlists and the seven operation mappings in CURRENT_STAGE.md.
"""

from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.model import AuditLog
from app.audit.repository import AuditLogRepository

AuditAction = Literal[
    "device.created",
    "device.updated",
    "telemetry.ingested",
    "alert.acknowledged",
    "alert.resolved",
    "test_task.created",
    "test_task.updated",
]
AuditResourceType = Literal["device", "telemetry", "alert", "test_task"]


def record_audit_event(
    session: Session,
    *,
    actor_id: UUID,
    action: AuditAction,
    resource_type: AuditResourceType,
    resource_id: UUID,
    event_metadata: dict[str, object],
) -> None:
    """Stage one trusted AuditLog through the caller's Repository and Session.

    Caller supplies a trusted actor, a materialized target UUID and explicitly
    allowlisted metadata, inside its existing business transaction. This helper
    does not flush, query, validate permissions, commit, roll back or close.
    Propagate failures so the owning use case can roll back business and audit.
    Never capture a request, credentials, an ORM dictionary or arbitrary payload.
    """
    repo_audit = AuditLogRepository(session)
    audit_log = AuditLog(
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        event_metadata=event_metadata,
    )
    repo_audit.add(audit_log)
