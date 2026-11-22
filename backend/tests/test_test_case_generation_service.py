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
from app.models.document_embedding import DocumentEmbedding
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as CaseEvidenceModel
from app.models.test_case_generation_run import TestCaseGenerationRun as GenerationRunModel
from app.models.project_requirement import ProjectRequirement
from app.models.test_case_requirement import TestCaseRequirement
from app.api.test_cases import _serialize_test_case
from app.models.workflow_run import WorkflowRun
from app.schemas.test_case_schema import GeneratedTestCase,TestCaseGenerationRequest as GenerationRequest
from app.agents.contracts import AgentContext
from app.agents.test_generation_agent import (
    TestGenerationAgent as GenerationAgent,
)

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
        DocumentEmbedding.__table__,
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
    assert cases[0]["test_type"] == "functional"
    assert db.query(CaseModel).one().test_type == "functional"
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
    stats = service.last_generation_stats
    assert stats["requested_max_cases"] == 5
    assert stats["generated_count"] == 3
    assert stats["duplicate_rejected_count"] == 2
    assert stats["final_persisted_count"] == 1
    assert stats["generation_status"] == "partial"
    assert "persisted 1 of 5 requested" in stats["diagnostic"]
    assert "2 duplicate" in stats["diagnostic"]
    assert "invalid" not in stats["diagnostic"]
    assert stats["retry_count"] == 2
    assert len(stats["response_diagnostics"]) == 3
    duplicate = stats["candidate_diagnostics"][0]
    assert duplicate["comparison"]["matched_candidate_index"] == 1
    assert duplicate["comparison"]["rule"] == "exact_behavioral_scenario"
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

    with pytest.raises(GenerationError, match="persistence_evidence_check") as error:
        _generate(service)

    _assert_no_generation_rows(db)
    stats = error.value.diagnostics["generation_stats"]
    assert stats["generation_status"] == "failed"
    assert stats["final_persisted_count"] == 0
    assert any(
        reason["code"] == "persistence_failure"
        for item in stats["candidate_diagnostics"]
        for reason in item["reasons"]
    )


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
    with pytest.raises(GenerationError, match="post_commit_recovery") as error:
        service.generate(
            user_id=USER_ID,
            project_id=PROJECT_ID,
            request=request,
            workflow_run_id=workflow.id,
            workflow_attempt_number=1,
        )

    assert "No cases were saved" not in str(error.value)
    assert "transaction may have committed" in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)
    recovery_stats = error.value.diagnostics["generation_stats"]
    assert recovery_stats["final_persisted_count"] == 1
    assert "committed successfully" in recovery_stats["diagnostic"]
    persisted_outcomes = [
        item
        for item in recovery_stats["candidate_outcomes"]
        if item["persisted"]
    ]
    assert persisted_outcomes == [
        {
            "attempt_number": 1,
            "candidate_index": 1,
            "outcome": "accepted",
            "persisted": True,
        }
    ]

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
                "action": "Submit valid credentials.",
                "expected_result": "The account is authenticated.",
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
    assert (
        "matching title and overall expected result alone"
        in " ".join(prompts["system_prompt"].split()).lower()
    )
    assert len(llm_calls) == service.MAX_GENERATION_ATTEMPTS
    assert service.last_generation_stats["duplicate_rejected_count"] == 3
    assert service.last_generation_stats["retry_count"] == 2
    duplicate = service.last_generation_stats["candidate_diagnostics"][0]
    assert duplicate["comparison"]["rule"] == "scenario_component_similarity"
    assert duplicate["comparison"]["matched_existing_case_id"] == 16
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
    feedback = json.loads(calls[1]["user_prompt"])["previous_rejection_feedback"]
    assert "missing_required_field" in feedback[0]["reason_codes"]
    assert feedback[0]["stage"] == "schema_validation"


def test_same_title_and_result_with_materially_different_steps_are_distinct():
    first = GeneratedTestCase.model_validate(_case("Account login"))
    different_steps = _case("Account login")
    different_steps["steps"] = [
        {
            "action": "Open the account recovery page and submit the registered email.",
            "expected_result": "A recovery message is sent to the registered address.",
        }
    ]
    second = GeneratedTestCase.model_validate(different_steps)

    assert not GenerationService._cases_are_duplicates(first, second)


def test_same_title_and_result_in_different_categories_are_distinct():
    first_data = _case("Account login")
    second_data = _case("Account login")
    second_data["category"] = "negative"
    first = GeneratedTestCase.model_validate(first_data)
    second = GeneratedTestCase.model_validate(second_data)

    assert not GenerationService._cases_are_duplicates(first, second)


def test_generated_test_type_defaults_only_when_missing_or_null(db):
    provided = _case("Explicit API test type")
    provided["test_type"] = "api"
    response = {"success": True, "answer": json.dumps([provided])}
    service = _service(db, response)
    request = GenerationRequest(
        requirements_prompt="Generate a login API test.",
        max_cases=1,
        categories=["positive"],
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)

    assert generated[0]["test_type"] == "api"
    assert db.query(CaseModel).one().test_type == "api"
    assert db.query(CaseModel).one().review_status == "draft"


