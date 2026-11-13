import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from passlib.context import CryptContext
from pydantic import ValidationError

from app.core.authorization import get_owned_document, get_owned_project
from app.core.config import Settings, settings
from app.core.dependencies import get_current_user
from app.core.security import ALGORITHM, create_access_token, hash_password, verify_password
from app.schemas.user_schema import UserCreate, UserLogin
from app.services import auth_service
from app.services.auth_service import AuthService


TEST_SIGNING_KEY = hashlib.sha256(b"TestNova offline security tests").hexdigest()


class FakeQuery:
    def __init__(self, result):
        self.result = result
        self.join_conditions = []
        self.filters = []

    def join(self, model, condition=None):
        self.join_conditions.append((model, condition))
        return self

    def filter(self, *conditions):
        self.filters.extend(conditions)
        return self

    def first(self):
        return self.result


class FakeDatabase:
    def __init__(self, result=None):
        self.result = result
        self.query_instance = None

    def query(self, model):
        self.query_instance = FakeQuery(self.result)
        return self.query_instance


def _credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _signed_token(payload: dict, key: str = TEST_SIGNING_KEY, algorithm: str = ALGORITHM) -> str:
    return jwt.encode(payload, key, algorithm=algorithm)


def _claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "42",
        "user_id": 42,
        "token_use": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET_KEY", TEST_SIGNING_KEY)


def test_password_hashing_accepts_long_passwords_and_legacy_bcrypt_hashes():
    long_password = "correct horse battery staple " * 4
    hashed = hash_password(long_password)

    assert hashed != long_password
    assert verify_password(long_password, hashed)
    assert not verify_password("incorrect password", hashed)
    assert not verify_password("password", "not-a-password-hash")

    legacy_hash = CryptContext(schemes=["bcrypt"]).hash("legacy password")
    assert verify_password("legacy password", legacy_hash)


def test_login_uses_one_safe_error_for_unknown_and_incorrect_credentials(monkeypatch):
    data = UserLogin(email="person@example.com", password="not-the-password")
    db = FakeDatabase()
    hash_calls = []
    monkeypatch.setattr(auth_service, "hash_password", lambda password: hash_calls.append(password))

    with pytest.raises(ValueError, match="^Invalid credentials$"):
        AuthService(db).login_user(data)

    assert hash_calls == [data.password]

    user = SimpleNamespace(
        id=42,
        email=data.email,
        name="Person",
        password_hash=hash_password("the-correct-password"),
    )
    with pytest.raises(ValueError, match="^Invalid credentials$"):
        AuthService(FakeDatabase(user)).login_user(data)


def test_login_returns_access_token_for_correct_password():
    password = "the-correct-password"
    user = SimpleNamespace(
        id=42,
        email="person@example.com",
        name="Person",
        password_hash=hash_password(password),
    )

    result = AuthService(FakeDatabase(user)).login_user(
        UserLogin(email=user.email, password=password)
    )
    claims = jwt.decode(result["access_token"], TEST_SIGNING_KEY, algorithms=[ALGORITHM])

    assert result["token_type"] == "bearer"
    assert claims["sub"] == "42"
    assert claims["token_use"] == "access"
    assert set(claims) == {"sub", "user_id", "token_use", "iat", "exp"}


def test_access_token_rejects_missing_or_invalid_user_identity():
    for data in ({}, {"user_id": 0}, {"user_id": True}, {"user_id": "42"}):
        with pytest.raises(ValueError):
            create_access_token(data)


def test_jwt_secret_is_required_and_rejects_low_entropy_values(monkeypatch):
    assert Settings.model_fields["JWT_SECRET_KEY"].is_required()
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
            GEMINI_API_KEY="offline-test-placeholder",
        )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            DATABASE_URL="sqlite://",
            GEMINI_API_KEY="offline-test-placeholder",
            JWT_SECRET_KEY="x" * 64,
        )

    configured = Settings(
        _env_file=None,
        DATABASE_URL="sqlite://",
        GEMINI_API_KEY="offline-test-placeholder",
        JWT_SECRET_KEY=TEST_SIGNING_KEY,
    )
    assert configured.JWT_SECRET_KEY == TEST_SIGNING_KEY


@pytest.mark.parametrize(
    "token",
    [
        "malformed",
        _signed_token(_claims(), key="wrong-test-signing-key" * 2),
        _signed_token(_claims(), algorithm="HS384"),
        _signed_token({key: value for key, value in _claims().items() if key != "exp"}),
        _signed_token({key: value for key, value in _claims().items() if key != "sub"}),
        _signed_token(
            _claims(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
        ),
        _signed_token(_claims(sub="")),
        _signed_token(_claims(token_use="refresh")),
        _signed_token(_claims(user_id=99)),
        _signed_token(_claims(iat="not-a-timestamp")),
    ],
)
def test_current_user_rejects_invalid_tokens_and_claims(token):
    with pytest.raises(HTTPException) as error:
        get_current_user(_credentials(token), FakeDatabase())

    assert error.value.status_code == 401
    assert error.value.headers["WWW-Authenticate"] == "Bearer"


def test_current_user_rejects_missing_credentials_without_querying_database():
    db = FakeDatabase()

    with pytest.raises(HTTPException) as error:
        get_current_user(None, db)

    assert error.value.status_code == 401
    assert db.query_instance is None


def test_current_user_accepts_valid_token_and_rejects_inactive_accounts():
    user = SimpleNamespace(id=42, is_active=True)
    token = create_access_token({"user_id": 42})
    assert get_current_user(_credentials(token), FakeDatabase(user)) is user

    with pytest.raises(HTTPException) as error:
        get_current_user(
            _credentials(token),
            FakeDatabase(SimpleNamespace(id=42, is_active=False)),
        )
    assert error.value.status_code == 401


def test_unknown_registration_role_is_not_persisted_by_the_user_schema():
    payload = UserCreate.model_validate(
        {
            "name": "New User",
            "email": "new@example.com",
            "password": "secure password longer than twelve",
            "workspace_name": "Workspace",
            "role": "admin",
            "owner_id": 1,
        }
    )

    assert "role" not in payload.model_fields_set
    assert "owner_id" not in payload.model_fields_set
    assert not hasattr(payload, "role")


@pytest.mark.parametrize(
    ("lookup", "model_name", "expected_values"),
    [
        (get_owned_project, "Project", {17, 29}),
        (get_owned_document, "Document", {17, 29}),
    ],
)
def test_project_and_document_authorization_queries_include_owner_scope(
    lookup,
    model_name,
    expected_values,
):
    resource = SimpleNamespace(id=17)
    db = FakeDatabase(resource)

    if model_name == "Project":
        result = lookup(db, project_id=17, user_id=29)
    else:
        result = lookup(db, document_id=17, user_id=29)

    assert result is resource
    compiled_values = {
        value
        for condition in db.query_instance.filters
        for value in condition.compile().params.values()
    }
    assert expected_values.issubset(compiled_values)


def test_foreign_project_is_not_returned_by_owner_scoped_lookup():
    db = FakeDatabase()

    assert get_owned_project(db, project_id=17, user_id=29) is None
