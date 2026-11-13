import logging

from sqlalchemy.orm import Session
from app.models.organization import Organization
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user_schema import UserCreate, UserLogin, UserResponse

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register_user(self, data: UserCreate) -> dict[str, object]:
        existing_user = self.db.query(User).filter(User.email == data.email).first()
        if existing_user:
            raise ValueError("Unable to register with the provided details")

        try:
            user = User(
                name=data.name,
                email=data.email,
                password_hash=hash_password(data.password),
            )
            self.db.add(user)
            self.db.flush()

            organization = Organization(
                name=data.workspace_name,
                owner_id=user.id,
            )
            self.db.add(organization)
            self.db.commit()
            self.db.refresh(user)
            self.db.refresh(organization)
            logger.info(
                "User registration completed: user_id=%s organization_id=%s",
                user.id,
                organization.id,
            )
        except Exception:
            self.db.rollback()
            raise

        return {
            "message": "Account successfully created",
            "user": UserResponse(
                id=user.id,
                name=user.name,
                email=user.email,
            ),
            "workspace":{
                "id":organization.id,
                "name":organization.name,
            },
        }

    def login_user(self, data: UserLogin) -> dict[str, object]:
        user = self.db.query(User).filter(User.email == data.email).first()
        if user is None:
            hash_password(data.password)
            logger.warning("Authentication failed: reason=invalid_credentials")
            raise ValueError("Invalid credentials")
        if not verify_password(data.password, user.password_hash):
            logger.warning("Authentication failed: reason=invalid_credentials")
            raise ValueError("Invalid credentials")
        if getattr(user, "is_active", True) is False:
            logger.warning("Authentication failed: reason=invalid_credentials")
            raise ValueError("Invalid credentials")

        token = create_access_token({"user_id": user.id})
        logger.info("Authentication succeeded: user_id=%s", user.id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": UserResponse(
                id=user.id,
                name=user.name,
                email=user.email,
            ),
        }