def test_null_test_type_defaults_and_invalid_test_type_is_diagnosed(db):
    defaulted = _case("Default null test type")
    defaulted["test_type"] = None
    valid_service = _service(
        db,
        {"success": True, "answer": json.dumps([defaulted])},
    )
    valid_result = valid_service.generate(
        USER_ID,
        PROJECT_ID,
        GenerationRequest(
            requirements_prompt="Generate a login test.",
            max_cases=1,
            categories=["positive"],
        ),
    )
    assert valid_result[0]["test_type"] == "functional"

    invalid = _case("Invalid explicit test type")
    invalid["test_type"] = " "
    invalid_service = _service(
        db,
        {"success": True, "answer": json.dumps([invalid])},
    )
    assert _generate(invalid_service) == []
    stats = invalid_service.last_generation_stats
    assert stats["invalid_rejected_count"] == 3
    assert stats["candidate_diagnostics"][0]["reasons"][0]["code"] == (
        "invalid_test_type"
    )


@pytest.mark.parametrize(
    ("invalid_field", "reason_code"),
    [
        ("title", "missing_required_field"),
        ("steps", "invalid_test_steps"),
        ("expected_result", "missing_expected_result"),
        ("requirement_keys", "unknown_requirement_id"),
        ("evidence_chunk_ids", "unknown_evidence_chunk"),
        ("category", "invalid_category"),
    ],
)
def test_candidate_rejections_include_safe_stage_and_reason(
    db,
    invalid_field,
    reason_code,
):
    candidate = _case(f"Invalid {invalid_field}")
    if invalid_field == "title":
        candidate.pop("title")
    elif invalid_field == "steps":
        candidate["steps"] = []
    elif invalid_field == "expected_result":
        candidate.pop("expected_result")
    elif invalid_field == "requirement_keys":
        candidate["requirement_keys"] = ["REQ-999"]
    elif invalid_field == "evidence_chunk_ids":
        candidate["evidence_chunk_ids"] = [999]
    else:
        candidate["category"] = "unsupported"

    service = _service(
        db,
        {"success": True, "answer": json.dumps([candidate])},
    )

    assert _generate(service) == []

    diagnostics = service.last_generation_stats["candidate_diagnostics"]
    assert len(diagnostics) == service.MAX_GENERATION_ATTEMPTS
    assert all(
        item["reasons"][0]["code"] == reason_code
        and item["stage"]
        and item["attempt_number"] >= 1
        for item in diagnostics
    )
    assert all("content" not in item and "candidate" not in item for item in diagnostics)


def test_run_19_aggregate_scenario_has_candidate_diagnostics_and_consistent_counts(db):
    valid = _case("Supported sign-in scenario")
    valid["steps"][0]["expected_result"] = "The account is authenticated."
    valid["expected_result"] = "The user reaches the authenticated area."
    missing_result = _case("Missing expected result")
    del missing_result["expected_result"]
    duplicate = dict(valid)
    invalid_type = _case("Invalid test type")
    invalid_type["test_type"] = ""

    responses = iter(
        [
            {"success": True, "answer": json.dumps([valid, missing_result])},
            {"success": True, "answer": json.dumps([duplicate])},
            {"success": True, "answer": json.dumps([invalid_type])},
        ]
    )
    service = _service(db, {"success": True, "answer": "[]"})
    service.llm_service.generate_content = lambda **_: next(responses)
    request = GenerationRequest(
        requirements_prompt="Generate supported sign-in tests.",
        max_cases=5,
        categories=["positive"],
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)
    stats = service.last_generation_stats

    assert len(generated) == 1
    assert stats["requested_max_cases"] == 5
    assert stats["generated_count"] == 4
    assert stats["duplicate_rejected_count"] == 1
    assert stats["invalid_rejected_count"] == 2
    assert stats["insufficient_evidence_count"] == 0
    assert stats["final_persisted_count"] == 1
    assert stats["retry_count"] == 2
    assert stats["generation_status"] == "partial"
    assert "persisted 1 of 5 requested" in stats["diagnostic"]
    assert "1 duplicate" in stats["diagnostic"]
    assert "2 invalid" in stats["diagnostic"]
    assert [item["candidate_index"] for item in stats["candidate_diagnostics"]] == [
        2,
        3,
        4,
    ]
    assert [
        item["reasons"][0]["code"]
        for item in stats["candidate_diagnostics"]
    ] == [
        "missing_expected_result",
        "duplicate_test_case",
        "invalid_test_type",
    ]
    assert [
        item["requested_capacity"] for item in stats["response_diagnostics"]
    ] == [5, 4, 4]
    assert [
        item["generation_remaining"] for item in stats["response_diagnostics"]
    ] == [5, 4, 4]
    assert [
        item["parsed_candidate_count"] for item in stats["response_diagnostics"]
    ] == [2, 1, 1]
    assert [
        item["schema_valid_candidate_count"]
        for item in stats["response_diagnostics"]
    ] == [1, 1, 0]
    assert [
        item["accepted_candidate_count"] for item in stats["response_diagnostics"]
    ] == [1, 0, 0]
    assert [
        item["rejected_candidate_count"] for item in stats["response_diagnostics"]
    ] == [1, 1, 1]
    assert [
        item["persisted_candidate_count"]
        for item in stats["response_diagnostics"]
    ] == [1, 0, 0]
    assert stats["candidate_outcomes"] == [
        {
            "attempt_number": 1,
            "candidate_index": 1,
            "outcome": "accepted",
            "persisted": True,
        },
        {
            "attempt_number": 1,
            "candidate_index": 2,
            "outcome": "rejected",
            "persisted": False,
        },
        {
            "attempt_number": 2,
            "candidate_index": 3,
            "outcome": "rejected",
            "persisted": False,
        },
        {
            "attempt_number": 3,
            "candidate_index": 4,
            "outcome": "rejected",
            "persisted": False,
        },
    ]
    assert generated[0]["test_type"] == "functional"
    run = db.query(GenerationRunModel).one()
    assert run.generated_case_count == stats["generated_count"]
    assert run.invalid_rejected_count == stats["invalid_rejected_count"]
    assert run.duplicate_rejected_count == stats["duplicate_rejected_count"]
    assert run.final_persisted_count == stats["final_persisted_count"]


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
    assert run.invalid_rejected_count == 0
    assert service.last_generation_stats["excess_candidate_count"] == 1
    assert run.final_persisted_count == 2
    assert run.retry_count == 0


