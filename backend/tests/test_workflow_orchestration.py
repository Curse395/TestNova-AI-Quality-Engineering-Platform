import json
import threading
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from fastapi import BackgroundTasks

from app.agents.contracts import (
    AgentContext,
    AgentInput,
    AgentOutput,
    AgentResult,
    WorkflowContext,
)
from app.agents.orchestrator import Orchestrator
from app.agents.bug_analysis_agent import BugAnalysisAgent
from app.agents.requirements_agent import RequirementsAnalysisAgent
from app.agents.review_agent import ReviewAgent
from app.agents.test_analysis_agent import TestAnalysisAgent as AnalysisAgent
from app.agents.quality_insight_agent import QualityInsightAgent
from app.database.connection import Base
from app.core.dependencies import get_current_user
from app.database.connection import get_db
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.models.workflow_run import WorkflowRun
from app.models.workflow_task import WorkflowTask
from app.models.workflow_task_attempt import WorkflowTaskAttempt
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as CaseEvidenceModel
from app.models.test_case_generation_run import (
    TestCaseGenerationRun as GenerationRunModel,
)
from app.models.project_requirement import ProjectRequirement
from app.models.test_case_requirement import TestCaseRequirement
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services import workflow_service
from app.services.workflow_service import WorkflowService
from app.services.workflow_validation_service import WorkflowValidationService
from app.services.test_case_evaluation_service import (
    TestCaseEvaluationService as EvaluationService,
)
from app.services.test_case_generation_service import (
    TestCaseGenerationService as GenerationService,
)
from app.schemas.test_case_schema import (
    TestCaseGenerationRequest as GenerationRequest,
)
from datetime import datetime, timedelta
from app.main import app

MODEL_TABLES = [
    User.__table__,
    Organization.__table__,
    Project.__table__,
    WorkflowRun.__table__,
    WorkflowTask.__table__,
    WorkflowTaskAttempt.__table__,
    GenerationRunModel.__table__,
    CaseModel.__table__,
    Document.__table__,
    DocumentChunk.__table__,
    CaseEvidenceModel.__table__,
    ProjectRequirement.__table__,
    TestCaseRequirement.__table__,
]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflow.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=MODEL_TABLES)
    session = sessionmaker(bind=engine)()
    user = User(name="Owner", email="owner@test.local", password_hash="test")
    session.add(user)
    session.flush()
    organization = Organization(name="Workspace", owner_id=user.id)
    session.add(organization)
    session.flush()
    project = Project(name="QA project", organitzation_id=organization.id)
    session.add(project)
    session.commit()
    try:
        yield session, user, project
    finally:
        session.close()
        engine.dispose()


def test_typed_workflow_contracts_validate_required_identity():
    request = AgentInput(
        workflow_id=1,
        task_id=2,
        project_id=3,
        user_id=4,
        task_type="requirements_analysis",
    )
    output = AgentOutput(
        agent_name="requirements_analysis_agent",
        status="completed",
        structured_data={"requirements": []},
    )
    context = WorkflowContext(project_id=3, user_id=4)

    assert request.input_data == {}
    assert output.structured_data == {"requirements": []}
    assert context.evidence_references == []
    with pytest.raises(ValidationError):
        AgentInput(workflow_id=1, task_type="requirements_analysis")


def test_orchestrator_classifies_supported_workflows_and_dependencies():
    assert Orchestrator.classify_task({"workflow_type": "test_generation"}) == "test_generation"
    assert Orchestrator.classify_task({"request": "please analyze bugs"}) == "bug_analysis"
    assert Orchestrator.classify_task({"request": "run complete QA"}) == "full_qa_workflow"
    assert Orchestrator.workflow_template("full_qa_workflow") == (
        "requirements_analysis",
        "change_risk_analysis",
        "test_analysis",
        "bug_analysis",
        "quality_insights",
        "test_generation",
        "deterministic_validation",
        "review",
        "aggregation",
    )
    with pytest.raises(ValueError, match="Unsupported"):
        Orchestrator.classify_task({"workflow_type": "unknown"})


def test_full_workflow_persists_results_and_skips_optional_agents(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="full_qa_workflow",
        status="running",
        input_data={"requirements_prompt": "Check the documented sign-in flow."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("full_qa_workflow"),
    )

    class FakeOrchestrator:
        def route(self, context: AgentContext) -> AgentResult:
            if context.task == "requirements_analysis":
                return AgentResult(
                    "requirements_analysis_agent",
                    "success",
                    data={
                        "requirements": [
                            {
                                "id": "REQ-1",
                                "description": "Users can sign in.",
                                "evidence_chunk_ids": [21],
                            }
                        ],
                        "acceptance_criteria": [],
                        "ambiguities": [],
                        "risks": [],
                        "evidence": [],
                    },
                    evidence=[
                        {
                            "document_id": 41,
                            "chunk_id": 21,
                            "document_name": "requirements.md",
                            "content": "Sign-in requires a registered account.",
                        }
                    ],
                )
            if context.task == "bug_analysis":
                return AgentResult(
                    "bug_analysis_agent",
                    "skipped",
                    data={
                        "reason": (
                            "No relevant bug reports or failed execution records "
                            "were found."
                        )
                    },
                )
            if context.task == "test_generation":
                assert context.inputs["workflow_run_id"] == workflow.id
                assert context.metadata["shared_context"]["requirements"]["requirements"]
                assert context.metadata["shared_context"]["evidence_references"][0][
                    "chunk_id"
                ] == 21
                assert "Users can sign in." in context.inputs[
                    "request"
                ].requirements_prompt
                assert "Sign-in requires a registered account." in context.inputs[
                    "request"
                ].requirements_prompt
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={
                        "generated_count": 1,
                        "test_cases": [{"id": 77, "title": "Sign in"}],
                    },
                )
            if context.task == "review":
                return AgentResult(
                    "review_agent",
                    "success",
                    data={
                        "recommendation": "human_review_required",
                        "findings": [],
                    },
                )
            if context.task == "quality_insights":
                return AgentResult(
                    "quality_insight_agent",
                    "success",
                    data={"insights": []},
                )
            if context.task == "test_analysis":
                return AgentResult(
                    "test_analysis_agent",
                    "success",
                    data={"analysis": {"overall_quality": "good"}},
                )
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(workflow_service, "_register_agents", lambda _db: FakeOrchestrator())
    monkeypatch.setattr(
        workflow_service.WorkflowValidationService,
        "validate",
        lambda *_args, **_kwargs: {
            "valid": True,
            "findings": [],
            "validated_case_ids": [77],
        },
    )

    workflow_service._execute_workflow(session, workflow)

    assert workflow.status == "completed"
    assert workflow.final_output["workflow_approval"] == "ready_for_human_review"
    assert workflow.final_output["results"]["bug_analysis"]["status"] == "skipped"
    assert all(task.status in {"completed", "skipped"} for task in tasks)
    assert list(workflow.final_output["results"]) == [
        task.task_type for task in tasks
    ]
    assert all(
        attempt.status in {"completed", "skipped"}
        for task in tasks
        for attempt in task.attempts
        if task.task_type != "bug_analysis"
    )


def test_workflow_template_persists_ordered_task_records(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="pending",
        input_data={},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )

    assert [task.task_type for task in tasks] == [
        "requirements_analysis",
        "test_generation",
        "deterministic_validation",
        "review",
        "aggregation",
    ]
    assert all(task.status == "pending" for task in tasks)
    assert tasks[0].depends_on_task_ids == []
    assert tasks[1].depends_on_task_ids == [tasks[0].id]


@pytest.mark.parametrize(
    ("prerequisite_status", "generation_runs"),
    [
        ("failed", False),
        ("skipped", False),
        ("partial", False),
        ("completed", True),
    ],
)
def test_task_prerequisites_must_succeed_before_generation(
    db,
    monkeypatch,
    prerequisite_status,
    generation_runs,
):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate sign-in tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    requirements_task = _task_by_type_for_test(tasks, "requirements_analysis")
    generation_task = _task_by_type_for_test(tasks, "test_generation")
    requirements_task.status = prerequisite_status
    requirements_task.output_data = {
        "structured_data": {},
        "status": prerequisite_status,
    }
    session.commit()
    calls = []

    class FakeOrchestrator:
        def route(self, context):
            calls.append(context.task)
            if context.task == "test_generation":
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={"test_cases": [{"id": 77}]},
                )
            if context.task == "review":
                return AgentResult(
                    "review_agent",
                    "success",
                    data={"recommendation": "human_review_required"},
                )
            raise AssertionError(f"Unexpected agent route: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    monkeypatch.setattr(
        WorkflowValidationService,
        "validate",
        lambda *_args, **_kwargs: {
            "valid": True,
            "findings": [],
            "validated_case_ids": [77],
        },
    )

    workflow_service._execute_workflow(session, workflow)

    if generation_runs:
        assert generation_task.status == "completed"
        assert "test_generation" in calls
    else:
        assert generation_task.status == "skipped"
        assert generation_task.error_details["code"] == "DEPENDENCY_NOT_SATISFIED"
        assert "test_generation" not in calls


