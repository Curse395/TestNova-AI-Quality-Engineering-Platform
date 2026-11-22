import os
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy.exc import SQLAlchemyError
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.api import uploads as uploads_api
from app.core import file_storage
from app.core.security import create_access_token
from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as EvidenceModel
from app.models.test_case_generation_run import (
    TestCaseGenerationRun as GenerationRunModel,
)
from app.models.user import User


def _set_upload_root(monkeypatch, root):
    monkeypatch.setattr(uploads_api, "UPLOAD_ROOT", root)
    monkeypatch.setattr(file_storage, "UPLOAD_ROOT", root)


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def isolate_upload_storage(tmp_path, monkeypatch):
    _set_upload_root(monkeypatch, tmp_path / "uploads")


def create_project_and_headers(email: str = "owner@example.com") -> tuple[int, dict[str, str]]:
    db = SessionLocal()
    try:
        user = User(name="Document Owner", email=email, password_hash="test-hash")
        db.add(user)
        db.flush()
        organization = Organization(name="Test Organization", owner_id=user.id)
        db.add(organization)
        db.flush()
        project = Project(name="Test Project", organitzation_id=organization.id)
        db.add(project)
        db.commit()
        return project.id, {
            "Authorization": f"Bearer {create_access_token({'user_id': user.id})}"
        }
    finally:
        db.close()


def create_document(
    project_id: int,
    storage_path: Path,
    filename: str = "requirements.txt",
) -> Document:
    db = SessionLocal()
    try:
        document = Document(
            filename=filename,
            content_type="text/plain",
            storage_path=str(storage_path),
            project_id=project_id,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    finally:
        db.close()


def test_upload_document_flow():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"name": "Uploader", "email": "uploader@example.com", "password": "securepass123", "workspace_name": "Upload Workspace"},
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
    assert response.json()["data"]["filename"] == "sample.txt"

    listing = client.get("/uploads/project/1", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1


def test_delete_document_removes_related_records_but_preserves_history_and_other_documents(
    monkeypatch,
    tmp_path,
):
    project_id, headers = create_project_and_headers()
    upload_root = tmp_path / "uploads"
    _set_upload_root(monkeypatch, upload_root)

    document_path = upload_root / str(project_id) / "document.txt"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("source document", encoding="utf-8")
    document = create_document(project_id, document_path)

    other_path = upload_root / str(project_id) / "other.txt"
    other_path.write_text("unrelated document", encoding="utf-8")
    other_document = create_document(project_id, other_path, "other.txt")

    db = SessionLocal()
    try:
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="source evidence",
        )
        other_chunk = DocumentChunk(
            document_id=other_document.id,
            chunk_index=0,
            content="unrelated evidence",
        )
        run = GenerationRunModel(
            project_id=project_id,
            created_by_user_id=1,
            requirements_prompt="Keep generated history",
            requested_categories=["positive"],
            max_cases=1,
        )
        db.add_all([chunk, other_chunk, run])
        db.flush()
        test_case = CaseModel(
            project_id=project_id,
            created_by_user_id=1,
            title="Preserved case",
            description="Generated before deletion",
            category="positive",
            priority="medium",
            steps=[],
            expected_result="The case remains",
            generation_run_id=run.id,
        )
        db.add(test_case)
        db.flush()
        db.add_all(
            [
                DocumentEmbedding(
                    chunk_id=chunk.id,
                    model_name="test-model",
                    embedding=[0.1] * 384,
                ),
                DocumentEmbedding(
                    chunk_id=other_chunk.id,
                    model_name="test-model",
                    embedding=[0.2] * 384,
                ),
                EvidenceModel(
                    test_case_id=test_case.id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                ),
            ]
        )
        db.commit()
        chunk_id = chunk.id
        other_chunk_id = other_chunk.id
        test_case_id = test_case.id
        run_id = run.id
    finally:
        db.close()

    response = TestClient(app).delete(
        f"/uploads/{document.id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["data"]["filename"] == "requirements.txt"
    assert response.json()["data"]["file_cleanup_warning"] is None
    assert not document_path.exists()

    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == document.id).count() == 0
        assert db.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).count() == 0
        assert db.query(DocumentEmbedding).filter(
            DocumentEmbedding.chunk_id == chunk_id
        ).count() == 0
        assert db.query(EvidenceModel).filter(
            EvidenceModel.document_id == document.id
        ).count() == 0
        assert db.query(CaseModel).filter(CaseModel.id == test_case_id).count() == 1
        assert db.query(GenerationRunModel).filter(
            GenerationRunModel.id == run_id
        ).count() == 1
        assert db.query(Document).filter(Document.id == other_document.id).count() == 1
        assert db.query(DocumentChunk).filter(
            DocumentChunk.id == other_chunk_id
        ).count() == 1
        assert db.query(DocumentEmbedding).filter(
            DocumentEmbedding.chunk_id == other_chunk_id
        ).count() == 1
        assert other_path.exists()
    finally:
        db.close()


