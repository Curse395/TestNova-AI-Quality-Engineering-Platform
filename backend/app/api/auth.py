from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.shemas.user_schema import UserCreate, UserLogin
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    service = AuthService(db)
    try:
        return service.register_user(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login")
def login(data: UserLogin, db: Session = Depends(get_db)) -> dict[str, object]:
    service = AuthService(db)
    try:
        return service.login_user(data)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc