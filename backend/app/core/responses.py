from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    field: str | None = None
    detail: str


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Any | None = None
    errors: list[ErrorDetail] | None = Field(default=None)


def success_response(data: Any = None, message: str = "Request completed successfully") -> ApiResponse:
    
    return ApiResponse(
    success=True,
    message=message,
    data=data,
    errors=None,)


def error_response(
    message: str,
    errors: list[ErrorDetail] | None = None,
    data: Any = None,
) -> ApiResponse:
    
    return ApiResponse(
    success=False,
    message=message,
    data=data,
    errors=errors,
)