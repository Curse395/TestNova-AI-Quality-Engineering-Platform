import logging
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session, sessionmaker

from app.agents.bug_analysis_agent import BugAnalysisAgent
from app.agents.change_risk_agent import ChangeRiskAgent
from app.agents.contracts import (
    AgentContext,
    AgentInput,
    AgentOutput,
    AgentResult,
    WorkflowContext,
)
from app.agents.orchestrator import Orchestrator
from app.agents.quality_insight_agent import QualityInsightAgent
from app.agents.requirements_agent import RequirementsAnalysisAgent
from app.agents.review_agent import ReviewAgent
from app.agents.test_analysis_agent import TestAnalysisAgent
from app.agents.test_generation_agent import TestGenerationAgent
from app.core.config import settings
from app.database.connection import SessionLocal
from app.models.workflow_run import WorkflowRun
from app.models.workflow_task import WorkflowTask
from app.models.workflow_task_attempt import WorkflowTaskAttempt
from app.models.test_case_generation_run import TestCaseGenerationRun
from app.schemas.test_case_schema import TestCaseGenerationRequest
from app.services.workflow_validation_service import WorkflowValidationService

logger = logging.getLogger(__name__)

MAX_REGENERATIONS = 2
MAX_GENERATION_ATTEMPTS = MAX_REGENERATIONS + 1
INTERRUPTED_AFTER = timedelta(minutes=10)
SUCCESSFUL_TASK_STATUSES = {"completed"}
TERMINAL_TASK_STATUSES = {"completed", "partial", "skipped", "failed"}
_ACTIVE_WORKFLOW_IDS: set[int] = set()
_ACTIVE_WORKFLOW_LOCK = threading.Lock()
_AGENT_TASK_SEMAPHORE = threading.BoundedSemaphore(
    settings.WORKFLOW_MAX_CONCURRENT_TASKS
)

TASK_AGENT_NAMES = {
    "requirements_analysis": "requirements_analysis_agent",
    "bug_analysis": "bug_analysis_agent",
    "test_generation": "test_generation_agent",
    "deterministic_validation": "workflow_validation_service",
    "review": "review_agent",
    "change_risk_analysis": "change_risk_agent",
    "quality_insights": "quality_insight_agent",
    "test_analysis": "test_analysis_agent",
    "aggregation": "orchestrator",
}


def _jsonable_agent_result(result: AgentResult) -> dict[str, Any]:
    status = {
        "success": "completed",
        "partial": "partial",
        "failed": "failed",
        "skipped": "skipped",
    }[result.status]
    return AgentOutput(
        agent_name=result.agent_name,
        status=status,
        structured_data=result.data,
        evidence_references=result.evidence,
        findings=result.data.get("findings", []),
        warnings=result.data.get("warnings", []),
        errors=[result.error] if result.error else [],
        execution_metadata=result.data.get("execution_metadata", {}),
    ).model_dump()


def _start_attempt(db: Session, task: WorkflowTask) -> WorkflowTaskAttempt:
    now = datetime.utcnow()
    claimed = db.execute(
        update(WorkflowTask)
        .where(
            WorkflowTask.id == task.id,
            or_(
                WorkflowTask.status.in_(("pending", "retrying", "failed")),
                and_(
                    WorkflowTask.task_type.in_(
                        ("test_generation", "deterministic_validation", "review")
                    ),
                    WorkflowTask.status == "completed",
                ),
            ),
        )
        .values(
            attempt_count=WorkflowTask.attempt_count + 1,
            status="running",
            started_at=now,
            completed_at=None,
            updated_at=now,
        )
    ).rowcount
    if not claimed:
        db.rollback()
        raise RuntimeError(f"Workflow task {task.id} is already running.")
    db.refresh(task)
    workflow = db.query(WorkflowRun).filter(
        WorkflowRun.id == task.workflow_run_id
    ).first()
    attempt = WorkflowTaskAttempt(
        workflow_task_id=task.id,
        attempt_number=task.attempt_count,
        status="running",
        started_at=now,
        created_at=now,
    )
    db.add(attempt)
    if workflow is not None:
        workflow.updated_at = now
    db.commit()
    db.refresh(attempt)
    return attempt


