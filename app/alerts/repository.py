"""Alert persistence queries on a caller-owned Session.

Threshold evaluation and lifecycle decisions stay in Services.
This Repository shares the use-case Session with other participating Repositories.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.model import Alert
from app.alerts.schema import AlertListQuery


class AlertRepository:
    """Use the caller's Session without committing, rolling back or closing it."""

    def __init__(self, session: Session) -> None:
        """Retain the supplied Session without creating database resources."""
        self.session = session

    def add(self, alert: Alert) -> None:
        """Stage the supplied Alert without threshold or state decisions."""
        self.session.add(alert)

    def get(self, alert_id: UUID, *, for_update: bool = False) -> Alert | None:
        """Look up an ID, optionally locking; return None for an absent row."""
        if for_update:
            stmt = select(Alert).where(Alert.id == alert_id).with_for_update()
        else:
            stmt = select(Alert).where(Alert.id == alert_id)

        alert = self.session.scalar(stmt)
        return alert

    def list_page(self, query: AlertListQuery) -> tuple[list[Alert], int]:
        """Share exact filters between count and page with stable time/ID ordering."""
        filters = []

        if query.device_id is not None:
            filters.append(Alert.device_id == query.device_id)
        if query.status is not None:
            filters.append(Alert.status == query.status)
        if query.severity is not None:
            filters.append(Alert.severity == query.severity)
        if query.type is not None:
            filters.append(Alert.type == query.type)

        stmt = select(Alert).where(*filters)

        count_stmt = select(func.count()).select_from(Alert).where(*filters)

        total = int(self.session.scalar(count_stmt) or 0)

        if query.sort_order == "asc":
            stmt = stmt.order_by(
                Alert.triggered_at.asc(),
                Alert.id.asc(),
            )
        else:
            stmt = stmt.order_by(
                Alert.triggered_at.desc(),
                Alert.id.desc(),
            )

        offset = (query.page - 1) * query.page_size
        stmt = stmt.offset(offset).limit(query.page_size)

        alerts = list(self.session.scalars(stmt).all())

        return alerts, total

    def refresh(self, alert: Alert) -> None:
        """Reload stored values without finalizing the transaction."""
        self.session.refresh(alert)
