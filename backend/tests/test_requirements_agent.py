import json
from types import SimpleNamespace

from app.agents.contracts import AgentContext, AgentResult
from app.agents.requirements_agent import RequirementsAnalysisAgent
from app.llm.contracts import LLMError, LLMErrorCategory, LLMResponse
from app.llm.telemetry import InMemoryLLMTelemetryService
from app.services.llm_services import LLMService
from app.services.workflow_service import (
    _dependency_succeeded,
    _jsonable_agent_result,
    _update_context_from_output,
)


def _evidence():
    return [
        {
            "chunk_id": 101,
            "document_id": 11,
            "document_name": "requirements.pdf",
            "source_type": "requirements",
            "content": (
                "REQ-001: Patient registration requires a unique email address. "
                "Acceptance criteria: duplicate email addresses are rejected. "
                "REQ-002: Authentication supports sign-in and sign-out."
            ),
        },
        {
            "chunk_id": 102,
            "document_id": 12,
            "document_name": "workflows.txt",
            "source_type": "document",
            "content": (
                "REQ-001: Patient registration requires a unique email address. "
                "A successful sign-in opens the authenticated patient dashboard."
            ),
        },
        {
            "chunk_id": 103,
            "document_id": 13,
            "document_name": "readme.txt",
            "source_type": "document",
            "content": "The project is built with a web application framework.",
        },
    ]


def _agent(
    answer,
    evidence=None,
    success=True,
    finish_reason=None,
    stage=None,
    error_category=None,
    error_type=None,
):
    sources = _evidence() if evidence is None else evidence
    knowledge = SimpleNamespace(
        run=lambda _context: AgentResult(
            "knowledge_agent",
            "success",
            data={"chunks": sources},
            evidence=sources,
        )
    )
    llm = SimpleNamespace(
        generate_content=lambda **_: {
            "success": success,
            "answer": answer,
            "finish_reason": finish_reason,
            "stage": stage,
            "error_category": error_category,
            "error_type": error_type,
            "provider": "gemini",
            "model": "gemini-model",
            "fallback_configured": False,
            "fallback_attempted": False,
            "fallback_eligible": error_category in {"rate_limit", "timeout"},
            "provider_attempt_count": 1,
            "retry_count": 0,
        }
    )
    return RequirementsAnalysisAgent(
        None,
        knowledge_agent=knowledge,
        llm_service=llm,
    )


def _run(agent):
    return agent.run(
        AgentContext(
            user_id=4,
            project_id=3,
            task="requirements_analysis",
        )
    )


def _output(**overrides):
    payload = {
        "requirements": [],
        "acceptance_criteria": [],
        "ambiguities": [],
        "risks": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


def _requirement(requirement_id, description, chunk_ids, **overrides):
    return {
        "id": requirement_id,
        "description": description,
        "classification": "explicit",
        "evidence_chunk_ids": chunk_ids,
        **overrides,
    }


def test_extracts_individual_requirements_and_separate_acceptance_criteria():
    result = _run(
        _agent(
            _output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101],
                    ),
                    _requirement(
                        "REQ-002",
                        "Authentication supports sign-in and sign-out.",
                        [101],
                    ),
                ],
                acceptance_criteria=[
                    {
                        "description": "Duplicate email addresses are rejected.",
                        "evidence_chunk_ids": [101],
                    }
                ],
            )
        )
    )

    assert result.status == "success"
    assert [item["id"] for item in result.data["requirements"]] == [
        "REQ-001",
        "REQ-002",
    ]
    assert result.data["requirements"][0]["evidence_references"] == [
        {
            "document_id": 11,
            "chunk_id": 101,
            "document_name": "requirements.pdf",
            "source_type": "requirements",
        }
    ]
    assert result.data["acceptance_criteria"][0]["description"] == (
        "Duplicate email addresses are rejected."
    )


