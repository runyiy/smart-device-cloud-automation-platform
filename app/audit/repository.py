"""Minimal audit persistence on the caller-owned Session."""

from sqlalchemy.orm import Session

from app.audit.model import AuditLog


class AuditLogRepository:
    """Stage supplied events; callers own safe metadata and transaction outcomes.

    No HTTP identity lookup, permission decision, event/payload extraction,
    querying, mutation API or Session finalization belongs in this repository.
    """

    def __init__(self, session: Session) -> None:
        """Retain the exact caller-owned Session without creating resources."""
        self.session = session

    def add(self, audit_log: AuditLog) -> None:
        """Stage the supplied row only; do not flush/commit/rollback/close.

        Use the same Session as the owning use case. Propagate persistence errors
        to that boundary; no independent transaction or best-effort fallback.
        """
        self.session.add(audit_log)