def test_empty_model_response_fails_without_repeating_an_identical_request(db):
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
    assert len(calls) == 1
    run = db.query(GenerationRunModel).one()
    assert run.status == "failed"
    assert run.max_cases == 4
    assert run.generated_case_count == 0
    assert run.final_persisted_count == 0
    assert run.retry_count == 0
    assert run.insufficient_evidence_count == 0
    assert service.last_generation_stats["diagnostic"] == (
        "The model returned an empty JSON array."
    )
    response_diagnostic = service.last_generation_stats["response_diagnostics"][0]
    assert response_diagnostic["requested_capacity"] == 4
    assert response_diagnostic["response_parse_status"] == "parsed"
    assert response_diagnostic["parsed_candidate_count"] == 0
    assert response_diagnostic["accepted_candidate_count"] == 0
    assert response_diagnostic["rejected_candidate_count"] == 0


def test_rejected_candidates_then_empty_response_preserves_outcome_and_feedback(db):
    existing = CaseModel(
        project_id=PROJECT_ID,
        created_by_user_id=USER_ID,
        **{
            key: value
            for key, value in _case().items()
            if key
            in {
                "title",
                "description",
                "category",
                "priority",
                "steps",
                "expected_result",
            }
        },
        review_status="draft",
    )
    workflow = WorkflowRun(
        project_id=PROJECT_ID,
        initiated_by=USER_ID,
        workflow_type="test_generation",
        status="running",
        input_data={},
    )
    db.add_all([existing, workflow])
    db.commit()
    existing_id = existing.id
    responses = iter(
        [
            {
                "success": True,
                "answer": json.dumps([_case()]),
                "provider": "gemini",
                "model": "gemini-test",
                "fallback_attempted": False,
                "fallback_succeeded": False,
                "provider_attempt_count": 3,
                "retry_count": 1,
                "primary_retry_count": 1,
                "retry_diagnostics": [
                    {
                        "provider": "gemini",
                        "attempt_number": 1,
                        "reason": "rate_limit",
                        "delay_seconds": 0.25,
                        "fallback_attempt": False,
                    }
                ],
                "finish_reason": "STOP",
                "input_token_count": 120,
                "output_token_count": 40,
                "total_token_count": 160,
            },
            {
                "success": True,
                "answer": "[]",
                "provider": "groq",
                "model": "groq-test",
                "fallback_attempted": True,
                "fallback_succeeded": True,
                "finish_reason": "STOP",
            },
        ]
    )
    prompts = []
    service = _service(db, {})

    def generate_content(**kwargs):
        prompts.append(kwargs)
        return next(responses)

    service.llm_service.generate_content = generate_content
    result = service.generate(
        USER_ID,
        PROJECT_ID,
        GenerationRequest(
            requirements_prompt="Generate login cases.",
            max_cases=3,
        ),
        workflow_run_id=workflow.id,
        workflow_attempt_number=2,
        workflow_task_id=77,
    )

    assert result == []
    stats = service.last_generation_stats
    assert stats["generated_count"] == 1
    assert stats["duplicate_rejected_count"] == 1
    assert stats["final_persisted_count"] == 0
    assert stats["generation_status"] == "failed"
    assert "Generated 1 candidate(s)" in stats["diagnostic"]
    assert "1 duplicate" in stats["diagnostic"]
    assert "subsequent model response returned an empty" in stats["diagnostic"]
    rejection = stats["candidate_diagnostics"][0]
    assert rejection["comparison"]["matched_existing_case_id"] == existing_id
    assert rejection["comparison"]["rule"] == "scenario_component_similarity"
    feedback = json.loads(prompts[1]["user_prompt"])["previous_rejection_feedback"]
    assert feedback[0]["stage"] == "duplicate_detection"
    assert feedback[0]["reason_codes"] == ["duplicate_test_case"]
    assert feedback[0]["duplicate_match"]["matched_existing_case_id"] == existing_id
    feedback_text = json.dumps(feedback).lower()
    assert "successful login" not in feedback_text
    assert "submit valid credentials" not in feedback_text
    assert stats["response_diagnostics"][0]["provider"] == "gemini"
    assert stats["response_diagnostics"][0]["model"] == "gemini-test"
    assert stats["response_diagnostics"][0]["input_token_count"] == 120
    assert stats["response_diagnostics"][0]["provider_attempt_count"] == 3
    assert stats["response_diagnostics"][0]["retry_count"] == 1
    assert stats["response_diagnostics"][0]["primary_retry_count"] == 1
    assert stats["response_diagnostics"][0]["retry_diagnostics"][0]["reason"] == (
        "rate_limit"
    )
    assert stats["response_diagnostics"][1]["fallback_succeeded"] is True
    correlation_id = stats["correlation_id"]
    assert correlation_id.startswith(f"wf{workflow.id}-task77-gen2-")
    assert all(
        call["metadata"]["correlation_id"] == correlation_id
        for call in prompts
    )
    assert prompts[0]["metadata"]["workflow_id"] == workflow.id
    assert prompts[0]["metadata"]["task_id"] == 77
    assert prompts[0]["metadata"]["generation_attempt_number"] == 2
    assert prompts[0]["request_id"].startswith(correlation_id)