def test_quality_insights_depends_on_test_analysis(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="quality_insights",
        status="pending",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("quality_insights"),
    )

    test_analysis = _task_by_type_for_test(tasks, "test_analysis")
    quality_insights = _task_by_type_for_test(tasks, "quality_insights")
    assert quality_insights.depends_on_task_ids == [test_analysis.id]


def test_independent_tasks_run_concurrently_with_bounded_sessions(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="full_qa_workflow",
        status="running",
        input_data={"change_summary": "Improve sign-in error handling."},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("full_qa_workflow"),
    )
    independent = [
        _task_by_type_for_test(tasks, task_type)
        for task_type in (
            "requirements_analysis",
            "change_risk_analysis",
            "test_analysis",
        )
    ]
    assert all(not task.depends_on_task_ids for task in independent)
    session.commit()

    lock = threading.Lock()
    concurrent_started = threading.Event()
    active = 0
    maximum_active = 0
    calls = []

    class FakeOrchestrator:
        def route(self, context):
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
                calls.append(context.task)
                if active >= 2:
                    concurrent_started.set()
            assert concurrent_started.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active -= 1
            return AgentResult(
                f"{context.task}_agent",
                "success",
                data={"task": context.task},
            )

    monkeypatch.setattr(
        workflow_service.settings,
        "WORKFLOW_MAX_CONCURRENT_TASKS",
        2,
    )
    monkeypatch.setattr(
        workflow_service.settings,
        "WORKFLOW_AGENT_TASK_TIMEOUT_SECONDS",
        10,
    )
    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    session_factory = sessionmaker(bind=session.get_bind())
    task_results = {}
    workflow_service._execute_parallel_batch(
        session,
        workflow,
        independent,
        {},
        task_results,
        session_factory,
    )

    assert len(calls) == 3
    assert maximum_active == 2
    assert [task.task_type for task in independent] == list(task_results)
    assert all(task.status == "completed" for task in independent)
    assert all(len(task.attempts) == 1 for task in independent)


def test_parallel_task_failure_preserves_success_and_blocks_dependents(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="full_qa_workflow",
        status="running",
        input_data={"requirements_prompt": "Check account recovery."},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("full_qa_workflow"),
    )
    requirements = _task_by_type_for_test(tasks, "requirements_analysis")
    test_analysis = _task_by_type_for_test(tasks, "test_analysis")
    quality = _task_by_type_for_test(tasks, "quality_insights")
    session.commit()

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "requirements_analysis":
                return AgentResult(
                    "requirements_analysis_agent",
                    "failed",
                    error={"code": "TEST_FAILURE", "message": "Controlled failure"},
                )
            return AgentResult(
                "test_analysis_agent",
                "success",
                data={"analysis": "preserved"},
            )

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    monkeypatch.setattr(
        workflow_service.settings,
        "WORKFLOW_MAX_CONCURRENT_TASKS",
        2,
    )
    workflow_service._execute_parallel_batch(
        session,
        workflow,
        [requirements, test_analysis],
        {},
        {},
        sessionmaker(bind=session.get_bind()),
    )
    assert requirements.status == "failed"
    assert test_analysis.status == "completed"
    assert test_analysis.output_data["structured_data"]["analysis"] == "preserved"
    assert quality.depends_on_task_ids == [test_analysis.id]
    assert test_analysis.id not in requirements.depends_on_task_ids

    workflow_service._execute_workflow(session, workflow)
    bug_analysis = _task_by_type_for_test(tasks, "bug_analysis")
    generation = _task_by_type_for_test(tasks, "test_generation")
    assert bug_analysis.status == "skipped"
    assert bug_analysis.error_details["code"] == "DEPENDENCY_NOT_SATISFIED"
    assert generation.status == "skipped"
    assert test_analysis.output_data["structured_data"]["analysis"] == "preserved"


def test_quality_insights_waits_for_test_analysis(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="quality_insights",
        status="running",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("quality_insights"),
    )
    session.commit()
    test_analysis_finished = threading.Event()
    execution_order = []

    class FakeOrchestrator:
        def route(self, context):
            execution_order.append(context.task)
            if context.task == "test_analysis":
                time.sleep(0.02)
                test_analysis_finished.set()
                return AgentResult(
                    "test_analysis_agent",
                    "success",
                    data={"analysis": "ready"},
                )
            assert context.task == "quality_insights"
            assert test_analysis_finished.is_set()
            return AgentResult(
                "quality_insight_agent",
                "success",
                data={"insights": "derived"},
            )

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    workflow_service._execute_workflow(session, workflow)

    assert execution_order == ["test_analysis", "quality_insights"]
    assert all(task.status == "completed" for task in tasks)


def test_test_analysis_empty_history_is_successful_empty_state():
    agent = AnalysisAgent.__new__(AnalysisAgent)
    agent.execution_service = SimpleNamespace(
        get_execution_history=lambda **_: {"executions": []}
    )
    result = agent.run(AgentContext(user_id=4, project_id=3, task="test_analysis"))

    assert result.status == "success"
    assert result.data == {
        "outcome": "no_execution_history",
        "message": "No execution history available for analysis.",
        "total_executions": 0,
    }


def test_quality_insight_agent_marks_empty_execution_metrics_unavailable():
    agent = QualityInsightAgent.__new__(QualityInsightAgent)
    agent.analytics = SimpleNamespace(
        get_project_overview=lambda **_: {"document_count": 1},
        get_document_statistics=lambda **_: {"processed_documents": 1},
    )
    agent.execution_service = SimpleNamespace(
        get_execution_history=lambda **_: {"executions": []}
    )
    agent.llm = SimpleNamespace(
        generate_content=lambda **_: {
            "success": True,
            "answer": '{"overall_quality":"insufficient_data"}',
            "model": "controlled-test",
        }
    )
    result = agent.run(
        AgentContext(user_id=4, project_id=3, task="quality_insights")
    )

    assert result.status == "success"
    assert result.data["metrics"]["testing_health"] == {
        "total_executions": 0,
        "status_distribution": {
            "passed": 0,
            "failed": 0,
            "error": 0,
            "other": 0,
        },
        "pass_rate_percentage": None,
    }


def test_quality_insights_runs_after_empty_test_analysis_result(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="quality_insights",
        status="running",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("quality_insights"),
    )
    session.commit()
    test_agent = AnalysisAgent.__new__(AnalysisAgent)
    test_agent.execution_service = SimpleNamespace(
        get_execution_history=lambda **_: {"executions": []}
    )
    quality_called = []

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "test_analysis":
                return test_agent.run(context)
            assert context.task == "quality_insights"
            quality_called.append(True)
            assert context.metadata["shared_context"]["test_analysis"]["outcome"] == (
                "no_execution_history"
            )
            return AgentResult(
                "quality_insight_agent",
                "success",
                data={
                    "testing_health": {
                        "total_executions": 0,
                        "pass_rate_percentage": None,
                    },
                    "insights": "Execution metrics are unavailable.",
                },
            )

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    workflow_service._execute_workflow(session, workflow)

    test_analysis = _task_by_type_for_test(tasks, "test_analysis")
    quality = _task_by_type_for_test(tasks, "quality_insights")
    assert quality_called == [True]
    assert test_analysis.status == "completed"
    assert quality.status == "completed"
    assert quality.output_data["structured_data"]["testing_health"][
        "pass_rate_percentage"
    ] is None


def test_actual_test_analysis_failure_blocks_quality_insights(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="quality_insights",
        status="running",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("quality_insights"),
    )
    session.commit()
    test_agent = AnalysisAgent.__new__(AnalysisAgent)

    def failed_history(**_):
        raise ValueError("Project not found or access denied.")

    test_agent.execution_service = SimpleNamespace(
        get_execution_history=failed_history
    )
    quality_calls = []

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "test_analysis":
                return test_agent.run(context)
            quality_calls.append(context.task)
            raise AssertionError("Quality Insights must not run after a real failure.")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    workflow_service._execute_workflow(session, workflow)

    test_analysis = _task_by_type_for_test(tasks, "test_analysis")
    quality = _task_by_type_for_test(tasks, "quality_insights")
    assert test_analysis.status == "failed"
    assert quality.status == "skipped"
    assert quality.error_details["code"] == "DEPENDENCY_NOT_SATISFIED"
    assert quality_calls == []


