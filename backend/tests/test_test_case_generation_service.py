import json
import importlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.genai import types
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from app.api import test_cases as test_cases_api
from app.database.connection import Base
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as CaseEvidenceModel
from app.models.test_case_generation_run import TestCaseGenerationRun as GenerationRunModel
from app.models.project_requirement import ProjectRequirement
from app.models.test_case_requirement import TestCaseRequirement
from app.models.workflow_run import WorkflowRun
from app.schemas.test_case_schema import GeneratedTestCase,TestCaseGenerationRequest as GenerationRequest

from app.services.llm_services import LLMService
from app.llm.providers.gemini import GeminiProvider
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
        ProjectRequirement.__table__,
        TestCaseRequirement.__table__,
        WorkflowRun.__table__,
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
    generation_run = db.query(GenerationRunModel).one()
    assert generation_run.max_cases == 5
    assert generation_run.generated_case_count == 3
    assert generation_run.duplicate_rejected_count == 2
    assert generation_run.final_persisted_count == 1
    assert generation_run.retry_count == 2
    assert generation_run.status == "partial"
    assert service.last_generation_stats == {
        "requested_max_cases": 5,
        "generated_count": 3,
        "duplicate_rejected_count": 2,
        "invalid_rejected_count": 0,
        "insufficient_evidence_count": 0,
        "final_persisted_count": 1,
        "generation_status": "partial",
        "retry_count": 2,
    }
    assert db.query(CaseEvidenceModel).one().chunk_id == CHUNK_ID
    assert cases[0]["evidence"][0]["document_name"] == "login.md"
    assert cases[0]["evidence"][0]["source_type"] == "requirements"
    assert cases[0]["evidence"][0]["source_metadata"]["section"] == "Authentication"
    assert cases[0]["evidence"][0]["excerpt"] == (
        "Users can sign in with registered credentials."
    )


def test_multiple_cases_and_chunks_persist_without_duplicate_shared_links(db):
    second_chunk = DocumentChunk(
        id=18,
        document_id=DOCUMENT_ID,
        chunk_index=1,
        content="Users can reset their password by email.",
    )
    db.add(second_chunk)
    db.commit()

    first_case = _case("Sign in")
    first_case["evidence_chunk_ids"] = [CHUNK_ID, 18]
    second_case = _case("Password reset")
    second_case["description"] = "Verify that a user can reset a forgotten password by email."
    second_case["steps"][0]["action"] = "Request a password reset email for the registered account."
    second_case["steps"][0]["expected_result"] = "A password reset email is sent to the registered address."
    second_case["expected_result"] = "The registered user can complete the documented password reset flow."
    second_case["evidence_chunk_ids"] = [CHUNK_ID]
    evidence = [_evidence(), _evidence(18)]
    service = _service(
        db,
        {"success": True, "answer": json.dumps([first_case, second_case])},
        evidence=evidence,
    )

    cases = _generate(service)

    assert len(cases) == 2
    persisted_links = (
        db.query(CaseEvidenceModel)
        .order_by(CaseEvidenceModel.test_case_id, CaseEvidenceModel.chunk_id)
        .all()
    )
    assert [
        (link.test_case_id, link.document_id, link.chunk_id)
        for link in persisted_links
    ] == [
        (cases[0]["id"], DOCUMENT_ID, CHUNK_ID),
        (cases[0]["id"], DOCUMENT_ID, 18),
        (cases[1]["id"], DOCUMENT_ID, CHUNK_ID),
    ]
    assert {item["chunk_id"] for item in cases[0]["evidence"]} == {
        CHUNK_ID,
        18,
    }
    assert [item["chunk_id"] for item in cases[1]["evidence"]] == [CHUNK_ID]


def test_evidence_from_another_project_is_rejected_before_persistence(db):
    other_document = Document(
        id=102,
        filename="other-project.md",
        content_type="text/plain",
        storage_path="unused",
        project_id=PROJECT_ID + 1,
    )
    db.add(other_document)
    db.flush()
    db.add(
        DocumentChunk(
            id=18,
            document_id=other_document.id,
            chunk_index=0,
            content="Evidence belonging to another project.",
        )
    )
    db.commit()

    case = _case("Other-project evidence")
    case["evidence_chunk_ids"] = [18]
    service = _service(
        db,
        {"success": True, "answer": json.dumps([case])},
        evidence=[
            {
                **_evidence(18),
                "document_id": other_document.id,
                "document_name": other_document.filename,
            }
        ],
    )

    with pytest.raises(GenerationError, match="persistence_evidence_check"):
        _generate(service)

    _assert_no_generation_rows(db)


