import json
import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.genai import types
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api import test_cases as test_cases_api
from app.database.connection import Base
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as CaseEvidenceModel
from app.models.test_case_generation_run import (
    TestCaseGenerationRun as GenerationRunModel,
)
from app.schemas.test_case_schema import TestCaseGenerationRequest as GenerationRequest
from app.services.llm_services import LLMService
from app.services.test_case_generation_service import (
    TestCaseGenerationError as GenerationError,
    TestCaseGenerationService as GenerationService,
)
from app.services import test_case_generation_service as generation_service_module

for model_module in (
    "app.models.document_embedding",
    "app.models.organization",
    "app.models.project",
    "app.models.user",
):
    importlib.import_module(model_module)


PROJECT_ID = 2
USER_ID = 7
DOCUMENT_ID = 101
CHUNK_ID = 17


def _case(title: str = "Successful login") -> dict:
    return {
        "title": title,
        "description": "Verify login with valid credentials.",
        "category": "positive",
        "priority": "high",
        "preconditions": "A registered account exists.",
        "steps": [
            {
                "action": "Submit valid credentials.",
                "expected_result": "The account is authenticated.",
            }
        ],
        "expected_result": "The user reaches the authenticated area.",
        "evidence_chunk_ids": [CHUNK_ID],
    }


