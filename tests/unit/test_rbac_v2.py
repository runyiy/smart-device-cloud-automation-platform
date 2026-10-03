"""V2-T6 role configuration and exact-principal boundaries."""

from typing import cast

import pytest
from fastapi import HTTPException

from app.auth.authorization import require_roles
from app.users.model import User, UserRole


@pytest.mark.parametrize(
    "allowlist",
    [
        (UserRole.ADMIN,),
        (UserRole.ADMIN, UserRole.OPERATOR),
        tuple(UserRole),
    ],
)
@pytest.mark.parametrize("role", list(UserRole))
def test_explicit_allowlists_return_same_user_or_403(
    allowlist: tuple[UserRole, ...],
    role: UserRole,
) -> None:
    user = User(role=role)
    checker = require_roles(*allowlist)
    if role in allowlist:
        assert checker(user) is user
    else:
        with pytest.raises(HTTPException) as denied:
            checker(user)
        assert denied.value.status_code == 403
        assert not denied.value.headers


@pytest.mark.parametrize(
    "allowlist",
    [
        (),
        ("admin",),
        (None,),
        (1,),
        (UserRole.ADMIN, "viewer"),
    ],
)
def test_invalid_configuration_rejects_at_factory_creation(
    allowlist: tuple[object, ...],
) -> None:
    with pytest.raises((ValueError, TypeError)):
        require_roles(*(cast(UserRole, role) for role in allowlist))


def test_no_implicit_admin_bypass_or_unknown_role_fallback() -> None:
    checker = require_roles(UserRole.VIEWER)
    for role in (UserRole.ADMIN, None, "unknown"):
        with pytest.raises(HTTPException) as denied:
            checker(User(role=role))
        assert denied.value.status_code == 403
