import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.organization import Organization
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def test_project_crud_and_dashboard_flow():
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"name": "Project Owner", "email": "owner@example.com", "password": "securepass123", "workspace_name": "Project Workspace"},
    )
    assert register_response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "owner@example.com").first()
        assert user is not None
        organization = Organization(name="Acme Org", owner_id=user.id)
        db.add(organization)
        db.commit()
        db.refresh(organization)
    finally:
        db.close()

    login_response = client.post(
        "/auth/login",
        json={"email": "owner@example.com", "password": "securepass123"},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_response = client.post(
        "/projects/",
        json={"name": "Alpha Project", "description": "Initial release", "organization_id": organization.id},
        headers=headers,
    )
    assert create_response.status_code == 200
    project_id = create_response.json()["data"]["id"]

    list_response = client.get("/projects/", headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1

    update_response = client.put(
        f"/projects/{project_id}",
        json={"name": "Alpha Project Updated", "description": "Updated description"},
        headers=headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["data"]["name"] == "Alpha Project Updated"

    dashboard_response = client.get(f"/projects/{project_id}/dashboard", headers=headers)
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["data"]["project_id"] == project_id
    assert dashboard_response.json()["data"]["status"] == "no_documents"

    delete_response = client.delete(f"/projects/{project_id}", headers=headers)
    assert delete_response.status_code == 200

    after_delete = client.get("/projects/", headers=headers)
    assert after_delete.status_code == 200
    assert after_delete.json()["data"] == []


def test_project_dashboard_reports_persisted_processing_and_embedding_state():
    client = TestClient(app)
    registration = client.post(
        "/auth/register",
        json={
            "name": "Dashboard Owner",
            "email": "dashboard-owner@example.com",
            "password": "securepass123",
            "workspace_name": "Dashboard Workspace",
        },
    )
    assert registration.status_code == 200
    login = client.post(
        "/auth/login",
        json={
            "email": "dashboard-owner@example.com",
            "password": "securepass123",
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    project_response = client.post(
        "/projects/",
        json={"name": "Dashboard Project"},
        headers=headers,
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["data"]["id"]

    db = SessionLocal()
    try:
        from app.models.document import Document
        from app.models.document_chunk import DocumentChunk
        from app.models.document_embedding import DocumentEmbedding
        from app.models.project import Project

        project = db.query(Project).filter(Project.id == project_id).first()
        document = Document(
            filename="requirements.txt",
            content_type="text/plain",
            storage_path="isolated-test-file",
            project_id=project.id,
            processing_status="uploaded",
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="The project dashboard must show persisted processing state.",
        )
        db.add(chunk)
        db.commit()
        document_id = document.id
        chunk_id = chunk.id
    finally:
        db.close()

    pending = client.get(
        f"/projects/{project_id}/dashboard",
        headers=headers,
    )
    assert pending.status_code == 200
    assert pending.json()["data"]["status"] == "processing"
    assert pending.json()["data"]["embedding_count"] == 0

    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        document.processing_status = "completed"
        db.add(
            DocumentEmbedding(
                chunk_id=chunk_id,
                model_name="isolated-test-model",
                embedding=[0.1] * 384,
            )
        )
        db.commit()
    finally:
        db.close()

    ready = client.get(
        f"/projects/{project_id}/dashboard",
        headers=headers,
    )
    assert ready.status_code == 200
    assert ready.json()["data"]["status"] == "ready"
    assert ready.json()["data"]["document_count"] == 1
    assert ready.json()["data"]["chunk_count"] == 1
    assert ready.json()["data"]["embedding_count"] == 1
