"""Request authentication over the application-owned context."""

from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from starlette import status

from app.api.dependencies import get_db_session
from app.auth.security import AuthConfig
from app.auth.service import AuthenticationError, resolve_current_user
from app.users.model import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_config(request: Request) -> AuthConfig:
    """Return the validated context on request.app.state.auth_config."""
    return cast(
        AuthConfig,
        request.app.state.auth_config,
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[Session, Depends(get_db_session)],
    config: Annotated[AuthConfig, Depends(get_auth_config)],
) -> User:
    """Resolve bearer identity; expected denial is 401 plus Bearer challenge.

    Missing/wrong/invalid credentials share the existing sanitized error envelope.
    No business-route RBAC or caller-owned Session finalization belongs here.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return resolve_current_user(
            session,
            credentials.credentials,
            config=config,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