def test_generation_retries_do_not_persist_the_same_candidate_twice(db):
    repeated_candidate = {"success": True, "answer": json.dumps([_case()])}
    responses = iter(
        [
            repeated_candidate,
            repeated_candidate,
            {"success": True, "answer": "[]"},
        ]
    )
    service = _service(db, {})
    service.llm_service.generate_content = lambda **_: next(responses)

    cases = _generate(service)

    assert len(cases) == 1
    assert db.query(CaseModel).count() == 1
    generation_run = db.query(GenerationRunModel).one()
    assert generation_run.final_persisted_count == 1
    assert generation_run.duplicate_rejected_count == 1
    assert generation_run.status == "partial"


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


def test_identical_behavioral_scenarios_are_duplicates_even_with_different_titles():
    original = GeneratedTestCase.model_validate(_case("Successful login"))
    reworded_title = GeneratedTestCase.model_validate(
        _case("Authenticate a registered account")
    )

    match = GenerationService._duplicate_match(original, reworded_title)

    assert match is not None
    assert match["rule"] == "exact_behavioral_scenario"


def test_shared_setup_with_different_execution_conditions_is_distinct():
    valid_login = _case("Sign in")
    valid_login["steps"] = [
        {
            "action": "Open the sign-in page.",
            "expected_result": "The sign-in form is displayed.",
        },
        {
            "action": "Enter a valid email and password.",
            "expected_result": "The authenticated dashboard is displayed.",
        },
    ]
    valid_login["expected_result"] = "The registered user reaches the dashboard."

    invalid_login = _case("Sign in")
    invalid_login["steps"] = [
        {
            "action": "Open the sign-in page.",
            "expected_result": "The sign-in form is displayed.",
        },
        {
            "action": "Enter an invalid email and password.",
            "expected_result": "Authentication is rejected and the user stays signed out.",
        },
    ]
    invalid_login["expected_result"] = (
        "The user remains unauthenticated after the invalid credentials."
    )

    assert not GenerationService._cases_are_duplicates(
        GeneratedTestCase.model_validate(valid_login),
        GeneratedTestCase.model_validate(invalid_login),
    )


def test_shared_steps_with_different_outcomes_are_distinct():
    completed = _case("Process payment")
    completed["steps"][0] = {
        "action": "Submit the payment using the saved card.",
        "expected_result": "The payment is approved and a receipt is issued.",
    }
    completed["expected_result"] = "The order is paid and a receipt is available."

    declined = _case("Process payment")
    declined["steps"][0] = {
        "action": "Submit the payment using the saved card.",
        "expected_result": "The payment is declined and no receipt is issued.",
    }
    declined["expected_result"] = (
        "The order remains unpaid and the customer is notified of the decline."
    )

    assert not GenerationService._cases_are_duplicates(
        GeneratedTestCase.model_validate(completed),
        GeneratedTestCase.model_validate(declined),
    )


def test_different_requirement_ids_do_not_hide_an_identical_scenario():
    first = _case("Successful login")
    first["requirement_keys"] = ["REQ-AUTH-01"]
    second = _case("Authenticate registered user")
    second["requirement_keys"] = ["REQ-AUTH-99"]

    assert GenerationService._cases_are_duplicates(
        GeneratedTestCase.model_validate(first),
        GeneratedTestCase.model_validate(second),
    )


def test_similar_authentication_terms_do_not_merge_different_functionality():
    login = _case("Authenticate user")
    login["steps"][0] = {
        "action": "Submit the registered user's password to sign in.",
        "expected_result": "The user reaches the protected dashboard.",
    }
    login["expected_result"] = "The user is authenticated for the session."

    password_reset = _case("Authenticate user")
    password_reset["steps"][0] = {
        "action": "Submit the registered user's email to request a password reset.",
        "expected_result": "A password reset message is sent to the email address.",
    }
    password_reset["expected_result"] = (
        "The user receives a password reset message and is not signed in."
    )

    assert not GenerationService._cases_are_duplicates(
        GeneratedTestCase.model_validate(login),
        GeneratedTestCase.model_validate(password_reset),
    )


def test_slightly_reworded_equivalent_scenario_is_duplicate():
    original = _case("Successful login")
    original["steps"][0]["action"] = (
        "Submit valid credentials for the registered account."
    )
    reworded = _case("Authenticate registered account")
    reworded["steps"][0]["action"] = (
        "Submit the registered account's valid credentials."
    )

    match = GenerationService._duplicate_match(
        GeneratedTestCase.model_validate(original),
        GeneratedTestCase.model_validate(reworded),
    )

    assert match is not None
    assert match["rule"] == "scenario_component_similarity"
    assert "semantic_jaccard" in match["comparison_methods"]
    assert match["comparison_thresholds"] == [0.9]
    assert match["action_similarities"] == [1.0]


def test_incomplete_candidate_is_not_classified_as_duplicate():
    incomplete = GeneratedTestCase.model_construct(
        title="Incomplete case",
        description="Incomplete",
        test_type="functional",
        category="positive",
        priority="medium",
        severity="medium",
        preconditions=None,
        steps=[],
        expected_result="The user is authenticated.",
        evidence_chunk_ids=[],
        requirement_keys=[],
    )
    complete = GeneratedTestCase.model_validate(_case())

    assert not GenerationService._cases_are_duplicates(incomplete, complete)


