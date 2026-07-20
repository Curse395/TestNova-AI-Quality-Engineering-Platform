import os
import sys
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User


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
        json={"name": "Embedding User", "email": "embeddings@example.com", "password": "securepass123"},
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

    document_id = upload_response.json()["id"]
    process_response = client.post(f"/documents/{document_id}/process", headers=headers)
    assert process_response.status_code == 200

    class DummyModel:
        def encode(self, texts, normalize_embeddings=True):
            return [[0.1, 0.2, 0.3] for _ in texts]

    dummy_module = SimpleNamespace(SentenceTransformer=lambda *_args, **_kwargs: DummyModel())
    monkeypatch.setitem(sys.modules, "sentence_transformers", dummy_module)

    regenerate_response = client.post(f"/embeddings/regenerate?document_id={document_id}", headers=headers)
    assert regenerate_response.status_code == 200
    assert regenerate_response.json()["generated"] >= 1
