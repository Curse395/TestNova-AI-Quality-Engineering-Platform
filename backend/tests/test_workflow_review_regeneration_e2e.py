import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import test_cases as test_cases_api
from app.api import workflows as workflows_api
from app.agents.contracts import AgentContext, AgentResult
from app.agents.orchestrator import Orchestrator
from app.agents.review_agent import ReviewAgent
from app.agents.test_generation_agent import TestGenerationAgent as GenerationAgent
from app.database.connection import Base
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as CaseEvidenceModel
from app.models.test_case_generation_run import (
    TestCaseGenerationRun as GenerationRunModel,
)
from app.models.project_requirement import ProjectRequirement
from app.models.test_case_requirement import TestCaseRequirement
from app.models.user import User
from app.models.workflow_run import WorkflowRun
from app.models.workflow_task import WorkflowTask
from app.models.workflow_task_attempt import WorkflowTaskAttempt
from app.services import workflow_service
from app.services.llm_services import LLMService
from app.services.test_case_generation_service import (
    TestCaseGenerationService as GenerationService,
)
from app.services.workflow_validation_service import WorkflowValidationService


WORKFLOW_TABLES = [
    User.__table__,
    Organization.__table__,
    Project.__table__,
    WorkflowRun.__table__,
    WorkflowTask.__table__,
    WorkflowTaskAttempt.__table__,
    GenerationRunModel.__table__,
    CaseModel.__table__,
    CaseEvidenceModel.__table__,
    Document.__table__,
    DocumentChunk.__table__,
    ProjectRequirement.__table__,
    TestCaseRequirement.__table__,
]


class StaticAgent:
    def __init__(self, name: str, data: dict):
        self.name = name
        self.data = data

    def run(self, _context: AgentContext) -> AgentResult:
        return AgentResult(self.name, "success", data=self.data)


@pytest.fixture
def workflow_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'workflow-review.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine, tables=WORKFLOW_TABLES)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    user = User(name="Workflow Owner", email="workflow-owner@test.local", password_hash="test")
    session.add(user)
    session.flush()
    organization = Organization(name="Workflow Workspace", owner_id=user.id)
    session.add(organization)
    session.flush()
    project = Project(name="Workflow Project", organitzation_id=organization.id)
    session.add(project)
    session.flush()
    document = Document(
        filename="sign-in-requirements.md",
        content_type="text/markdown",
        storage_path="unused",
        project_id=project.id,
        uploaded_by_user_id=user.id,
        source_type="requirements",
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=0,
        content="Registered users can sign in with valid account credentials.",
    )
    session.add(chunk)
    session.commit()

    try:
        yield session, user, project, document, chunk
    finally:
        session.close()
        engine.dispose()


def _register_full_workflow_agents(db):
    orchestrator = Orchestrator()
    for task, name, data in (
        ("requirements_analysis", "requirements_analysis_agent", {"requirements": []}),
        ("bug_analysis", "bug_analysis_agent", {"bugs": []}),
        ("test_analysis", "test_analysis_agent", {"total_executions": 0}),
        ("quality_insights", "quality_insight_agent", {"insights": []}),
        ("change_risk_analysis", "change_risk_agent", {"risks": []}),
    ):
        orchestrator.register(task, StaticAgent(name, data))
    orchestrator.register("test_generation", GenerationAgent(db))
    orchestrator.register("review", ReviewAgent(db))
    return orchestrator