def test_task_claim_prevents_duplicate_execution(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    task = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )[0]
    session.commit()

    attempt = workflow_service._start_attempt(session, task)
    with pytest.raises(RuntimeError, match="already running"):
        workflow_service._start_attempt(session, task)
    session.refresh(task)
    assert task.attempt_count == 1
    assert session.query(WorkflowTaskAttempt).filter_by(
        workflow_task_id=task.id
    ).count() == 1
    assert attempt.status == "running"


def _create_case_for_approval(
    session,
    user,
    project,
    evidence_project=None,
    valid=True,
    attach_evidence=True,
):
    evidence_project = evidence_project or project
    document = Document(
        filename="requirements.md",
        content_type="text/plain",
        storage_path="unused",
        project_id=evidence_project.id,
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content="Users can sign in with a registered account.",
    )
    session.add(chunk)
    session.flush()
    case = CaseModel(
        project_id=project.id,
        created_by_user_id=user.id,
        title="Sign-in behavior" if valid else "",
        description="Verify documented sign-in." if valid else "",
        category="positive",
        priority="high",
        steps=(
            [{"action": "Submit credentials", "expected_result": "Sign in succeeds"}]
            if valid
            else []
        ),
        expected_result="The user is signed in." if valid else "",
        review_status="draft",
    )
    session.add(case)
    session.flush()
    if attach_evidence:
        session.add(
            CaseEvidenceModel(
                test_case_id=case.id,
                document_id=document.id,
                chunk_id=chunk.id,
            )
        )
    session.commit()
    return case


def _approve_via_api(session, user, project, case_id):
    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    try:
        return TestClient(app).patch(
            f"/projects/{project.id}/test-cases/{case_id}/approve"
        )
    finally:
        app.dependency_overrides.clear()


def test_approval_requires_deterministic_validation_and_acceptable_review(
    db,
    monkeypatch,
):
    session, user, project = db
    case = _create_case_for_approval(session, user, project)
    monkeypatch.setattr(
        EvaluationService,
        "evaluate",
        lambda *_args, **_kwargs: {
            "evaluation_status": "completed",
            "recommendation": "human_review_required",
            "findings": [],
            "checks": {},
            "evidence": [],
        },
    )

    response = _approve_via_api(session, user, project, case.id)

    assert response.status_code == 200
    session.refresh(case)
    assert case.review_status == "approved"


def test_owner_can_explicitly_approve_after_semantic_evaluation_is_unavailable(
    db,
    monkeypatch,
):
    session, user, project = db
    case = _create_case_for_approval(session, user, project)
    monkeypatch.setattr(
        EvaluationService,
        "evaluate",
        lambda *_args, **_kwargs: {
            "evaluation_status": "unavailable",
            "recommendation": "human_review_required",
            "findings": [
                {
                    "severity": "low",
                    "check": "semantic_evaluation",
                    "message": "Semantic support was not established.",
                }
            ],
            "checks": {
                "semantic_evaluation": {
                    "status": "evaluation_unavailable",
                    "reason": "Provider request failed.",
                }
            },
            "evidence": [],
        },
    )

    response = _approve_via_api(session, user, project, case.id)

    assert response.status_code == 200
    session.refresh(case)
    assert case.review_status == "approved"


def test_approval_rejects_missing_fields_steps_and_evidence(db, monkeypatch):
    session, user, project = db
    case = _create_case_for_approval(
        session,
        user,
        project,
        valid=False,
        attach_evidence=False,
    )
    evaluations = []
    monkeypatch.setattr(
        EvaluationService,
        "evaluate",
        lambda *_args, **_kwargs: evaluations.append(True) or {},
    )

    response = _approve_via_api(session, user, project, case.id)

    assert response.status_code == 422
    assert evaluations == []
    session.refresh(case)
    assert case.review_status == "draft"


def test_approval_rejects_evidence_from_another_project(db, monkeypatch):
    session, user, project = db
    other_project = Project(
        name="Other project",
        organitzation_id=project.organitzation_id,
    )
    session.add(other_project)
    session.commit()
    case = _create_case_for_approval(
        session,
        user,
        project,
        evidence_project=other_project,
    )
    monkeypatch.setattr(
        EvaluationService,
        "evaluate",
        lambda *_args, **_kwargs: {
            "evaluation_status": "completed",
            "recommendation": "human_review_required",
            "findings": [],
            "checks": {},
            "evidence": [],
        },
    )

    response = _approve_via_api(session, user, project, case.id)

    assert response.status_code == 422
    session.refresh(case)
    assert case.review_status == "draft"


def test_approval_rejects_unacceptable_evaluation_findings(db, monkeypatch):
    session, user, project = db
    case = _create_case_for_approval(session, user, project)
    monkeypatch.setattr(
        EvaluationService,
        "evaluate",
        lambda *_args, **_kwargs: {
            "evaluation_status": "completed",
            "recommendation": "needs_revision",
            "findings": [
                {"severity": "high", "message": "Expected result is unsupported."}
            ],
            "checks": {},
            "evidence": [],
        },
    )

    response = _approve_via_api(session, user, project, case.id)

    assert response.status_code == 422
    session.refresh(case)
    assert case.review_status == "draft"


def test_requirements_agent_retains_only_supported_chunk_references():
    evidence = [
        {
            "chunk_id": 21,
            "document_id": 11,
            "document_name": "requirements.md",
            "content": "REQ-1: Users can sign in with a registered account.",
        }
    ]
    knowledge = SimpleNamespace(
        run=lambda _context: AgentResult(
            "knowledge_agent",
            "success",
            data={"chunks": evidence},
            evidence=evidence,
        )
    )
    llm = SimpleNamespace(
        generate_content=lambda **_: {
            "success": True,
            "answer": json.dumps(
                {
                    "requirements": [
                        {
                            "id": "REQ-1",
                            "description": "Users can sign in.",
                            "classification": "explicit",
                            "evidence_chunk_ids": [21],
                        }
                    ],
                    "acceptance_criteria": [],
                    "ambiguities": [],
                    "risks": [],
                    "evidence": [],
                }
            ),
        }
    )
    agent = RequirementsAnalysisAgent(
        None,
        knowledge_agent=knowledge,
        llm_service=llm,
    )

    result = agent.run(AgentContext(user_id=4, project_id=3, task="requirements_analysis"))

    assert result.status == "success"
    assert result.data["requirements"][0]["evidence_chunk_ids"] == [21]
    assert result.evidence == evidence


def test_bug_analysis_skips_without_reports_or_failed_executions():
    agent = BugAnalysisAgent(
        None,
        retrieval_service=SimpleNamespace(search_project_context=lambda **_: []),
        execution_service=SimpleNamespace(
            get_execution_history=lambda **_: {"executions": [{"status": "passed"}]}
        ),
        llm_service=SimpleNamespace(),
    )

    result = agent.run(AgentContext(user_id=4, project_id=3, task="bug_analysis"))

    assert result.status == "skipped"
    assert "No relevant" in result.data["reason"]


@pytest.mark.parametrize(
    ("report_text", "expected_status", "requirement_id", "result_status"),
    [
        (
            "A customer reported an unexpected sign-in issue.",
            "inferred",
            "REQ-1",
            "success",
        ),
        ("REQ-1 fails for test case 31.", "confirmed", "REQ-1", "success"),
        ("REQ-1 fails for test case 31.", "unsupported", "REQ-9", "failed"),
    ],
)
def test_bug_relationship_confirmation_requires_direct_evidence(
    report_text,
    expected_status,
    requirement_id,
    result_status,
):
    reports = [
        {
            "chunk_id": 21,
            "document_id": 11,
            "document_name": "bug-report.md",
            "content": report_text,
        }
    ]
    answer = {
        "bugs": [],
        "observed_behavior": [],
        "expected_behavior": [],
        "related_requirements": [
            {
                "requirement_id": requirement_id,
                "relationship_status": "confirmed",
                "evidence_chunk_ids": [21],
                "execution_ids": [],
            }
        ],
        "related_test_cases": [
            {
                "test_case_id": 31,
                "relationship_status": "confirmed",
                "evidence_chunk_ids": [21],
                "execution_ids": [7],
            }
        ],
        "inferred_relationships": [],
    }
    agent = BugAnalysisAgent(
        None,
        retrieval_service=SimpleNamespace(
            search_project_context=lambda **_: reports
        ),
        execution_service=SimpleNamespace(
            get_execution_history=lambda **_: {
                "executions": [
                    {"id": 7, "status": "failed", "test_case_id": 31}
                ]
            }
        ),
        llm_service=SimpleNamespace(
            generate_content=lambda **_: {
                "success": True,
                "answer": json.dumps(answer),
            }
        ),
    )

    result = agent.run(
        AgentContext(
            user_id=4,
            project_id=3,
            task="bug_analysis",
            metadata={
                "shared_context": {
                    "requirements": {
                        "requirements": [
                            {"id": "REQ-1", "description": "Users can sign in."}
                        ]
                    }
                }
            },
        )
    )

    assert result.status == result_status
    if result_status == "failed":
        assert result.error["code"] == "BUG_ANALYSIS_OUTPUT_INVALID"
        assert result.evidence == reports
        return
    assert result.data["related_requirements"][0]["relationship_status"] == expected_status
    assert result.data["related_test_cases"][0]["relationship_status"] == "confirmed"
    assert result.data["related_requirements"][0]["evidence_chunk_ids"] == [21]


