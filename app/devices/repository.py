"""Device persistence queries on a caller-owned Session.

Business decisions belong to Services; write finalization belongs to the
use-case transaction boundary. Reads and refresh never finalize transactions.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.devices.model import Device
from app.devices.schema import DeviceListQuery


class DeviceRepository:
    """Use one caller-owned Session; never commit, roll back, or close it."""

    def __init__(self, session: Session) -> None:
        """Retain the supplied Session without creating database resources."""
        self.session = session

    def add(self, device: Device) -> None:
        """Stage the supplied entity; let the caller flush or finalize its write."""
        self.session.add(device)

    def get(self, device_id: UUID, *, for_update: bool = False) -> Device | None:
        """Look up an ID, optionally locking until the caller ends its transaction."""
        if for_update:
            stmt = select(Device).where(Device.id == device_id).with_for_update()
        else:
            stmt = select(Device).where(Device.id == device_id)

        device = self.session.scalar(stmt)
        return device

    def list_page(self, query: DeviceListQuery) -> tuple[list[Device], int]:
        """Return an exactly filtered page, stable ordering and pre-pagination total."""
        filters = []

        if query.status is not None:
            filters.append(Device.status == query.status)

        if query.model is not None:
            filters.append(Device.model == query.model)

        if query.serial_number is not None:
            filters.append(Device.serial_number == query.serial_number)

        stmt = select(Device).where(*filters)

        count_stmt = select(func.count()).select_from(Device).where(*filters)

        total = int(self.session.scalar(count_stmt) or 0)

        sort_columns = {
            "created_at": Device.created_at,
            "serial_number": Device.serial_number,
        }

        sort_column = sort_columns[query.sort_by]

        if query.sort_order == "asc":
            stmt = stmt.order_by(
                sort_column.asc(),
                Device.id.asc(),
            )
        else:
            stmt = stmt.order_by(
                sort_column.desc(),
                Device.id.desc(),
            )

        offset = (query.page - 1) * query.page_size
        stmt = stmt.offset(offset).limit(query.page_size)

        devices = list(self.session.scalars(stmt).all())

        return devices, total

    def refresh(self, device: Device) -> None:
        """Reload persisted values without finalizing or owning the transaction."""
        self.session.refresh(device)
