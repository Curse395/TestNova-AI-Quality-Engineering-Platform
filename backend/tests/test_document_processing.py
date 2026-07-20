import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_document_processing_pipeline():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"name": "Processor", "email": "processor@example.com", "password": "securepass123"},
    )
    assert register_response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "processor@example.com").first()
        assert user is not None
        organization = Organization(name="Processing Org", owner_id=user.id)
        db.add(organization)
        db.commit()
        db.refresh(organization)

        project = Project(name="Processing Project", organitzation_id=organization.id)
        db.add(project)
        db.commit()
        db.refresh(project)
    finally:
        db.close()

    login_response = client.post(
        "/auth/login",
        json={"email": "processor@example.com", "password": "securepass123"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload_response = client.post(
        "/uploads/?project_id=1",
        files={"file": ("sample.txt", BytesIO(b"This is a document for processing. It should be normalized and split into chunks."), "text/plain")},
        headers=headers,
    )
    assert upload_response.status_code == 200

    document_id = upload_response.json()["id"]
    process_response = client.post(f"/documents/{document_id}/process", headers=headers)

    assert process_response.status_code == 200
    assert process_response.json()["chunk_count"] >= 1
