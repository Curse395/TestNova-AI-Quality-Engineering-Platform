from datetime import datetime
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import update
from sqlalchemy.orm import Session, selectinload

from app.agents.orchestrator import Orchestrator
from app.core.authorization import get_owned_project
from app.core.dependencies import CurrentUser
from app.core.rate_limit import limit_requests
from app.database.connection import get_db
from app.models.workflow_run import WorkflowRun
from app.models.workflow_task import WorkflowTask
from app.models.workflow_task_attempt import WorkflowTaskAttempt
from app.schemas.workflow_schema import WorkflowStartRequest
from app.services.workflow_service import (
    WorkflowService,
    execute_workflow_background,
)

router = APIRouter(prefix="/projects", tags=["Workflows"])
logger = logging.getLogger(__name__)


def _authorized_workflow(
    db: Session,
    current_user_id: int,
    project_id: int,
    workflow_id: int,
) -> WorkflowRun:
    project = get_owned_project(db, project_id, current_user_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    workflow = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.id == workflow_id,
            WorkflowRun.project_id == project_id,
        )
        .options(
            selectinload(WorkflowRun.tasks).selectinload(WorkflowTask.attempts)
        )
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return workflow


def _attempt_payload(
    task: WorkflowTask,
    attempt: WorkflowTaskAttempt,
) -> dict:
    output = attempt.output_data if isinstance(attempt.output_data, dict) else {}
    metadata = output.get("execution_metadata", {})
    generation_attempt_number = (
        metadata.get("generation_attempt_number")
        if task.task_type == "test_generation" and isinstance(metadata, dict)
        else None
    )
    return {
        "attempt_number": attempt.attempt_number,
        "task_attempt_number": attempt.attempt_number,
        "generation_attempt_number": generation_attempt_number,
        "status": attempt.status,
        "output_data": attempt.output_data,
        "error_details": attempt.error_details,
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
        "created_at": attempt.created_at,
    }


def _workflow_payload(workflow: WorkflowRun) -> dict:
    return {
        "id": workflow.id,
        "project_id": workflow.project_id,
        "workflow_type": workflow.workflow_type,
        "generation_attempt_count": workflow.generation_attempt_count,
        "status": workflow.status,
        "final_output": workflow.final_output,
        "error_summary": workflow.error_summary,
        "can_resume": workflow.status in {"failed", "partially_completed"},
        "resume_reason": (
            None
            if workflow.status in {"failed", "partially_completed"}
            else "Only failed or partially completed workflows can be resumed."
        ),
        "created_at": workflow.created_at,
        "started_at": workflow.started_at,
        "completed_at": workflow.completed_at,
        "updated_at": workflow.updated_at,
        "tasks": [
            {
                "id": task.id,
                "agent_name": task.agent_name,
                "task_type": task.task_type,
                "status": task.status,
                "depends_on_task_ids": task.depends_on_task_ids,
                "output_data": task.output_data,
                "error_details": task.error_details,
                "attempt_count": task.attempt_count,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "input_summary": _task_input_summary(workflow, task),
                "attempts": [
                    _attempt_payload(task, attempt)
                    for attempt in sorted(task.attempts, key=lambda item: item.attempt_number)
                ],
            }
            for task in workflow.tasks
        ],
    }


def _workflow_summary(workflow: WorkflowRun) -> dict:
    return {
        "id": workflow.id,
        "project_id": workflow.project_id,
        "workflow_type": workflow.workflow_type,
        "status": workflow.status,
        "error_summary": workflow.error_summary,
        "can_resume": workflow.status in {"failed", "partially_completed"},
        "resume_reason": (
            None
            if workflow.status in {"failed", "partially_completed"}
            else "Only failed or partially completed workflows can be resumed."
        ),
        "created_at": workflow.created_at,
        "started_at": workflow.started_at,
        "completed_at": workflow.completed_at,
        "updated_at": workflow.updated_at,
        "tasks": [
            {
                "id": task.id,
                "agent_name": task.agent_name,
                "task_type": task.task_type,
                "status": task.status,
                "attempt_count": task.attempt_count,
                "input_summary": _task_input_summary(workflow, task),
            }
            for task in workflow.tasks
        ],
    }


