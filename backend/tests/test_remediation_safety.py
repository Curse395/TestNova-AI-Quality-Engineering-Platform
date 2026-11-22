from io import BytesIO
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import uploads
from app.core import file_storage
from app.api import test_cases
from app.core.security import ALGORITHM, create_access_token
from app.core.config import settings
from app.database.connection import Base, engine
from app.main import app
from app.services.document_processing_service import DocumentProcessingService
from app.services.embedding_service import EmbeddingService
from app.schemas.test_execution_schema import APIRequestConfig
from app.services.test_execution_service import TestExecutionService as ExecutionService


@pytest.fixture
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield TestClient(app)
    Base.metadata.drop_all(bind=engine)


def create_project(client: TestClient, email: str) -> tuple[str, int]:
    registration = client.post(
        "/auth/register",
        json={
            "name": "Test Owner",
            "email": email,
            "password": "safe-test-password",
            "workspace_name": "Test Workspace",
        },
    )
    assert registration.status_code == 200
    workspace_id = registration.json()["workspace"]["id"]
    login = client.post(
        "/auth/login",
        json={"email": email, "password": "safe-test-password"},
    )
    token = login.json()["access_token"]
    project_response = client.post(
        "/projects/",
        json={"name": "Test Project", "organization_id": workspace_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert project_response.status_code == 200
    return token, project_response.json()["data"]["id"]


def _set_upload_root(monkeypatch, root):
    monkeypatch.setattr(uploads, "UPLOAD_ROOT", root)
    monkeypatch.setattr(file_storage, "UPLOAD_ROOT", root)


def test_jwt_uses_configured_secret():
    token = create_access_token({"user_id": 123})
    from jose import jwt
    from app.core.config import settings

    assert jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])["user_id"] == 123


def test_upload_rejects_unsupported_and_mismatched_formats():
    with pytest.raises(HTTPException) as unsupported:
        uploads._validate_upload("payload.exe", "application/octet-stream")
    assert unsupported.value.status_code == 415

    with pytest.raises(HTTPException) as mismatch:
        uploads._validate_upload("payload.pdf", "text/plain")
    assert mismatch.value.status_code == 415