def test_merges_duplicate_requirement_evidence_across_chunks():
    result = _run(
        _agent(
            _output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101],
                    ),
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [102],
                    ),
                ]
            )
        )
    )

    assert result.status == "success"
    requirement = result.data["requirements"][0]
    assert requirement["evidence_chunk_ids"] == [101, 102]
    assert [item["document_id"] for item in requirement["evidence_references"]] == [
        11,
        12,
    ]


def test_accepts_multiple_supporting_chunks_and_ignores_irrelevant_context():
    result = _run(
        _agent(
            _output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101, 102],
                    )
                ]
            )
        )
    )

    assert result.status == "success"
    assert result.data["requirements"][0]["evidence_chunk_ids"] == [101, 102]
    assert 103 not in result.data["requirements"][0]["evidence_chunk_ids"]


def test_llm_request_respects_configured_evidence_context_budget(monkeypatch):
    sources = [
        {
            "chunk_id": 301 + index,
            "document_id": 31,
            "document_name": "requirements.pdf",
            "source_type": "requirements",
            "content": (
                "REQ-001: Patient registration requires a unique email address. "
                + ("Supporting source details. " * 7)
            ),
        }
        for index in range(10)
    ]
    monkeypatch.setattr(
        "app.services.context_builder_service.settings.CONTEXT_TOKEN_BUDGET",
        150,
    )
    captured = []
    llm = SimpleNamespace(
        generate_content=lambda **kwargs: (
            captured.append(kwargs)
            or {
                "success": True,
                "answer": _output(
                    requirements=[
                        _requirement(
                            "REQ-001",
                            "Patient registration requires a unique email address.",
                            [301],
                        )
                    ]
                ),
                "provider": "gemini",
                "model": "gemini-model",
                "stage": "complete",
                "provider_attempt_count": 1,
                "retry_count": 0,
            }
        )
    )
    knowledge = SimpleNamespace(
        run=lambda _context: AgentResult(
            "knowledge_agent",
            "success",
            data={"chunks": sources},
            evidence=sources,
        )
    )

    result = _run(
        RequirementsAnalysisAgent(
            None,
            knowledge_agent=knowledge,
            llm_service=llm,
        )
    )

    sent_chunks = [
        source
        for call in captured
        for source in json.loads(call["user_prompt"])["sources"]
    ]
    assert len(captured) > 1
    assert {source["chunk_id"] for source in sent_chunks} == {
        source["chunk_id"] for source in sources
    }
    assert sum(len(call["user_prompt"]) for call in captured) == int(
        result.data["execution_metadata"]["llm"]["input_context_char_count"]
    )
    assert int(
        result.data["execution_metadata"]["llm"]["input_context_chunk_count"]
    ) == len(sources)
    assert result.status == "success"
    assert {item["chunk_id"] for item in result.evidence} == {
        item["chunk_id"] for item in sent_chunks
    }


def test_valid_records_survive_unsupported_entry_as_partial_result():
    result = _run(
        _agent(
            _output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101],
                    ),
                    _requirement(
                        "REQ-999",
                        "Unsupported requirement.",
                        [999],
                    ),
                ]
            )
        )
    )

    assert result.status == "partial"
    assert [item["id"] for item in result.data["requirements"]] == ["REQ-001"]
    assert "requirements[1] was rejected" in result.data["warnings"][0]


def test_rejects_requirement_id_not_present_in_cited_chunks():
    result = _run(
        _agent(
            _output(
                requirements=[
                    _requirement(
                        "REQ-999",
                        "Unsupported requirement.",
                        [101],
                    )
                ]
            )
        )
    )

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_OUTPUT_INVALID"
    assert "requirement ID is not present" in result.data["warnings"][0]


def test_empty_structured_response_with_valid_requirement_evidence_fails():
    result = _run(_agent(_output()))

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_NOT_EXTRACTED"
    assert result.data["requirements"] == []
    assert len(result.data["evidence"]) == 3


def test_missing_requirement_evidence_is_a_failure_not_partial_success():
    result = _run(_agent(_output(), evidence=[]))

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_EVIDENCE_NOT_FOUND"


