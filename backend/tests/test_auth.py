import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.database.connection import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_register_and_login_flow():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"name": "Jane Doe", "email": "jane@example.com", "password": "securepass123"},
    )

    assert register_response.status_code == 200
    assert register_response.json()["user"]["email"] == "jane@example.com"

    login_response = client.post(
        "/auth/login",
        json={"email": "jane@example.com", "password": "securepass123"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["token_type"] == "bearer"
    assert login_response.json()["access_token"]
    assert login_response.json()["user"]["email"] == "jane@example.com"