def test_existing_case_from_another_project_is_not_a_duplicate(db):
    other_project_case = CaseModel(
        project_id=PROJECT_ID + 1,
        created_by_user_id=USER_ID,
        title="Successful login",
        description="Equivalent but isolated case.",
        category="positive",
        priority="high",
        preconditions="A registered account exists.",
        steps=[
            {
                "action": "Submit valid credentials.",
                "expected_result": "The account is authenticated.",
            }
        ],
        expected_result="The user reaches the authenticated area.",
        review_status="draft",
    )
    db.add(other_project_case)
    db.commit()
    service = _service(
        db,
        {"success": True, "answer": json.dumps([_case()])},
    )

    generated = service.generate(
        USER_ID,
        PROJECT_ID,
        GenerationRequest(
            requirements_prompt="Generate a login test.",
            max_cases=1,
            categories=["positive"],
        ),
    )

    assert len(generated) == 1
    assert service.last_generation_stats["duplicate_rejected_count"] == 0


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


@pytest.mark.parametrize(
    ("key", "description", "title", "action", "expected"),
    [
        (
            "REQ-002",
            "Authentication supports sign-in and sign-out; protected pages require authentication.",
            "Verify sign-in and protected pages require authentication",
            "Sign in with a registered account and open a protected page.",
            "The authenticated user can access the protected page.",
        ),
        (
            "REQ-003",
            "Users can search for doctors by name, specialty, and available date.",
            "Search doctors by specialty and available date",
            "Search for a doctor using the specialty and available date filters.",
            "Matching doctors are shown for the selected specialty and date.",
        ),
        (
            "REQ-004",
            "A patient can book an available appointment slot.",
            "Book an available appointment slot",
            "Select an available appointment slot and confirm the booking.",
            "The selected appointment slot is booked for the patient.",
        ),
        (
            "REQ-001",
            "Patient registration requires a unique email address.",
            "Register a patient using a unique email address",
            "Submit patient registration details with a unique email address.",
            "The patient is registered with the supplied unique email address.",
        ),
    ],
)
def test_missing_model_requirement_keys_are_mapped_by_semantic_relevance(
    db,
    key,
    description,
    title,
    action,
    expected,
):
    evidence = {
        **_evidence(),
        "content": description,
    }
    db.query(DocumentChunk).filter(DocumentChunk.id == CHUNK_ID).one().content = (
        description
    )
    db.commit()
    generated_case = _case(title)
    generated_case.update(
        description=description,
        steps=[{"action": action, "expected_result": expected}],
        expected_result=expected,
    )
    service = _service(
        db,
        {"success": True, "answer": json.dumps([generated_case])},
        evidence=[evidence],
    )
    request = GenerationRequest(
        requirements_prompt=description,
        requirements=[
            {
                "requirement_key": key,
                "description": description,
                "evidence_chunk_ids": [CHUNK_ID],
            }
        ],
        max_cases=1,
        categories=["positive"],
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)

    assert generated[0]["requirements"][0]["requirement_key"] == key
    assert generated[0]["requirement_ids"]
    assert service.last_generation_stats["traced_case_count"] == 1
    assert service.last_generation_stats["requirement_keys_covered"] == [key]
    saved = db.query(CaseModel).one()
    assert _serialize_test_case(saved)["requirements"][0]["requirement_key"] == key


def test_semantic_mapping_links_multiple_requirements_for_one_case(db):
    requirements = [
        {
            "requirement_key": "REQ-001",
            "description": "Patient registration requires a unique email address.",
            "evidence_chunk_ids": [CHUNK_ID],
        },
        {
            "requirement_key": "REQ-003",
            "description": "Users can search doctors by name and specialty.",
            "evidence_chunk_ids": [CHUNK_ID],
        },
    ]
    evidence = {
        **_evidence(),
        "content": "Register a patient and search for doctors by specialty.",
    }
    db.query(DocumentChunk).filter(DocumentChunk.id == CHUNK_ID).one().content = (
        evidence["content"]
    )
    db.commit()
    generated_case = _case("Register a patient and search doctors by specialty")
    generated_case.update(
        description="Register a patient and search the doctor directory.",
        steps=[
            {
                "action": "Register a patient with a unique email, then search doctors by specialty.",
                "expected_result": "The patient is registered and matching doctors are listed.",
            }
        ],
        expected_result="The patient is registered and matching doctors are listed.",
    )
    service = _service(
        db,
        {"success": True, "answer": json.dumps([generated_case])},
        evidence=[evidence],
    )

    generated = service.generate(
        USER_ID,
        PROJECT_ID,
        GenerationRequest(
            requirements_prompt="Cover patient registration and doctor search.",
            requirements=requirements,
            max_cases=1,
            categories=["positive"],
        ),
    )

    assert {
        item["requirement_key"] for item in generated[0]["requirements"]
    } == {"REQ-001", "REQ-003"}
    assert service.last_generation_stats["traced_case_count"] == 1
    assert service.last_generation_stats["requirement_keys_covered"] == [
        "REQ-001",
        "REQ-003",
    ]


