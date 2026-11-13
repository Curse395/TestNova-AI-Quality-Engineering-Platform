from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.rate_limit import limit_requests
from app.database.connection import get_db
from app.schemas.user_schema import UserCreate, UserLogin
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    dependencies=[Depends(limit_requests("auth-register", limit=5, window_seconds=60))],
)
def register(data: UserCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    service = AuthService(db)
    try:
        payload = service.register_user(data)
        return {
            "success": True,
            "message": "Registration completed successfully",
            "data": payload,
            "errors": None,
            **payload,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/login",
    dependencies=[Depends(limit_requests("auth-login", limit=10, window_seconds=60))],
)
def login(data: UserLogin, db: Session = Depends(get_db)) -> dict[str, object]:
    service = AuthService(db)
    try:
        payload = service.login_user(data)
        return {
            "success": True,
            "message": "Login completed successfully",
            "data": payload,
            "errors": None,
            **payload,
        }
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
