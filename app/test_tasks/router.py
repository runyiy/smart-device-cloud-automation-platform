"""Task HTTP handlers with sanitized domain-error mapping."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette import status

from app.api.dependencies import get_db_session
from app.api.errors import ErrorResponse
from app.auth.authorization import require_roles
from app.devices.service import DeviceNotFoundError
from app.test_tasks.schema import TestTaskCreate, TestTaskRead, TestTaskUpdate
from app.test_tasks.service import (
    InactiveDeviceError,
    InvalidTestTaskStateError,
    TestTaskNotFoundError,
    create_test_task,
    get_test_task,
    update_test_task,
)
from app.users.model import UserRole

router = APIRouter(prefix="/test-tasks", tags=["test-tasks"])


@router.post(
    "",
    response_model=TestTaskRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN,
                UserRole.OPERATOR,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
def register_test_task(
    data: TestTaskCreate,
    session: Annotated[Session, Depends(get_db_session)],
) -> TestTaskRead:
    """Create a task with HTTP 201 and map Device eligibility failures."""
    try:
        test_task = create_test_task(session=session, data=data)
        return TestTaskRead.model_validate(test_task)

    except DeviceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc

    except InactiveDeviceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc


@router.get(
    "/{task_id}",
    response_model=TestTaskRead,
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN,
                UserRole.OPERATOR,
                UserRole.VIEWER,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
def read_test_task(
    task_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> TestTaskRead:
    """Return task details or a sanitized missing-target response."""
    try:
        test_task = get_test_task(session=session, task_id=task_id)

        return TestTaskRead.model_validate(test_task)

    except TestTaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc


@router.patch(
    "/{task_id}",
    response_model=TestTaskRead,
    dependencies=[
        Depends(
            require_roles(
                UserRole.ADMIN,
                UserRole.OPERATOR,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
def patch_test_task(
    task_id: UUID,
    data: TestTaskUpdate,
    session: Annotated[Session, Depends(get_db_session)],
) -> TestTaskRead:
    """Delegate supplied task changes and map missing/conflicting states."""
    try:
        test_task = update_test_task(session=session, task_id=task_id, data=data)
        return TestTaskRead.model_validate(test_task)

    except TestTaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc

    except InvalidTestTaskStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