def _bug_analysis_agent_for_response(answer, reports, executions=None):
    return BugAnalysisAgent(
        None,
        retrieval_service=SimpleNamespace(
            search_project_context=lambda **_: reports
        ),
        execution_service=SimpleNamespace(
            get_execution_history=lambda **_: {
                "executions": executions or []
            }
        ),
        llm_service=SimpleNamespace(
            generate_content=lambda **_: {
                "success": True,
                "answer": json.dumps(answer),
            }
        ),
    )


def _bug_analysis_response(**overrides):
    answer = {
        "bugs": [],
        "observed_behavior": [],
        "expected_behavior": [],
        "related_requirements": [],
        "related_test_cases": [],
        "inferred_relationships": [],
    }
    answer.update(overrides)
    return answer


def test_bug_analysis_accepts_supported_bug_records_and_exact_prompt_schema():
    reports = [
        {
            "chunk_id": chunk_id,
            "document_id": 11,
            "document_name": "02_MediTrack_Bug_Reports.csv",
            "content": (
                f"BUG-{bug_id} description from source; "
                f"BUG-{bug_id + 1} description from source"
            ),
        }
        for chunk_id, bug_id in ((46, 101), (47, 103), (48, 105))
    ]
    bugs = [
        {
            "bug_id": f"BUG-{bug_id}",
            "evidence_chunk_ids": [46 + (index // 2)],
            "execution_ids": [],
        }
        for index, bug_id in enumerate(range(101, 107))
    ]
    response = _bug_analysis_response(
        bugs=bugs,
        observed_behavior=[
            {"evidence_chunk_ids": [46], "execution_ids": []}
        ],
        expected_behavior=[
            {"evidence_chunk_ids": [47], "execution_ids": []}
        ],
    )
    prompts = {}

    class PromptCapturingLLM:
        def generate_content(self, **kwargs):
            prompts.update(kwargs)
            return {"success": True, "answer": json.dumps(response)}

    agent = BugAnalysisAgent(
        None,
        retrieval_service=SimpleNamespace(
            search_project_context=lambda **_: reports
        ),
        execution_service=SimpleNamespace(
            get_execution_history=lambda **_: {"executions": []}
        ),
        llm_service=PromptCapturingLLM(),
    )
    result = agent.run(
        AgentContext(user_id=4, project_id=3, task="bug_analysis")
    )

    assert result.status == "success"
    assert [item["bug_id"] for item in result.data["bugs"]] == [
        f"BUG-{bug_id}" for bug_id in range(101, 107)
    ]
    assert [item["chunk_id"] for item in result.data["evidence"]] == [46, 47, 48]
    prompt = prompts["system_prompt"]
    for field in (
        "bugs",
        "observed_behavior",
        "expected_behavior",
        "related_requirements",
        "related_test_cases",
        "inferred_relationships",
    ):
        assert f'"{field}": [entry, ...]' in prompt
    assert '"evidence_chunk_ids": an array of integer chunk IDs' in prompt
    assert '"relationship_status" as exactly "confirmed" or "inferred"' in prompt


@pytest.mark.parametrize(
    ("field", "entry", "diagnostic"),
    [
        (
            "bugs",
            {"bug_id": "BUG-101", "evidence_chunk_ids": [], "execution_ids": []},
            "uncited claim",
        ),
        (
            "bugs",
            {"bug_id": "BUG-101", "evidence_chunk_ids": [999], "execution_ids": []},
            "unsupported chunk citation",
        ),
        (
            "related_requirements",
            {
                "requirement_id": "REQ-999",
                "relationship_status": "inferred",
                "evidence_chunk_ids": [46],
                "execution_ids": [],
            },
            "unsupported requirement relationship",
        ),
        (
            "related_test_cases",
            {
                "test_case_id": 999,
                "relationship_status": "inferred",
                "evidence_chunk_ids": [46],
                "execution_ids": [],
            },
            "unsupported test-case relationship",
        ),
    ],
)
def test_bug_analysis_invalid_output_preserves_evidence_and_logs_diagnostic(
    field,
    entry,
    diagnostic,
    caplog,
):
    reports = [
        {
            "chunk_id": 46,
            "document_id": 11,
            "document_name": "02_MediTrack_Bug_Reports.csv",
            "content": "BUG-101 source evidence",
        }
    ]
    response = _bug_analysis_response(**{field: [entry]})
    agent = _bug_analysis_agent_for_response(response, reports)

    with caplog.at_level("WARNING", logger="app.agents.bug_analysis_agent"):
        result = agent.run(
            AgentContext(user_id=4, project_id=3, task="bug_analysis")
        )

    assert result.status == "failed"
    assert result.error["code"] == "BUG_ANALYSIS_OUTPUT_INVALID"
    assert result.evidence == reports
    assert diagnostic in caplog.text
    assert diagnostic not in result.error["message"]
    assert "Traceback" not in result.error["message"]


def test_review_agent_returns_actionable_feedback_without_auto_approval():
    agent = ReviewAgent.__new__(ReviewAgent)
    agent.service = SimpleNamespace(
        evaluate=lambda **_: {
            "evaluation_status": "completed",
            "recommendation": "human_review_required",
            "review_status": "draft",
            "findings": [
                {
                    "severity": "high",
                    "check": "scenario_coverage",
                    "message": "Add the documented recovery scenario.",
                }
            ],
            "checks": {
                "linked_evidence_count": 1,
                "verified_evidence_count": 1,
                "invalid_evidence_chunk_ids": [],
                "exact_duplicate_case_ids": [],
                "semantic_evaluation": {
                    "evidence_support": "partially_supported",
                    "expected_result_support": "supported",
                    "requirement_coverage": "partial",
                },
            },
            "evidence": [{"document_id": 11, "chunk_id": 21}],
        }
    )

    result = agent.run(
        AgentContext(
            user_id=4,
            project_id=3,
            task="review",
            inputs={"test_case_id": 9},
        )
    )

    assert result.status == "success"
    assert result.data["recommendation"] == "needs_revision"
    assert result.data["missing_scenarios"][0]["check"] == "scenario_coverage"
    assert result.data["evidence_quality"]["verified_evidence_count"] == 1
    assert result.data["coverage_observations"]["requirement_coverage"] == "partial"
    assert result.data["actionable_regeneration_feedback"]
    assert result.data["requires_human_approval"] is True


def test_review_agent_keeps_low_severity_evidence_note_non_blocking():
    agent = ReviewAgent.__new__(ReviewAgent)
    agent.service = SimpleNamespace(
        evaluate=lambda **_: {
            "evaluation_status": "completed",
            "recommendation": "human_review_required",
            "review_status": "draft",
            "findings": [
                {
                    "severity": "low",
                    "check": "evidence_integrity",
                    "message": (
                        "Project-scoped evidence links are valid; semantic support "
                        "is evaluated separately."
                    ),
                }
            ],
            "checks": {
                "linked_evidence_count": 1,
                "verified_evidence_count": 1,
                "invalid_evidence_chunk_ids": [],
                "exact_duplicate_case_ids": [],
                "semantic_evaluation": {
                    "evidence_support": "supported",
                    "expected_result_support": "supported",
                },
            },
            "evidence": [{"document_id": 11, "chunk_id": 21}],
        }
    )

    result = agent.run(
        AgentContext(
            user_id=4,
            project_id=3,
            task="review",
            inputs={"test_case_id": 9},
        )
    )

    assert result.status == "success"
    assert result.data["recommendation"] == "human_review_required"
    assert result.data["warnings"][0].startswith(
        "Project-scoped evidence links are valid"
    )
    assert result.data["actionable_regeneration_feedback"] == []


def test_deterministic_validation_rejects_bad_project_evidence_and_duplicates(db):
    session, user, project = db
    document = Document(
        filename="requirements.md",
        content_type="text/plain",
        storage_path="unused",
        project_id=project.id,
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content="Users can sign in.",
    )
    session.add(chunk)
    session.flush()
    cases = [
        CaseModel(
            project_id=project.id,
            created_by_user_id=user.id,
            title="Sign in",
            description="Verify sign in.",
            category="positive",
            priority="high",
            steps=[{"action": "Submit credentials", "expected_result": "Sign in succeeds"}],
            expected_result="The user is signed in.",
            review_status="draft",
        ),
        CaseModel(
            project_id=project.id,
            created_by_user_id=user.id,
            title="  sign in ",
            description="Verify sign in again.",
            category="positive",
            priority="high",
            steps=[{"action": "Submit credentials", "expected_result": "Sign in succeeds"}],
            expected_result="The user is signed in.",
            review_status="draft",
        ),
    ]
    session.add_all(cases)
    session.flush()
    session.add_all(
        [
            CaseEvidenceModel(
                test_case_id=case.id,
                document_id=document.id,
                chunk_id=chunk.id,
            )
            for case in cases
        ]
    )
    session.commit()

    result = WorkflowValidationService(session).validate(
        user.id,
        project.id,
        [case.id for case in cases],
    )

    assert not result["valid"]
    assert any(item["check"] == "duplicate" for item in result["findings"])
    assert result["validated_case_ids"] == [cases[0].id]


def test_validation_failure_limits_generation_to_two_regenerations(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate authentication coverage."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    generation_calls = []

    class FakeOrchestrator:
        def route(self, context: AgentContext) -> AgentResult:
            if context.task == "requirements_analysis":
                return AgentResult("requirements_analysis_agent", "success", data={})
            if context.task == "test_generation":
                generation_calls.append(context.inputs["workflow_attempt_number"])
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={"test_cases": [{"id": 80 + len(generation_calls)}]},
                )
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(workflow_service, "_register_agents", lambda _db: FakeOrchestrator())
    monkeypatch.setattr(
        workflow_service.WorkflowValidationService,
        "validate",
        lambda *_args, **_kwargs: {
            "valid": False,
            "findings": [{"check": "evidence", "message": "invalid evidence"}],
            "validated_case_ids": [],
        },
    )

    workflow_service._execute_workflow(session, workflow)

    assert generation_calls == [1, 2, 3]
    assert workflow.generation_attempt_count == 3
    assert _task_by_type_for_test(tasks, "test_generation").attempt_count == 3
    assert _task_by_type_for_test(tasks, "deterministic_validation").attempt_count == 3
    assert _task_by_type_for_test(tasks, "test_generation").status == "completed"
    assert _task_by_type_for_test(tasks, "deterministic_validation").status == "failed"
    assert workflow.status == "partially_completed"


def test_review_exception_preserves_generation_and_validation_success(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate supported tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    review_calls = []

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "requirements_analysis":
                return AgentResult("requirements_analysis_agent", "success", data={})
            if context.task == "test_generation":
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={
                        "generated_count": 1,
                        "test_cases": [{"id": 501, "title": "Supported case"}],
                    },
                )
            if context.task == "review":
                review_calls.append(context.inputs["test_case_id"])
                raise RuntimeError("controlled review exception")
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    validation_calls = []

    def validate(*_args, **kwargs):
        validation_calls.append(kwargs["test_case_ids"])
        return {
            "valid": True,
            "findings": [],
            "validated_case_ids": kwargs["test_case_ids"],
        }

    monkeypatch.setattr(WorkflowValidationService, "validate", validate)

    workflow_service._execute_workflow(session, workflow)

    generation = _task_by_type_for_test(tasks, "test_generation")
    validation = _task_by_type_for_test(tasks, "deterministic_validation")
    review = _task_by_type_for_test(tasks, "review")
    assert generation.status == "completed"
    assert generation.attempts[-1].status == "completed"
    assert generation.output_data["structured_data"]["test_cases"][0]["id"] == 501
    assert validation.status == "completed"
    assert validation.output_data["validated_case_ids"] == [501]
    assert review.status == "failed"
    assert review.attempts[-1].status == "failed"
    assert review.error_details["code"] == "REVIEW_FAILED"
    assert review_calls == [501]
    assert validation_calls == [[501]]
    assert workflow.status == "partially_completed"
    assert workflow.final_output["results"]["test_generation"]["status"] == "completed"
    assert workflow.error_summary == "1 workflow task(s) failed or were blocked."


def test_reviewer_feedback_survives_regeneration_retry_exhaustion(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate supported appointment tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    generation_requests = []
    review_calls = []
    feedback = (
        "Avoid duplicate normalized title and expected result from existing "
        "test cases 16 and 17."
    )

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "requirements_analysis":
                return AgentResult("requirements_analysis_agent", "success", data={})
            if context.task == "test_generation":
                generation_requests.append(
                    (
                        context.inputs["workflow_attempt_number"],
                        context.inputs["request"].requirements_prompt,
                    )
                )
                generation_number = context.inputs["workflow_attempt_number"]
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={
                        "generated_count": 1,
                        "test_cases": [
                            {
                                "id": 600 + generation_number,
                                "title": f"Distinct supported case {generation_number}",
                            }
                        ],
                    },
                )
            if context.task == "review":
                review_calls.append(context.inputs["test_case_id"])
                return AgentResult(
                    "review_agent",
                    "success",
                    data={
                        "recommendation": "needs_revision",
                        "findings": [
                            {
                                "severity": "medium",
                                "check": "duplicate_check",
                                "message": feedback,
                            }
                        ],
                        "actionable_regeneration_feedback": [feedback],
                    },
                )
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    monkeypatch.setattr(
        WorkflowValidationService,
        "validate",
        lambda *_args, **kwargs: {
            "valid": True,
            "findings": [],
            "validated_case_ids": kwargs["test_case_ids"],
        },
    )

    workflow_service._execute_workflow(session, workflow)

    generation = _task_by_type_for_test(tasks, "test_generation")
    validation = _task_by_type_for_test(tasks, "deterministic_validation")
    review = _task_by_type_for_test(tasks, "review")
    assert [attempt for attempt, _ in generation_requests] == [1, 2, 3]
    assert "Avoid duplicate normalized title" not in generation_requests[0][1]
    assert all(
        "Avoid duplicate normalized title" in prompt
        for _, prompt in generation_requests[1:]
    )
    assert review_calls == [601, 602, 603]
    assert generation.status == "completed"
    assert validation.status == "completed"
    assert review.status == "completed"
    assert [attempt.status for attempt in review.attempts] == [
        "retrying",
        "retrying",
        "completed",
    ]
    assert review.output_data["review_status"] == "needs_revision"
    assert review.output_data["workflow_approval"] == "needs_revision"
    assert feedback in review.output_data["actionable_feedback"]
    assert workflow.generation_attempt_count == 3
    assert workflow.status == "completed"
    assert workflow.final_output["workflow_approval"] == "needs_revision"
    assert workflow.error_summary is None


def test_validation_exception_fails_validation_and_blocks_review(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate supported tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "requirements_analysis":
                return AgentResult("requirements_analysis_agent", "success", data={})
            if context.task == "test_generation":
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={"test_cases": [{"id": 502, "title": "Supported case"}]},
                )
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )

    def fail_validation(*_args, **_kwargs):
        raise RuntimeError("controlled validation exception")

    monkeypatch.setattr(WorkflowValidationService, "validate", fail_validation)

    workflow_service._execute_workflow(session, workflow)

    generation = _task_by_type_for_test(tasks, "test_generation")
    validation = _task_by_type_for_test(tasks, "deterministic_validation")
    review = _task_by_type_for_test(tasks, "review")
    assert generation.status == "completed"
    assert validation.status == "failed"
    assert validation.error_details["code"] == "VALIDATION_FAILED"
    assert validation.attempts[-1].status == "failed"
    assert review.status == "skipped"
    assert review.error_details["code"] == "DEPENDENCY_NOT_SATISFIED"
    assert workflow.status == "partially_completed"


def test_genuine_generation_failure_remains_failed(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate supported tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    generation_calls = []

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "requirements_analysis":
                return AgentResult("requirements_analysis_agent", "success", data={})
            if context.task == "test_generation":
                generation_calls.append(
                    context.inputs["workflow_attempt_number"]
                )
                return AgentResult(
                    "test_generation_agent",
                    "failed",
                    error={"code": "GENERATION_FAILED", "message": "controlled"},
                )
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )

    workflow_service._execute_workflow(session, workflow)

    generation = _task_by_type_for_test(tasks, "test_generation")
    assert generation_calls == [1, 2, 3]
    assert generation.status == "failed"
    assert generation.attempts[-1].status == "failed"
    assert workflow.status == "partially_completed"


def test_committed_generation_failure_reuses_same_generation_attempt(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={"requirements_prompt": "Generate supported tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    generation_requests = []

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "requirements_analysis":
                return AgentResult("requirements_analysis_agent", "success", data={})
            if context.task == "test_generation":
                attempt_number = context.inputs["workflow_attempt_number"]
                reuse = context.inputs["reuse_existing_workflow_attempt"]
                generation_requests.append((attempt_number, reuse))
                if not reuse:
                    session.add(
                        GenerationRunModel(
                            project_id=project.id,
                            created_by_user_id=user.id,
                            requirements_prompt="Generate supported tests.",
                            requested_categories=["positive"],
                            max_cases=1,
                            status="completed",
                            generated_case_count=1,
                            workflow_run_id=workflow.id,
                            workflow_attempt_number=attempt_number,
                        )
                    )
                    session.commit()
                    return AgentResult(
                        "test_generation_agent",
                        "failed",
                        error={
                            "code": "GENERATION_FAILED",
                            "message": "Response lost after persistence.",
                        },
                    )
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={
                        "generated_count": 1,
                        "test_cases": [{"id": 504, "title": "Recovered case"}],
                    },
                )
            if context.task == "review":
                return AgentResult(
                    "review_agent",
                    "success",
                    data={"recommendation": "human_review_required"},
                )
            raise AssertionError(f"Unexpected task: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    monkeypatch.setattr(
        WorkflowValidationService,
        "validate",
        lambda *_args, **kwargs: {
            "valid": True,
            "findings": [],
            "validated_case_ids": kwargs["test_case_ids"],
        },
    )

    workflow_service._execute_workflow(session, workflow)

    generation = _task_by_type_for_test(tasks, "test_generation")
    assert generation_requests == [(1, False), (1, True)]
    assert generation.attempt_count == 1
    assert generation.status == "completed"
    assert generation.attempts[0].status == "completed"
    assert workflow.generation_attempt_count == 1
    assert (
        session.query(GenerationRunModel)
        .filter_by(workflow_run_id=workflow.id, workflow_attempt_number=1)
        .count()
        == 1
    )


def test_workflow_api_scopes_path_project_and_persists_start(db, monkeypatch):
    session, user, project = db

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    started = []
    monkeypatch.setattr(
        "app.api.workflows.execute_workflow_background",
        lambda workflow_id: started.append(workflow_id),
    )
    try:
        client = TestClient(app)
        response = client.post(
            f"/projects/{project.id}/workflows",
            json={
                "workflow_type": "test_generation",
                "requirements_prompt": "Check the account sign-in path.",
                "project_id": project.id + 100,
                "user_id": user.id + 100,
            },
        )
        workflow_id = response.json()["data"]["id"]
        details = client.get(f"/projects/{project.id}/workflows/{workflow_id}")
        history = client.get(f"/projects/{project.id}/workflows")
        task_history = client.get(
            f"/projects/{project.id}/workflows/{workflow_id}/tasks"
        )
        invalid_categories = client.post(
            f"/projects/{project.id}/workflows",
            json={
                "workflow_type": "test_generation",
                "requirements_prompt": "Check the account sign-in path.",
                "categories": [],
            },
        )
        duplicate = client.post(
            f"/projects/{project.id}/workflows",
            json={"workflow_type": "bug_analysis"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    data = response.json()["data"]
    assert data["project_id"] == project.id
    assert data["workflow_type"] == "test_generation"
    assert all(task["status"] == "pending" for task in data["tasks"])
    assert started == [data["id"]]
    assert details.status_code == 200
    assert history.status_code == 200
    summary = history.json()["data"][0]
    assert summary["id"] == workflow_id
    assert "final_output" not in summary
    assert all("output_data" not in task for task in summary["tasks"])
    assert task_history.status_code == 200
    assert invalid_categories.status_code == 422
    assert duplicate.status_code == 409
    assert len(task_history.json()["data"]) == len(data["tasks"])
    saved = session.query(WorkflowRun).filter(WorkflowRun.id == data["id"]).one()
    assert saved.initiated_by == user.id


def test_workflow_details_return_ordered_attempts_and_generated_case_evidence(db):
    session, user, project = db
    now = datetime.utcnow()
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="partially_completed",
        input_data={},
        created_at=now - timedelta(minutes=3),
        started_at=now - timedelta(minutes=2),
        completed_at=now,
        updated_at=now,
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    generation_task = _task_by_type_for_test(tasks, "test_generation")
    generation_task.status = "partial"
    generation_task.attempt_count = 2
    generation_task.output_data = {
        "status": "partial",
        "structured_data": {
            "test_cases": [
                {
                    "id": 41,
                    "title": "Reject an invalid sign-in",
                    "description": "An invalid password is rejected.",
                    "category": "negative",
                    "priority": "high",
                    "severity": "medium",
                    "preconditions": "A registered account exists.",
                    "steps": [
                        {
                            "action": "Submit an invalid password.",
                            "expected_result": "The sign-in is rejected.",
                        }
                    ],
                    "expected_result": "No authenticated session is created.",
                    "requirements": [
                        {
                            "id": 5,
                            "requirement_key": "AUTH-01",
                            "description": "Users must authenticate before access.",
                        }
                    ],
                    "evidence": [
                        {
                            "document_id": 7,
                            "document_name": "auth-requirements.pdf",
                            "source_type": "requirements",
                            "chunk_id": 12,
                            "source_metadata": {"source_location": {"page_number": 2}},
                            "excerpt": "A valid account credential is required.",
                        }
                    ],
                }
            ]
        },
    }
    session.add_all(
        [
            WorkflowTaskAttempt(
                workflow_task_id=generation_task.id,
                attempt_number=2,
                status="partial",
                started_at=now - timedelta(seconds=20),
                completed_at=now,
                created_at=now,
            ),
            WorkflowTaskAttempt(
                workflow_task_id=generation_task.id,
                attempt_number=1,
                status="retrying",
                started_at=now - timedelta(minutes=1),
                completed_at=now - timedelta(seconds=30),
                created_at=now - timedelta(minutes=1),
            ),
        ]
    )
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get(
            f"/projects/{project.id}/workflows/{workflow.id}"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "partially_completed"
    assert data["created_at"] and data["started_at"]
    assert data["completed_at"] and data["updated_at"]
    assert [task["id"] for task in data["tasks"]] == sorted(
        task["id"] for task in data["tasks"]
    )
    generation = next(
        task for task in data["tasks"] if task["task_type"] == "test_generation"
    )
    assert [attempt["attempt_number"] for attempt in generation["attempts"]] == [1, 2]
    case = generation["output_data"]["structured_data"]["test_cases"][0]
    assert case["severity"] == "medium"
    assert case["requirements"][0]["requirement_key"] == "AUTH-01"
    assert case["evidence"][0]["document_name"] == "auth-requirements.pdf"
    assert case["evidence"][0]["excerpt"] == "A valid account credential is required."


def test_workflow_creation_rolls_back_run_when_task_creation_fails(db, monkeypatch):
    session, user, project = db

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(
        WorkflowService,
        "create_tasks",
        staticmethod(lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError())),
    )
    try:
        response = TestClient(app).post(
            f"/projects/{project.id}/workflows",
            json={"workflow_type": "test_generation"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert session.query(WorkflowRun).filter_by(project_id=project.id).count() == 0


def test_workflow_scheduling_failure_is_persisted_as_resumable(db, monkeypatch):
    session, user, project = db

    def override_db():
        yield session

    def fail_schedule(*_args, **_kwargs):
        raise RuntimeError("scheduler unavailable")

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(BackgroundTasks, "add_task", fail_schedule)
    try:
        response = TestClient(app).post(
            f"/projects/{project.id}/workflows",
            json={"workflow_type": "test_generation"},
        )
    finally:
        app.dependency_overrides.clear()

    workflow = session.query(WorkflowRun).filter_by(project_id=project.id).one()
    assert response.status_code == 503
    assert workflow.status == "failed"
    assert len(workflow.tasks) == len(
        Orchestrator.workflow_template("test_generation")
    )
    assert "could not be scheduled" in workflow.error_summary


def test_workflow_api_returns_not_found_for_other_users_project(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="partially_completed",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    other_user = User(
        name="Other",
        email="other@test.local",
        password_hash="test",
    )
    session.add(other_user)
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        history = client.get(f"/projects/{project.id}/workflows")
        details = client.get(
            f"/projects/{project.id}/workflows/{workflow.id}"
        )
        tasks = client.get(
            f"/projects/{project.id}/workflows/{workflow.id}/tasks"
        )
        resume = client.post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
        start = client.post(
            f"/projects/{project.id}/workflows",
            json={"workflow_type": "bug_analysis"},
        )
    finally:
        app.dependency_overrides.clear()

    assert [
        history.status_code,
        details.status_code,
        tasks.status_code,
        resume.status_code,
        start.status_code,
    ] == [404, 404, 404, 404, 404]
    assert session.query(WorkflowRun).count() == 1


def test_task_history_and_resume_are_project_owner_scoped(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="partially_completed",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    other_user = User(
        name="Other",
        email="other@test.local",
        password_hash="test",
    )
    session.add(other_user)
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: other_user
    app.dependency_overrides[get_db] = override_db
    scheduled = []
    monkeypatch.setattr(
        "app.api.workflows.execute_workflow_background",
        lambda workflow_id: scheduled.append(workflow_id),
    )
    try:
        client = TestClient(app)
        task_history = client.get(
            f"/projects/{project.id}/workflows/{workflow.id}/tasks"
        )
        resume = client.post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
    finally:
        app.dependency_overrides.clear()

    assert task_history.status_code == 404
    assert resume.status_code == 404
    assert workflow.status == "partially_completed"
    assert scheduled == []


def test_api_start_runs_controlled_workflow_to_persisted_terminal_result(
    db,
    monkeypatch,
):
    session, user, project = db
    session_factory = sessionmaker(bind=session.get_bind())
    monkeypatch.setattr(
        workflow_service,
        "SessionLocal",
        lambda: session_factory(),
    )
    handoffs = []

    class FakeOrchestrator:
        def route(self, context):
            handoffs.append(context.task)
            if context.task == "requirements_analysis":
                return AgentResult(
                    "requirements_analysis_agent",
                    "success",
                    data={
                        "requirements": [
                            {"id": "REQ-1", "description": "Users can sign in."}
                        ]
                    },
                    evidence=[{"document_id": 1, "chunk_id": 2}],
                )
            if context.task == "test_generation":
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={
                        "generated_count": 1,
                        "test_cases": [{"id": 77, "title": "Sign in"}],
                    },
                )
            if context.task == "review":
                return AgentResult(
                    "review_agent",
                    "success",
                    data={
                        "recommendation": "human_review_required",
                        "findings": [],
                    },
                )
            raise AssertionError(f"Unexpected agent route: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    validation_calls = []

    def validate(*_args, **kwargs):
        validation_calls.append(kwargs["test_case_ids"])
        return {
            "valid": True,
            "findings": [],
            "validated_case_ids": kwargs["test_case_ids"],
        }

    monkeypatch.setattr(WorkflowValidationService, "validate", validate)

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.post(
            f"/projects/{project.id}/workflows",
            json={
                "workflow_type": "test_generation",
                "requirements_prompt": "Check the documented sign-in flow.",
            },
        )
        workflow_id = response.json()["data"]["id"]
        details = client.get(f"/projects/{project.id}/workflows/{workflow_id}")
        task_history = client.get(
            f"/projects/{project.id}/workflows/{workflow_id}/tasks"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert details.status_code == 200
    assert task_history.status_code == 200
    session.expire_all()
    workflow = session.query(WorkflowRun).filter_by(project_id=project.id).one()
    assert handoffs == ["requirements_analysis", "test_generation", "review"]
    assert validation_calls == [[77]]
    assert workflow.status == "completed"
    assert workflow.final_output["results"]["test_generation"]["test_cases"][0]["id"] == 77
    assert details.json()["data"]["status"] == "completed"
    assert details.json()["data"]["final_output"]["results"]["test_generation"][
        "test_cases"
    ][0]["title"] == "Sign in"
    generation_history = next(
        item
        for item in task_history.json()["data"]
        if item["task_type"] == "test_generation"
    )
    assert generation_history["status"] == "completed"
    assert generation_history["attempts"][0]["status"] == "completed"
    assert generation_history["output_data"]["structured_data"]["test_cases"][0][
        "id"
    ] == 77
    assert workflow.final_output["results"]["test_generation"]["review"]["review_status"] == (
        "reviewed_pending_human_approval"
    )
    assert all(task.status == "completed" for task in workflow.tasks)
    assert all(task.attempts for task in workflow.tasks)


def test_resume_after_reviewer_rejection_generates_new_cases_with_feedback(
    db,
    monkeypatch,
):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="partially_completed",
        input_data={
            "requirements_prompt": "Generate sign-in tests.",
            "generation_feedback": ["Reviewer: Cover recovery after lockout."],
        },
        generation_attempt_count=1,
        final_output={"workflow_context": {}, "results": {}},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    requirements = _task_by_type_for_test(tasks, "requirements_analysis")
    generation = _task_by_type_for_test(tasks, "test_generation")
    validation = _task_by_type_for_test(tasks, "deterministic_validation")
    review = _task_by_type_for_test(tasks, "review")
    requirements.status = "completed"
    requirements.attempt_count = 1
    requirements.output_data = {
        "status": "completed",
        "structured_data": {"requirements": []},
        "evidence_references": [],
    }
    generation.status = "failed"
    generation.attempt_count = 1
    generation.output_data = {
        "agent_name": "test_generation_agent",
        "status": "completed",
        "structured_data": {"test_cases": [{"id": 101, "title": "Old case"}]},
        "evidence_references": [],
    }
    validation.status = "completed"
    validation.output_data = {"valid": True, "findings": []}
    review.status = "failed"
    review.attempt_count = 1
    review.output_data = {
        "workflow_approval": "needs_revision",
        "actionable_feedback": ["Cover recovery after lockout."],
        "findings": [{"message": "Cover recovery after lockout."}],
    }
    session.add(
        WorkflowTaskAttempt(
            workflow_task_id=requirements.id,
            attempt_number=1,
            status="completed",
            started_at=datetime.utcnow(),
        )
    )
    session.add(
        WorkflowTaskAttempt(
            workflow_task_id=generation.id,
            attempt_number=1,
            status="completed",
            output_data=generation.output_data,
            started_at=datetime.utcnow(),
        )
    )
    session.add(
        WorkflowTaskAttempt(
            workflow_task_id=review.id,
            attempt_number=1,
            status="failed",
            output_data=review.output_data,
            started_at=datetime.utcnow(),
        )
    )
    session.add(
        GenerationRunModel(
            project_id=project.id,
            created_by_user_id=user.id,
            requirements_prompt="Generate sign-in tests.",
            requested_categories=["positive"],
            max_cases=1,
            status="completed",
            generated_case_count=1,
            workflow_run_id=workflow.id,
            workflow_attempt_number=1,
        )
    )
    session.commit()
    prompts = []

    class FakeOrchestrator:
        def route(self, context):
            if context.task == "test_generation":
                prompts.append(context.inputs["request"].requirements_prompt)
                return AgentResult(
                    "test_generation_agent",
                    "success",
                    data={"test_cases": [{"id": 202, "title": "New recovery case"}]},
                )
            if context.task == "review":
                return AgentResult(
                    "review_agent",
                    "success",
                    data={"recommendation": "human_review_required", "findings": []},
                )
            raise AssertionError(f"Unexpected agent route: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    monkeypatch.setattr(
        WorkflowValidationService,
        "validate",
        lambda *_args, **kwargs: {
            "valid": True,
            "findings": [],
            "validated_case_ids": kwargs["test_case_ids"],
        },
    )
    session_factory = sessionmaker(bind=session.get_bind())
    monkeypatch.setattr(
        workflow_service,
        "SessionLocal",
        lambda: session_factory(),
    )

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
    finally:
        app.dependency_overrides.clear()

    session.expire_all()
    workflow = session.query(WorkflowRun).filter_by(id=workflow.id).one()
    assert response.status_code == 202
    assert workflow.status == "completed"
    assert workflow.generation_attempt_count == 2
    assert len(prompts) == 1
    assert "Cover recovery after lockout" in prompts[0]
    assert workflow.final_output["results"]["test_generation"]["test_cases"][0]["id"] == 202


def test_resume_runs_unfinished_review_without_regenerating_or_revalidating(
    db,
    monkeypatch,
):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="partially_completed",
        input_data={"requirements_prompt": "Generate supported tests."},
        generation_attempt_count=1,
        final_output={"workflow_context": {}, "results": {}},
    )
    session.add(workflow)
    session.flush()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    requirements = _task_by_type_for_test(tasks, "requirements_analysis")
    generation = _task_by_type_for_test(tasks, "test_generation")
    validation = _task_by_type_for_test(tasks, "deterministic_validation")
    review = _task_by_type_for_test(tasks, "review")
    requirements.status = "completed"
    requirements.attempt_count = 1
    requirements.output_data = {
        "status": "completed",
        "structured_data": {"requirements": []},
    }
    generation_output = {
        "agent_name": "test_generation_agent",
        "status": "completed",
        "structured_data": {
            "generated_count": 1,
            "test_cases": [{"id": 503, "title": "Persisted case"}],
        },
        "evidence_references": [],
        "execution_metadata": {"generation_attempt_number": 1},
    }
    generation.status = "failed"
    generation.attempt_count = 2
    generation.output_data = generation_output
    generation.error_details = {
        "code": "WORKFLOW_GENERATION_FAILED",
        "message": "A downstream stage previously failed.",
    }
    validation.status = "completed"
    validation.attempt_count = 1
    validation.output_data = {
        "status": "completed",
        "valid": True,
        "findings": [],
        "validated_case_ids": [503],
    }
    review.status = "skipped"
    review.attempt_count = 1
    review.output_data = {
        "status": "skipped",
        "reason": "This stage is coordinated with test generation.",
    }
    session.add_all(
        [
            WorkflowTaskAttempt(
                workflow_task_id=requirements.id,
                attempt_number=1,
                status="completed",
                output_data=requirements.output_data,
                started_at=datetime.utcnow(),
            ),
            WorkflowTaskAttempt(
                workflow_task_id=generation.id,
                attempt_number=2,
                status="completed",
                output_data=generation_output,
                started_at=datetime.utcnow(),
            ),
            WorkflowTaskAttempt(
                workflow_task_id=validation.id,
                attempt_number=1,
                status="completed",
                output_data=validation.output_data,
                started_at=datetime.utcnow(),
            ),
            WorkflowTaskAttempt(
                workflow_task_id=review.id,
                attempt_number=1,
                status="skipped",
                output_data=review.output_data,
                started_at=datetime.utcnow(),
            ),
            GenerationRunModel(
                project_id=project.id,
                created_by_user_id=user.id,
                requirements_prompt="Generate supported tests.",
                requested_categories=["positive"],
                max_cases=1,
                status="completed",
                generated_case_count=1,
                workflow_run_id=workflow.id,
                workflow_attempt_number=1,
            ),
        ]
    )
    session.commit()
    calls = []

    class FakeOrchestrator:
        def route(self, context):
            calls.append(context.task)
            if context.task == "review":
                assert context.inputs["test_case_id"] == 503
                return AgentResult(
                    "review_agent",
                    "success",
                    data={
                        "recommendation": "human_review_required",
                        "findings": [],
                    },
                )
            raise AssertionError(f"Unexpected agent rerun: {context.task}")

    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        lambda _db: FakeOrchestrator(),
    )
    monkeypatch.setattr(
        WorkflowValidationService,
        "validate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Completed validation must not be rerun.")
        ),
    )
    session_factory = sessionmaker(bind=session.get_bind())
    monkeypatch.setattr(workflow_service, "SessionLocal", session_factory)

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
    finally:
        app.dependency_overrides.clear()

    session.expire_all()
    workflow = session.query(WorkflowRun).filter_by(id=workflow.id).one()
    generation = _task_by_type_for_test(workflow.tasks, "test_generation")
    validation = _task_by_type_for_test(workflow.tasks, "deterministic_validation")
    review = _task_by_type_for_test(workflow.tasks, "review")
    assert response.status_code == 202
    assert calls == ["review"]
    assert generation.status == "completed"
    assert generation.attempt_count == 2
    assert validation.status == "completed"
    assert validation.attempt_count == 1
    assert review.status == "completed"
    assert review.attempt_count == 2
    assert workflow.generation_attempt_count == 1
    assert workflow.status == "completed"
    response_generation = next(
        item
        for item in response.json()["data"]["tasks"]
        if item["task_type"] == "test_generation"
    )
    assert response.json()["data"]["generation_attempt_count"] == 1
    assert response_generation["attempts"][0]["task_attempt_number"] == 2
    assert response_generation["attempts"][0]["generation_attempt_number"] == 1


def test_stale_workflow_is_marked_interrupted_for_safe_resume(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={},
        updated_at=datetime.utcnow() - timedelta(minutes=20),
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    tasks[0].status = "running"
    session.commit()

    assert WorkflowService.mark_interrupted(workflow)
    assert workflow.status == "partially_completed"
    assert tasks[0].status == "failed"
    assert tasks[0].error_details["message"]


def test_stale_pending_workflow_is_explicitly_failed_and_recoverable(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="pending",
        input_data={},
        updated_at=datetime.utcnow() - timedelta(minutes=20),
    )
    session.add(workflow)
    session.flush()
    WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    session.commit()

    assert WorkflowService.mark_interrupted(workflow)
    assert workflow.status == "failed"
    assert "Resume is available" in workflow.error_summary


def test_stale_pending_workflow_can_be_reconciled_and_resumed_via_api(
    db,
    monkeypatch,
):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="pending",
        input_data={},
        updated_at=datetime.utcnow() - timedelta(minutes=20),
    )
    session.add(workflow)
    session.flush()
    WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    session.commit()

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    scheduled = []
    monkeypatch.setattr(
        "app.api.workflows.execute_workflow_background",
        lambda workflow_id: scheduled.append(workflow_id),
    )
    try:
        client = TestClient(app)
        history = client.get(f"/projects/{project.id}/workflows")
        resume = client.post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
    finally:
        app.dependency_overrides.clear()

    assert history.status_code == 200
    assert workflow.status == "pending"
    assert resume.status_code == 202
    assert scheduled == [workflow.id]


def test_resume_endpoint_only_requeues_incomplete_tasks(db, monkeypatch):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="partially_completed",
        input_data={"requirements_prompt": "Generate sign-in tests."},
    )
    session.add(workflow)
    session.commit()
    tasks = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )
    tasks[0].status = "completed"
    tasks[1].status = "failed"
    session.commit()
    started = []

    def override_db():
        yield session

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(
        "app.api.workflows.execute_workflow_background",
        lambda workflow_id: started.append(workflow_id),
    )
    try:
        client = TestClient(app)
        response = client.post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
        duplicate = client.post(
            f"/projects/{project.id}/workflows/{workflow.id}/resume"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert duplicate.status_code == 409
    assert workflow.status == "pending"
    assert tasks[0].status == "completed"
    assert tasks[1].status == "pending"
    assert started == [workflow.id]


def test_generation_resume_reuses_persisted_workflow_attempt(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="running",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    generation_run = GenerationRunModel(
        project_id=project.id,
        created_by_user_id=user.id,
        requirements_prompt="Generate sign-in test coverage.",
        requested_categories=["positive"],
        max_cases=1,
        status="completed",
        generated_case_count=1,
        workflow_run_id=workflow.id,
        workflow_attempt_number=1,
    )
    session.add(generation_run)
    session.flush()
    document = Document(
        filename="requirements.md",
        content_type="text/plain",
        storage_path="unused",
        project_id=project.id,
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content="Users can sign in.",
    )
    session.add(chunk)
    session.flush()
    case = CaseModel(
        project_id=project.id,
        created_by_user_id=user.id,
        generation_run_id=generation_run.id,
        title="Sign in",
        description="Verify sign in.",
        category="positive",
        priority="high",
        steps=[{"action": "Submit credentials", "expected_result": "Sign in succeeds"}],
        expected_result="The user is signed in.",
        review_status="draft",
    )
    session.add(case)
    session.flush()
    session.add(
        CaseEvidenceModel(
            test_case_id=case.id,
            document_id=document.id,
            chunk_id=chunk.id,
        )
    )
    session.commit()

    service = GenerationService.__new__(GenerationService)
    service.db = session
    reused = service.generate(
        user.id,
        project.id,
        GenerationRequest(
            requirements_prompt="Generate sign-in test coverage.",
            categories=["positive"],
            max_cases=1,
        ),
        workflow_run_id=workflow.id,
        workflow_attempt_number=1,
        reuse_existing_workflow_attempt=True,
    )

    assert [item["id"] for item in reused] == [case.id]
    assert reused[0]["evidence"][0]["chunk_id"] == chunk.id
    assert (
        session.query(GenerationRunModel)
        .filter_by(workflow_run_id=workflow.id, workflow_attempt_number=1)
        .count()
        == 1
    )


def test_attempt_and_generation_idempotency_keys_are_unique_and_validated(db):
    session, user, project = db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="test_generation",
        status="pending",
        input_data={},
    )
    session.add(workflow)
    session.flush()
    task = WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("test_generation"),
    )[0]
    attempt = WorkflowTaskAttempt(
        workflow_task_id=task.id,
        attempt_number=1,
        status="completed",
        started_at=datetime.utcnow(),
    )
    session.add(attempt)
    session.commit()

    session.add(
        WorkflowTaskAttempt(
            workflow_task_id=task.id,
            attempt_number=1,
            status="completed",
            started_at=datetime.utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(
        WorkflowTaskAttempt(
            workflow_task_id=task.id,
            attempt_number=0,
            status="completed",
            started_at=datetime.utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.add(
        WorkflowTaskAttempt(
            workflow_task_id=task.id,
            attempt_number=2,
            status="unknown",
            started_at=datetime.utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    generation_values = {
        "project_id": project.id,
        "created_by_user_id": user.id,
        "requirements_prompt": "Generate sign-in tests.",
        "requested_categories": ["positive"],
        "max_cases": 1,
        "status": "completed",
        "generated_case_count": 0,
        "workflow_run_id": workflow.id,
        "workflow_attempt_number": 1,
    }
    session.add(GenerationRunModel(**generation_values))
    session.commit()
    session.add(GenerationRunModel(**generation_values))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def _task_by_type_for_test(tasks, task_type):
    return next(task for task in tasks if task.task_type == task_type)
