"""Telemetry persistence queries on a caller-owned Session.

Persistence contracts are recorded in CURRENT_STAGE.md.
The calling Service owns Device validation, watermark changes and transactions.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.telemetry.model import Telemetry
from app.telemetry.schema import TelemetryListQuery


class TelemetryRepository:
    """Use the caller's Session without committing, rolling back or closing it."""

    def __init__(self, session: Session) -> None:
        """Retain the supplied Session without creating database resources."""
        self.session = session

    def add(self, telemetry: Telemetry) -> None:
        """Stage a supplied sample without evaluating thresholds or finalizing."""
        self.session.add(telemetry)

    def list_page(
        self, device_id: UUID, query: TelemetryListQuery
    ) -> tuple[list[Telemetry], int]:
        """Scope count and page to Device, exact filters and stable time/ID order."""

        filters = [
            Telemetry.device_id == device_id,
        ]

        if query.metric is not None:
            filters.append(Telemetry.metric == query.metric)

        if query.from_time is not None:
            filters.append(Telemetry.recorded_at >= query.from_time)

        if query.to_time is not None:
            filters.append(Telemetry.recorded_at <= query.to_time)

        stmt = select(Telemetry).where(*filters)

        count_stmt = select(func.count()).select_from(Telemetry).where(*filters)

        total = int(self.session.scalar(count_stmt) or 0)

        if query.sort_order == "asc":
            stmt = stmt.order_by(
                Telemetry.recorded_at.asc(),
                Telemetry.id.asc(),
            )
        else:
            stmt = stmt.order_by(
                Telemetry.recorded_at.desc(),
                Telemetry.id.desc(),
            )

        offset = (query.page - 1) * query.page_size
        stmt = stmt.offset(offset).limit(query.page_size)

        telemetries = list(self.session.scalars(stmt).all())

        return telemetries, total

    def refresh(self, telemetry: Telemetry) -> None:
        """Reload stored values without finalizing the transaction."""
        self.session.refresh(telemetry)
