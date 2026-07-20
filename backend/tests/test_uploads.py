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


def test_upload_document_flow():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"name": "Uploader", "email": "uploader@example.com", "password": "securepass123"},
    )
    assert register_response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "uploader@example.com").first()
        assert user is not None
        organization = Organization(name="Upload Org", owner_id=user.id)
        db.add(organization)
        db.commit()
        db.refresh(organization)

        project = Project(name="Upload Project", organitzation_id=organization.id)
        db.add(project)
        db.commit()
        db.refresh(project)
    finally:
        db.close()

    login_response = client.post(
        "/auth/login",
        json={"email": "uploader@example.com", "password": "securepass123"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/uploads/?project_id=1",
        files={"file": ("sample.txt", BytesIO(b"hello testnova"), "text/plain")},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "sample.txt"

    listing = client.get("/uploads/project/1", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
