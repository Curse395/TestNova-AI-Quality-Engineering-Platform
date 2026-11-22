import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api import analytics as analytics_api
from app.models.organization import Organization
from app.models.project import Project
from app.models.workflow_run import WorkflowRun
from app.llm.contracts import LLMError, LLMErrorCategory, LLMResponse
from app.llm.telemetry import InMemoryLLMTelemetryService
from app.schemas.quality_summary_schema import (
    QualitySummaryContent,
    QualitySummaryResponse,
)
from app.services.project_intelligence_service import (
    EvidenceFingerprintCache,
    ProjectIntelligenceService,
    _evidence_fingerprint,
)


def _summary_payload(evidence_id="test_case_statistics"):
    statement = {
        "statement": "Observed test-case evidence is available.",
        "evidence_ids": [evidence_id],
        "interpretation": False,
    }
    return {
        "overall_summary": statement,
        "testing_activity": [],
        "test_case_quality": [],
        "requirement_traceability": [],
        "execution_trends": [],
        "significant_failures": [],
        "identified_risks": [],
        "missing_evidence": [],
        "recommended_actions": [],
        "limitations": [],
    }


class _FakeLLM:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.arguments = []

    def generate_content(self, **kwargs):
        self.calls += 1
        self.arguments.append(kwargs)
        return self.response


class _AuthorizationQuery:
    def __init__(self, project):
        self.project = project
        self.joins = []
        self.filters = []

    def join(self, model, onclause=None):
        self.joins.append((model, onclause))
        return self

    def filter(self, *_conditions):
        self.filters.extend(_conditions)
        return self

    def first(self):
        return self.project


class _AuthorizationDB:
    def __init__(self, project):
        self.project = project
        self.queried_model = None

    def query(self, model):
        self.queried_model = model
        self.query_result = _AuthorizationQuery(self.project)
        return self.query_result


class _EmptyWorkflowQuery:
    def filter(self, *_conditions):
        return self

    def options(self, *_options):
        return self

    def order_by(self, *_expressions):
        return self

    def limit(self, _limit):
        return self

    def all(self):
        return []


class _EmptyWorkflowDB(_AuthorizationDB):
    def query(self, model):
        self.queried_model = model
        if model is Project:
            self.query_result = _AuthorizationQuery(self.project)
            return self.query_result
        assert model is WorkflowRun
        return _EmptyWorkflowQuery()


class _LoaderOption:
    def selectinload(self, _relationship):
        return self


def test_risk_analytics_separates_ai_inference_from_observed_execution_failures():
    risk_task = (
        41,
        52,
        "completed",
        {
            "structured_data": {
                "risk_level": "High",
                "risk_score": 97,
                "risk_factors": ["Session expiry regression"],
                "potential_impact": ["Users may need to sign in again."],
                "reasoning": "A changed authentication flow was supplied.",
            },
            "evidence_references": [
                {"document_id": 9, "chunk_id": 3, "content": "not returned"}
            ],
        },
        datetime(2026, 11, 13),
    )

    result = ProjectIntelligenceService.build_risk_analytics(
        [risk_task],
        [("failed", 2), ("error", 1), ("passed", 5)],
        [(100, "failed"), (101, "error"), (102, "passed")],
    )

    assert result["risk_count"] == 2
    assert result["severity_counts"] == {
        "critical": 0,
        "high": 1,
        "medium": 0,
        "low": 0,
        "unclassified": 1,
    }
    inferred, observed = result["risks"]
    assert inferred["kind"] == "ai_inferred"
    assert inferred["category"] == "change_impact"
    assert inferred["severity"] == "high"
    assert "risk_score" not in inferred
    assert inferred["supporting_evidence_available"] is True
    assert inferred["evidence_references"][1]["id"] == "document:9:chunk:3"
    assert all("content" not in reference for reference in inferred["evidence_references"])
    assert observed["kind"] == "observed_fact"
    assert observed["severity"] == "unclassified"
    assert observed["supporting_evidence_available"] is True
    assert observed["evidence_reference_count"] == 3
    assert result["high_priority_risks"] == [inferred]


def test_risk_analytics_reports_insufficient_evidence_without_inventing_risks():
    result = ProjectIntelligenceService.build_risk_analytics([], [], [])

    assert result["risk_count"] == 0
    assert result["risks"] == []
    assert result["evidence_available"] is False
    assert result["supporting_evidence_available"] is False
    assert result["unavailable_reason"]


