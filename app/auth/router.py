"""Login and current-user HTTP adapters under the versioned API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette import status

from app.api.dependencies import get_db_session
from app.api.errors import ErrorResponse
from app.auth.dependencies import get_auth_config, get_current_user
from app.auth.schema import CurrentUserRead, LoginRequest, TokenResponse
from app.auth.security import AuthConfig
from app.auth.service import AuthenticationError, login
from app.users.model import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
        },
    },
)
def login_user(
    data: LoginRequest,
    session: Annotated[Session, Depends(get_db_session)],
    config: Annotated[AuthConfig, Depends(get_auth_config)],
) -> TokenResponse:
    """Delegate login; map AuthenticationError to 401 with Bearer challenge."""
    try:
        return login(
            session=session,
            data=data,
            config=config,
        )

    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.get(
    "/me",
    response_model=CurrentUserRead,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    },
)
def read_current_user(
    user: Annotated[User, Depends(get_current_user)],
) -> CurrentUserRead:
    """Serialize the resolved User through the explicit public allowlist."""
    return CurrentUserRead.model_validate(user)