@pytest.mark.parametrize(
    ("scenario", "expected_generations", "expected_approval"),
    [
        ("corrected", 2, "ready_for_human_review"),
        ("persistent_rejection", 3, "needs_revision"),
        ("semantic_unavailable", 1, "ready_for_human_review"),
        ("semantic_timeout", 1, "ready_for_human_review"),
    ],
)
def test_full_qa_workflow_review_regeneration_cycle(
    workflow_db,
    monkeypatch,
    scenario,
    expected_generations,
    expected_approval,
):
    session, user, project, document, chunk = workflow_db
    workflow = WorkflowRun(
        project_id=project.id,
        initiated_by=user.id,
        workflow_type="full_qa_workflow",
        status="running",
        input_data={
            "requirements_prompt": "Generate test coverage for documented sign-in.",
            "max_cases": 1,
        },
    )
    session.add(workflow)
    session.flush()
    tasks = workflow_service.WorkflowService.create_tasks(
        session,
        workflow,
        Orchestrator.workflow_template("full_qa_workflow"),
    )
    session.commit()

    generation_prompts = []
    validation_calls = []
    semantic_review_calls = []

    monkeypatch.setattr(LLMService, "__init__", lambda self: None)
    monkeypatch.setattr(
        GenerationService,
        "_retrieve_chunks",
        lambda *_args: [
            {
                "chunk_id": chunk.id,
                "document_id": document.id,
                "document_name": document.filename,
                "source_type": "requirements",
                "source_metadata": {},
                "content": chunk.content,
                "similarity": 0.9,
            }
        ],
    )

    def generate_content(_self, *, system_prompt, user_prompt, **_kwargs):
        if "Test Case Generation Agent" in system_prompt:
            generation_prompts.append(user_prompt)
            generation_number = len(generation_prompts)
            category = (
                ["positive", "negative", "boundary"][generation_number - 1]
                if scenario == "persistent_rejection"
                else "positive"
            )
            case = {
                "title": f"Sign-in scenario {generation_number}",
                "description": "Verify a documented registered-user sign-in.",
                "test_type": "security",
                "category": category,
                "priority": "high",
                "preconditions": "A registered account exists.",
                "steps": [
                    {
                        "action": (
                            "Submit an incorrect password for the registered account."
                            if scenario == "persistent_rejection"
                            and generation_number == 2
                            else "Submit an empty password for the registered account."
                            if scenario == "persistent_rejection"
                            and generation_number == 3
                            else "Submit valid account credentials."
                        ),
                        "expected_result": "The account is authenticated.",
                    }
                ],
                "expected_result": (
                    "The registered user signs in successfully."
                    if scenario == "corrected" and generation_number > 1
                    else "The user is redirected to the undocumented admin dashboard."
                ),
                "evidence_chunk_ids": [chunk.id],
            }
            return {"success": True, "answer": json.dumps([case])}

        assert "Test Case Quality Evaluator" in system_prompt
        review_input = json.loads(user_prompt)
        title = review_input["test_case"]["title"]
        semantic_review_calls.append(title)
        if scenario == "semantic_unavailable":
            return {
                "success": False,
                "answer": "",
                "error": "Gemini provider request failed",
            }
        if scenario == "semantic_timeout":
            raise TimeoutError("Gemini provider timed out")

        corrected_case = scenario == "corrected" and title.endswith("2")
        if corrected_case:
            result = {
                "evidence_support": "supported",
                "expected_result_support": "supported",
                "evidence_relevance": "relevant",
                "steps_actionable": "yes",
                "category_appropriate": "yes",
                "test_type_appropriate": "yes",
                "requirement_coverage": "adequate",
                "findings": [],
            }
        else:
            result = {
                "evidence_support": "partially_supported",
                "expected_result_support": "unsupported",
                "evidence_relevance": "relevant",
                "steps_actionable": "yes",
                "category_appropriate": "yes",
                "test_type_appropriate": "yes",
                "requirement_coverage": "partial",
                "findings": [
                    {
                        "severity": "high",
                        "check": "expected_result_support",
                        "message": (
                            "Replace the unsupported dashboard redirect with the "
                            "documented sign-in outcome."
                        ),
                    }
                ],
            }
        return {"success": True, "answer": json.dumps(result)}

    monkeypatch.setattr(LLMService, "generate_content", generate_content)
    monkeypatch.setattr(
        workflow_service,
        "_register_agents",
        _register_full_workflow_agents,
    )

    original_validate = WorkflowValidationService.validate

    def validate_and_record(self, **kwargs):
        result = original_validate(self, **kwargs)
        validation_calls.append((kwargs["test_case_ids"], result))
        return result

    monkeypatch.setattr(
        WorkflowValidationService,
        "validate",
        validate_and_record,
    )

    workflow_service._execute_workflow(session, workflow)

    task_by_type = {task.task_type: task for task in tasks}
    generation_task = task_by_type["test_generation"]
    validation_task = task_by_type["deterministic_validation"]
    review_task = task_by_type["review"]

    assert workflow.status == "completed", [
        (task.task_type, task.status, task.error_details)
        for task in tasks
    ]
    assert workflow.final_output["workflow_approval"] == expected_approval
    assert workflow.generation_attempt_count == expected_generations
    assert generation_task.status == "completed"
    assert len(generation_task.attempts) == expected_generations
    assert validation_task.status == "completed"
    assert len(validation_task.attempts) == expected_generations
    assert len(validation_calls) == expected_generations
    assert all(result["valid"] for _, result in validation_calls)
    assert review_task.status == "completed"
    assert len(review_task.attempts) == expected_generations
    assert len(semantic_review_calls) == expected_generations
    assert len(generation_prompts) == expected_generations
    assert workflow.error_summary is None
    persisted_cases = (
        session.query(CaseModel)
        .filter(CaseModel.project_id == project.id)
        .all()
    )
    assert len(persisted_cases) == expected_generations
    assert all(case.test_type == "security" for case in persisted_cases)
    expected_categories = (
        ["positive", "negative", "boundary"]
        if scenario == "persistent_rejection"
        else ["positive"] * expected_generations
    )
    assert [case.category for case in persisted_cases] == expected_categories
    persisted_evidence = (
        session.query(CaseEvidenceModel)
        .join(CaseModel, CaseModel.id == CaseEvidenceModel.test_case_id)
        .filter(CaseModel.project_id == project.id)
        .all()
    )
    assert len(persisted_evidence) == expected_generations
    assert all(
        link.document_id == document.id and link.chunk_id == chunk.id
        for link in persisted_evidence
    )

    case_history = test_cases_api.list_project_test_cases(
        project_id=project.id,
        current_user=user,
        db=session,
    )
    saved_generated_cases = {
        item["id"]: item for item in case_history["data"]
    }
    assert all(
        saved_generated_cases[case.id]["evidence"][0]["chunk_id"] == chunk.id
        for case in persisted_cases
    )
    final_case = next(
        item
        for item in case_history["data"]
        if item["title"] == f"Sign-in scenario {expected_generations}"
    )
    assert final_case["evidence"] == [
        {
            "document_id": document.id,
            "document_name": document.filename,
            "source_type": "requirements",
            "chunk_id": chunk.id,
            "source_metadata": {},
            "excerpt": chunk.content,
        }
    ]

    workflow_history = workflows_api.get_workflow(
        project_id=project.id,
        workflow_id=workflow.id,
        current_user=user,
        db=session,
    )["data"]
    assert workflow_history["status"] == "completed"
    final_generation = workflow_history["final_output"]["results"][
        "test_generation"
    ]
    assert final_generation["test_cases"][-1]["evidence"][0]["chunk_id"] == (
        chunk.id
    )
    assert final_generation["test_cases"][-1]["evidence"][0]["document_id"] == (
        document.id
    )
    generation_task_history = next(
        task
        for task in workflow_history["tasks"]
        if task["task_type"] == "test_generation"
    )
    final_generation_attempt = max(
        generation_task_history["attempts"],
        key=lambda attempt: attempt["generation_attempt_number"],
    )
    assert final_generation_attempt["output_data"]["structured_data"][
        "test_cases"
    ][0]["evidence"][0]["chunk_id"] == chunk.id
    final_review = workflow_history["final_output"]["results"]["review"]
    reviewed_evidence = final_review["reviews"][0]["evidence_references"]
    assert reviewed_evidence[0]["chunk_id"] == chunk.id
    assert reviewed_evidence[0]["document_id"] == document.id

    if scenario == "corrected":
        assert review_task.output_data["workflow_approval"] == "ready_for_human_review"
        assert "documented sign-in outcome" in generation_prompts[1]
        assert [attempt.status for attempt in review_task.attempts] == [
            "retrying",
            "completed",
        ]
    elif scenario == "persistent_rejection":
        assert review_task.output_data["review_status"] == "needs_revision"
        assert review_task.output_data["workflow_approval"] == "needs_revision"
        assert [attempt.status for attempt in review_task.attempts] == [
            "retrying",
            "retrying",
            "completed",
        ]
        assert workflow.final_output["results"]["review"]["workflow_approval"] == (
            "needs_revision"
        )
        assert "documented sign-in outcome" in generation_prompts[1]
        assert "documented sign-in outcome" in generation_prompts[2]
    else:
        assert review_task.output_data["workflow_approval"] == (
            "ready_for_human_review"
        )
        assert review_task.output_data["reviews"][0]["structured_data"][
            "recommendation"
        ] == "manual_review_required"
        assert review_task.output_data["actionable_feedback"] == []
        assert review_task.output_data["reviews"][0]["structured_data"][
            "checks"
        ]["semantic_evaluation"]["status"] == "evaluation_unavailable"
        assert review_task.output_data["reviews"][0]["structured_data"][
            "recommendation"
        ] == "manual_review_required"