def test_post_commit_response_error_reuses_exact_workflow_generation_attempt(
    db,
    monkeypatch,
):
    workflow = WorkflowRun(
        id=1,
        project_id=PROJECT_ID,
        initiated_by=USER_ID,
        workflow_type="test_generation",
        status="running",
        input_data={},
    )
    db.add(workflow)
    db.commit()
    llm_calls = []
    service = _service(
        db,
        {"success": True, "answer": json.dumps([_case()])},
    )
    original_generate = service.llm_service.generate_content

    def generate_content(**kwargs):
        llm_calls.append(kwargs)
        return original_generate(**kwargs)

    service.llm_service.generate_content = generate_content
    original_commit = db.commit
    raised_after_commit = False

    def commit_then_raise_once():
        nonlocal raised_after_commit
        original_commit()
        if not raised_after_commit:
            raised_after_commit = True
            raise RuntimeError("simulated lost response after commit")

    monkeypatch.setattr(db, "commit", commit_then_raise_once)
    request = GenerationRequest(
        requirements_prompt="Generate login test cases."
    )
    with pytest.raises(GenerationError, match="post_commit_recovery"):
        service.generate(
            user_id=USER_ID,
            project_id=PROJECT_ID,
            request=request,
            workflow_run_id=workflow.id,
            workflow_attempt_number=1,
        )

    monkeypatch.setattr(db, "commit", original_commit)
    recovered = service.generate(
        user_id=USER_ID,
        project_id=PROJECT_ID,
        request=request,
        workflow_run_id=workflow.id,
        workflow_attempt_number=1,
        reuse_existing_workflow_attempt=True,
    )

    assert len(recovered) == 1
    assert recovered[0]["title"] == "Successful login"
    assert len(llm_calls) == service.MAX_GENERATION_ATTEMPTS
    assert db.scalar(select(func.count()).select_from(CaseModel)) == 1
    assert db.scalar(select(func.count()).select_from(GenerationRunModel)) == 1


def test_existing_project_duplicate_is_contextualized_and_filtered(db):
    existing = CaseModel(
        id=16,
        project_id=PROJECT_ID,
        created_by_user_id=USER_ID,
        title="  successful LOGIN ",
        description="Existing project case.",
        category="positive",
        priority="high",
        steps=[
            {
                "action": "Submit credentials.",
                "expected_result": "Authentication succeeds.",
            }
        ],
        expected_result="The user reaches the authenticated area.",
        review_status="draft",
    )
    db.add(existing)
    db.commit()
    prompts = {}
    service = _service(db, {"success": True, "answer": json.dumps([_case()])})
    llm_calls = []

    def capture_prompt(**kwargs):
        llm_calls.append(kwargs)
        prompts.update(kwargs)
        return {"success": True, "answer": json.dumps([_case()])}

    service.llm_service.generate_content = capture_prompt

    cases = _generate(service)

    assert cases == []
    existing_cases = json.loads(prompts["user_prompt"])["existing_project_test_cases"]
    assert existing_cases[0] == {
        "id": 16,
        "title": "  successful LOGIN ",
        "expected_result": "The user reaches the authenticated area.",
        "category": "positive",
        "requirement_keys": [],
    }
    assert "normalized title and expected result" in prompts["system_prompt"]
    assert len(llm_calls) == service.MAX_GENERATION_ATTEMPTS
    assert service.last_generation_stats["duplicate_rejected_count"] == 3
    assert service.last_generation_stats["retry_count"] == 2
    assert db.scalar(select(func.count()).select_from(CaseModel)) == 1
    assert db.scalar(select(func.count()).select_from(GenerationRunModel)) == 1


def test_generation_retries_invalid_candidates_then_persists_valid_case(db):
    service = _service(db, {"success": True, "answer": "[]"})
    responses = [
        {"success": True, "answer": json.dumps([{"title": "missing fields"}])},
        {"success": True, "answer": json.dumps([_case()])},
        {"success": True, "answer": "[]"},
    ]
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    service.llm_service.generate_content = generate_content

    cases = _generate(service)

    assert len(cases) == 1
    assert service.last_generation_stats["invalid_rejected_count"] == 1
    assert service.last_generation_stats["retry_count"] == 2
    assert len(calls) == 3


