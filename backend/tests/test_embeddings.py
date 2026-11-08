import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.services.model_service import ModelService


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_embedding_regeneration_flow(monkeypatch):
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={
            "name": "Embedding User",
            "email": "embeddings@example.com",
            "password": "securepass123",
            "workspace_name": "Embedding Workspace",
        },
    )
    assert register_response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "embeddings@example.com").first()
        assert user is not None
        organization = Organization(name="Embedding Org", owner_id=user.id)
        db.add(organization)
        db.commit()
        db.refresh(organization)

        project = Project(name="Embedding Project", organitzation_id=organization.id)
        db.add(project)
        db.commit()
        db.refresh(project)
    finally:
        db.close()

    login_response = client.post(
        "/auth/login",
        json={"email": "embeddings@example.com", "password": "securepass123"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    upload_response = client.post(
        "/uploads/?project_id=1",
        files={"file": ("sample.txt", BytesIO(b"This content should become an embedding after processing."), "text/plain")},
        headers=headers,
    )
    assert upload_response.status_code == 200

    document_id = upload_response.json()["data"]["id"]
    process_response = client.post(f"/documents/{document_id}/process", headers=headers)
    assert process_response.status_code == 200, process_response.text

    class DummyModel:
        calls = 0

        def encode(self, texts, normalize_embeddings=True):
            self.calls += 1

            class DummyVector(list):
                def tolist(self):
                    return list(self)

            return DummyVector([0.1] * 384)

    monkeypatch.setattr(ModelService, "_embedding_model", DummyModel())

    regenerate_response = client.post(
        f"/embeddings/regenerate?project_id=1&document_id={document_id}",
        headers=headers,
    )
    assert regenerate_response.status_code == 200
    assert regenerate_response.json()["data"]["generated"] >= 1

    repeated_response = client.post(
        f"/embeddings/regenerate?project_id=1&document_id={document_id}",
        headers=headers,
    )
    assert repeated_response.status_code == 200
    assert repeated_response.json()["data"]["generated"] == 0
    assert ModelService._embedding_model.calls == 1