def test_risk_analytics_keeps_unknown_assessment_severity_unclassified():
    result = ProjectIntelligenceService.build_risk_analytics(
        [
            (
                1,
                2,
                "partial",
                {"structured_data": {"risk_level": "certain", "risk_factors": ["Possible impact"]}},
                None,
            )
        ],
        [],
        [],
    )

    assert result["risks"][0]["severity"] == "unclassified"
    assert result["severity_counts"]["unclassified"] == 1
    assert result["risks"][0]["assessed_at"] is None


def test_risk_analytics_caps_returned_records_but_preserves_full_distribution_counts():
    tasks = [
        (
            workflow_id,
            workflow_id,
            "completed",
            {
                "structured_data": {
                    "risk_level": "medium",
                    "risk_factors": [f"risk-{index}" for index in range(20)],
                }
            },
            None,
        )
        for workflow_id in range(1, 7)
    ]

    result = ProjectIntelligenceService.build_risk_analytics(tasks, [], [])

    assert result["risk_count"] == 120
    assert result["returned_risk_count"] == 100
    assert result["risk_findings_truncated"] is True
    assert result["severity_counts"]["medium"] == 120


def test_workflow_monitoring_preserves_attempt_order_and_safe_timing_fields():
    started = datetime(2026, 11, 13, 10)
    completed = started + timedelta(seconds=2)
    task = SimpleNamespace(
        id=7,
        created_at=started,
        agent_name="test_generation_agent",
        task_type="test_generation",
        status="failed",
        attempt_count=2,
        started_at=started,
        completed_at=completed,
        error_details={"code": "GENERATION_FAILED", "message": "API key=secret-value"},
        attempts=[
            SimpleNamespace(
                attempt_number=2,
                status="failed",
                started_at=started,
                completed_at=completed,
                error_details={"message": "Bearer abc.def.ghi"},
            ),
            SimpleNamespace(
                attempt_number=1,
                status="retrying",
                started_at=started,
                completed_at=None,
                error_details=None,
            ),
        ],
    )
    later_task = SimpleNamespace(
        id=8,
        created_at=started + timedelta(seconds=1),
        agent_name="review_agent",
        task_type="review",
        status="completed",
        attempt_count=1,
        started_at=None,
        completed_at=None,
        error_details=None,
        attempts=[],
    )
    workflow = SimpleNamespace(
        id=5,
        workflow_type="full_qa_workflow",
        status="partially_completed",
        created_at=started,
        started_at=started,
        completed_at=None,
        error_summary="The workflow stopped.",
        tasks=[later_task, task],
    )

    result = ProjectIntelligenceService._safe_workflow_monitoring(workflow)
    monitored_task = result["tasks"][0]

    assert result["snapshot_only"] is True
    assert result["duration_ms"] is None
    assert result["failed_task_count"] == 1
    assert result["retried_task_count"] == 1
    assert [item["id"] for item in result["tasks"]] == [7, 8]
    assert monitored_task["plan_order"] == 1
    assert monitored_task["execution_order"] == 1
    assert monitored_task["duration_ms"] == 2000
    assert [attempt["attempt_number"] for attempt in monitored_task["attempts"]] == [1, 2]
    assert "[redacted]" in monitored_task["error"]["message"]
    assert "secret-value" not in str(result)
    assert "abc.def.ghi" not in str(result)


def test_workflow_monitoring_handles_empty_history_and_missing_timestamps():
    workflow = SimpleNamespace(
        id=1,
        workflow_type="bug_analysis",
        status="pending",
        created_at=None,
        started_at=None,
        completed_at=None,
        error_summary=None,
        tasks=[],
    )
    result = ProjectIntelligenceService._safe_workflow_monitoring(workflow)

    assert result["tasks"] == []
    assert result["duration_ms"] is None
    assert result["started_at"] is None


def test_owner_can_read_empty_persisted_workflow_history(monkeypatch):
    monkeypatch.setattr(
        "app.services.project_intelligence_service.selectinload",
        lambda _relationship: _LoaderOption(),
    )
    db = _EmptyWorkflowDB(project=SimpleNamespace(id=9))

    result = ProjectIntelligenceService(db=db).get_workflow_monitoring(9, 3)

    assert result == {
        "project_id": 9,
        "snapshot_only": True,
        "workflow_count": 0,
        "workflows": [],
    }


def test_summary_schema_requires_at_least_one_evidence_reference():
    payload = _summary_payload()
    payload["overall_summary"]["evidence_ids"] = []

    with pytest.raises(ValidationError):
        QualitySummaryContent.model_validate(payload)