def test_max_cases_is_a_hard_limit_and_over_generation_is_accounted(db):
    cases = [_case(f"Login scenario {index}") for index in range(1, 4)]
    for index, case in enumerate(cases, start=1):
        case["steps"][0]["action"] = (
            "Submit valid credentials for the registered account."
            if index == 1
            else f"Submit an incorrect password on attempt number {index}."
            if index == 2
            else f"Submit a password with exactly {index + 10} characters."
        )
        case["expected_result"] = (
            f"The documented login result for scenario {index} occurs."
        )
        case["steps"][0]["expected_result"] = case["expected_result"]
    service = _service(
        db,
        {"success": True, "answer": json.dumps(cases)},
    )
    request = GenerationRequest(
        requirements_prompt="Generate login test cases.",
        max_cases=2,
    )

    result = service.generate(USER_ID, PROJECT_ID, request)

    assert len(result) == 2
    assert len(db.query(CaseModel).all()) == 2
    run = db.query(GenerationRunModel).one()
    assert run.max_cases == 2
    assert run.generated_case_count == 3
    assert run.invalid_rejected_count == 1
    assert run.final_persisted_count == 2
    assert run.retry_count == 0


def test_insufficient_supported_cases_return_partial_result_with_bounded_retries(db):
    service = _service(db, {"success": True, "answer": "[]"})
    calls = []

    def generate_empty(**kwargs):
        calls.append(kwargs)
        return {"success": True, "answer": "[]"}

    service.llm_service.generate_content = generate_empty
    request = GenerationRequest(
        requirements_prompt="Generate login test cases.",
        max_cases=4,
    )

    result = service.generate(USER_ID, PROJECT_ID, request)

    assert result == []
    assert len(calls) == service.MAX_GENERATION_ATTEMPTS
    run = db.query(GenerationRunModel).one()
    assert run.status == "partial"
    assert run.max_cases == 4
    assert run.generated_case_count == 0
    assert run.final_persisted_count == 0
    assert run.retry_count == service.MAX_GENERATION_ATTEMPTS - 1
    assert run.insufficient_evidence_count == 0


def test_semantically_similar_generated_scenarios_are_filtered(db):
    first = _case("Authenticate using a registered account")
    first["description"] = "Valid credentials open the authenticated user area."
    first["steps"][0]["action"] = "Sign in with the account's valid credentials."
    second = _case("Login with valid registered credentials")
    second["description"] = "A registered account reaches its authenticated area."
    second["steps"][0]["action"] = "Authenticate using the valid account credentials."
    response = {"success": True, "answer": json.dumps([first, second])}
    service = _service(db, response)

    result = _generate(service)

    assert len(result) == 1
    assert service.last_generation_stats["duplicate_rejected_count"] >= 1


def test_distinct_expected_outcomes_are_not_semantic_duplicates():
    successful = GeneratedTestCase.model_validate(_case("Sign in with credentials"))
    rejected_data = _case("Sign in with credentials")
    rejected_data["steps"][0]["expected_result"] = (
        "The account remains unauthenticated and an error is shown."
    )
    rejected_data["expected_result"] = (
        "The account is rejected and remains unauthenticated."
    )
    rejected = GeneratedTestCase.model_validate(rejected_data)

    assert not GenerationService._cases_are_duplicates(successful, rejected)


def test_all_supported_scenario_categories_have_behavioral_content(db):
    contents = [
        "A registered user can sign in using a valid email address and password.",
        "The system rejects an incorrect password and reports an authentication error.",
        "Passwords must contain between 12 and 64 characters.",
        "A user can retry sign-in after a failed attempt without losing the account.",
    ]
    evidence = []
    cases = []
    for index, (category, content, title, action, result_text) in enumerate(
        [
            ("positive", contents[0], "Valid sign-in", "Submit a registered email and valid password.", "The user reaches the authenticated page."),
            ("negative", contents[1], "Incorrect password", "Submit the registered email with an incorrect password.", "The system rejects authentication and reports the documented error."),
            ("boundary", contents[2], "Minimum password length", "Submit a password containing exactly 12 characters.", "The password meets the documented minimum length."),
            ("edge", contents[3], "Retry after failed sign-in", "Submit a failed sign-in followed by a valid retry.", "The retry succeeds without account loss."),
        ],
        start=1,
    ):
        chunk_id = CHUNK_ID if index == 1 else 17 + index
        if index > 1:
            db.add(
                DocumentChunk(
                    id=chunk_id,
                    document_id=DOCUMENT_ID,
                    chunk_index=index - 1,
                    content=content,
                )
            )
        item = {**_evidence(chunk_id), "content": content}
        evidence.append(item)
        case = _case(title)
        case.update(
            category=category,
            description=content,
            steps=[{"action": action, "expected_result": result_text}],
            expected_result=result_text,
            evidence_chunk_ids=[chunk_id],
        )
        cases.append(case)
    db.commit()
    service = _service(
        db,
        {"success": True, "answer": json.dumps(cases)},
        evidence=evidence,
    )
    request = GenerationRequest(
        requirements_prompt="Generate scenario coverage for documented sign-in rules.",
        max_cases=4,
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)

    assert {case["category"] for case in generated} == {
        "positive",
        "negative",
        "boundary",
        "edge",
    }
    assert all(case["steps"][0]["action"] for case in generated)