def test_delete_document_returns_404_for_another_users_document(monkeypatch, tmp_path):
    project_id, _ = create_project_and_headers("first@example.com")
    _, other_headers = create_project_and_headers("second@example.com")
    upload_root = tmp_path / "uploads"
    _set_upload_root(monkeypatch, upload_root)

    document_path = upload_root / str(project_id) / "private.txt"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("private", encoding="utf-8")
    document = create_document(project_id, document_path)

    response = TestClient(app).delete(
        f"/uploads/{document.id}",
        headers=other_headers,
    )

    assert response.status_code == 404
    assert document_path.exists()
    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == document.id).count() == 1
    finally:
        db.close()


def test_delete_document_returns_404_when_missing():
    _, headers = create_project_and_headers()
    response = TestClient(app).delete("/uploads/9999", headers=headers)
    assert response.status_code == 404


def test_delete_document_handles_missing_physical_file(monkeypatch, tmp_path):
    project_id, headers = create_project_and_headers()
    upload_root = tmp_path / "uploads"
    _set_upload_root(monkeypatch, upload_root)
    document = create_document(
        project_id,
        upload_root / str(project_id) / "already-missing.txt",
    )

    response = TestClient(app).delete(
        f"/uploads/{document.id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert "already missing" in response.json()["data"]["file_cleanup_warning"]
    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == document.id).count() == 0
    finally:
        db.close()


def test_delete_document_rolls_back_when_database_commit_fails(
    monkeypatch,
    tmp_path,
):
    project_id, headers = create_project_and_headers()
    upload_root = tmp_path / "uploads"
    _set_upload_root(monkeypatch, upload_root)
    document_path = upload_root / str(project_id) / "rollback.txt"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("must remain", encoding="utf-8")
    document = create_document(project_id, document_path)

    db = SessionLocal()
    try:
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="rollback evidence",
        )
        db.add(chunk)
        db.commit()
        chunk_id = chunk.id
    finally:
        db.close()

    def fail_commit(_session):
        raise SQLAlchemyError("simulated commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = TestClient(app).delete(
        f"/uploads/{document.id}",
        headers=headers,
    )

    assert response.status_code == 500
    assert document_path.exists()
    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == document.id).count() == 1
        assert db.query(DocumentChunk).filter(DocumentChunk.id == chunk_id).count() == 1
    finally:
        db.close()


def test_delete_document_rejects_storage_path_outside_upload_root(
    monkeypatch,
    tmp_path,
):
    project_id, headers = create_project_and_headers()
    upload_root = tmp_path / "uploads"
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("must never be deleted", encoding="utf-8")
    _set_upload_root(monkeypatch, upload_root)
    document = create_document(project_id, outside_path)

    response = TestClient(app).delete(
        f"/uploads/{document.id}",
        headers=headers,
    )

    assert response.status_code == 400
    assert outside_path.exists()
    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == document.id).count() == 1
    finally:
        db.close()


def test_delete_document_reports_physical_cleanup_failure(
    monkeypatch,
    tmp_path,
):
    project_id, headers = create_project_and_headers()
    upload_root = tmp_path / "uploads"
    _set_upload_root(monkeypatch, upload_root)
    document_path = upload_root / str(project_id) / "locked.txt"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("cleanup warning", encoding="utf-8")
    document = create_document(project_id, document_path)

    def fail_unlink(_path, *args, **kwargs):
        raise PermissionError("simulated filesystem denial")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    response = TestClient(app).delete(
        f"/uploads/{document.id}",
        headers=headers,
    )

    assert response.status_code == 200
    assert "could not be removed" in response.json()["data"]["file_cleanup_warning"]
    db = SessionLocal()
    try:
        assert db.query(Document).filter(Document.id == document.id).count() == 0
    finally:
        db.close()
    assert document_path.exists()


def test_delete_document_requires_authentication():
    response = TestClient(app).delete("/uploads/1")
    assert response.status_code == 401