def _evidence(chunk_id: int = CHUNK_ID) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": DOCUMENT_ID,
        "document_name": "login.md",
        "source_type": "requirements",
        "source_metadata": {"section": "Authentication"},
        "similarity": 0.82,
        "content": "Users can sign in with registered credentials.",
    }


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    tables = [
        Document.__table__,
        DocumentChunk.__table__,
        CaseModel.__table__,
        CaseEvidenceModel.__table__,
        GenerationRunModel.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    session.add(
        Document(
            id=DOCUMENT_ID,
            filename="login.md",
            content_type="text/plain",
            storage_path="unused",
            project_id=PROJECT_ID,
        )
    )
    session.add(
        DocumentChunk(
            id=CHUNK_ID,
            document_id=DOCUMENT_ID,
            chunk_index=0,
            content="Users can sign in with registered credentials.",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _service(db, response: dict, evidence: list[dict] | None = None):
    service = GenerationService.__new__(GenerationService)
    service.db = db
    service.retrieval_service = SimpleNamespace(
        search_project_context=lambda **_: evidence or [_evidence()]
    )
    service._retrieve_chunks = lambda *_: evidence or [_evidence()]
    service.llm_service = SimpleNamespace(
        generate_content=lambda **_: response
    )
    return service


def _generate(service):
    return service.generate(
        user_id=USER_ID,
        project_id=PROJECT_ID,
        request=GenerationRequest(
            requirements_prompt="Generate login test cases."
        ),
    )


def _assert_no_generation_rows(db):
    assert db.scalar(select(func.count()).select_from(CaseModel)) == 0
    assert db.scalar(select(func.count()).select_from(CaseEvidenceModel)) == 0
    assert db.scalar(select(func.count()).select_from(GenerationRunModel)) == 0


def test_valid_model_cases_are_persisted_with_evidence(db):
    service = _service(
        db,
        {"success": True, "answer": json.dumps([_case()])},
    )

    cases = _generate(service)

    assert len(cases) == 1
    assert cases[0]["title"] == "Successful login"
    assert db.scalar(select(func.count()).select_from(CaseModel)) == 1
    assert db.scalar(select(func.count()).select_from(CaseEvidenceModel)) == 1
    assert db.scalar(select(func.count()).select_from(GenerationRunModel)) == 1
    assert db.query(CaseEvidenceModel).one().chunk_id == CHUNK_ID
    assert cases[0]["evidence"][0]["document_name"] == "login.md"
    assert cases[0]["evidence"][0]["source_type"] == "requirements"
    assert cases[0]["evidence"][0]["source_metadata"]["section"] == "Authentication"
    assert cases[0]["evidence"][0]["excerpt"] == (
        "Users can sign in with registered credentials."
    )


def test_empty_array_with_missing_login_evidence_logs_likely_gap(db, caplog):
    irrelevant_evidence = [
        {
            "chunk_id": CHUNK_ID,
            "document_id": DOCUMENT_ID,
            "document_name": "checkout.txt",
            "content": "The checkout page accepts a cart and payment method.",
        }
    ]
    service = _service(
        db,
        {"success": True, "answer": "[]"},
        evidence=irrelevant_evidence,
    )

    with pytest.raises(GenerationError, match="empty_output") as exc:
        _generate(service)

    assert "valid JSON array with zero test cases" in str(exc.value)
    assert "authentication_evidence_chunks=0" in caplog.text
    assert "diagnostic=likely_insufficient_evidence" in caplog.text
    _assert_no_generation_rows(db)


def test_empty_array_with_login_evidence_logs_topic_match(db, caplog):
    service = _service(db, {"success": True, "answer": "[]"})

    with pytest.raises(GenerationError, match="empty_output"):
        _generate(service)

    assert "authentication_evidence_chunks=1" in caplog.text
    assert "diagnostic=authentication_evidence_present" in caplog.text
    _assert_no_generation_rows(db)


def test_missing_project_embeddings_are_generated_before_retrieval(monkeypatch):
    class MissingChunksQuery:
        def join(self, *_):
            return self

        def outerjoin(self, *_):
            return self

        def filter(self, *_):
            return self

        def all(self):
            return [(12,), (13,)]

    class FakeEmbeddingService:
        def __init__(self, db):
            self.db = db

        def generate_embeddings(self, *, project_id, chunk_ids):
            assert project_id == PROJECT_ID
            generated_chunk_ids.extend(chunk_ids)
            return len(chunk_ids)

    generated_chunk_ids = []
    monkeypatch.setattr(
        generation_service_module,
        "EmbeddingService",
        FakeEmbeddingService,
    )
    service = GenerationService.__new__(GenerationService)
    service.db = SimpleNamespace(query=lambda *_: MissingChunksQuery())
    retrieved = [
        [{"chunk_id": 8, "content": "Checkout evidence."}],
        [{"chunk_id": 12, "content": "Sign in with valid credentials."}],
    ]
    retrieval_calls = []

    def search_project_context(**kwargs):
        retrieval_calls.append(kwargs)
        return retrieved[len(retrieval_calls) - 1]

    service.retrieval_service = SimpleNamespace(
        search_project_context=search_project_context
    )
    request = GenerationRequest(
        requirements_prompt="Generate login test cases."
    )

    chunks = service._retrieve_chunks(USER_ID, PROJECT_ID, request)

    assert generated_chunk_ids == [12, 13]
    assert len(retrieval_calls) == 2
    assert chunks[0]["chunk_id"] == 12


def test_malformed_json_has_distinct_stage_and_writes_nothing(db):
    service = _service(db, {"success": True, "answer": "[{"})

    with pytest.raises(GenerationError, match="json_parse"):
        _generate(service)

    _assert_no_generation_rows(db)


def test_provider_failure_has_distinct_stage_and_writes_nothing(db):
    service = _service(
        db,
        {
            "success": False,
            "stage": "provider_request",
            "error": "Gemini provider request failed",
        },
    )

    with pytest.raises(GenerationError, match="provider_request"):
        _generate(service)

    _assert_no_generation_rows(db)



def test_endpoint_returns_bad_gateway_for_generation_failures(monkeypatch):
    from app.agents.contracts import AgentResult

    class FailedGenerationAgent:
        name = "test_generation_agent"

        def __init__(self, db):
            self.db = db

        def run(self, context):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "GENERATION_FAILED",
                    "message": "Test-case generation failed at json_parse.",
                },
            )

    monkeypatch.setattr(
        test_cases_api,
        "TestGenerationAgent",
        FailedGenerationAgent,
    )

    with pytest.raises(HTTPException) as exc:
        test_cases_api.generate_test_cases(
            project_id=PROJECT_ID,
            request=GenerationRequest(
                requirements_prompt="Generate login test cases."
            ),
            current_user=SimpleNamespace(id=USER_ID),
            db=None,
        )

    assert exc.value.status_code == 502
    assert "json_parse" in exc.value.detail


def test_schema_validation_failure_has_distinct_stage_and_writes_nothing(db):
    invalid_case = _case()
    invalid_case.pop("title")
    service = _service(
        db,
        {"success": True, "answer": json.dumps([invalid_case])},
    )

    with pytest.raises(GenerationError, match="schema_validation"):
        _generate(service)

    _assert_no_generation_rows(db)


def test_invalid_evidence_reference_is_rejected_without_writes(db):
    invalid_case = _case()
    invalid_case["evidence_chunk_ids"] = [999]
    service = _service(
        db,
        {"success": True, "answer": json.dumps([invalid_case])},
    )

    with pytest.raises(GenerationError, match="evidence_validation"):
        _generate(service)

    _assert_no_generation_rows(db)


def test_persistence_failure_rolls_back_all_rows(db):
    second_case = _case("Second login case")
    second_case["evidence_chunk_ids"] = [18]
    second_case["steps"][0]["action"] = "Submit a second supported login scenario."
    second_case["steps"][0]["expected_result"] = "The second scenario is handled."
    service = _service(
        db,
        {"success": True, "answer": json.dumps([_case(), second_case])},
        evidence=[_evidence(), _evidence(18)],
    )

    with pytest.raises(GenerationError, match="persistence_evidence_check"):
        _generate(service)

    _assert_no_generation_rows(db)


def _llm_service(response):
    service = LLMService.__new__(LLMService)
    service.model_name = "test-model"
    service.generation_config = types.GenerateContentConfig(temperature=0.2)
    service.client = SimpleNamespace(
        models=SimpleNamespace(generate_content=response)
    )
    return service


def test_llm_uses_sdk_system_instruction_and_json_response_mode():
    response = SimpleNamespace(
        text='[{"title":"case"}]',
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
    )
    provider_call = {}

    def generate_content(**kwargs):
        provider_call.update(kwargs)
        return response

    service = _llm_service(generate_content)

    result = service.generate_content(
        system_prompt="Return a JSON array.",
        user_prompt="Create one case.",
        response_mime_type="application/json",
    )

    assert result["success"] is True
    assert result["answer"] == response.text
    assert provider_call["contents"] == "Create one case."
    assert provider_call["config"].system_instruction == "Return a JSON array."
    assert provider_call["config"].response_mime_type == "application/json"
    assert service.generation_config.system_instruction is None


def test_llm_provider_failure_is_reported_without_provider_details():
    def fail_provider(**_):
        raise RuntimeError("sensitive provider response")

    result = _llm_service(fail_provider).generate_content(
        system_prompt="system",
        user_prompt="user",
    )

    assert result["success"] is False
    assert result["stage"] == "provider_request"
    assert result["error"] == "Gemini provider request failed"
    assert "sensitive provider response" not in str(result)


def test_llm_empty_text_reports_finish_reason():
    response = SimpleNamespace(
        text=None,
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.SAFETY)],
    )
    result = _llm_service(lambda **_: response).generate_content(
        system_prompt="system",
        user_prompt="user",
    )

    assert result["success"] is False
    assert result["stage"] == "empty_response"
    assert result["finish_reason"] == "SAFETY"


def test_llm_response_extraction_failure_has_distinct_stage():
    class BrokenResponse:
        candidates = [SimpleNamespace(finish_reason=types.FinishReason.OTHER)]

        @property
        def text(self):
            raise AttributeError("sensitive provider response")

    result = _llm_service(lambda **_: BrokenResponse()).generate_content(
        system_prompt="system",
        user_prompt="user",
    )

    assert result["success"] is False
    assert result["stage"] == "response_extraction"
    assert result["finish_reason"] == "OTHER"
    assert "sensitive provider response" not in str(result)