def test_multiple_requirements_and_documents_are_traced_and_persisted(db):
    second_document = Document(
        id=102,
        filename="password-rules.json",
        content_type="application/json",
        storage_path="unused",
        project_id=PROJECT_ID,
        source_type="requirements",
    )
    db.add(second_document)
    db.add(
        DocumentChunk(
            id=18,
            document_id=second_document.id,
            chunk_index=0,
            content='{"requirement_id":"REQ-PASS-01","description":"Passwords must contain at least 12 characters."}',
        )
    )
    db.commit()
    evidence = [
        _evidence(),
        {
            **_evidence(18),
            "document_id": second_document.id,
            "document_name": second_document.filename,
            "content": '{"requirement_id":"REQ-PASS-01","description":"Passwords must contain at least 12 characters."}',
        },
    ]
    login_case = _case("Sign in with registered credentials")
    login_case["requirement_keys"] = ["REQ-LOGIN-01"]
    case = _case("Password minimum length")
    case["description"] = "Enforce the password length requirement."
    case["requirement_keys"] = ["REQ-PASS-01"]
    case["steps"][0]["action"] = "Submit a password containing exactly 12 characters."
    case["steps"][0]["expected_result"] = "The password meets the documented minimum length."
    case["expected_result"] = "The password is accepted at the documented minimum."
    case["evidence_chunk_ids"] = [18]
    request = GenerationRequest(
        requirements_prompt="REQ-LOGIN-01: Users sign in with registered credentials.",
        requirements=[
            {
                "requirement_key": "REQ-PASS-01",
                "description": "Passwords must contain at least 12 characters.",
                "evidence_chunk_ids": [18],
            }
        ],
        max_cases=2,
    )
    service = _service(
        db,
        {"success": True, "answer": json.dumps([login_case, case])},
        evidence=evidence,
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)

    requirements = {
        row.requirement_key: row
        for row in db.query(ProjectRequirement).all()
    }
    assert len(generated) == 2
    assert generated[0]["requirement_ids"] == [requirements["REQ-LOGIN-01"].id]
    assert generated[1]["requirement_ids"] == [requirements["REQ-PASS-01"].id]
    assert db.query(TestCaseRequirement).count() == 2
    assert {item["document_id"] for case_item in generated for item in case_item["evidence"]} == {
        DOCUMENT_ID,
        102,
    }
    assert generated[1]["severity"] == "medium"


def test_fewer_cases_are_returned_than_requested_when_only_one_is_distinct(db):
    first = _case("One supported login case")
    first["steps"][0]["action"] = "Submit valid registered credentials."
    first["steps"][0]["expected_result"] = "The account is authenticated."
    response = {"success": True, "answer": json.dumps([first])}
    service = _service(db, response)
    request = GenerationRequest(
        requirements_prompt="Generate login test cases.",
        max_cases=5,
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)

    assert len(generated) == 1
    assert len(db.query(CaseModel).all()) == 1
    assert service.last_generation_stats["requested_max_cases"] == 5
    assert service.last_generation_stats["final_persisted_count"] == 1


def test_concurrency_feedback_prompts_for_actionable_supported_steps(db):
    prompts = {}
    response_case = _case("Concurrent appointment booking")
    response_case["description"] = "Exercise two requests for one appointment slot."
    response_case["steps"] = [
        {
            "action": "Prepare two independent authenticated patient sessions.",
            "expected_result": "Both sessions are authenticated.",
        },
        {
            "action": "Select the same available appointment slot and submit both booking requests concurrently.",
            "expected_result": "Both requests are submitted at the same time.",
        },
        {
            "action": "Inspect both booking responses and the slot booking record.",
            "expected_result": "Exactly one booking succeeds, the other receives the documented conflict response, and the slot has one confirmed booking.",
        },
    ]
    response_case["expected_result"] = (
        "Only one booking is confirmed for the appointment slot."
    )
    service = _service(
        db,
        {"success": True, "answer": json.dumps([response_case])},
    )

    def capture_prompt(**kwargs):
        prompts.update(kwargs)
        return {"success": True, "answer": json.dumps([response_case])}

    service.llm_service.generate_content = capture_prompt
    request = GenerationRequest(
        requirements_prompt=(
            "Reviewer feedback: Make concurrent booking steps actionable. "
            "The same available appointment slot must not be booked twice."
        )
    )

    cases = service.generate(USER_ID, PROJECT_ID, request)

    assert len(cases) == 1
    normalized_system_prompt = " ".join(prompts["system_prompt"].split())
    assert "two independent authenticated sessions" in normalized_system_prompt
    assert "submit the two requests concurrently" in normalized_system_prompt
    assert "documented conflict outcome" in normalized_system_prompt
    assert "Reviewer feedback" in prompts["user_prompt"]