def test_unrelated_case_remains_unmapped_and_invalid_key_is_rejected(db):
    requirement = {
        "requirement_key": "REQ-002",
        "description": "Authentication supports sign-in and protected pages.",
        "evidence_chunk_ids": [CHUNK_ID],
    }
    evidence = {**_evidence(), "content": requirement["description"]}
    db.query(DocumentChunk).filter(DocumentChunk.id == CHUNK_ID).one().content = (
        evidence["content"]
    )
    db.commit()
    unrelated = _case("Export REQ-002 from the quality dashboard report")
    unrelated.update(
        description="Download a report from the analytics dashboard.",
        steps=[
            {
                "action": "Export the quality dashboard report.",
                "expected_result": "The report is downloaded.",
            }
        ],
        expected_result="The report is downloaded.",
    )
    service = _service(
        db,
        {"success": True, "answer": json.dumps([unrelated])},
        evidence=[evidence],
    )
    request = GenerationRequest(
        requirements_prompt="Generate a dashboard report test.",
        requirements=[requirement],
        max_cases=1,
        categories=["positive"],
    )

    generated = service.generate(USER_ID, PROJECT_ID, request)

    assert generated[0]["requirements"] == []
    assert service.last_generation_stats["traced_case_count"] == 0
    assert service.last_generation_stats["requirement_keys_covered"] == []

    invalid = _case("Sign in with an unknown requirement")
    invalid.update(
        description=requirement["description"],
        requirement_keys=["REQ-999"],
    )
    invalid_service = _service(
        db,
        {"success": True, "answer": json.dumps([invalid])},
        evidence=[evidence],
    )
    invalid_result = invalid_service.generate(
        USER_ID,
        PROJECT_ID,
        request.model_copy(update={"requirements_prompt": "Generate sign-in tests."}),
    )

    assert invalid_result == []
    assert invalid_service.last_generation_stats["invalid_rejected_count"] == 3
    assert invalid_service.last_generation_stats["traced_case_count"] == 0


def test_ambiguous_similar_requirements_are_not_assigned_automatically(db):
    requirements = [
        {
            "requirement_key": "REQ-AUTH-01",
            "description": "Users can sign in with registered credentials.",
            "evidence_chunk_ids": [CHUNK_ID],
        },
        {
            "requirement_key": "REQ-AUTH-02",
            "description": "Registered users authenticate with valid credentials to sign in.",
            "evidence_chunk_ids": [CHUNK_ID],
        },
    ]
    evidence = {
        **_evidence(),
        "content": "Users can sign in with registered credentials.",
    }
    db.query(DocumentChunk).filter(DocumentChunk.id == CHUNK_ID).one().content = (
        evidence["content"]
    )
    db.commit()
    generated_case = _case("Sign in with registered credentials")
    generated_case.update(
        description="Verify account sign-in with valid credentials.",
        steps=[
            {
                "action": "Submit registered account credentials.",
                "expected_result": "The user is authenticated.",
            }
        ],
        expected_result="The user is authenticated.",
    )
    service = _service(
        db,
        {"success": True, "answer": json.dumps([generated_case])},
        evidence=[evidence],
    )

    generated = service.generate(
        USER_ID,
        PROJECT_ID,
        GenerationRequest(
            requirements_prompt="Generate credential sign-in coverage.",
            requirements=requirements,
            max_cases=1,
            categories=["positive"],
        ),
    )

    assert generated[0]["requirements"] == []
    assert service.last_generation_stats["traced_case_count"] == 0


def test_generation_retry_preserves_semantically_mapped_requirement_reference(db):
    requirement = {
        "requirement_key": "REQ-004",
        "description": "Patients can book an available appointment slot.",
        "evidence_chunk_ids": [CHUNK_ID],
    }
    evidence = {**_evidence(), "content": requirement["description"]}
    db.query(DocumentChunk).filter(DocumentChunk.id == CHUNK_ID).one().content = (
        evidence["content"]
    )
    db.commit()
    invalid = _case("Invalid first candidate")
    invalid["category"] = "unsupported"
    valid = _case("Book an available appointment slot")
    valid.update(
        description=requirement["description"],
        steps=[
            {
                "action": "Select an available appointment slot and book it.",
                "expected_result": "The appointment is booked.",
            }
        ],
        expected_result="The appointment is booked.",
    )
    responses = iter(
        [
            {"success": True, "answer": json.dumps([invalid])},
            {"success": True, "answer": json.dumps([valid])},
        ]
    )
    service = _service(
        db,
        {"success": True, "answer": "unused"},
        evidence=[evidence],
    )
    service.llm_service.generate_content = lambda **_: next(responses)

    generated = service.generate(
        USER_ID,
        PROJECT_ID,
        GenerationRequest(
            requirements_prompt="Generate appointment booking tests.",
            requirements=[requirement],
            max_cases=1,
            categories=["positive"],
        ),
    )

    assert generated[0]["requirements"][0]["requirement_key"] == "REQ-004"
    assert service.last_generation_stats["retry_count"] == 1
    assert service.last_generation_stats["traced_case_count"] == 1
    assert db.query(TestCaseRequirement).count() == 1


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
    assert db.query(GenerationRunModel).one().status == "failed"


