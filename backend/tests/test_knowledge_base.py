import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_knowledge_base_index_and_search():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"name": "Knowledge User", "email": "kb@example.com", "password": "securepass123"},
    )
    assert register_response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "kb@example.com").first()
        assert user is not None
        organization = Organization(name="KB Org", owner_id=user.id)
        db.add(organization)
        db.commit()
        db.refresh(organization)

        project = Project(name="KB Project", organitzation_id=organization.id)
        db.add(project)
        db.commit()
        db.refresh(project)
    finally:
        db.close()

    login_response = client.post(
        "/auth/login",
        json={"email": "kb@example.com", "password": "securepass123"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload_response = client.post(
        "/uploads/?project_id=1",
        files={"file": ("requirements.txt", BytesIO(b"Regression testing coverage for release confidence and quality risk."), "text/plain")},
        headers=headers,
    )
    assert upload_response.status_code == 200

    index_response = client.post("/projects/1/knowledge-base/index", headers=headers)
    assert index_response.status_code == 200
    assert index_response.json()["data"]["chunks"] >= 1

    search_response = client.get("/projects/1/knowledge-base?query=regression", headers=headers)
    assert search_response.status_code == 200
    assert len(search_response.json()) >= 1