def test_upload_uses_safe_name_and_server_generated_path(client, monkeypatch, tmp_path):
    token, project_id = create_project(client, "upload-safety@example.com")
    _set_upload_root(monkeypatch, tmp_path)

    response = client.post(
        f"/uploads/?project_id={project_id}",
        files={"file": (r"..\outside.txt", BytesIO(b"safe contents"), "text/plain")},
        data={"source_type": "requirements"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["filename"] == "outside.txt"
    stored_files = list(tmp_path.rglob("*.txt"))
    assert len(stored_files) == 1
    assert tmp_path.resolve() in stored_files[0].resolve().parents
    assert stored_files[0].name != "outside.txt"
    assert "storage_path" not in payload
    assert payload["processing_status"] == "uploaded"
    assert payload["source_type"] == "requirements"


def test_upload_rejects_empty_file(client, monkeypatch, tmp_path):
    token, project_id = create_project(client, "empty-upload@example.com")
    _set_upload_root(monkeypatch, tmp_path)

    response = client.post(
        f"/uploads/?project_id={project_id}",
        files={"file": ("empty.txt", BytesIO(b""), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_upload_enforces_configured_size_limit(client, monkeypatch, tmp_path):
    token, project_id = create_project(client, "large-upload@example.com")
    _set_upload_root(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 4)

    response = client.post(
        f"/uploads/?project_id={project_id}",
        files={"file": ("large.txt", BytesIO(b"12345"), "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 413
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_embedding_endpoint_rejects_another_users_project(client):
    _owner_token, project_id = create_project(client, "owner@example.com")
    other_token, _other_project_id = create_project(client, "other@example.com")

    response = client.post(
        f"/embeddings/regenerate?project_id={project_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404


def test_chat_session_creation_rejects_another_users_project(client):
    _owner_token, project_id = create_project(client, "chat-owner@example.com")
    other_token, _ = create_project(client, "chat-other@example.com")

    response = client.post(
        f"/chat/sessions?project_id={project_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert response.status_code == 404


def test_empty_embedding_scope_does_not_query_or_generate():
    db = Mock()
    assert EmbeddingService(db).generate_embeddings(project_id=17, chunk_ids=[]) == 0
    db.query.assert_not_called()


def test_xlsx_parser_reads_every_nonempty_row_and_sheet(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "multi-sheet.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "First"
    workbook.active.append(["Requirement", "Priority"])
    workbook.active.append(["REQ-1", "High"])
    second = workbook.create_sheet("Second")
    second.append(["Issue", "Status"])
    second.append(["BUG-2", "Open"])
    workbook.save(path)

    text = DocumentProcessingService(Mock()).parse_document(str(path))

    assert "Sheet: First" in text
    assert "REQ-1 | High" in text
    assert "Sheet: Second" in text
    assert "BUG-2 | Open" in text


def test_chunking_preserves_line_boundaries_and_overlap():
    service = DocumentProcessingService(Mock())
    text = "## Requirements\nREQ-1 title and acceptance text\n| ID | Priority |\n| R-2 | High |"

    chunks = service.chunk_text(text, chunk_size=8, overlap=2)
    combined = "\n".join(chunks)

    assert "## Requirements" in combined
    assert "REQ-1 title" in combined
    assert "| ID | Priority |" in combined
    assert "| R-2 | High |" in combined
    assert all(len(chunk.split()) <= 8 for chunk in chunks)


def test_chunking_rejects_invalid_overlap():
    service = DocumentProcessingService(Mock())
    with pytest.raises(ValueError, match="overlap"):
        service.chunk_text("some words", chunk_size=4, overlap=4)


def test_execution_snapshot_redacts_sensitive_request_values():
    config = APIRequestConfig(
        method="POST",
        url="https://api.example.com/check?access_token=url-secret&region=west",
        headers={"Authorization": "header-secret", "X-Trace": "trace-id"},
        params={"api_key": "param-secret", "query": "safe"},
        json_body={"nested": {"password": "body-secret", "note": "safe"}},
        expected_status_code=200,
        expected_json_fields={"access_token": "expected-secret"},
    )

    snapshot = ExecutionService._build_request_snapshot(config)
    redacted = ExecutionService._redact_request_snapshot(
        {
            "url": "https://api.example.com/check?token=legacy-secret",
            "headers": {"X-Auth-Token": "legacy-header-secret"},
        }
    )
    serialized = str(snapshot) + str(redacted)

    assert "url-secret" not in serialized
    assert "header-secret" not in serialized
    assert "param-secret" not in serialized
    assert "body-secret" not in serialized
    assert "legacy-secret" not in serialized
    assert "legacy-header-secret" not in serialized
    assert snapshot["headers"]["X-Trace"] == "trace-id"
    assert snapshot["json_body"]["nested"]["note"] == "safe"


def test_execution_assertions_redact_sensitive_expected_and_actual_values():
    failures = ExecutionService._check_json_fields(
        {"access_token": "actual-secret", "profile": {"password": "actual-password"}},
        {
            "access_token": "expected-secret",
            "profile": {"password": "expected-password"},
        },
    )

    assert "actual-secret" not in str(failures)
    assert "expected-secret" not in str(failures)
    assert "actual-password" not in str(failures)
    assert "expected-password" not in str(failures)


def test_dashboard_does_not_report_unmeasured_test_generation_impact(client):
    token, _project_id = create_project(client, "dashboard-metrics@example.com")

    response = client.get(
        "/dashboard/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["test_generation"] == {
        "coverage_uplift": None,
        "flake_reduction": None,
        "time_saved_minutes": None,
    }


def test_review_api_includes_agent_evidence(monkeypatch):
    evidence = [{"document_id": 3, "chunk_id": 9}]
    result = Mock(
        status="success",
        agent_name="review_agent",
        data={"recommendation": "human_review_required"},
        evidence=evidence,
    )
    monkeypatch.setattr(
        test_cases,
        "ReviewAgent",
        lambda _db: Mock(run=lambda _context: result),
    )

    response = test_cases.review_test_case(
        project_id=7,
        test_case_id=8,
        current_user=Mock(id=2),
        db=Mock(),
    )

    assert response["evidence"] == evidence