def test_case_history_returns_multiple_verified_sources_only(workflow_db):
    session, user, project, document, chunk = workflow_db
    second_chunk = DocumentChunk(
        document_id=document.id,
        chunk_index=1,
        content="Password reset links expire after one hour.",
        source_metadata={"source_location": {"section": "Password reset"}},
    )
    other_project_document = Document(
        filename="other-project.md",
        content_type="text/markdown",
        storage_path="unused",
        project_id=project.id + 1,
        uploaded_by_user_id=user.id,
    )
    mismatched_document = Document(
        filename="same-project-other-source.md",
        content_type="text/markdown",
        storage_path="unused",
        project_id=project.id,
        uploaded_by_user_id=user.id,
    )
    session.add_all([second_chunk, other_project_document, mismatched_document])
    session.flush()
    other_project_chunk = DocumentChunk(
        document_id=other_project_document.id,
        chunk_index=0,
        content="Unrelated project evidence.",
    )
    mismatched_chunk = DocumentChunk(
        document_id=mismatched_document.id,
        chunk_index=0,
        content="Evidence from a different same-project document.",
    )
    session.add_all([other_project_chunk, mismatched_chunk])
    session.flush()
    test_case = CaseModel(
        project_id=project.id,
        created_by_user_id=user.id,
        title="Verify reset link expiry",
        description="Check the documented password reset expiration.",
        category="positive",
        priority="high",
        steps=[
            {
                "action": "Use a password reset link after one hour.",
                "expected_result": "The expiration rule is applied.",
            }
        ],
        expected_result="The reset link follows its documented expiry.",
    )
    session.add(test_case)
    session.flush()
    session.add_all(
        [
            CaseEvidenceModel(
                test_case_id=test_case.id,
                document_id=document.id,
                chunk_id=chunk.id,
            ),
            CaseEvidenceModel(
                test_case_id=test_case.id,
                document_id=document.id,
                chunk_id=second_chunk.id,
            ),
            CaseEvidenceModel(
                test_case_id=test_case.id,
                document_id=other_project_document.id,
                chunk_id=other_project_chunk.id,
            ),
            CaseEvidenceModel(
                test_case_id=test_case.id,
                document_id=document.id,
                chunk_id=mismatched_chunk.id,
            ),
        ]
    )
    session.commit()

    validation = WorkflowValidationService(session).validate(
        user_id=user.id,
        project_id=project.id,
        test_case_ids=[test_case.id],
    )
    assert validation["valid"] is False
    assert any(item["check"] == "evidence" for item in validation["findings"])

    history = test_cases_api.list_project_test_cases(
        project_id=project.id,
        current_user=user,
        db=session,
    )
    evidence = history["data"][0]["evidence"]
    assert [(item["document_id"], item["chunk_id"]) for item in evidence] == [
        (document.id, chunk.id),
        (document.id, second_chunk.id),
    ]
    assert evidence[1]["source_metadata"]["source_location"]["section"] == (
        "Password reset"
    )
    assert evidence[1]["excerpt"] == second_chunk.content


