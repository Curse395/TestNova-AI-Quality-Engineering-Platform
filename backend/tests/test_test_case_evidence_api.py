import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.database.connection import Base, SessionLocal, engine
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_case_evidence import TestCaseEvidence
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _project_and_auth(email: str):
    db = SessionLocal()
    try:
        user = User(name="Evidence User", email=email, password_hash="test-hash")
        db.add(user)
        db.flush()
        organization = Organization(name="Evidence Org", owner_id=user.id)
        db.add(organization)
        db.flush()
        project = Project(name="Evidence Project", organitzation_id=organization.id)
        db.add(project)
        db.commit()
        return (
            project.id,
            {"Authorization": f"Bearer {create_access_token({'user_id': user.id})}"},
            user.id,
        )
    finally:
        db.close()


def test_list_test_cases_returns_verified_source_metadata_and_excerpt():
    project_id, headers, user_id = _project_and_auth("evidence-owner@example.com")
    db = SessionLocal()
    try:
        document = Document(
            filename="specification.pdf",
            content_type="application/pdf",
            storage_path="unused",
            project_id=project_id,
            source_type="requirements",
        )
        db.add(document)
        db.flush()
        chunk = DocumentChunk(
            document_id=document.id,
            chunk_index=3,
            content="Users must receive a confirmation after saving.",
            source_metadata={
                "filename": document.filename,
                "source_type": "requirements",
                "source_location": {"page_numbers": [2], "section": "Notifications"},
            },
        )
        db.add(chunk)
        db.flush()
        test_case = TestCase(
            project_id=project_id,
            created_by_user_id=user_id,
            title="Saving confirmation",
            description="Confirm the documented save behavior.",
            category="positive",
            priority="medium",
            steps=[{"action": "Save a record", "expected_result": "Confirmation appears"}],
            expected_result="The confirmation is shown.",
        )
        db.add(test_case)
        db.flush()
        db.add(
            TestCaseEvidence(
                test_case_id=test_case.id,
                document_id=document.id,
                chunk_id=chunk.id,
            )
        )
        db.commit()
    finally:
        db.close()

    response = TestClient(app).get(
        f"/projects/{project_id}/test-cases",
        headers=headers,
    )

    assert response.status_code == 200
    evidence = response.json()["data"][0]["evidence"][0]
    assert evidence["document_name"] == "specification.pdf"
    assert evidence["source_type"] == "requirements"
    assert evidence["source_metadata"]["source_location"]["page_numbers"] == [2]
    assert evidence["excerpt"] == "Users must receive a confirmation after saving."


def test_list_test_cases_does_not_expose_another_users_project():
    project_id, _, _ = _project_and_auth("evidence-first@example.com")
    _, other_headers, _ = _project_and_auth("evidence-second@example.com")

    response = TestClient(app).get(
        f"/projects/{project_id}/test-cases",
        headers=other_headers,
    )

    assert response.status_code == 404


def test_test_case_without_evidence_returns_empty_evidence_list():
    project_id, headers, user_id = _project_and_auth("no-evidence@example.com")
    db = SessionLocal()
    try:
        case = TestCase(
            project_id=project_id,
            created_by_user_id=user_id,
            title="Unlinked case",
            description="A case with no sources.",
            category="positive",
            priority="low",
            steps=[{"action": "Run", "expected_result": "Runs"}],
            expected_result="Completes.",
        )
        db.add(case)
        db.commit()
    finally:
        db.close()

    response = TestClient(app).get(
        f"/projects/{project_id}/test-cases",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["evidence"] == []
