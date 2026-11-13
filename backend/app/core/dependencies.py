from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.security import ALGORITHM
from app.database.connection import get_db
from app.models.user import User

security = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "Invalid or expired token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Authentication required")

    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[ALGORITHM],
            options={
                "require_exp": True,
                "require_iat": True,
                "require_sub": True,
            },
        )
    except (JWTError, TypeError, ValueError) as exc:
        raise _unauthorized() from exc

    subject = payload.get("sub")
    user_id = payload.get("user_id")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    now = int(datetime.now(timezone.utc).timestamp())
    if (
        not isinstance(subject, str)
        or not subject.isascii()
        or not subject.isdecimal()
        or subject.startswith("0")
        or isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or subject != str(user_id)
        or user_id < 1
        or payload.get("token_use") != "access"
        or isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or issued_at > now + 60
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at <= now
    ):
        raise _unauthorized("Invalid token claims")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or getattr(user, "is_active", True) is False:
        raise _unauthorized()

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