def test_testing_discipline_is_independent_of_scenario_category(workflow_db):
    session, user, project, _, chunk = workflow_db
    classifications = (
        ("security", "positive"),
        ("security", "negative"),
        ("functional", "positive"),
        ("functional", "negative"),
        ("security", "edge"),
    )
    case_ids = []
    for index, (test_type, category) in enumerate(classifications, start=1):
        case = CaseModel(
            project_id=project.id,
            created_by_user_id=user.id,
            title=f"Classification case {index}",
            description="A classified scenario with verified source evidence.",
            test_type=test_type,
            category=category,
            priority="medium",
            preconditions="A test account is available.",
            steps=[
                {
                    "action": "Run the documented scenario.",
                    "expected_result": "The documented behavior is observed.",
                }
            ],
            expected_result="The documented behavior is observed.",
            review_status="draft",
        )
        session.add(case)
        session.flush()
        session.add(
            CaseEvidenceModel(
                test_case_id=case.id,
                document_id=chunk.document_id,
                chunk_id=chunk.id,
            )
        )
        case_ids.append(case.id)

    session.commit()
    result = WorkflowValidationService(session).validate(
        user_id=user.id,
        project_id=project.id,
        test_case_ids=case_ids,
    )

    assert result["valid"] is True, result["findings"]
    assert result["validated_case_ids"] == case_ids