def test_empty_array_with_missing_login_evidence_logs_likely_gap(db, caplog):
    caplog.set_level("INFO")
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

    assert _generate(service) == []

    assert "authentication_evidence_chunks=0" in caplog.text
    assert "diagnostic=likely_insufficient_evidence" in caplog.text
    assert db.query(GenerationRunModel).one().final_persisted_count == 0


def test_empty_array_with_login_evidence_logs_topic_match(db, caplog):
    caplog.set_level("INFO")
    service = _service(db, {"success": True, "answer": "[]"})

    assert _generate(service) == []

    assert "authentication_evidence_chunks=1" in caplog.text
    assert "diagnostic=authentication_evidence_present" in caplog.text
    assert db.query(GenerationRunModel).one().final_persisted_count == 0


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


def test_invalid_case_schema_is_rejected_and_accounted_without_saving_cases(db):
    invalid_case = _case()
    invalid_case.pop("title")
    service = _service(
        db,
        {"success": True, "answer": json.dumps([invalid_case])},
    )

    assert _generate(service) == []

    assert db.scalar(select(func.count()).select_from(CaseModel)) == 0
    run = db.query(GenerationRunModel).one()
    assert run.invalid_rejected_count == service.MAX_GENERATION_ATTEMPTS
    assert run.final_persisted_count == 0


def test_invalid_evidence_reference_is_rejected_and_accounted(db):
    invalid_case = _case()
    invalid_case["evidence_chunk_ids"] = [999]
    service = _service(
        db,
        {"success": True, "answer": json.dumps([invalid_case])},
    )

    assert _generate(service) == []

    assert db.scalar(select(func.count()).select_from(CaseModel)) == 0
    run = db.query(GenerationRunModel).one()
    assert run.invalid_rejected_count == service.MAX_GENERATION_ATTEMPTS
    assert run.final_persisted_count == 0


def test_persistence_failure_rolls_back_all_rows(db):
    second_case = _case("Second login case")
    second_case["evidence_chunk_ids"] = [18]
    second_case["steps"][0]["action"] = "Submit an invalid password on the fifth attempt."
    second_case["steps"][0]["expected_result"] = "The documented lockout rule is applied."
    second_case["expected_result"] = "The account is locked after the fifth failed attempt."
    service = _service(
        db,
        {"success": True, "answer": json.dumps([_case(), second_case])},
        evidence=[_evidence(), _evidence(18)],
    )

    with pytest.raises(GenerationError, match="persistence_evidence_check"):
        _generate(service)

    _assert_no_generation_rows(db)


def _llm_service(response):
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=response)
    )
    provider = GeminiProvider(
        api_key="not-a-real-key",
        model_name="test-model",
        client=client,
    )
    return LLMService(provider=provider)


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
    assert provider_call["config"].temperature == 0.2


def test_markdown_fenced_json_array_is_parsed_and_persisted(db):
    service = _service(
        db,
        {
            "success": True,
            "answer": "```json\n" + json.dumps([_case()]) + "\n```",
        },
    )

    cases = _generate(service)

    assert len(cases) == 1
    assert cases[0]["title"] == "Successful login"
    assert db.scalar(select(func.count()).select_from(CaseModel)) == 1


def test_generated_case_rejects_placeholder_preconditions_and_invalid_severity():
    with pytest.raises(ValidationError):
        GeneratedTestCase.model_validate(
            {
                "title": "Login test",
                "description": "Check login flow.",
                "category": "positive",
                "priority": "high",
                "severity": "urgent",
                "preconditions": "N/A",
                "steps": [{"action": "Login", "expected_result": "OK"}],
                "expected_result": "The user is logged in.",
                "evidence_chunk_ids": [CHUNK_ID],
            }
        )


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