def test_quality_summary_uses_structured_output_and_caches_identical_evidence():
    llm = _FakeLLM({"success": True, "answer": json.dumps(_summary_payload())})
    cache = EvidenceFingerprintCache()
    service = ProjectIntelligenceService(
        db=None,
        llm_service=llm,
        summary_cache=cache,
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 3}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    first = service.generate_quality_summary(8, 2)
    second = service.generate_quality_summary(8, 2)

    assert first["status"] == "available"
    assert first["cached"] is False
    assert second["cached"] is True
    assert llm.calls == 1
    assert first["summary"]["overall_summary"]["evidence_ids"] == ["test_case_statistics"]
    QualitySummaryResponse.model_validate(first)


def test_quality_summary_cache_invalidates_when_evidence_changes():
    llm = _FakeLLM({"success": True, "answer": json.dumps(_summary_payload())})
    service = ProjectIntelligenceService(
        db=None,
        llm_service=llm,
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    evidence = {"test_case_statistics": {"total_cases": 1}}
    service._summary_evidence = lambda *_args: (
        evidence,
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    first = service.generate_quality_summary(8, 2)
    evidence["test_case_statistics"]["total_cases"] = 2
    second = service.generate_quality_summary(8, 2)

    assert first["evidence_fingerprint"] != second["evidence_fingerprint"]
    assert llm.calls == 2


def test_quality_summary_cache_is_project_scoped_even_for_identical_metrics():
    llm = _FakeLLM({"success": True, "answer": json.dumps(_summary_payload())})
    service = ProjectIntelligenceService(
        db=None,
        llm_service=llm,
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 3}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    first = service.generate_quality_summary(8, 2)
    second = service.generate_quality_summary(9, 2)

    assert first["evidence_fingerprint"] != second["evidence_fingerprint"]
    assert llm.calls == 2


def test_quality_summary_prompt_preserves_empty_metrics_and_excludes_readiness_claims():
    llm = _FakeLLM({"success": True, "answer": json.dumps(_summary_payload())})
    service = ProjectIntelligenceService(
        db=None,
        llm_service=llm,
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 0}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    result = service.generate_quality_summary(8, 2)

    assert result["status"] == "available"
    assert '"total_cases": 0' in llm.arguments[0]["user_prompt"]
    assert "release-readiness verdict" in llm.arguments[0]["system_prompt"]
    prompt = llm.arguments[0]["system_prompt"]
    assert "must each be JSON arrays of SummaryStatement objects" in prompt
    assert "return an empty array []" in prompt
    assert "never omit a required field" in prompt


def test_quality_summary_accepts_empty_and_populated_array_sections_with_valid_evidence():
    payload = _summary_payload()
    payload["testing_activity"] = [{
        "statement": "Three saved test cases were observed.",
        "evidence_ids": ["test_case_statistics"],
        "interpretation": False,
    }]
    llm = _FakeLLM({"success": True, "answer": json.dumps(payload)})
    service = ProjectIntelligenceService(
        db=None,
        llm_service=llm,
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 3}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    result = service.generate_quality_summary(8, 2)

    assert result["status"] == "available"
    assert result["summary"]["testing_activity"] == payload["testing_activity"]
    assert result["summary"]["execution_trends"] == []
    QualitySummaryResponse.model_validate(result)


@pytest.mark.parametrize(
    "field_name",
    [
        "testing_activity",
        "test_case_quality",
        "requirement_traceability",
        "execution_trends",
        "significant_failures",
        "identified_risks",
        "missing_evidence",
        "recommended_actions",
        "limitations",
    ],
)
def test_quality_summary_rejects_non_array_section_values(field_name, caplog):
    payload = _summary_payload()
    payload[field_name] = {
        "statement": "This malformed object must not be coerced into a list.",
        "evidence_ids": ["test_case_statistics"],
        "interpretation": False,
    }
    service = ProjectIntelligenceService(
        db=None,
        llm_service=_FakeLLM({"success": True, "answer": json.dumps(payload)}),
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 0}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    with caplog.at_level("WARNING", logger="app.services.project_intelligence_service"):
        result = service.generate_quality_summary(8, 2)

    assert result["status"] == "unavailable"
    assert result["_failure_category"] == "structured_output_invalid"
    assert f"validation_fields={field_name}" in caplog.text


@pytest.mark.parametrize(
    "field_name",
    [
        "testing_activity",
        "test_case_quality",
        "requirement_traceability",
        "execution_trends",
        "significant_failures",
        "identified_risks",
        "missing_evidence",
        "recommended_actions",
        "limitations",
    ],
)
def test_quality_summary_does_not_fill_missing_required_array_sections(field_name):
    payload = _summary_payload()
    del payload[field_name]
    service = ProjectIntelligenceService(
        db=None,
        llm_service=_FakeLLM({"success": True, "answer": json.dumps(payload)}),
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 0}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    result = service.generate_quality_summary(8, 2)

    assert result["status"] == "unavailable"
    assert result["_failure_category"] == "structured_output_invalid"


def test_generated_summary_redacts_sensitive_values_before_returning():
    payload = _summary_payload()
    payload["overall_summary"]["statement"] = "Observed API key=secret-value in the report."
    service = ProjectIntelligenceService(
        db=None,
        llm_service=_FakeLLM({"success": True, "answer": json.dumps(payload)}),
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 3}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    result = service.generate_quality_summary(8, 2)

    statement = result["summary"]["overall_summary"]["statement"]
    assert "secret-value" not in statement
    assert "[redacted]" in statement


def test_quality_summary_uses_existing_central_llm_fallback(monkeypatch):
    from app.services.llm_services import LLMService

    class FakeProvider:
        def __init__(self, provider_name, model_name, response_text=None, fail=False):
            self.provider_name = provider_name
            self.model_name = model_name
            self.response_text = response_text
            self.fail = fail

        def generate(self, request):
            if self.fail:
                return LLMResponse(
                    provider=self.provider_name,
                    model=self.model_name,
                    success=False,
                    text="",
                    stage="provider_request",
                    error="Provider request failed.",
                    error_details=LLMError(
                        category=LLMErrorCategory.TIMEOUT,
                        message="Provider request failed.",
                        stage="provider_request",
                    ),
                )
            return LLMResponse(
                provider=self.provider_name,
                model=self.model_name,
                success=True,
                text=self.response_text,
                stage="complete",
            )

    primary = FakeProvider("primary", "primary-model", fail=True)
    fallback = FakeProvider(
        "fallback",
        "fallback-model",
        response_text=json.dumps(_summary_payload()),
    )
    monkeypatch.setattr(
        "app.services.llm_services.get_provider",
        lambda provider_name, _model: fallback,
    )
    service_llm = LLMService(
        provider=primary,
        fallback_enabled=True,
        fallback_provider_name="fallback",
        fallback_model_name="fallback-model",
        telemetry_service=InMemoryLLMTelemetryService(),
    )
    service = ProjectIntelligenceService(
        db=None,
        llm_service=service_llm,
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 3}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    result = service.generate_quality_summary(8, 2)

    assert result["status"] == "available"
    assert result["summary"]["overall_summary"]["evidence_ids"] == ["test_case_statistics"]


@pytest.mark.parametrize(
    "response,expected_category,expected_log_fields,secret_text",
    [
        (
            {
                "success": False,
                "error": "provider details must not escape",
                "provider": "gemini",
                "model": "configured-model",
                "stage": "provider_request",
                "error_category": "provider_api",
                "error_type": "APIError",
                "fallback_attempted": True,
            },
            "llm_response_failed",
            ("diagnostic=llm_response", "project_id=8", "failure_category=llm_response_failed", "response_state=unsuccessful_response", "error_category=provider_api"),
            "provider details must not escape",
        ),
        (
            {"success": True, "answer": ""},
            "llm_response_failed",
            ("diagnostic=llm_response", "project_id=8", "failure_category=llm_response_failed", "response_state=empty_answer"),
            "",
        ),
        (
            {"success": True, "answer": "{not-json"},
            "structured_output_invalid",
            ("diagnostic=structured_output_validation", "project_id=8", "failure_category=structured_output_invalid", "error_category=structured_output_parse", "error_stage=structured_output_parse"),
            "{not-json",
        ),
        (
            {
                "success": True,
                "answer": json.dumps({
                    **_summary_payload(),
                    "private project document": "sensitive project text",
                }),
            },
            "structured_output_invalid",
            ("diagnostic=structured_output_validation", "project_id=8", "failure_category=structured_output_invalid", "validation_error_count=1", "validation_fields=other", "validation_codes=extra_forbidden"),
            "sensitive project text",
        ),
        (
            {"success": True, "answer": json.dumps(_summary_payload("private project reference"))},
            "evidence_reference_invalid",
            ("diagnostic=evidence_reference_validation", "project_id=8", "failure_category=evidence_reference_invalid", "error_type=ValueError", "invalid_reference_count=1", "allowed_evidence_count=1"),
            "private project reference",
        ),
    ],
)
def test_quality_summary_logs_safe_unavailable_branch_diagnostics(
    response,
    expected_category,
    expected_log_fields,
    secret_text,
    caplog,
):
    service = ProjectIntelligenceService(
        db=None,
        llm_service=_FakeLLM(response),
        summary_cache=EvidenceFingerprintCache(),
    )
    service.require_owned_project = lambda *_args: None
    service._summary_evidence = lambda *_args: (
        {"test_case_statistics": {"total_cases": 0}},
        [{"id": "test_case_statistics", "description": "Persisted case counts."}],
    )

    with caplog.at_level("WARNING", logger="app.services.project_intelligence_service"):
        result = service.generate_quality_summary(8, 2)

    assert result["status"] == "unavailable"
    assert result["summary"] is None
    assert result["error"] == "Quality summary is temporarily unavailable."
    assert result["_failure_category"] == expected_category
    for field in expected_log_fields:
        assert field in caplog.text
    if secret_text:
        assert secret_text not in caplog.text


@pytest.mark.parametrize(
    "failure_category,expected_log_category",
    [
        ("evidence_reference_invalid", "evidence_reference_invalid"),
        ("sensitive document contents", "unclassified"),
    ],
)
def test_quality_summary_api_logs_status_and_safe_category_then_removes_internal_marker(
    monkeypatch,
    caplog,
    failure_category,
    expected_log_category,
):
    class _StubProjectIntelligenceService:
        def __init__(self, _db):
            pass

        def generate_quality_summary(self, *, project_id, current_user_id):
            assert project_id == 2
            assert current_user_id == 7
            return {
                "project_id": project_id,
                "status": "unavailable",
                "summary": None,
                "evidence_sources": [],
                "generated_at": None,
                "cached": False,
                "evidence_fingerprint": "safe-fingerprint",
                "limitations": [],
                "error": "Quality summary is temporarily unavailable.",
                "_failure_category": failure_category,
            }

    monkeypatch.setattr(
        analytics_api,
        "ProjectIntelligenceService",
        _StubProjectIntelligenceService,
    )

    with caplog.at_level("WARNING", logger="app.api.analytics"):
        result = analytics_api.generate_quality_summary(
            project_id=2,
            current_user=SimpleNamespace(id=7),
            db=object(),
        )

    assert result["status"] == "unavailable"
    assert "_failure_category" not in result
    QualitySummaryResponse.model_validate(result)
    assert "Quality summary API result: project_id=2 status=unavailable" in caplog.text
    assert f"failure_category={expected_log_category}" in caplog.text
    if expected_log_category == "unclassified":
        assert failure_category not in caplog.text


def test_summary_evidence_fingerprint_is_stable_and_changes_with_metrics():
    first = _evidence_fingerprint({"runs": {"passed": 1}, "name": "project"})
    reordered = _evidence_fingerprint({"name": "project", "runs": {"passed": 1}})
    changed = _evidence_fingerprint({"name": "project", "runs": {"passed": 2}})

    assert first == reordered
    assert first != changed


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("get_project_risks", (9, 3)),
        ("get_workflow_monitoring", (9, 3)),
        ("generate_quality_summary", (9, 3)),
    ],
)
def test_project_intelligence_methods_reject_non_owner_before_data_access(
    method_name,
    args,
):
    db = _AuthorizationDB(project=None)
    service = ProjectIntelligenceService(db=db, llm_service=_FakeLLM({}))

    with pytest.raises(ValueError, match="Project not found"):
        getattr(service, method_name)(*args)

    assert db.queried_model is Project


def test_workflow_monitor_limit_is_validated():
    service = ProjectIntelligenceService(db=_AuthorizationDB(project=None))

    with pytest.raises(ValueError, match="between 1 and 100"):
        service.get_workflow_monitoring(1, 1, limit=101)


def test_project_ownership_query_uses_existing_organization_owner_relation():
    db = _AuthorizationDB(project=SimpleNamespace(id=9))
    ProjectIntelligenceService(db=db).require_owned_project(9, 3)

    assert db.queried_model is Project
    assert len(db.query_result.joins) == 1
    joined_model, onclause = db.query_result.joins[0]
    assert joined_model is Organization
    assert onclause.compare(Project.organitzation_id == Organization.id)
    assert len(db.query_result.filters) == 2
