from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext
from passlib.exc import UnknownHashError

from app.core.config import settings

pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    deprecated=["bcrypt"],
)

ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(hours=24)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except (UnknownHashError, TypeError, ValueError):
        return False


def create_access_token(data: dict[str, object]) -> str:
    user_id = data.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise ValueError("An access token requires a positive integer user_id")

    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "token_use": "access",
        "iat": issued_at,
        "exp": issued_at + ACCESS_TOKEN_LIFETIME,
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=ALGORITHM,
        headers={"typ": "JWT"},
    )