@pytest.mark.parametrize(
    ("semantic_overrides", "expected_recommendation", "expected_check"),
    [
        ({}, "human_review_required", None),
        (
            {"expected_result_support": "contradictory"},
            "needs_revision",
            "semantic_contradiction",
        ),
        (
            {"evidence_relevance": "irrelevant"},
            "needs_revision",
            "evidence_relevance",
        ),
        (
            {"test_type_appropriate": "no"},
            "needs_revision",
            "test_type",
        ),
    ],
)
def test_semantic_review_separates_support_relevance_and_classification(
    workflow_db,
    monkeypatch,
    semantic_overrides,
    expected_recommendation,
    expected_check,
):
    session, user, project, document, chunk = workflow_db
    generation_run = GenerationRunModel(
        project_id=project.id,
        created_by_user_id=user.id,
        requirements_prompt="Registered users can sign in with valid credentials.",
        requested_categories=["positive"],
        max_cases=1,
    )
    session.add(generation_run)
    session.flush()
    case = CaseModel(
        project_id=project.id,
        created_by_user_id=user.id,
        generation_run_id=generation_run.id,
        title="Security sign-in scenario",
        description="Check the sign-in flow using the documented requirements.",
        test_type="security",
        category="positive",
        priority="high",
        preconditions="A registered account exists.",
        steps=[
            {
                "action": "Submit valid account credentials.",
                "expected_result": "The account is authenticated.",
            }
        ],
        expected_result="The registered user signs in successfully.",
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

    response = {
        "evidence_support": "supported",
        "expected_result_support": "supported",
        "evidence_relevance": "relevant",
        "steps_actionable": "yes",
        "category_appropriate": "yes",
        "test_type_appropriate": "yes",
        "requirement_coverage": "adequate",
        "findings": [],
        **semantic_overrides,
    }
    prompts = []

    monkeypatch.setattr(LLMService, "__init__", lambda self: None)

    def generate_content(_self, *, system_prompt, user_prompt, **_kwargs):
        assert "Test Case Quality Evaluator" in system_prompt
        prompts.append(json.loads(user_prompt))
        return {"success": True, "answer": json.dumps(response)}

    monkeypatch.setattr(LLMService, "generate_content", generate_content)
    review = ReviewAgent(session).run(
        AgentContext(
            user_id=user.id,
            project_id=project.id,
            task="review",
            inputs={"test_case_id": case.id},
        )
    )

    assert review.status == "success", review.error
    assert review.data["recommendation"] == expected_recommendation
    assert review.data["evidence_quality"]["reference_status"] == "valid_reference"
    assert prompts[0]["test_case"]["test_type"] == "security"
    assert prompts[0]["test_case"]["category"] == "positive"
    if expected_check is not None:
        assert expected_check in {item["check"] for item in review.data["findings"]}


def test_deterministic_validation_rejects_placeholder_expected_results(
    workflow_db,
):
    session, user, project, document, chunk = workflow_db
    case = CaseModel(
        project_id=project.id,
        created_by_user_id=user.id,
        title="Sign-in behavior",
        description="Verify documented sign-in behavior.",
        test_type="functional",
        category="positive",
        priority="medium",
        preconditions="A registered account exists.",
        steps=[
            {
                "action": "Submit valid credentials.",
                "expected_result": "TBD",
            }
        ],
        expected_result="TBD",
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

    result = WorkflowValidationService(session).validate(
        user_id=user.id,
        project_id=project.id,
        test_case_ids=[case.id],
    )

    assert result["valid"] is False
    assert {item["check"] for item in result["findings"]} >= {
        "expected_result",
        "steps",
    }
