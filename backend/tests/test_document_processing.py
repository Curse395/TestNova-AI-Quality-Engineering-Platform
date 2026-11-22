import os
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.api import uploads as uploads_api
from app.core import file_storage
from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def isolate_upload_storage(tmp_path, monkeypatch):
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(uploads_api, "UPLOAD_ROOT", upload_root)
    monkeypatch.setattr(file_storage, "UPLOAD_ROOT", upload_root)


def test_document_processing_pipeline():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={
            "name": "Processor",
            "email": "processor@example.com",
            "password": "securepass123",
            "workspace_name": "Processing Workspace",
        },
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

    document_id = upload_response.json()["data"]["id"]
    process_response = client.post(f"/documents/{document_id}/process", headers=headers)

    assert process_response.status_code == 200, process_response.text
    payload = process_response.json()["data"]
    assert payload["document_id"] == document_id
    assert payload["chunks_created"] >= 1
    assert payload["status"] == "completed"

    db = SessionLocal()
    try:
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        assert len(chunks) == payload["chunks_created"]
        assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
        assert all(chunk.content for chunk in chunks)
        assert all(chunk.source_metadata["source_type"] == "document" for chunk in chunks)
        assert all(chunk.source_metadata["file_type"] == ".txt" for chunk in chunks)
        assert all(
            chunk.source_metadata["extraction"]["parser"] == "utf-8-text"
            for chunk in chunks
        )
        assert all(
            chunk.source_metadata["filename"] == "sample.txt"
            for chunk in chunks
        )
        assert db.query(DocumentEmbedding).count() == 0
    finally:
        db.close()

    # Reprocessing replaces the existing ingestion set instead of appending to it.
    repeat_response = client.post(f"/documents/{document_id}/process", headers=headers)
    assert repeat_response.status_code == 200
    assert repeat_response.json()["data"]["chunks_created"] == payload["chunks_created"]

    db = SessionLocal()
    try:
        assert (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == document_id)
            .count()
            == payload["chunks_created"]
        )
    finally:
        db.close()
