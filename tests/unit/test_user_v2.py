"""V2-T4 User metadata and caller-owned persistence contracts."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    String,
    Table,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.base import Base
from app.users.model import User, UserRole
from app.users.repository import UserRepository


def test_user_model_contract() -> None:
    table = User.__table__
    assert isinstance(table, Table)
    assert table.metadata is Base.metadata
    assert list(table.columns.keys()) == [
        "id",
        "email",
        "password_hash",
        "is_active",
        "role",
        "created_at",
    ]
    assert all(not column.nullable for column in table.columns)
    assert all(column.onupdate is None for column in table.columns)
    assert table.c.id.primary_key and table.c.id.type.python_type is type(uuid4())
    assert table.c.id.default is not None and table.c.id.default.is_callable
    assert table.c.id.server_default is None
    assert isinstance(table.c.email.type, String)
    assert table.c.email.type.length == 254
    assert isinstance(table.c.password_hash.type, String)
    assert table.c.password_hash.type.length == 255
    assert table.c.email.default is None and table.c.password_hash.default is None
    assert getattr(table.c.is_active.default, "arg", None) is True
    assert str(getattr(table.c.is_active.server_default, "arg", None)) == "true"
    assert getattr(table.c.role.default, "arg", None) is UserRole.VIEWER
    assert str(getattr(table.c.role.server_default, "arg", None)) == "viewer"
    assert isinstance(table.c.role.type, Enum)
    assert table.c.role.type.length == 8 and not table.c.role.type.native_enum
    assert set(table.c.role.type.enums) == {"admin", "operator", "viewer"}
    assert isinstance(table.c.created_at.type, DateTime)
    assert table.c.created_at.type.timezone
    assert table.c.created_at.default is None
    assert (
        str(getattr(table.c.created_at.server_default, "arg", None))
        == "CURRENT_TIMESTAMP"
    )
    assert {role.value for role in UserRole} == {"admin", "operator", "viewer"}
    assert {
        item.name for item in table.constraints if isinstance(item, CheckConstraint)
    } == {
        "ck_users_email_normalized",
        "ck_users_password_hash_non_empty",
        "ck_users_role_valid",
    }
    uniques = [item for item in table.constraints if isinstance(item, UniqueConstraint)]
    assert len(uniques) == 1 and uniques[0].name == "uq_users_email"
    assert list(uniques[0].columns.keys()) == ["email"]
    assert not table.indexes and not inspect(User).relationships


@pytest.mark.parametrize("for_update", [False, True])
def test_repository_delegates_without_owning_transaction(for_update: bool) -> None:
    session = MagicMock(spec=Session)
    row = User(id=uuid4(), email="a@example.test", password_hash="opaque")
    session.scalar.return_value = row
    repo = UserRepository(session)
    assert repo.session is session
    repo.add(row)
    assert repo.get(row.id, for_update=for_update) is row
    assert ("FOR UPDATE" in str(session.scalar.call_args.args[0])) is for_update
    repo.refresh(row)
    session.add.assert_called_once_with(row)
    session.refresh.assert_called_once_with(row)
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()


@pytest.mark.parametrize("email", ["a@example.test", " A@Example.Test "])
def test_email_lookup_preserves_exact_input_and_propagates_database_error(
    email: str,
) -> None:
    session = MagicMock(spec=Session)
    session.scalar.return_value = None
    repo = UserRepository(session)
    assert repo.get_by_email(email) is None
    query = session.scalar.call_args.args[0]
    assert list(query.compile().params.values()) == [email]
    assert "FOR UPDATE" not in str(query) and "is_active =" not in str(query)
    error = OperationalError("injected", {}, RuntimeError("injected"))
    session.scalar.side_effect = error
    with pytest.raises(OperationalError) as caught:
        repo.get_by_email(email)
    assert caught.value is error
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    session.close.assert_not_called()