def _finish_attempt(
    db: Session,
    task: WorkflowTask,
    attempt: WorkflowTaskAttempt,
    status: str,
    output: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    now = datetime.utcnow()
    workflow = db.query(WorkflowRun).filter(
        WorkflowRun.id == task.workflow_run_id
    ).first()
    attempt.status = status
    attempt.output_data = output
    attempt.error_details = error
    attempt.completed_at = now
    task.status = (
        status
        if status in {"completed", "partial", "skipped", "failed", "retrying"}
        else "failed"
    )
    task.output_data = output
    task.error_details = error
    task.completed_at = now
    task.updated_at = now
    if workflow is not None:
        workflow.updated_at = now
    db.commit()


class WorkflowService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def create_tasks(
        db: Session,
        workflow: WorkflowRun,
        task_types: tuple[str, ...],
    ) -> list[WorkflowTask]:
        tasks = []
        task_ids: dict[str, int] = {}
        for task_type in task_types:
            if task_type == "bug_analysis":
                prerequisites = (
                    ("requirements_analysis",)
                    if "requirements_analysis" in task_ids
                    else ()
                )
            elif task_type == "test_generation":
                prerequisites = tuple(
                    prerequisite
                    for prerequisite in ("requirements_analysis", "bug_analysis")
                    if prerequisite in task_ids
                )
            elif task_type == "deterministic_validation":
                prerequisites = ("test_generation",)
            elif task_type == "review":
                prerequisites = ("deterministic_validation",)
            elif task_type == "quality_insights":
                prerequisites = ("test_analysis",)
            elif task_type == "aggregation":
                prerequisites = tuple(task_ids)
            else:
                prerequisites = ()
            task = WorkflowTask(
                workflow_run_id=workflow.id,
                agent_name=TASK_AGENT_NAMES[task_type],
                task_type=task_type,
                status="pending",
                depends_on_task_ids=[
                    task_ids[prerequisite]
                    for prerequisite in prerequisites
                    if prerequisite in task_ids
                ],
                input_data={},
            )
            db.add(task)
            db.flush()
            tasks.append(task)
            task_ids[task_type] = task.id
        return tasks

    @staticmethod
    def mark_interrupted(workflow: WorkflowRun) -> bool:
        with _ACTIVE_WORKFLOW_LOCK:
            if workflow.id in _ACTIVE_WORKFLOW_IDS:
                return False
        if workflow.status not in {"pending", "running"} or (
            workflow.updated_at is None
            or datetime.utcnow() - workflow.updated_at <= INTERRUPTED_AFTER
        ):
            return False
        was_pending = workflow.status == "pending"
        workflow.status = "failed" if was_pending else "partially_completed"
        workflow.error_summary = (
            "Workflow was accepted but did not start. Resume is available."
            if was_pending
            else "Workflow execution stopped before all task results were persisted. "
            "Resume is available."
        )
        for task in workflow.tasks:
            if task.status == "running":
                for attempt in task.attempts:
                    if attempt.status == "running":
                        attempt.status = "interrupted"
                        attempt.completed_at = datetime.utcnow()
                task.status = "failed"
                task.error_details = {
                    "message": "Workflow process stopped before this task completed."
                }
                task.completed_at = datetime.utcnow()
                task.updated_at = datetime.utcnow()
        workflow.completed_at = datetime.utcnow()
        workflow.updated_at = datetime.utcnow()
        return True


def _register_agents(db: Session) -> Orchestrator:
    orchestrator = Orchestrator()
    orchestrator.register("requirements_analysis", RequirementsAnalysisAgent(db))
    orchestrator.register("bug_analysis", BugAnalysisAgent(db))
    orchestrator.register("test_generation", TestGenerationAgent(db))
    orchestrator.register("review", ReviewAgent(db))
    orchestrator.register("change_risk_analysis", ChangeRiskAgent(db))
    orchestrator.register("quality_insights", QualityInsightAgent(db))
    orchestrator.register("test_analysis", TestAnalysisAgent(db))
    return orchestrator


def _agent_context(
    workflow: WorkflowRun,
    task_type: str,
    shared_context: dict[str, Any],
    task_id: int,
    inputs: dict[str, Any] | None = None,
) -> AgentContext:
    validated_context = WorkflowContext(
        project_id=workflow.project_id,
        user_id=workflow.initiated_by,
        requirements=shared_context.get("requirements", {}),
        bug_analysis=shared_context.get("bug_analysis", {}),
        generated_test_cases=shared_context.get("generated_test_cases", []),
        evaluation_findings=shared_context.get("evaluation_findings", []),
        change_risks=shared_context.get("change_risks", {}),
        test_analysis=shared_context.get("test_analysis", {}),
        quality_insights=shared_context.get("quality_insights", {}),
        evidence_references=shared_context.get("evidence_references", []),
        workflow_metadata=shared_context.get("workflow_metadata", {}),
    ).model_dump(exclude={"project_id", "user_id"})
    validated_context.update(shared_context)
    agent_input = AgentInput(
        workflow_id=workflow.id,
        task_id=task_id,
        project_id=workflow.project_id,
        user_id=workflow.initiated_by,
        task_type=task_type,
        input_data=inputs or {},
        shared_context=validated_context,
        evidence_references=validated_context.get("evidence_references", []),
    )
    return AgentContext(
        user_id=agent_input.user_id,
        project_id=agent_input.project_id,
        task=agent_input.task_type,
        inputs={
            **agent_input.input_data,
            "shared_context": agent_input.shared_context,
            "evidence_references": agent_input.evidence_references,
        },
        metadata={
            "workflow_id": agent_input.workflow_id,
            "task_id": agent_input.task_id,
            "shared_context": agent_input.shared_context,
        },
    )


def _store_result(
    db: Session,
    task: WorkflowTask,
    attempt: WorkflowTaskAttempt,
    result: AgentResult,
) -> dict[str, Any]:
    output = _jsonable_agent_result(result)
    task_status = (
        "skipped"
        if result.status == "skipped"
        else "failed"
        if result.status == "failed"
        else "partial"
        if result.status == "partial"
        else "completed"
    )
    _finish_attempt(
        db,
        task,
        attempt,
        task_status,
        output=output,
        error=result.error,
    )
    return output


def _requirements_prompt(
    workflow: WorkflowRun,
    shared_context: dict[str, Any],
) -> str:
    supplied = workflow.input_data.get("requirements_prompt")
    requirements = shared_context.get("requirements", {})
    statements = []
    if isinstance(supplied, str) and supplied.strip():
        statements.append(f"User focus:\n{supplied.strip()}")
    for field in ("requirements", "acceptance_criteria"):
        for item in requirements.get(field, []):
            if isinstance(item, dict) and isinstance(item.get("description"), str):
                classification = item.get("classification")
                label = (
                    f"{classification.capitalize()} requirement"
                    if field == "requirements" and classification in {"explicit", "inferred"}
                    else "Acceptance criterion"
                )
                statements.append(f"{label}: {item['description'].strip()}")
    request = workflow.input_data.get("request")
    if not statements and isinstance(request, str) and request.strip():
        statements.append(f"User request:\n{request.strip()}")
    bug_data = shared_context.get("bug_analysis", {})
    for bug in bug_data.get("bugs", []):
        if isinstance(bug, dict) and isinstance(bug.get("description"), str):
            statements.append(f"Reported defect: {bug['description'].strip()}")
    evidence = shared_context.get("evidence_references", [])
    sources = evidence[:5] if isinstance(evidence, list) else []
    for source in sources:
        if not isinstance(source, dict):
            continue
        excerpt = str(source.get("content") or source.get("excerpt") or "").strip()
        if excerpt:
            statements.append(
                "Project evidence "
                f"(document {source.get('document_id')}, chunk {source.get('chunk_id')}): "
                f"{excerpt[:600]}"
            )
    combined = "\n\n".join(dict.fromkeys(statements))
    return combined[:10000]


def _task_by_type(tasks: list[WorkflowTask], task_type: str) -> WorkflowTask | None:
    return next((task for task in tasks if task.task_type == task_type), None)


def _generation_run_exists(
    db: Session,
    workflow_id: int,
    generation_attempt_number: int,
) -> bool:
    return (
        db.query(TestCaseGenerationRun.id)
        .filter(
            TestCaseGenerationRun.workflow_run_id == workflow_id,
            TestCaseGenerationRun.workflow_attempt_number
            == generation_attempt_number,
        )
        .first()
        is not None
    )


def _dependency_succeeded(task: WorkflowTask, dependent_type: str) -> bool:
    if dependent_type == "aggregation" and task.status in {
        "completed",
        "partial",
        "skipped",
        "failed",
    }:
        return True
    if task.status in SUCCESSFUL_TASK_STATUSES:
        return True
    if (
        dependent_type == "test_generation"
        and task.task_type == "bug_analysis"
        and task.status == "skipped"
    ):
        output = task.output_data or {}
        if isinstance(output, dict):
            structured = output.get("structured_data", {})
            reason = (
                structured.get("reason", "")
                if isinstance(structured, dict)
                else output.get("reason", "")
            )
        else:
            reason = ""
        return "No relevant bug reports or failed execution records" in reason
    return False


def _record_generation_feedback(
    db: Session,
    workflow: WorkflowRun,
    messages: list[str],
) -> list[str]:
    existing = workflow.input_data.get("generation_feedback", [])
    feedback = [
        item.strip()
        for item in existing
        if isinstance(item, str) and item.strip()
    ] if isinstance(existing, list) else []
    for message in messages:
        if message.strip() and message.strip() not in feedback:
            feedback.append(message.strip())
    workflow.input_data = {
        **workflow.input_data,
        "generation_feedback": feedback,
    }
    workflow.updated_at = datetime.utcnow()
    db.commit()
    return feedback


def _apply_generation_feedback(
    request: TestCaseGenerationRequest,
    base_prompt: str,
    feedback: list[str],
) -> None:
    prompt_parts = [base_prompt]
    if feedback:
        prompt_parts.append(
            "Previously observed deterministic-validation or reviewer feedback "
            "to address:\n" + "\n".join(f"- {item}" for item in feedback)
        )
    request.requirements_prompt = "\n\n".join(prompt_parts)


def _restore_persisted_context(
    tasks: list[WorkflowTask],
    shared_context: dict[str, Any],
    task_results: dict[str, Any],
) -> None:
    context_keys = {
        "requirements_analysis": "requirements",
        "bug_analysis": "bug_analysis",
        "change_risk_analysis": "change_risks",
        "quality_insights": "quality_insights",
        "test_analysis": "test_analysis",
    }
    for task in tasks:
        output = task.output_data
        if not isinstance(output, dict):
            continue
        task_results.setdefault(task.task_type, output)
        structured = output.get("structured_data")
        if task.task_type in context_keys and isinstance(structured, dict):
            shared_context.setdefault(context_keys[task.task_type], structured)
            if task.task_type == "requirements_analysis":
                shared_context.setdefault(
                    "evidence_references",
                    output.get("evidence_references", []),
                )
        if task.task_type == "test_generation":
            cases = (
                structured.get("test_cases", [])
                if isinstance(structured, dict)
                else output.get("test_cases", [])
            )
            if isinstance(cases, list):
                shared_context.setdefault("generated_test_cases", cases)
        if task.task_type == "review":
            review_data = structured if isinstance(structured, dict) else output
            shared_context.setdefault(
                "evaluation_findings",
                review_data.get("findings", []),
            )
            if review_data.get("workflow_approval"):
                shared_context.setdefault(
                    "workflow_approval",
                    review_data["workflow_approval"],
                )


def _execute_generation_review(
    db: Session,
    workflow: WorkflowRun,
    tasks: list[WorkflowTask],
    orchestrator: Orchestrator,
    shared_context: dict[str, Any],
) -> dict[str, Any]:
    generation_task = _task_by_type(tasks, "test_generation")
    validation_task = _task_by_type(tasks, "deterministic_validation")
    review_task = _task_by_type(tasks, "review")
    if generation_task is None:
        return {}

    prompt = _requirements_prompt(workflow, shared_context)
    if len(prompt) < 5:
        error = {
            "code": "REQUIREMENTS_UNAVAILABLE",
            "message": "Test generation requires project evidence or a requirements prompt.",
        }
        attempt = _start_attempt(db, generation_task)
        _finish_attempt(
            db,
            generation_task,
            attempt,
            "failed",
            output={"status": "failed", "errors": [error]},
            error=error,
        )
        return {"status": "failed", "errors": [error]}

    request = TestCaseGenerationRequest(
        requirements_prompt=prompt,
        document_ids=workflow.input_data.get("document_ids"),
        source_types=workflow.input_data.get("source_types"),
        max_cases=workflow.input_data.get("max_cases", 5),
        categories=workflow.input_data.get(
            "categories", ["positive", "negative", "boundary", "edge"]
        ),
        requirements=workflow.input_data.get("requirements", []),
    )
    persisted_feedback = workflow.input_data.get("generation_feedback", [])
    persisted_feedback = (
        [item for item in persisted_feedback if isinstance(item, str) and item.strip()]
        if isinstance(persisted_feedback, list)
        else []
    )
    _apply_generation_feedback(request, prompt, persisted_feedback)
    last_result: dict[str, Any] = {"status": "failed"}
    latest_attempt = (
        db.query(WorkflowTaskAttempt)
        .filter(WorkflowTaskAttempt.workflow_task_id == generation_task.id)
        .order_by(WorkflowTaskAttempt.attempt_number.desc())
        .first()
    )
    if latest_attempt is not None:
        latest_generation_run = (
            db.query(TestCaseGenerationRun.workflow_attempt_number)
            .filter(
                TestCaseGenerationRun.workflow_run_id == workflow.id,
                TestCaseGenerationRun.workflow_attempt_number.is_not(None),
            )
            .order_by(
                TestCaseGenerationRun.workflow_attempt_number.desc()
            )
            .first()
        )
        workflow.generation_attempt_count = max(
            workflow.generation_attempt_count,
            latest_generation_run[0] if latest_generation_run is not None else 0,
        )
        db.commit()

    latest_attempt_output = (
        latest_attempt.output_data
        if latest_attempt is not None
        and isinstance(latest_attempt.output_data, dict)
        else {}
    )
    latest_execution_metadata = latest_attempt_output.get(
        "execution_metadata", {}
    )
    persisted_generation_number = (
        latest_execution_metadata.get("generation_attempt_number")
        if isinstance(latest_execution_metadata, dict)
        else None
    )
    recover_committed_attempt = (
        latest_attempt
        if latest_attempt is not None
        and latest_attempt.status in {"failed", "retrying"}
        and isinstance(persisted_generation_number, int)
        and _generation_run_exists(
            db,
            workflow.id,
            persisted_generation_number,
        )
        else None
    )
    recover_running_attempt = (
        latest_attempt
        if latest_attempt is not None
        and latest_attempt.status in {"running", "interrupted"}
        else None
    )
    validation_output_before_resume = (
        validation_task.output_data
        if validation_task is not None and isinstance(validation_task.output_data, dict)
        else {}
    )
    review_output_before_resume = (
        review_task.output_data
        if review_task is not None and isinstance(review_task.output_data, dict)
        else {}
    )
    validation_needs_work = (
        validation_task is not None
        and validation_task.status in {"pending", "running", "failed", "retrying"}
        and validation_output_before_resume.get("valid") is not False
    )
    review_needs_work = (
        review_task is not None
        and review_task.status
        in {"pending", "running", "failed", "retrying", "skipped"}
        and review_output_before_resume.get("workflow_approval") != "needs_revision"
    )
    can_recover_completed_generation = (
        latest_attempt is not None
        and latest_attempt.status == "completed"
        and generation_task.status == "completed"
        and validation_output_before_resume.get("valid") is not False
        and review_output_before_resume.get("workflow_approval") != "needs_revision"
        and (validation_needs_work or review_needs_work)
    )
    generation_plans: list[tuple[int, WorkflowTaskAttempt | None, bool]] = []
    if recover_running_attempt is not None:
        generation_plans.append(
            (
                persisted_generation_number
                if isinstance(persisted_generation_number, int)
                else workflow.generation_attempt_count,
                recover_running_attempt,
                True,
            )
        )
    elif recover_committed_attempt is not None:
        generation_plans.append(
            (
                persisted_generation_number,
                recover_committed_attempt,
                True,
            )
        )
    elif can_recover_completed_generation:
        generation_number = (
            persisted_generation_number
            if isinstance(persisted_generation_number, int)
            else workflow.generation_attempt_count
        )
        if generation_number > 0:
            generation_plans.append((generation_number, latest_attempt, False))

    next_generation_number = workflow.generation_attempt_count + 1
    generation_plans.extend(
        (number, None, False)
        for number in range(
            next_generation_number,
            MAX_GENERATION_ATTEMPTS + 1,
        )
    )
    for generation_number, existing_attempt, reuse_interrupted_attempt in generation_plans:
        if existing_attempt is None:
            generation_attempt = _start_attempt(db, generation_task)
            workflow.generation_attempt_count = max(
                workflow.generation_attempt_count,
                generation_number,
            )
            db.commit()
        else:
            generation_attempt = existing_attempt
            if reuse_interrupted_attempt:
                now = datetime.utcnow()
                generation_attempt.status = "running"
                generation_attempt.completed_at = None
                generation_task.status = "running"
                generation_task.started_at = now
                generation_task.completed_at = None
                generation_task.updated_at = now
                workflow.updated_at = now
                db.commit()
        validation_attempt = None
        review_attempt = None
        try:
            recovering_completed_generation = (
                can_recover_completed_generation
                and existing_attempt is latest_attempt
            )
            if recovering_completed_generation:
                persisted_generation = generation_task.output_data or {}
                generation_result = AgentResult(
                    agent_name=persisted_generation.get(
                        "agent_name",
                        TASK_AGENT_NAMES["test_generation"],
                    ),
                    status="success",
                    data=persisted_generation.get("structured_data", {}),
                    evidence=persisted_generation.get("evidence_references", []),
                )
            else:
                generation_result = orchestrator.route(
                    _agent_context(
                        workflow,
                        "test_generation",
                        shared_context,
                        generation_task.id,
                        {
                            "request": request,
                            "workflow_run_id": workflow.id,
                            "workflow_attempt_number": generation_number,
                            "reuse_existing_workflow_attempt": reuse_interrupted_attempt,
                        },
                    )
                )
            generated_output = _jsonable_agent_result(generation_result)
            generated_output["execution_metadata"] = {
                **generated_output.get("execution_metadata", {}),
                "generation_attempt_number": generation_number,
            }
            if generation_result.status == "failed":
                committed_result_recovery = False
                if (
                    _generation_run_exists(db, workflow.id, generation_number)
                ):
                    generation_result = orchestrator.route(
                        _agent_context(
                            workflow,
                            "test_generation",
                            shared_context,
                            generation_task.id,
                            {
                                "request": request,
                                "workflow_run_id": workflow.id,
                                "workflow_attempt_number": generation_number,
                                "reuse_existing_workflow_attempt": True,
                            },
                        )
                    )
                    generated_output = _jsonable_agent_result(generation_result)
                    generated_output["execution_metadata"] = {
                        **generated_output.get("execution_metadata", {}),
                        "generation_attempt_number": generation_number,
                    }
                    committed_result_recovery = True
            else:
                committed_result_recovery = False
            if generation_result.status == "failed":
                _finish_attempt(
                    db,
                    generation_task,
                    generation_attempt,
                    "failed"
                    if committed_result_recovery
                    or generation_number >= MAX_GENERATION_ATTEMPTS
                    else "retrying",
                    generated_output,
                    generation_result.error,
                )
                generation_error = generation_result.error or {}
                if (
                    generation_error.get("stage")
                    in {"existing_case_duplicate", "generated_case_duplicate"}
                    and generation_number < MAX_GENERATION_ATTEMPTS
                ):
                    persisted_feedback = _record_generation_feedback(
                        db,
                        workflow,
                        [
                            "Generation duplicate check: "
                            + generation_error.get(
                                "message",
                                "Avoid existing project test cases and provide "
                                "a genuinely distinct supported scenario.",
                            )
                        ],
                    )
                    _apply_generation_feedback(request, prompt, persisted_feedback)
                if (
                    generation_number < MAX_GENERATION_ATTEMPTS
                    and not committed_result_recovery
                ):
                    continue
                last_result = generated_output
                break

            if not recovering_completed_generation:
                _finish_attempt(
                    db,
                    generation_task,
                    generation_attempt,
                    "partial"
                    if generation_result.status == "partial"
                    else "completed",
                    generated_output,
                )
            generated_cases = generation_result.data.get("test_cases", [])
            case_ids = [
                case.get("id")
                for case in generated_cases
                if isinstance(case, dict) and isinstance(case.get("id"), int)
            ]
            if (
                recovering_completed_generation
                and validation_task is not None
                and validation_task.status == "completed"
                and isinstance(validation_task.output_data, dict)
                and validation_task.output_data.get("valid") is True
            ):
                validation_output = validation_task.output_data
            else:
                validation_attempt = (
                    _start_attempt(db, validation_task)
                    if validation_task is not None
                    else None
                )
                validation = WorkflowValidationService(db).validate(
                    user_id=workflow.initiated_by,
                    project_id=workflow.project_id,
                    test_case_ids=case_ids,
                )
                validation_output = {
                    "status": "completed" if validation["valid"] else "failed",
                    "valid": validation["valid"],
                    "findings": validation["findings"],
                    "validated_case_ids": validation["validated_case_ids"],
                }
                if validation_attempt is not None:
                    _finish_attempt(
                        db,
                        validation_task,
                        validation_attempt,
                        "completed" if validation["valid"] else (
                            "retrying"
                            if generation_number < MAX_GENERATION_ATTEMPTS
                            else "failed"
                        ),
                        validation_output,
                    )
            validation = {
                "valid": validation_output.get("valid") is True,
                "findings": validation_output.get("findings", []),
            }
            if not validation["valid"]:
                last_result = {
                    "status": "completed",
                    "test_cases": generated_cases,
                    "validation": validation_output,
                    "review": {},
                }
                if generation_number < MAX_GENERATION_ATTEMPTS:
                    messages = [
                        f"Deterministic validation: {item['message']}"
                        for item in validation["findings"]
                        if isinstance(item, dict) and item.get("message")
                    ]
                    persisted_feedback = _record_generation_feedback(
                        db,
                        workflow,
                        messages,
                    )
                    _apply_generation_feedback(request, prompt, persisted_feedback)
                    continue
                break

            if review_task is not None:
                review_attempt = _start_attempt(db, review_task)
                reviews = []
                review_failed = False
                for case_id in case_ids:
                    review_result = orchestrator.route(
                        _agent_context(
                            workflow,
                            "review",
                            shared_context,
                            review_task.id,
                            {"test_case_id": case_id},
                        )
                    )
                    reviews.append(_jsonable_agent_result(review_result))
                    if review_result.status == "failed":
                        review_failed = True
                requires_revision = review_failed or any(
                    item.get("structured_data", {}).get("recommendation")
                    == "needs_revision"
                    for item in reviews
                )
                review_output = {
                    "reviews": reviews,
                    "review_status": (
                        "failed"
                        if review_failed
                        else "needs_revision"
                        if requires_revision
                        else "reviewed_pending_human_approval"
                    ),
                    "workflow_approval": (
                        "not_ready"
                        if review_failed
                        else "needs_revision"
                        if requires_revision
                        else "ready_for_human_review"
                    ),
                    "requires_human_approval": True,
                    "validation_passed": True,
                    "findings": [
                        finding
                        for item in reviews
                        for finding in item.get("structured_data", {}).get(
                            "findings", []
                        )
                    ],
                    "missing_scenarios": [
                        scenario
                        for item in reviews
                        for scenario in item.get("structured_data", {}).get(
                            "missing_scenarios", []
                        )
                    ],
                    "evidence_quality": [
                        item.get("structured_data", {}).get("evidence_quality", {})
                        for item in reviews
                    ],
                    "coverage_observations": [
                        item.get("structured_data", {}).get(
                            "coverage_observations", {}
                        )
                        for item in reviews
                    ],
                    "actionable_feedback": [
                        feedback
                        for item in reviews
                        for feedback in item.get("structured_data", {}).get(
                            "actionable_regeneration_feedback", []
                        )
                        if isinstance(feedback, str)
                    ],
                }
                if review_failed:
                    review_error = next(
                        (
                            item["errors"][0]
                            for item in reviews
                            if item.get("status") == "failed"
                            and item.get("errors")
                        ),
                        {
                            "code": "REVIEW_FAILED",
                            "message": "One or more test cases could not be reviewed.",
                        },
                    )
                    review_output["errors"] = [
                        item["errors"][0]
                        for item in reviews
                        if item.get("status") == "failed" and item.get("errors")
                    ]
                    _finish_attempt(
                        db,
                        review_task,
                        review_attempt,
                        "failed",
                        review_output,
                        error=(
                            review_error
                            if isinstance(review_error, dict)
                            else {"message": str(review_error)}
                        ),
                    )
                    shared_context["generated_test_cases"] = generated_cases
                    shared_context["evaluation_findings"] = review_output["findings"]
                    shared_context["workflow_approval"] = "not_ready"
                    last_result = {
                        "status": "completed",
                        "test_cases": generated_cases,
                        "validation": validation_output,
                        "review": review_output,
                    }
                    db.commit()
                    break
                if requires_revision:
                    final_review_attempt = (
                        generation_number >= MAX_GENERATION_ATTEMPTS
                    )
                    review_output["review_status"] = (
                        "needs_revision" if final_review_attempt else "retrying"
                    )
                    review_output["workflow_approval"] = "needs_revision"
                    _finish_attempt(
                        db,
                        review_task,
                        review_attempt,
                        "completed" if final_review_attempt else "retrying",
                        review_output,
                    )
                    last_result = {
                        "status": "completed",
                        "test_cases": generated_cases,
                        "validation": validation_output,
                        "review": review_output,
                    }
                    if generation_number < MAX_GENERATION_ATTEMPTS:
                        persisted_feedback = _record_generation_feedback(
                            db,
                            workflow,
                            [
                                f"Reviewer: {item}"
                                for item in review_output["actionable_feedback"]
                            ],
                        )
                        _apply_generation_feedback(request, prompt, persisted_feedback)
                        continue
                    shared_context["generated_test_cases"] = generated_cases
                    shared_context["evaluation_findings"] = review_output["findings"]
                    shared_context["workflow_approval"] = "needs_revision"
                    if validation_task is not None:
                        validation_task.output_data = validation_output
                        validation_task.status = "completed"
                        validation_task.completed_at = datetime.utcnow()
                    db.commit()
                    break
                _finish_attempt(
                    db,
                    review_task,
                    review_attempt,
                    "completed",
                    review_output,
                )
            else:
                review_output = {}

            shared_context["generated_test_cases"] = generated_cases
            shared_context["evaluation_findings"] = (
                review_output.get("findings", []) if review_task is not None else []
            )
            shared_context["workflow_approval"] = (
                review_output.get("workflow_approval", "ready_for_human_review")
                if review_task is not None
                else "ready_for_human_review"
            )
            if validation_task is not None:
                validation_task.output_data = validation_output
                validation_task.status = "completed"
                validation_task.completed_at = datetime.utcnow()
            last_result = {
                "status": "completed",
                "test_cases": generated_cases,
                "validation": validation_output,
                "review": review_output,
            }
            db.commit()
            return last_result
        except Exception:
            generation_is_running = generation_attempt.status == "running"
            failed_stage = (
                "generation"
                if generation_is_running
                else "validation"
                if (
                    validation_attempt is not None
                    and validation_attempt.status == "running"
                )
                or (
                    validation_task is not None
                    and validation_task.status != "completed"
                    and review_attempt is None
                )
                else "review"
            )
            db.rollback()
            logger.exception(
                "Test generation workflow stage failed: workflow_id=%s",
                workflow.id,
            )
            error = {
                "code": f"{failed_stage.upper()}_FAILED",
                "message": (
                    "Test generation failed."
                    if failed_stage == "generation"
                    else "Deterministic validation failed."
                    if failed_stage == "validation"
                    else "Test case review failed."
                ),
            }
            try:
                if failed_stage == "generation":
                    committed_generation = _generation_run_exists(
                        db,
                        workflow.id,
                        generation_number,
                    )
                    generation_error_output = {
                        "status": "failed",
                        "errors": [error],
                        "execution_metadata": {
                            "generation_attempt_number": generation_number,
                        },
                    }
                    _finish_attempt(
                        db,
                        generation_task,
                        generation_attempt,
                        "failed"
                        if committed_generation
                        or generation_number >= MAX_GENERATION_ATTEMPTS
                        else "retrying",
                        output=generation_error_output,
                        error=error,
                    )
                    last_result = {"status": "failed", "errors": [error]}
                    if (
                        generation_number < MAX_GENERATION_ATTEMPTS
                        and not committed_generation
                    ):
                        continue
                    break

                downstream_task = (
                    validation_task
                    if failed_stage == "validation"
                    else review_task
                )
                downstream_attempt = (
                    validation_attempt
                    if failed_stage == "validation"
                    else review_attempt
                )
                if downstream_task is not None:
                    if downstream_attempt is None:
                        downstream_attempt = _start_attempt(db, downstream_task)
                    if downstream_attempt.status == "running":
                        stage_output = {
                            "status": "failed",
                            "errors": [error],
                        }
                        _finish_attempt(
                            db,
                            downstream_task,
                            downstream_attempt,
                            "failed",
                            output=stage_output,
                            error=error,
                        )
                persisted_generation = generation_task.output_data or {}
                structured = persisted_generation.get("structured_data", {})
                generated_cases = (
                    structured.get("test_cases", [])
                    if isinstance(structured, dict)
                    else []
                )
                last_result = {
                    "status": "completed",
                    "test_cases": generated_cases,
                    "validation": (
                        validation_task.output_data
                        if validation_task is not None
                        else {}
                    ),
                    "review": (
                        review_task.output_data if review_task is not None else {}
                    ),
                }
            except Exception:
                db.rollback()
                last_result = {
                    "status": (
                        "failed" if failed_stage == "generation" else "completed"
                    ),
                    "errors": [error],
                }
            if failed_stage != "generation":
                break

    if validation_task is not None and validation_task.status in {"running", "retrying"}:
        validation_task.status = "failed"
        validation_task.completed_at = datetime.utcnow()
    if review_task is not None and review_task.status in {"running", "retrying"}:
        review_task.status = "failed"
        review_task.completed_at = datetime.utcnow()
    if isinstance(last_result.get("validation"), dict) and not last_result[
        "validation"
    ].get("valid"):
        shared_context["workflow_approval"] = "blocked_deterministic_validation"
    elif isinstance(last_result.get("review"), dict):
        shared_context["workflow_approval"] = last_result["review"].get(
            "workflow_approval",
            "needs_revision",
        )
    else:
        shared_context["workflow_approval"] = "not_ready"
    if generation_task.status in {"running", "retrying"}:
        generation_task.status = "failed"
        generation_task.completed_at = datetime.utcnow()
    db.commit()
    return last_result


def _agent_inputs(workflow: WorkflowRun, task_type: str) -> dict[str, Any]:
    if task_type == "requirements_analysis":
        return {
            "query": (
                workflow.input_data.get("requirements_prompt")
                or workflow.input_data.get("request")
                or "Project requirements, specifications, user stories, and acceptance criteria"
            )
        }
    if task_type == "change_risk_analysis":
        return {
            "change_summary": workflow.input_data["change_summary"],
            "change_type": workflow.input_data.get("change_type", "general"),
            "changed_files": workflow.input_data.get("changed_files", []),
            "additional_context": workflow.input_data.get("additional_context", ""),
        }
    return {}


def _run_isolated_agent(
    session_factory: sessionmaker,
    task_context: AgentContext,
    deadline: float,
) -> AgentResult:
    remaining = deadline - monotonic()
    if remaining <= 0 or not _AGENT_TASK_SEMAPHORE.acquire(timeout=max(0, remaining)):
        return AgentResult(
            agent_name=f"{task_context.task}_agent",
            status="failed",
            error={
                "code": "AGENT_TASK_TIMEOUT",
                "message": "Agent task did not start before the configured execution window.",
            },
        )
    try:
        if monotonic() >= deadline:
            return AgentResult(
                agent_name=f"{task_context.task}_agent",
                status="failed",
                error={
                    "code": "AGENT_TASK_TIMEOUT",
                    "message": "Agent task did not start before the configured execution window.",
                },
            )
        db = session_factory()
        try:
            return _register_agents(db).route(deepcopy(task_context))
        finally:
            db.close()
    finally:
        _AGENT_TASK_SEMAPHORE.release()


def _update_context_from_output(
    task_type: str,
    output: dict[str, Any],
    shared_context: dict[str, Any],
) -> None:
    structured = output.get("structured_data")
    if not isinstance(structured, dict):
        return
    context_keys = {
        "requirements_analysis": "requirements",
        "bug_analysis": "bug_analysis",
        "change_risk_analysis": "change_risks",
        "quality_insights": "quality_insights",
        "test_analysis": "test_analysis",
    }
    key = context_keys.get(task_type)
    if key:
        shared_context[key] = structured
    if task_type == "requirements_analysis":
        shared_context["evidence_references"] = output.get(
            "evidence_references", []
        )


def _mark_dependency_blocked(
    db: Session,
    task: WorkflowTask,
    dependencies: list[WorkflowTask],
) -> dict[str, Any]:
    reason = "This task was blocked because one or more prerequisites did not succeed."
    output = {
        "status": "skipped",
        "reason": reason,
        "blocked_by": [
            {"task_type": dependency.task_type, "status": dependency.status}
            for dependency in dependencies
        ],
    }
    attempt = _start_attempt(db, task)
    _finish_attempt(
        db,
        task,
        attempt,
        "skipped",
        output,
        error={"code": "DEPENDENCY_NOT_SATISFIED", "message": reason},
    )
    return output


def _execute_parallel_batch(
    db: Session,
    workflow: WorkflowRun,
    tasks: list[WorkflowTask],
    shared_context: dict[str, Any],
    task_results: dict[str, Any],
    session_factory: sessionmaker,
) -> None:
    prepared: list[
        tuple[WorkflowTask, WorkflowTaskAttempt, AgentContext]
    ] = []
    for task in sorted(tasks, key=lambda item: item.id):
        if (
            task.task_type == "change_risk_analysis"
            and not workflow.input_data.get("change_summary")
        ):
            output = {
                "agent_name": task.agent_name,
                "status": "skipped",
                "structured_data": {
                    "reason": "No change summary was supplied for this workflow."
                },
                "evidence_references": [],
                "errors": [],
            }
            attempt = _start_attempt(db, task)
            _finish_attempt(db, task, attempt, "skipped", output)
            task_results[task.task_type] = output
            continue
        attempt = _start_attempt(db, task)
        task_context = _agent_context(
            workflow,
            task.task_type,
            deepcopy(shared_context),
            task.id,
            _agent_inputs(workflow, task.task_type),
        )
        prepared.append((task, attempt, task_context))

    if not prepared:
        return

    executor = ThreadPoolExecutor(
        max_workers=settings.WORKFLOW_MAX_CONCURRENT_TASKS,
        thread_name_prefix="testnova-agent",
    )
    deadline = monotonic() + settings.WORKFLOW_AGENT_TASK_TIMEOUT_SECONDS
    future_items = {
        executor.submit(_run_isolated_agent, session_factory, context, deadline): (
            task,
            attempt,
        )
        for task, attempt, context in prepared
    }
    done, pending = wait(
        future_items,
        timeout=settings.WORKFLOW_AGENT_TASK_TIMEOUT_SECONDS,
    )
    for future in pending:
        future.cancel()
    executor.shutdown(wait=True, cancel_futures=True)

    result_by_task_id: dict[int, AgentResult] = {}
    timeout_ids = {task.id for future in pending for task, _ in [future_items[future]]}
    for future, (task, _attempt) in future_items.items():
        if task.id in timeout_ids:
            result_by_task_id[task.id] = AgentResult(
                agent_name=task.agent_name,
                status="failed",
                error={
                    "code": "AGENT_TASK_TIMEOUT",
                    "message": (
                        "Agent task exceeded the configured execution window. "
                        "Synchronous work already running was allowed to finish."
                    ),
                },
            )
            continue
        try:
            result = future.result()
            if not isinstance(result, AgentResult):
                raise TypeError("Agent must return an AgentResult.")
            result_by_task_id[task.id] = result
        except Exception:
            logger.exception(
                "Parallel workflow agent failed: workflow_id=%s task_id=%s",
                workflow.id,
                task.id,
            )
            result_by_task_id[task.id] = AgentResult(
                agent_name=task.agent_name,
                status="failed",
                error={
                    "code": "AGENT_EXECUTION_FAILED",
                    "message": "Agent execution failed.",
                },
            )

    for task, attempt, _context in prepared:
        result = result_by_task_id[task.id]
        output = _store_result(db, task, attempt, result)
        task_results[task.task_type] = output
        _update_context_from_output(task.task_type, output, shared_context)
    db.commit()


def _execute_workflow(db: Session, workflow: WorkflowRun) -> None:
    tasks = (
        db.query(WorkflowTask)
        .filter(WorkflowTask.workflow_run_id == workflow.id)
        .order_by(WorkflowTask.id.asc())
        .all()
    )
    saved = workflow.final_output or {}
    shared_context = deepcopy(saved.get("workflow_context") or {})
    shared_context.setdefault(
        "workflow_metadata",
        {"workflow_type": workflow.workflow_type},
    )
    typed_context = WorkflowContext(
        project_id=workflow.project_id,
        user_id=workflow.initiated_by,
        requirements=shared_context.get("requirements", {}),
        bug_analysis=shared_context.get("bug_analysis", {}),
        generated_test_cases=shared_context.get("generated_test_cases", []),
        evaluation_findings=shared_context.get("evaluation_findings", []),
        change_risks=shared_context.get("change_risks", {}),
        test_analysis=shared_context.get("test_analysis", {}),
        quality_insights=shared_context.get("quality_insights", {}),
        evidence_references=shared_context.get("evidence_references", []),
        workflow_metadata=shared_context.get("workflow_metadata", {}),
    ).model_dump(exclude={"project_id", "user_id"})
    shared_context.update(typed_context)
    task_results = dict(saved.get("results") or {})
    _restore_persisted_context(tasks, shared_context, task_results)
    session_factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    coordinated_types = {
        "test_generation",
        "deterministic_validation",
        "review",
        "aggregation",
    }
    task_by_id = {task.id: task for task in tasks}
    while True:
        pending_tasks = [
            task
            for task in tasks
            if task.task_type not in coordinated_types and task.status == "pending"
        ]
        if not pending_tasks:
            break
        ready: list[WorkflowTask] = []
        blocked: list[tuple[WorkflowTask, list[WorkflowTask]]] = []
        for task in pending_tasks:
            dependencies = [
                task_by_id[task_id]
                for task_id in task.depends_on_task_ids or []
                if task_id in task_by_id
            ]
            if all(
                dependency.status in TERMINAL_TASK_STATUSES
                for dependency in dependencies
            ):
                unsuccessful = [
                    dependency
                    for dependency in dependencies
                    if not _dependency_succeeded(dependency, task.task_type)
                ]
                if unsuccessful:
                    blocked.append((task, unsuccessful))
                else:
                    ready.append(task)
        for task, unsuccessful in blocked:
            task_results[task.task_type] = _mark_dependency_blocked(
                db, task, unsuccessful
            )
        if blocked:
            db.commit()
        if ready:
            _execute_parallel_batch(
                db,
                workflow,
                ready,
                shared_context,
                task_results,
                session_factory,
            )
            workflow.final_output = {
                "workflow_context": deepcopy(shared_context),
                "results": dict(task_results),
            }
            workflow.updated_at = datetime.utcnow()
            db.commit()
            continue
        if not blocked:
            break

    generation_task = _task_by_type(tasks, "test_generation")
    if generation_task is not None:
        dependencies = [
            task_by_id[task_id]
            for task_id in generation_task.depends_on_task_ids or []
            if task_id in task_by_id
        ]
        unsuccessful = [
            dependency
            for dependency in dependencies
            if not _dependency_succeeded(dependency, "test_generation")
        ]
        validation_task = _task_by_type(tasks, "deterministic_validation")
        review_task = _task_by_type(tasks, "review")
        stages_pending = any(
            task is not None and task.status in {"pending", "running", "failed"}
            for task in (validation_task, review_task)
        )
        if generation_task.status == "pending" and unsuccessful:
            task_results["test_generation"] = _mark_dependency_blocked(
                db, generation_task, unsuccessful
            )
        elif generation_task.status == "pending" or (
            generation_task.status == "completed" and stages_pending
        ):
            result = _execute_generation_review(
                db,
                workflow,
                tasks,
                _register_agents(db),
                shared_context,
            )
            task_results["test_generation"] = result
            if (
                validation_task is not None
                and isinstance(validation_task.output_data, dict)
            ):
                task_results["deterministic_validation"] = (
                    validation_task.output_data
                )
            if review_task is not None and isinstance(review_task.output_data, dict):
                task_results["review"] = review_task.output_data
        db.commit()

    for task_type in ("deterministic_validation", "review"):
        task = _task_by_type(tasks, task_type)
        if task is None or task.status != "pending":
            continue
        dependencies = [
            task_by_id[task_id]
            for task_id in task.depends_on_task_ids or []
            if task_id in task_by_id
        ]
        unsuccessful = [
            dependency
            for dependency in dependencies
            if not _dependency_succeeded(dependency, task_type)
        ]
        if unsuccessful:
            task_results[task_type] = _mark_dependency_blocked(
                db, task, unsuccessful
            )
        else:
            error = {
                "code": "COORDINATED_STAGE_NOT_EXECUTED",
                "message": (
                    "The coordinated stage did not execute after its prerequisites "
                    "completed. Resume is available."
                ),
            }
            attempt = _start_attempt(db, task)
            output = {"status": "failed", "errors": [error]}
            _finish_attempt(db, task, attempt, "failed", output, error)
            task_results[task_type] = output
    db.commit()

    for task in tasks:
        if task.task_type == "aggregation" or task.status in TERMINAL_TASK_STATUSES:
            continue
        error = {
            "code": "WORKFLOW_TASK_UNRESOLVED",
            "message": "Workflow scheduler could not reach this task.",
        }
        if task.status == "running":
            for attempt in task.attempts:
                if attempt.status == "running":
                    attempt.status = "failed"
                    attempt.error_details = error
                    attempt.completed_at = datetime.utcnow()
            task.status = "failed"
            task.error_details = error
            task.completed_at = datetime.utcnow()
        else:
            attempt = _start_attempt(db, task)
            output = {"status": "failed", "errors": [error]}
            _finish_attempt(db, task, attempt, "failed", output, error)
            task_results[task.task_type] = output
    db.commit()

    aggregation = _task_by_type(tasks, "aggregation")
    if aggregation is not None and aggregation.status == "pending":
        unresolved = [
            task_by_id[task_id]
            for task_id in aggregation.depends_on_task_ids or []
            if task_id in task_by_id
            and task_by_id[task_id].status not in TERMINAL_TASK_STATUSES
        ]
        if not unresolved:
            ordered_results = {
                task.task_type: task_results[task.task_type]
                for task in tasks
                if task.task_type in task_results
            }
            task_output = {
                "status": "completed",
                "results": ordered_results,
                "workflow_context": deepcopy(shared_context),
                "workflow_approval": shared_context.get(
                    "workflow_approval", "not_applicable"
                ),
            }
            attempt = _start_attempt(db, aggregation)
            _finish_attempt(db, aggregation, attempt, "completed", task_output)
            task_results["aggregation"] = task_output
        else:
            error = {
                "code": "AGGREGATION_DEPENDENCY_UNRESOLVED",
                "message": "Aggregation waited for all workflow tasks to finish.",
            }
            attempt = _start_attempt(db, aggregation)
            _finish_attempt(
                db,
                aggregation,
                attempt,
                "failed",
                {"status": "failed", "errors": [error]},
                error,
            )
            task_results["aggregation"] = aggregation.output_data or {}

    statuses = [task.status for task in tasks if task.task_type != "aggregation"]
    failures = sum(
        task.status == "failed"
        or (
            task.status == "skipped"
            and isinstance(task.error_details, dict)
            and task.error_details.get("code") == "DEPENDENCY_NOT_SATISFIED"
        )
        for task in tasks
        if task.task_type != "aggregation"
    )
    partial_outputs = any(
        output.get("status") == "partial"
        for output in task_results.values()
        if isinstance(output, dict)
    ) or any(status == "partial" for status in statuses)
    if failures and failures == len(statuses):
        workflow.status = "failed"
    elif failures or partial_outputs:
        workflow.status = "partially_completed"
    else:
        workflow.status = "completed"
    workflow.final_output = {
        "workflow_context": shared_context,
        "results": {
            task.task_type: task_results[task.task_type]
            for task in tasks
            if task.task_type in task_results
        },
        "workflow_approval": shared_context.get(
            "workflow_approval", "not_applicable"
        ),
    }
    workflow.completed_at = datetime.utcnow()
    workflow.updated_at = datetime.utcnow()
    workflow.error_summary = (
        f"{failures} workflow task(s) failed or were blocked." if failures else None
    )
    db.commit()


def execute_workflow_background(workflow_id: int) -> None:
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        claimed = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.id == workflow_id,
                WorkflowRun.status == "pending",
            )
            .update(
                {
                    WorkflowRun.status: "running",
                    WorkflowRun.started_at: now,
                    WorkflowRun.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if not claimed:
            return
        with _ACTIVE_WORKFLOW_LOCK:
            _ACTIVE_WORKFLOW_IDS.add(workflow_id)
        workflow = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
        if workflow is None:
            logger.error("Workflow disappeared after claim: id=%s", workflow_id)
            return
        _execute_workflow(db, workflow)
    except Exception:
        db.rollback()
        logger.exception("Workflow execution failed: workflow_id=%s", workflow_id)
        workflow = db.query(WorkflowRun).filter(WorkflowRun.id == workflow_id).first()
        if workflow is not None:
            for task in workflow.tasks:
                if task.status == "running":
                    for attempt in task.attempts:
                        if attempt.status == "running":
                            attempt.status = "failed"
                            attempt.error_details = {
                                "message": "Workflow execution stopped unexpectedly."
                            }
                            attempt.completed_at = datetime.utcnow()
                    task.status = "failed"
                    task.error_details = {
                        "message": "Execution stopped unexpectedly; resume is available."
                    }
                    task.completed_at = datetime.utcnow()
            workflow.status = "failed"
            workflow.error_summary = "Workflow execution stopped unexpectedly."
            workflow.completed_at = datetime.utcnow()
            workflow.updated_at = datetime.utcnow()
            db.commit()
    finally:
        with _ACTIVE_WORKFLOW_LOCK:
            _ACTIVE_WORKFLOW_IDS.discard(workflow_id)
        db.close()
