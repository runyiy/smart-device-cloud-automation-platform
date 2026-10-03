"""Fixed-role HTTP dependencies over the authenticated database User."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException
from starlette import status

from app.auth.dependencies import get_current_user
from app.users.model import User, UserRole


def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Build a FastAPI dependency over the accepted get_current_user.

    Empty/invalid role configuration is rejected at factory creation, before
    returning the per-request checker.
    The returned callable takes User through Depends(get_current_user), checks
    its current database role against the explicit allowlist and returns the
    same User on success. An authenticated denied User receives HTTP 403;
    authentication failures retain the existing HTTP 401/Bearer contract.

    No implicit admin bypass, Session creation/finalization, business query,
    write lock, role hierarchy, token-role lookup or audit write belongs here.
    Business Routers call this factory for each protected operation.
    """
    if not allowed_roles:
        raise ValueError("At least one allowed role is required")

    for role in allowed_roles:
        if not isinstance(role, UserRole):
            raise TypeError("Allowed roles must be UserRole values")

    def dependency(
        current_user: Annotated[
            User,
            Depends(get_current_user),
        ],
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
            )

        return current_user

    return dependency