def _task_input_summary(workflow: WorkflowRun, task: WorkflowTask) -> str:
    summaries = {
        "requirements_analysis": "Project-scoped requirement evidence and request",
        "bug_analysis": "Project-scoped defect and failed-execution evidence",
        "test_generation": "Requirements, cited evidence, and persisted feedback",
        "deterministic_validation": "Generated test cases and evidence links",
        "review": "Generated cases and deterministic validation findings",
        "change_risk_analysis": "Change summary and project-scoped evidence",
        "test_analysis": "Project test-execution history",
        "quality_insights": "Project analytics and test-execution history",
        "aggregation": "Persisted outputs from all workflow tasks",
    }
    if (
        task.task_type == "change_risk_analysis"
        and not workflow.input_data.get("change_summary")
    ):
        return "Skipped: no change summary was supplied"
    return summaries.get(task.task_type, "Task-specific workflow inputs")


@router.post(
    "/{project_id}/workflows",
    status_code=202,
    dependencies=[Depends(limit_requests("workflow-start", limit=5, window_seconds=60))],
)
def start_workflow(
    project_id: int,
    request: WorkflowStartRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_owned_project(
        db,
        project_id,
        current_user.id,
        for_update=True,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    input_data = request.model_dump(exclude_none=True)
    try:
        workflow_type = Orchestrator.classify_task(input_data)
        task_types = Orchestrator.workflow_template(workflow_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    active_workflows = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.project_id == project_id,
            WorkflowRun.status.in_(("pending", "running")),
        )
        .all()
    )
    for candidate in active_workflows:
        if WorkflowService.mark_interrupted(candidate):
            db.commit()
    active = next(
        (
            candidate
            for candidate in active_workflows
            if candidate.status in {"pending", "running"}
        ),
        None,
    )
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="An active workflow already exists for the project.",
        )

    workflow = WorkflowRun(
        project_id=project_id,
        initiated_by=current_user.id,
        workflow_type=workflow_type,
        status="pending",
        input_data=input_data,
    )
    try:
        db.add(workflow)
        db.flush()
        WorkflowService.create_tasks(db, workflow, task_types)
        db.commit()
        db.refresh(workflow)
    except Exception:
        db.rollback()
        logger.exception("Workflow creation failed for project %s", project_id)
        raise HTTPException(
            status_code=500,
            detail="Workflow could not be created.",
        ) from None
    try:
        background_tasks.add_task(execute_workflow_background, workflow.id)
    except Exception:
        logger.exception("Workflow scheduling failed: workflow_id=%s", workflow.id)
        workflow.status = "failed"
        workflow.error_summary = (
            "Workflow was persisted but could not be scheduled. Resume is available."
        )
        workflow.completed_at = datetime.utcnow()
        workflow.updated_at = datetime.utcnow()
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Workflow was created but could not be scheduled.",
                "workflow_id": workflow.id,
            },
        ) from None
    db.refresh(workflow)
    return {
        "success": True,
        "message": "Workflow accepted.",
        "data": _workflow_payload(workflow),
    }


@router.get("/{project_id}/workflows")
def list_workflows(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    workflows = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.project_id == project_id)
        .options(selectinload(WorkflowRun.tasks))
        .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
        .limit(limit)
        .all()
    )
    for workflow in workflows:
        if WorkflowService.mark_interrupted(workflow):
            db.commit()
    return {
        "success": True,
        "data": [_workflow_summary(workflow) for workflow in workflows],
    }


