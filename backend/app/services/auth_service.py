from sqlalchemy.orm import Session
from app.models.organization import Organization
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.shemas.user_schema import UserCreate, UserLogin, UserResponse


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def register_user(self, data: UserCreate) -> dict[str, object]:
        existing_user = self.db.query(User).filter(User.email == data.email).first()
        if existing_user:
            raise ValueError("This e-mail is already registered")

        user = User(
            name=data.name,
            email=data.email,
            password_hash=hash_password(data.password),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        organization=Organization(
            name=data.workspace_name,
            owner_id=user.id,
        )
        self.db.add(organization)
        self.db.commit()
        self.db.refresh(organization)

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
        if not user or not verify_password(data.password, user.password_hash):
            raise ValueError("Invalid credentials")

        token = create_access_token({"user_id": user.id})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": UserResponse(
                id=user.id,
                name=user.name,
                email=user.email,
            ),
        }
