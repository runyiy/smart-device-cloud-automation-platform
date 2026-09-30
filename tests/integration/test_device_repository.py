"""V2-T1 Repository and transaction acceptance on guarded migrated PostgreSQL."""

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError

from app.db.session import create_session_factory
from app.devices.model import Device
from app.devices.repository import DeviceRepository
from app.devices.schema import DeviceCreate, DeviceListQuery, DeviceUpdate
from app.devices.service import (
    DuplicateSerialNumberError,
    create_device,
    update_device,
)
from tests.integration.test_device_t3 import seed
from tests.integration.test_devices import device_engine as device_engine


def new_device(serial: str = "REPO-1") -> Device:
    return Device(
        id=uuid4(),
        serial_number=serial,
        name="Original",
        model="M1",
        firmware_version="v1",
    )


def test_repository_leaves_commit_and_rollback_to_caller(device_engine: Engine) -> None:
    factory = create_session_factory(device_engine)
    for should_commit in (False, True):
        row = new_device(f"REPO-{should_commit}")
        row_id = row.id
        with factory() as session:
            repo = DeviceRepository(session)
            with (
                patch.object(session, "commit", wraps=session.commit) as commit,
                patch.object(session, "rollback", wraps=session.rollback) as rollback,
                patch.object(session, "close", wraps=session.close) as close,
            ):
                repo.add(row)
                session.flush()
                repo.refresh(row)
                assert repo.get(row_id) is row
                assert repo.get(UUID(int=999)) is None
                assert repo.get(UUID(int=999), for_update=True) is None
                page, total = repo.list_page(DeviceListQuery())
                assert [item.id for item in page] == [row_id] and total == 1
                assert row.created_at is not None and row.status == "active"
                commit.assert_not_called()
                rollback.assert_not_called()
                close.assert_not_called()
            with factory() as observer:
                assert observer.get(Device, row_id) is None
            if should_commit:
                session.commit()
            else:
                session.rollback()
        with factory() as observer:
            assert (observer.get(Device, row_id) is not None) is should_commit


def test_repository_exact_filters_total_and_tied_order(device_engine: Engine) -> None:
    ids = seed(device_engine)
    with create_session_factory(device_engine)() as session:
        repo = DeviceRepository(session)
        for column in ("created_at", "serial_number"):
            for direction, expected in (("asc", ids), ("desc", ids[::-1])):
                for page in (1, 2, 3):
                    rows, total = repo.list_page(
                        DeviceListQuery(
                            sort_by=column, sort_order=direction, page=page, page_size=2
                        )
                    )
                    start = (page - 1) * 2
                    assert [row.id for row in rows] == expected[start : start + 2]
                    assert total == 3
        cases = [
            (DeviceListQuery(model="M1"), ids[:2][::-1], 2),
            (DeviceListQuery(status="inactive"), [ids[1]], 1),
            (DeviceListQuery(serial_number="SN-3"), [ids[2]], 1),
            (
                DeviceListQuery(model="M1", status="inactive", serial_number="SN-2"),
                [ids[1]],
                1,
            ),
            (DeviceListQuery(model="M1", status="active", serial_number="SN-2"), [], 0),
            (DeviceListQuery(model="m1"), [], 0),
            (DeviceListQuery(serial_number="sn-1"), [], 0),
            (DeviceListQuery(model="M1", page=9), [], 2),
        ]
        for query, expected, expected_total in cases:
            rows, total = repo.list_page(query)
            assert [row.id for row in rows] == expected
            assert total == expected_total


def test_repository_lock_lasts_until_caller_finishes(device_engine: Engine) -> None:
    device_id = seed(device_engine)[0]
    factory = create_session_factory(device_engine)
    with factory() as owner, factory() as competitor:
        assert DeviceRepository(owner).get(device_id, for_update=True) is not None
        # Ordinary reads remain possible, while a second row lock must wait.
        assert DeviceRepository(competitor).get(device_id) is not None
        competitor.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as caught:
            DeviceRepository(competitor).get(device_id, for_update=True)
        assert getattr(caught.value.orig, "sqlstate", None) == "55P03"
        competitor.rollback()
        owner.rollback()
        assert DeviceRepository(competitor).get(device_id, for_update=True) is not None