@router.get("/{project_id}/workflows/{workflow_id}")
def get_workflow(
    project_id: int,
    workflow_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    workflow = _authorized_workflow(db, current_user.id, project_id, workflow_id)
    if WorkflowService.mark_interrupted(workflow):
        db.commit()
    return {"success": True, "data": _workflow_payload(workflow)}


@router.get("/{project_id}/workflows/{workflow_id}/tasks")
def list_workflow_tasks(
    project_id: int,
    workflow_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    workflow = _authorized_workflow(db, current_user.id, project_id, workflow_id)
    if WorkflowService.mark_interrupted(workflow):
        db.commit()
    tasks = (
        db.query(WorkflowTask)
        .filter(WorkflowTask.workflow_run_id == workflow.id)
        .options(selectinload(WorkflowTask.attempts))
        .order_by(WorkflowTask.id.asc())
        .all()
    )
    return {
        "success": True,
        "data": [
            {
                "id": task.id,
                "agent_name": task.agent_name,
                "task_type": task.task_type,
                "status": task.status,
                "depends_on_task_ids": task.depends_on_task_ids,
                "input_summary": _task_input_summary(workflow, task),
                "output_data": task.output_data,
                "attempt_count": task.attempt_count,
                "error_details": task.error_details,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "attempts": [
                    _attempt_payload(task, attempt)
                    for attempt in sorted(
                        task.attempts,
                        key=lambda item: item.attempt_number,
                    )
                ],
            }
            for task in tasks
        ],
    }


@router.post(
    "/{project_id}/workflows/{workflow_id}/resume",
    status_code=202,
    dependencies=[Depends(limit_requests("workflow-resume", limit=5, window_seconds=60))],
)
def resume_workflow(
    project_id: int,
    workflow_id: int,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    workflow = _authorized_workflow(db, current_user.id, project_id, workflow_id)
    workflow = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.id == workflow_id,
            WorkflowRun.project_id == project_id,
        )
        .with_for_update()
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    WorkflowService.mark_interrupted(workflow)
    if workflow.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Workflow is still active and cannot be resumed.",
        )
    if workflow.status not in {"failed", "partially_completed"}:
        raise HTTPException(
            status_code=409,
            detail="Only failed or interrupted workflows can be resumed.",
        )
    task_by_type = {task.task_type: task     for task in sorted(workflow.tasks, key=lambda item: item.id)}
    generation_task = task_by_type.get("test_generation")
    if generation_task is not None and generation_task.status == "failed":
        latest_generation_attempt = max(
            generation_task.attempts,
            key=lambda attempt: attempt.attempt_number,
            default=None,
        )
        generation_output = (
            latest_generation_attempt.output_data
            if latest_generation_attempt is not None
            and isinstance(latest_generation_attempt.output_data, dict)
            else {}
        )
        structured_generation = generation_output.get("structured_data", {})
        if (
            latest_generation_attempt is not None
            and latest_generation_attempt.status == "completed"
            and generation_output.get("status") == "completed"
            and isinstance(structured_generation, dict)
            and isinstance(structured_generation.get("test_cases"), list)
        ):
            generation_task.status = "completed"
            generation_task.error_details = None
            generation_task.completed_at = latest_generation_attempt.completed_at
            generation_task.updated_at = datetime.utcnow()

    validation_task = task_by_type.get("deterministic_validation")
    validation_succeeded = (
        validation_task is not None
        and validation_task.status == "completed"
        and isinstance(validation_task.output_data, dict)
        and validation_task.output_data.get("valid") is True
    )
    generation_succeeded = (
        generation_task is not None
        and generation_task.status == "completed"
        and isinstance(generation_task.output_data, dict)
        and generation_task.output_data.get("status") == "completed"
    )
    for task in sorted(workflow.tasks, key=lambda item: item.id):
        recoverable_review_skip = (
            task.task_type == "review"
            and task.status == "skipped"
            and validation_succeeded
            and generation_succeeded
            and isinstance(task.output_data, dict)
            and task.output_data.get("reason")
            == "This stage is coordinated with test generation."
        )
        if task.status in {"failed", "retrying", "running"} or (
            task.status == "skipped"
            and isinstance(task.error_details, dict)
            and task.error_details.get("code") == "DEPENDENCY_NOT_SATISFIED"
        ) or recoverable_review_skip:
            task.status = "pending"
            task.error_details = None
            task.completed_at = None
            task.updated_at = datetime.utcnow()
    now = datetime.utcnow()
    claimed = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.id == workflow.id,
            WorkflowRun.status.in_(("failed", "partially_completed")),
        )
        .update(
            {
                WorkflowRun.status: "pending",
                WorkflowRun.error_summary: None,
                WorkflowRun.completed_at: None,
                WorkflowRun.updated_at: now,
            },
            synchronize_session=False,
        )
    )
    if not claimed:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Workflow has already been resumed or is not resumable.",
        )
    db.commit()
    try:
        background_tasks.add_task(execute_workflow_background, workflow.id)
    except Exception:
        logger.exception("Workflow resume scheduling failed: workflow_id=%s", workflow.id)
        db.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == workflow.id,
                WorkflowRun.status == "pending",
            )
            .values(
                status="failed",
                error_summary="Workflow resume could not be scheduled. Resume is available.",
                completed_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Workflow resume could not be scheduled.",
        ) from None
    db.refresh(workflow)
    return {
        "success": True,
        "message": "Workflow resume accepted.",
        "data": _workflow_payload(workflow),
    }