def test_irrelevant_retrieved_context_does_not_create_requirements():
    irrelevant = [
        {
            "chunk_id": 201,
            "document_id": 21,
            "document_name": "readme.txt",
            "source_type": "document",
            "content": "This project uses a web framework and a relational database.",
        }
    ]
    result = _run(_agent(_output(), evidence=irrelevant))

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_NOT_EXTRACTED"
    assert result.data["requirements"] == []


def test_malformed_llm_response_returns_clear_failure_with_evidence():
    result = _run(_agent('{"requirements": ['))

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_OUTPUT_INVALID"
    assert "valid JSON object" in result.error["message"]
    assert result.data["evidence"][0]["chunk_id"] == 101


def test_empty_provider_response_is_distinct_from_provider_failure():
    result = _run(
        _agent(
            "",
            success=False,
            stage="empty_response",
            error_category="empty_response",
        )
    )

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_EMPTY_RESPONSE"
    assert result.error["stage"] == "empty_response"
    assert result.error["error_category"] == "empty_response"


def test_provider_failure_preserves_safe_diagnostics_for_workflow_output():
    result = _run(
        _agent(
            "",
            success=False,
            stage="provider_request",
            error_category="rate_limit",
            error_type="RateLimitError",
        )
    )

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_EXTRACTION_UNAVAILABLE"
    assert result.error["provider"] == "gemini"
    assert result.error["model"] == "gemini-model"
    assert result.error["stage"] == "provider_request"
    assert result.error["error_category"] == "rate_limit"
    assert result.error["error_type"] == "RateLimitError"
    assert result.error["fallback_attempted"] == "false"
    workflow_output = _jsonable_agent_result(result)
    assert workflow_output["status"] == "failed"
    assert workflow_output["errors"][0]["error_category"] == "rate_limit"


def test_token_truncated_response_cannot_be_reported_as_success():
    response = _output(
        requirements=[
            _requirement(
                "REQ-001",
                "Patient registration requires a unique email address.",
                [101],
            )
        ]
    )
    result = _run(_agent(response, finish_reason="MAX_TOKENS"))

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_OUTPUT_TRUNCATED"


def test_invalid_provider_success_indicator_is_not_treated_as_success():
    result = _run(_agent(_output(), success="true"))

    assert result.status == "failed"
    assert result.error["code"] == "REQUIREMENTS_OUTPUT_INVALID"


def test_retried_agent_run_can_recover_after_provider_failure():
    sources = _evidence()
    responses = [
        {
            "success": False,
            "answer": "",
            "stage": "provider_request",
            "error_category": "rate_limit",
        },
        {
            "success": True,
            "answer": _output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101],
                    )
                ]
            ),
        },
    ]
    knowledge = SimpleNamespace(
        run=lambda _context: AgentResult(
            "knowledge_agent",
            "success",
            data={"chunks": sources},
            evidence=sources,
        )
    )
    llm = SimpleNamespace(
        generate_content=lambda **_: responses.pop(0)
    )
    agent = RequirementsAnalysisAgent(
        None,
        knowledge_agent=knowledge,
        llm_service=llm,
    )

    failed_attempt = _run(agent)
    successful_attempt = _run(agent)

    assert failed_attempt.status == "failed"
    assert successful_attempt.status == "success"
    assert successful_attempt.data["requirements"][0]["id"] == "REQ-001"


