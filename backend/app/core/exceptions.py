import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette import status
from starlette.responses import JSONResponse

from app.core.error_codes import TestNovaErrorCodes
from app.core.responses import ErrorDetail, error_response

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        code = TestNovaErrorCodes.RESOURCE_NOT_FOUND if exc.status_code == status.HTTP_404_NOT_FOUND else TestNovaErrorCodes.AUTHENTICATION_FAILED if exc.status_code == status.HTTP_401_UNAUTHORIZED else TestNovaErrorCodes.INTERNAL_SERVER_ERROR
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            code = TestNovaErrorCodes.VALIDATION_ERROR
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            code = TestNovaErrorCodes.AUTHENTICATION_FAILED

        payload = error_response(
            message=detail,
            data=None,
            errors=[ErrorDetail(code=code, field=None, detail=detail)],
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        payload = error_response(
            message="Validation failed",
            data=None,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=payload.model_dump())

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error(
            "Database operation failed: path=%s error_type=%s",
            request.url.path,
            type(exc).__name__,
        )
        payload = error_response(
            message="Database operation failed",
            data=None,
            errors=[ErrorDetail(code=TestNovaErrorCodes.INTERNAL_SERVER_ERROR, field=None, detail="Database operation failed")],
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        payload = error_response(
            message="Internal server error",
            data=None,
            errors=[ErrorDetail(code=TestNovaErrorCodes.INTERNAL_SERVER_ERROR, field=None, detail="Internal server error")],
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=payload.model_dump())
