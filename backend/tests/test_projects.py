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

    delete_response = client.delete(f"/projects/{project_id}", headers=headers)
    assert delete_response.status_code == 200

    after_delete = client.get("/projects/", headers=headers)
    assert after_delete.status_code == 200
    assert after_delete.json()["data"] == []