def test_requirements_extraction_uses_fallback_and_records_provider_diagnostics(
    monkeypatch,
):
    class FakeProvider:
        def __init__(self, provider_name, model_name, response):
            self.provider_name = provider_name
            self.model_name = model_name
            self.response = response

        def generate(self, _request):
            return self.response

    primary = FakeProvider(
        "gemini",
        "gemini-model",
        LLMResponse(
            provider="gemini",
            model="gemini-model",
            success=False,
            text="",
            stage="provider_request",
            error="Provider request failed",
            error_type="RateLimitError",
            error_details=LLMError(
                category=LLMErrorCategory.RATE_LIMIT,
                message="Provider request failed",
                stage="provider_request",
                provider="gemini",
                model="gemini-model",
                error_type="RateLimitError",
            ),
        ),
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        LLMResponse(
            provider="groq",
            model="groq-model",
            success=True,
            text=_output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101],
                    )
                ]
            ),
            stage="complete",
        ),
    )
    from app.services import llm_services

    monkeypatch.setattr(
        llm_services,
        "get_provider",
        lambda _provider_name, _model_name: fallback,
    )
    llm = LLMService(
        provider=primary,
        fallback_enabled=True,
        fallback_provider_name="groq",
        telemetry_service=InMemoryLLMTelemetryService(),
    )
    sources = _evidence()
    knowledge = SimpleNamespace(
        run=lambda _context: AgentResult(
            "knowledge_agent",
            "success",
            data={"chunks": sources},
            evidence=sources,
        )
    )
    agent = RequirementsAnalysisAgent(
        None,
        knowledge_agent=knowledge,
        llm_service=llm,
    )

    result = _run(agent)

    assert result.status == "success"
    assert result.data["requirements"][0]["id"] == "REQ-001"
    assert result.data["requirements"][0]["evidence_references"][0]["chunk_id"] == 101
    diagnostics = result.data["execution_metadata"]["llm"]
    assert {
        key: diagnostics[key]
        for key in (
            "provider",
            "model",
            "stage",
            "provider_attempt_count",
            "retry_count",
            "fallback_configured",
            "fallback_attempted",
            "fallback_succeeded",
            "primary_provider",
            "primary_model",
            "primary_failure_stage",
            "primary_error_category",
            "primary_error_type",
            "fallback_provider",
            "fallback_model",
            "input_context_chunk_count",
        )
    } == {
        "provider": "groq",
        "model": "groq-model",
        "stage": "complete",
        "provider_attempt_count": "3",
        "retry_count": "1",
        "fallback_configured": "true",
        "fallback_attempted": "true",
        "fallback_succeeded": "true",
        "primary_provider": "gemini",
        "primary_model": "gemini-model",
        "primary_failure_stage": "provider_request",
        "primary_error_category": "rate_limit",
        "primary_error_type": "RateLimitError",
        "fallback_provider": "groq",
        "fallback_model": "groq-model",
        "input_context_chunk_count": "3",
    }
    assert int(
        diagnostics["input_context_char_count"]
    ) > 0


def test_partial_requirements_are_exposed_and_only_usable_partial_output_unblocks_generation():
    response = _output(
        requirements=[
            _requirement(
                "REQ-001",
                "Patient registration requires a unique email address.",
                [101],
            ),
            _requirement("REQ-999", "Unsupported requirement.", [999]),
        ]
    )
    workflow_output = _jsonable_agent_result(_run(_agent(response)))
    task = SimpleNamespace(
        status="partial",
        task_type="requirements_analysis",
        output_data=workflow_output,
    )

    assert workflow_output["status"] == "partial"
    assert workflow_output["structured_data"]["requirements"][0]["id"] == "REQ-001"
    assert workflow_output["findings"][0]["id"] == "REQ-001"
    assert _dependency_succeeded(task, "test_generation") is True
    shared_context = {}
    _update_context_from_output(
        "requirements_analysis",
        workflow_output,
        shared_context,
    )
    assert shared_context["requirements"]["requirements"][0]["id"] == "REQ-001"
    assert shared_context["evidence_references"][0]["chunk_id"] == 101
    task.output_data["structured_data"]["requirements"] = []
    assert _dependency_succeeded(task, "test_generation") is False


def test_failed_requirements_output_blocks_test_generation():
    failed = _run(
        _agent(
            "",
            success=False,
            stage="provider_request",
            error_category="provider_api",
        )
    )
    output = _jsonable_agent_result(failed)
    task = SimpleNamespace(
        status="failed",
        task_type="requirements_analysis",
        output_data=output,
    )

    assert output["status"] == "failed"
    assert output["structured_data"]["requirements"] == []
    assert _dependency_succeeded(task, "test_generation") is False