@pytest.mark.parametrize(
    ("cases", "generation_status", "expected_status"),
    [
        ([{"id": 41}], "completed", "success"),
        ([{"id": 41}], "partial", "partial"),
        ([{"id": 41}], "failed", "failed"),
        ([], "failed", "failed"),
    ],
)
def test_generation_agent_reports_usable_case_statuses(
    monkeypatch,
    cases,
    generation_status,
    expected_status,
):
    service = SimpleNamespace(
        generate=lambda **_: cases,
        last_generation_stats={
            "generation_status": generation_status,
            "diagnostic": "No supported cases were returned.",
        },
    )
    monkeypatch.setattr(
        GenerationAgent,
        "__init__",
        lambda self, _db: setattr(self, "service", service),
    )

    result = GenerationAgent(None).run(
        AgentContext(
            user_id=USER_ID,
            project_id=PROJECT_ID,
            task="test_generation",
            inputs={
                "request": GenerationRequest(
                    requirements_prompt="Generate login test cases."
                )
            },
        )
    )

    assert result.status == expected_status
    if generation_status == "failed":
        assert result.error == {
            "code": (
                "NO_USABLE_TEST_CASES"
                if not cases
                else "GENERATION_FAILED"
            ),
            "message": "No supported cases were returned.",
        }


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


def test_empty_retrieval_diagnostics_distinguish_missing_documents_and_embeddings(
    db,
):
    service = _service(db, {"success": True, "answer": "[]"})
    request = GenerationRequest(requirements_prompt="Generate login test cases.")

    missing_embeddings = service._empty_retrieval_diagnostic(PROJECT_ID, request)
    assert missing_embeddings["code"] == "PROJECT_EMBEDDINGS_MISSING"
    assert missing_embeddings["document_chunk_count"] == 1
    assert missing_embeddings["missing_embedding_count"] == 1

    db.query(DocumentChunk).delete()
    db.commit()
    no_document_chunks = service._empty_retrieval_diagnostic(PROJECT_ID, request)
    assert no_document_chunks["code"] == "PROJECT_DOCUMENT_CHUNKS_NOT_FOUND"
    assert "Process project documents" in no_document_chunks["message"]


def test_empty_retrieval_with_embedded_documents_reports_no_relevant_chunks(
    db,
    monkeypatch,
):
    monkeypatch.setattr(
        generation_service_module.ModelService,
        "EMBEDDING_MODEL_NAME",
        "test-embedding-model",
    )
    db.add(
        DocumentEmbedding(
            chunk_id=CHUNK_ID,
            model_name="test-embedding-model",
            embedding=[0.0] * 384,
        )
    )
    db.commit()
    service = _service(db, {"success": True, "answer": "[]"})
    request = GenerationRequest(requirements_prompt="Generate login test cases.")

    diagnostic = service._empty_retrieval_diagnostic(PROJECT_ID, request)

    assert diagnostic["code"] == "NO_RELEVANT_EVIDENCE"
    assert diagnostic["document_chunk_count"] == 1
    assert diagnostic["missing_embedding_count"] == 0


def test_empty_retrieval_failure_exposes_actionable_diagnostic(db):
    service = _service(db, {"success": True, "answer": "[]"})
    service._retrieve_chunks = lambda *_: []

    with pytest.raises(GenerationError, match="PROJECT_EMBEDDINGS_MISSING") as error:
        _generate(service)

    assert error.value.stage == "PROJECT_EMBEDDINGS_MISSING"
    assert error.value.diagnostics["retrieval"]["code"] == (
        "PROJECT_EMBEDDINGS_MISSING"
    )
    assert "Reprocess document embeddings" in str(error.value)
    _assert_no_generation_rows(db)


def test_malformed_json_has_distinct_stage_and_writes_nothing(db):
    service = _service(db, {"success": True, "answer": "[{"})

    with pytest.raises(GenerationError, match="json_parse") as error:
        _generate(service)

    _assert_no_generation_rows(db)
    stats = error.value.diagnostics["generation_stats"]
    assert stats["generation_status"] == "failed"
    assert stats["retry_count"] == 2
    assert stats["response_diagnostics"][-1]["reason_code"] == (
        "malformed_response"
    )


def test_provider_failure_has_distinct_stage_and_writes_nothing(db):
    service = _service(
        db,
        {
            "success": False,
            "stage": "provider_request",
            "error": "Gemini provider request failed",
        },
    )

    with pytest.raises(GenerationError, match="provider_request") as error:
        _generate(service)

    _assert_no_generation_rows(db)
    stats = error.value.diagnostics["generation_stats"]
    assert stats["retry_count"] == 2
    assert len(stats["response_diagnostics"]) == 3
    assert "Gemini provider request failed" not in str(stats)



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
                    "generation_stats": {
                        "generated_count": 2,
                        "final_persisted_count": 0,
                        "candidate_diagnostics": [
                            {
                                "candidate_index": 1,
                                "attempt_number": 1,
                                "stage": "schema_validation",
                                "reasons": [{"code": "invalid_test_steps"}],
                            }
                        ],
                    },
                },
            )

    monkeypatch.setattr(
        test_cases_api,
        "TestGenerationAgent",
        FailedGenerationAgent,
    )

    response = test_cases_api.generate_test_cases(
        project_id=PROJECT_ID,
        request=GenerationRequest(
            requirements_prompt="Generate login test cases."
        ),
        current_user=SimpleNamespace(id=USER_ID),
        db=None,
    )

    payload = json.loads(response.body)
    assert response.status_code == 502
    assert "json_parse" in payload["detail"]
    assert payload["generated_count"] == 2
    assert payload["final_persisted_count"] == 0
    assert payload["generation_stats"]["candidate_diagnostics"][0][
        "reasons"
    ][0]["code"] == "invalid_test_steps"


