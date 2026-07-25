from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.responses import ApiResponse, success_response
from app.database.connection import get_db
from app.shemas.user_schema import UserCreate, UserLogin
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register")
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


@router.post("/login")
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