def test_exhaustive_requirement_sources_reach_extraction_with_ids_preserved():
    requirement_chunks = [
        {
            "chunk_id": 201 + index,
            "document_id": 50,
            "document_name": "requirements.pdf",
            "source_type": "requirements",
            "content": f"REQ-{index + 1:03}: Requirement number {index + 1} is supported.",
        }
        for index in range(3)
    ]
    knowledge = SimpleNamespace(
        run=lambda _context: AgentResult(
            "knowledge_agent", "success", data={"chunks": []}
        ),
        get_project_source_chunks=lambda **_: requirement_chunks,
    )
    captured = []
    answer = _output(
        requirements=[
            _requirement(
                f"REQ-{index + 1:03}",
                f"Requirement number {index + 1} is supported.",
                [201 + index],
            )
            for index in range(3)
        ]
    )
    llm = SimpleNamespace(
        generate_content=lambda **kwargs: (
            captured.append(kwargs["user_prompt"])
            or {"success": True, "answer": answer, "provider": "mock", "model": "mock"}
        )
    )
    agent = RequirementsAnalysisAgent(None, knowledge_agent=knowledge, llm_service=llm)

    result = _run(agent)

    assert result.status == "success"
    sent_sources = json.loads(captured[0])["sources"]
    assert {source["chunk_id"] for source in sent_sources} >= {201, 202, 203}
    assert [item["id"] for item in result.data["requirements"]] == [
        "REQ-001", "REQ-002", "REQ-003"
    ]


def test_all_twelve_numbered_requirements_validate_across_three_chunks():
    ranges = ((1, 4), (5, 9), (10, 12))
    evidence = []
    requirements = []
    for chunk_id, (first, last) in enumerate(ranges, start=401):
        descriptions = [
            f"REQ-{number:03}: Synthetic requirement {number} is supported."
            for number in range(first, last + 1)
        ]
        evidence.append(
            {
                "chunk_id": chunk_id,
                "document_id": 80,
                "document_name": "requirements.pdf",
                "source_type": "requirements",
                "content": " ".join(descriptions),
            }
        )
        requirements.extend(
            _requirement(
                f"REQ-{number:03}",
                f"Synthetic requirement {number} is supported.",
                [chunk_id],
            )
            for number in range(first, last + 1)
        )

    result = _run(
        _agent(
            _output(requirements=requirements),
            evidence=evidence,
        )
    )

    assert result.status == "success"
    assert [item["id"] for item in result.data["requirements"]] == [
        f"REQ-{number:03}" for number in range(1, 13)
    ]
    assert {reference["chunk_id"] for item in result.data["requirements"] for reference in item["evidence_references"]} == {
        401, 402, 403
    }


def test_non_functional_requirements_are_preserved_separately():
    sources = _evidence()
    sources[0]["content"] += " Non-functional: patient pages load in under two seconds."
    result = _run(
        _agent(
            _output(
                requirements=[
                    _requirement(
                        "REQ-001",
                        "Patient registration requires a unique email address.",
                        [101],
                    )
                ],
                non_functional_requirements=[
                    {
                        "description": "Patient pages should load in under two seconds.",
                        "evidence_chunk_ids": [101],
                    }
                ],
            ),
            evidence=sources,
        )
    )

    assert result.status == "success"
    assert len(result.data["requirements"]) == 1
    assert result.data["non_functional_requirements"][0]["description"] == (
        "Patient pages should load in under two seconds."
    )


def test_context_batches_cover_oversized_selected_chunks():
    from app.services.context_builder_service import ContextBuilderService

    builder = ContextBuilderService()
    chunks = [
        {
            "chunk_id": 301 + index,
            "document_id": 70,
            "document_name": "large-requirements.pdf",
            "source_type": "requirements",
            "content": f"REQ-{index + 1:03} " + ("requirement text " * 30),
        }
        for index in range(3)
    ]

    batches = builder.build_context_batches(chunks, token_budget=100)
    sent_ids = {
        source["chunk_id"]
        for batch in batches
        for source in builder.build_context(batch, token_budget=100)["sources"]
    }

    assert sent_ids == {301, 302, 303}
    assert len(batches) > 1