@pytest.mark.parametrize("operation", ["create", "update"])
def test_post_commit_refresh_failure_keeps_write_and_cleans_read_transaction(
    device_engine: Engine, operation: str
) -> None:
    device_id = seed(device_engine)[0]
    factory = create_session_factory(device_engine)
    error = OperationalError("refresh", {}, Exception("injected"))
    with factory() as session:
        # A prerequisite read deliberately exercises an existing autobegin.
        assert DeviceRepository(session).get(device_id) is not None

        def fail_refresh(instance: object) -> None:
            session.execute(text("SELECT 1"))
            raise error

        with patch.object(session, "refresh", side_effect=fail_refresh):
            with pytest.raises(OperationalError) as caught:
                if operation == "create":
                    create_device(
                        session,
                        DeviceCreate(
                            serial_number="AFTER-COMMIT",
                            name="Persisted",
                            model="M1",
                            firmware_version="v1",
                        ),
                    )
                else:
                    update_device(session, device_id, DeviceUpdate(name="Persisted"))
        assert caught.value is error
        assert not session.in_transaction()
        with factory() as observer:
            if operation == "create":
                persisted = observer.scalar(
                    select(Device).where(Device.serial_number == "AFTER-COMMIT")
                )
            else:
                persisted = observer.get(Device, device_id)
            assert persisted is not None and persisted.name == "Persisted"
        assert session.scalar(text("SELECT 1")) == 1


@pytest.mark.parametrize("operation", ["create", "update"])
def test_unexpected_flush_failure_rolls_back_and_allows_session_reuse(
    device_engine: Engine, operation: str
) -> None:
    device_id = seed(device_engine)[0]
    factory = create_session_factory(device_engine)
    error = RuntimeError("injected flush failure")
    with factory() as session:
        assert DeviceRepository(session).get(device_id) is not None
        with patch.object(session, "flush", side_effect=error):
            with pytest.raises(RuntimeError) as caught:
                if operation == "create":
                    create_device(
                        session,
                        DeviceCreate(
                            serial_number="MUST-NOT-PERSIST",
                            name="Rejected",
                            model="M1",
                            firmware_version="v1",
                        ),
                    )
                else:
                    update_device(session, device_id, DeviceUpdate(name="Rejected"))
        assert caught.value is error
        assert not session.in_transaction(), "Failed use case left its transaction open"
        assert not session.new and not session.dirty
        create_device(
            session,
            DeviceCreate(
                serial_number="REUSED",
                name="Allowed",
                model="M1",
                firmware_version="v1",
            ),
        )
        with factory() as observer:
            row = observer.get(Device, device_id)
            assert row is not None and row.name == "Original"
            assert (
                observer.scalar(
                    select(Device).where(Device.serial_number == "MUST-NOT-PERSIST")
                )
                is None
            )
            assert (
                observer.scalar(select(Device).where(Device.serial_number == "REUSED"))
                is not None
            )


def test_unique_conflict_leaves_session_reusable(device_engine: Engine) -> None:
    seed(device_engine)
    factory = create_session_factory(device_engine)
    with factory() as session:
        with pytest.raises(DuplicateSerialNumberError):
            create_device(
                session,
                DeviceCreate(
                    serial_number="SN-1",
                    name="Duplicate",
                    model="M1",
                    firmware_version="v1",
                ),
            )
        assert not session.in_transaction()
        assert not session.new and not session.dirty
        saved = create_device(
            session,
            DeviceCreate(
                serial_number="AFTER-CONFLICT",
                name="Allowed",
                model="M1",
                firmware_version="v1",
            ),
        )
        with factory() as observer:
            assert observer.get(Device, saved.id) is not None