def test_endpoint_exposes_no_usable_case_diagnostic(monkeypatch):
    from app.agents.contracts import AgentResult

    class EmptyGenerationAgent:
        name = "test_generation_agent"

        def __init__(self, _db):
            pass

        def run(self, _context):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                data={
                    "generated_count": 0,
                    "test_cases": [],
                    "generation_stats": {
                        "generation_status": "failed",
                        "generated_count": 0,
                        "final_persisted_count": 0,
                        "candidate_diagnostics": [],
                        "diagnostic": "The model returned an empty JSON array.",
                    },
                },
                error={
                    "code": "NO_USABLE_TEST_CASES",
                    "message": "The model returned an empty JSON array.",
                },
            )

    monkeypatch.setattr(
        test_cases_api,
        "TestGenerationAgent",
        EmptyGenerationAgent,
    )

    response = test_cases_api.generate_test_cases(
        project_id=PROJECT_ID,
        request=GenerationRequest(
            requirements_prompt="Generate login test cases."
        ),
        current_user=SimpleNamespace(id=USER_ID),
        db=None,
    )

    payload = json.loads(response.body)
    assert response.status_code == 422
    assert payload["detail"] == "The model returned an empty JSON array."
    assert payload["generated_count"] == 0
    assert payload["final_persisted_count"] == 0
    assert payload["generation_stats"]["candidate_diagnostics"] == []


def test_endpoint_preserves_partial_generation_status(monkeypatch):
    from app.agents.contracts import AgentResult

    class PartialGenerationAgent:
        name = "test_generation_agent"

        def __init__(self, _db):
            pass

        def run(self, _context):
            return AgentResult(
                agent_name=self.name,
                status="partial",
                data={
                    "generated_count": 4,
                    "final_persisted_count": 1,
                    "test_cases": [{"id": 41, "title": "Supported case"}],
                    "generation_stats": {
                        "requested_max_cases": 3,
                        "generated_count": 4,
                        "final_persisted_count": 1,
                        "generation_status": "partial",
                    },
                },
            )

    monkeypatch.setattr(
        test_cases_api,
        "TestGenerationAgent",
        PartialGenerationAgent,
    )

    result = test_cases_api.generate_test_cases(
        project_id=PROJECT_ID,
        request=GenerationRequest(
            requirements_prompt="Generate login test cases.",
            max_cases=3,
        ),
        current_user=SimpleNamespace(id=USER_ID),
        db=None,
    )

    assert result["success"] is True
    assert result["status"] == "partial"
    assert result["generated_count"] == 4
    assert result["final_persisted_count"] == 1


def test_generation_agent_separates_candidate_and_persisted_counts(monkeypatch):
    service = SimpleNamespace(
        generate=lambda **_: [{"id": 41, "title": "Supported case"}],
        last_generation_stats={
            "generated_count": 4,
            "final_persisted_count": 1,
            "generation_status": "partial",
        },
    )
    monkeypatch.setattr(
        GenerationAgent,
        "__init__",
        lambda self, _db: setattr(self, "service", service),
    )

    result = GenerationAgent(None).run(
        AgentContext(
            user_id=USER_ID,
            project_id=PROJECT_ID,
            task="test_generation",
            inputs={
                "request": GenerationRequest(
                    requirements_prompt="Generate login test cases."
                )
            },
        )
    )

    assert result.status == "partial"
    assert result.data["generated_count"] == (
        result.data["generation_stats"]["generated_count"]
    )
    assert result.data["final_persisted_count"] == (
        result.data["generation_stats"]["final_persisted_count"]
    )


def test_generation_agent_preserves_metrics_when_retries_are_exhausted(monkeypatch):
    generation_stats = {
        "generated_count": 2,
        "final_persisted_count": 0,
        "generation_status": "failed",
        "retry_count": 2,
        "candidate_diagnostics": [],
        "response_diagnostics": [
            {
                "attempt_number": 3,
                "stage": "provider_request",
                "reason_code": "provider_request_failed",
                "message": "The language model provider did not return a usable response.",
            }
        ],
    }

    def fail_generation(**_):
        raise GenerationError(
            "provider_request",
            "No usable candidate response was returned after retries",
            diagnostics={"generation_stats": generation_stats},
        )

    service = SimpleNamespace(generate=fail_generation)
    monkeypatch.setattr(
        GenerationAgent,
        "__init__",
        lambda self, _db: setattr(self, "service", service),
    )

    result = GenerationAgent(None).run(
        AgentContext(
            user_id=USER_ID,
            project_id=PROJECT_ID,
            task="test_generation",
            inputs={
                "request": GenerationRequest(
                    requirements_prompt="Generate login test cases."
                )
            },
        )
    )

    assert result.status == "failed"
    assert result.data["generated_count"] == 2
    assert result.data["final_persisted_count"] == 0
    assert result.data["generation_stats"] == result.error["generation_stats"]


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
    assert run.insufficient_evidence_count == 0
    assert run.final_persisted_count == 0
    assert run.status == "failed"


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
    assert run.invalid_rejected_count == 0
    assert run.insufficient_evidence_count == service.MAX_GENERATION_ATTEMPTS
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
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=7,
            total_token_count=19,
        ),
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
        metadata={"correlation_id": "workflow-task-generation"},
        request_id="workflow-task-generation:llm1",
    )

    assert result["success"] is True
    assert result["answer"] == response.text
    assert provider_call["contents"] == "Create one case."
    assert provider_call["config"].system_instruction == "Return a JSON array."
    assert provider_call["config"].response_mime_type == "application/json"
    assert provider_call["config"].temperature == 0.2
    assert result["input_token_count"] == 12
    assert result["output_token_count"] == 7
    assert result["total_token_count"] == 19


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
