"""Transport schemas used by the V0-T2 system endpoints."""

from typing import Literal

from pydantic import BaseModel


class PingResponse(BaseModel):
    """Response contract for the versioned ping endpoint."""

    message: Literal["pong"]
