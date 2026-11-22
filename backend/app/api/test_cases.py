
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field,field_validator

from app.core.authorization import get_owned_project
from app.core.dependencies import CurrentUser
from app.core.rate_limit import limit_requests
from app.database.connection import get_db
from app.schemas.test_case_schema import (
    TestCaseGenerationRequest,
    TestCaseUpdate,
)
from app.services.project_service import ProjectService
from app.agents.test_generation_agent import TestGenerationAgent
from app.services.test_case_evaluation_service import TestCaseEvaluationService
from app.agents.contracts import AgentContext
from app.agents.orchestrator import Orchestrator
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.change_risk_agent import ChangeRiskAgent
from app.agents.review_agent import ReviewAgent
from app.agents.test_analysis_agent import TestAnalysisAgent
from app.agents.quality_insight_agent import QualityInsightAgent
from app.models.test_case import TestCase
from app.models.test_case_evidence import TestCaseEvidence
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.project_requirement import ProjectRequirement
from app.models.test_case_generation_run import TestCaseGenerationRun
from app.models.test_case_requirement import TestCaseRequirement

router = APIRouter(prefix="/projects",tags=["Test Cases"])


def _case_requirement_data(test_case: TestCase) -> tuple[list[int], list[dict[str, object]]]:
    links = sorted(
        test_case.requirement_links,
        key=lambda link: (link.requirement.requirement_key, link.requirement_id),
    )
    return (
        [link.requirement_id for link in links],
        [
            {
                "id": link.requirement_id,
                "requirement_key": link.requirement.requirement_key,
                "description": link.requirement.description,
            }
            for link in links
        ],
    )


def _serialize_test_case(
    test_case: TestCase,
    evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    requirement_ids, requirements = _case_requirement_data(test_case)
    return {
        "id": test_case.id,
        "project_id": test_case.project_id,
        "title": test_case.title,
        "description": test_case.description,
        "test_type": test_case.test_type,
        "category": test_case.category,
        "priority": test_case.priority,
        "severity": test_case.severity,
        "preconditions": test_case.preconditions,
        "steps": test_case.steps,
        "expected_result": test_case.expected_result,
        "review_status": test_case.review_status,
        "created_at": test_case.created_at,
        "generation_run_id": test_case.generation_run_id,
        "requirement_ids": requirement_ids,
        "requirements": requirements,
        "evidence": evidence or [],
    }


class ChangeRiskRequest(BaseModel):
    change_summary: str = Field(min_length=10, max_length=5000)
    change_type: str = Field(default="general", max_length=100)
    changed_files: list[str] = Field(default_factory=list, max_length=100)
    additional_context: str = Field(default="", max_length=5000)

    @field_validator("change_type")


    @classmethod
    def validate_change_type(cls, value):
        value=value.strip().lower()

        if not value:
            raise ValueError("Change type cannot be empty")
        return value


@router.get("/{project_id}/test-cases")
def list_project_test_cases(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = 100,
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 200")

    cases = (
        db.query(TestCase)
        .filter(TestCase.project_id == project_id)
        .order_by(TestCase.created_at.desc(), TestCase.id.desc())
        .limit(limit)
        .all()
    )
    case_ids = [case.id for case in cases]
    evidence_by_case: dict[int, list[dict[str, object]]] = {
        case_id: [] for case_id in case_ids
    }

    if case_ids:
        evidence_rows = (
            db.query(TestCaseEvidence, Document, DocumentChunk)
            .join(TestCase, TestCase.id == TestCaseEvidence.test_case_id)
            .join(Document, Document.id == TestCaseEvidence.document_id)
            .join(
                DocumentChunk,
                DocumentChunk.id == TestCaseEvidence.chunk_id,
            )
            .filter(
                TestCase.id.in_(case_ids),
                TestCase.project_id == project_id,
                Document.project_id == project_id,
                DocumentChunk.document_id == Document.id,
            )
            .order_by(TestCaseEvidence.id.asc())
            .all()
        )
        for link, document, chunk in evidence_rows:
            evidence_by_case[link.test_case_id].append(
                {
                    "document_id": document.id,
                    "document_name": document.filename,
                    "source_type": document.source_type or "document",
                    "chunk_id": chunk.id,
                    "source_metadata": chunk.source_metadata or {},
                    "excerpt": chunk.content,
                }
            )

    return {
        "success": True,
        "message": "Test cases retrieved successfully",
        "data": [
            _serialize_test_case(case, evidence_by_case[case.id])
            for case in cases
        ],
        "errors": None,
    }


@router.get("/{project_id}/test-cases/{test_case_id}")
def get_project_test_case(
    project_id: int,
    test_case_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    test_case = (
        db.query(TestCase)
        .filter(
            TestCase.id == test_case_id,
            TestCase.project_id == project_id,
        )
        .first()
    )
    if test_case is None:
        raise HTTPException(status_code=404, detail="Test case not found")

    evidence_rows = (
        db.query(TestCaseEvidence, Document, DocumentChunk)
        .join(Document, Document.id == TestCaseEvidence.document_id)
        .join(DocumentChunk, DocumentChunk.id == TestCaseEvidence.chunk_id)
        .filter(
            TestCaseEvidence.test_case_id == test_case.id,
            Document.project_id == project_id,
            DocumentChunk.document_id == Document.id,
        )
        .order_by(TestCaseEvidence.id.asc())
        .all()
    )
    evidence = [
        {
            "document_id": document.id,
            "document_name": document.filename,
            "source_type": document.source_type or "document",
            "chunk_id": chunk.id,
            "source_metadata": chunk.source_metadata or {},
            "excerpt": chunk.content,
        }
        for _, document, chunk in evidence_rows
    ]
    return {
        "success": True,
        "data": _serialize_test_case(test_case, evidence),
    }


@router.patch("/{project_id}/test-cases/{test_case_id}")
def update_project_test_case(
    project_id: int,
    test_case_id: int,
    changes: TestCaseUpdate,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    test_case = (
        db.query(TestCase)
        .filter(
            TestCase.id == test_case_id,
            TestCase.project_id == project_id,
        )
        .first()
    )
    if test_case is None:
        raise HTTPException(status_code=404, detail="Test case not found")

    updates = changes.model_dump(exclude_unset=True)
    if any(
        updates.get(field) is None
        for field in (
            "title",
            "description",
            "category",
            "priority",
            "severity",
            "steps",
            "expected_result",
        )
        if field in updates
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Title, description, category, priority, severity, steps, and "
                "expected result cannot be null."
            ),
        )
    requirement_ids = updates.pop("requirement_ids", None)
    requirement_keys = updates.pop("requirement_keys", None)
    if requirement_ids is not None and requirement_keys is not None:
        raise HTTPException(
            status_code=422,
            detail="Supply requirement IDs or requirement keys, not both.",
        )
    requirements = None
    if requirement_keys is not None:
        requirements = (
            db.query(ProjectRequirement)
            .filter(
                ProjectRequirement.project_id == project_id,
                ProjectRequirement.requirement_key.in_(requirement_keys),
            )
            .all()
            if requirement_keys
            else []
        )
        if len(requirements) != len(requirement_keys):
            raise HTTPException(
                status_code=422,
                detail="One or more requirement keys do not belong to this project.",
            )
        requirement_ids = [item.id for item in requirements]
    elif requirement_ids is not None:
        requirements = (
            db.query(ProjectRequirement)
            .filter(
                ProjectRequirement.project_id == project_id,
                ProjectRequirement.id.in_(requirement_ids),
            )
            .all()
            if requirement_ids
            else []
        )
        if len(requirements) != len(requirement_ids):
            raise HTTPException(
                status_code=422,
                detail="One or more requirement IDs do not belong to this project.",
            )

    for field, value in updates.items():
        if field == "steps":
            value = [step.model_dump() for step in value]
        setattr(test_case, field, value)
    if requirement_ids is not None:
        db.query(TestCaseRequirement).filter(
            TestCaseRequirement.test_case_id == test_case.id
        ).delete(synchronize_session=False)
        for requirement in requirements:
            db.add(
                TestCaseRequirement(
                    test_case_id=test_case.id,
                    requirement_id=requirement.id,
                )
            )
    if updates or requirement_ids is not None or requirement_keys is not None:
        test_case.review_status = "draft"

    try:
        db.commit()
        db.refresh(test_case)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to update test case.",
        ) from exc
    return {"success": True, "data": _serialize_test_case(test_case)}


@router.delete("/{project_id}/test-cases/{test_case_id}")
def delete_project_test_case(
    project_id: int,
    test_case_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    test_case = (
        db.query(TestCase)
        .filter(
            TestCase.id == test_case_id,
            TestCase.project_id == project_id,
        )
        .first()
    )
    if test_case is None:
        raise HTTPException(status_code=404, detail="Test case not found")
    try:
        db.delete(test_case)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to delete test case.",
        ) from exc
    return {
        "success": True,
        "data": {"test_case_id": test_case_id, "project_id": project_id},
    }


@router.get("/{project_id}/test-case-generation-runs")
def list_project_test_case_generation_runs(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = 100,
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="Limit must be between 1 and 200")
    runs = (
        db.query(TestCaseGenerationRun)
        .filter(TestCaseGenerationRun.project_id == project_id)
        .order_by(
            TestCaseGenerationRun.created_at.desc(),
            TestCaseGenerationRun.id.desc(),
        )
        .limit(limit)
        .all()
    )
    run_data = []
    for run in runs:
        cases = (
            db.query(TestCase)
            .filter(
                TestCase.generation_run_id == run.id,
                TestCase.project_id == project_id,
            )
            .all()
        )
        category_counts: dict[str, int] = {}
        requirement_keys: set[str] = set()
        traced_case_count = 0
        for case in cases:
            category_counts[case.category] = category_counts.get(case.category, 0) + 1
            if case.requirement_links:
                traced_case_count += 1
            requirement_keys.update(
                link.requirement.requirement_key
                for link in case.requirement_links
            )
        run_data.append(
            {
                "id": run.id,
                "project_id": run.project_id,
                "requirements_prompt": run.requirements_prompt,
                "requested_categories": run.requested_categories,
                "requirement_keys": run.requirement_keys or [],
                "requirement_keys_covered": sorted(requirement_keys),
                "requested_max_cases": run.max_cases,
                "generated_count": run.generated_case_count,
                "duplicate_rejected_count": run.duplicate_rejected_count,
                "invalid_rejected_count": run.invalid_rejected_count,
                "insufficient_evidence_count": run.insufficient_evidence_count,
                "final_persisted_count": run.final_persisted_count,
                "generation_status": run.status,
                "retry_count": run.retry_count,
                "created_at": run.created_at,
                "category_counts": category_counts,
                "traced_case_count": traced_case_count,
                "case_count": len(cases),
            }
        )
    return {"success": True, "data": run_data}


@router.post(
    "/{project_id}/test-cases/generate",
    dependencies=[Depends(limit_requests("test-case-generation", limit=3, window_seconds=60))],
)
def generate_test_cases(project_id:int,request:TestCaseGenerationRequest,current_user:CurrentUser,db:Session = Depends(get_db)):

    orchestrator=Orchestrator()
    orchestrator.register("test_generation",TestGenerationAgent(db))
    orchestrator.register("knowledge_search",KnowledgeAgent(db))

    context=AgentContext(user_id=current_user.id,project_id=project_id,task="test_generation",inputs={"request":request})
    result=orchestrator.route(context)

    if result.status == "failed":
        error = result.error or {}
        code = error.get("code", "GENERATION_FAILED")
        message = error.get("message", "Test-case generation failed.")
        generation_stats = error.get("generation_stats")
        if not isinstance(generation_stats, dict):
            generation_stats = (
                result.data.get("generation_stats", {})
                if isinstance(result.data, dict)
                else {}
            )
        if not isinstance(generation_stats, dict):
            generation_stats = {}
        failure_payload = {
            "detail": message,
            "generation_stats": generation_stats,
            "generated_count": generation_stats.get("generated_count", 0),
            "final_persisted_count": generation_stats.get(
                "final_persisted_count",
                0,
            ),
        }

        if code == "PERMISSION_DENIED":
            raise HTTPException(status_code=403, detail=message)
        if code == "INVALID_REQUEST":
            raise HTTPException(status_code=400, detail=message)
        if code == "GENERATION_FAILED":
            return JSONResponse(status_code=502, content=failure_payload)
        if code == "NO_USABLE_TEST_CASES":
            return JSONResponse(status_code=422, content=failure_payload)

        raise HTTPException(status_code=500,detail="Test-case generation failed unexpectedly.")

    if result.status not in {"success", "partial"}:
        raise HTTPException(
            status_code=500,
            detail="Test-case generation returned an invalid status.",
        )

    return {
        "success": True,
        "status": "partial" if result.status == "partial" else "completed",
        "message": (
            "Test cases generated partially."
            if result.status == "partial"
            else "Test cases generated successfully."
        ),
        "generated_count": result.data["generated_count"],
        "final_persisted_count": result.data.get(
            "final_persisted_count",
            len(result.data["test_cases"]),
        ),
        "generation_stats": result.data.get("generation_stats", {}),
        "test_cases": result.data["test_cases"]
    }

@router.post(
    "/{project_id}/test-cases/{test_case_id}/evaluate",
    dependencies=[Depends(limit_requests("test-case-evaluation", limit=10, window_seconds=60))],
)
def evaluate_test_case(project_id: int,test_case_id:int,current_user:CurrentUser,db:Session = Depends(get_db)):
    service = TestCaseEvaluationService(db)
    try:
        return service.evaluate(user_id=current_user.id,project_id=project_id,test_case_id=test_case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{project_id}/test-case-generation-runs/{generation_run_id}/evaluate",
    dependencies=[Depends(limit_requests("generation-evaluation", limit=10, window_seconds=60))],
)
def evaluate_test_case_generation_run(
    project_id: int,
    generation_run_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    service = TestCaseEvaluationService(db)
    try:
        return service.evaluate_generation_run(
            user_id=current_user.id,
            project_id=project_id,
            generation_run_id=generation_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


#Manually checked the code by me


@router.patch("/{project_id}/test-cases/{test_case_id}/approve")
def approve_test_case(project_id:int,test_case_id:int,current_user:CurrentUser,db:Session=Depends(get_db)):
    project = get_owned_project(db, project_id, current_user.id)

    if not project:
        raise HTTPException(status_code=404,detail="Project not found or access denied.")

    test_case = (db.query(TestCase).filter(TestCase.id==test_case_id,TestCase.project_id==project_id).first())

    if not test_case:
        raise HTTPException(status_code=404,detail="Test case not found.")

    if test_case.review_status == "approved":
        return {
            "success": True,
            "message": "Test case is already approved.",
            "test_case_id": test_case.id,
            "review_status": "approved"
        }

    test_case.review_status = "approved"

    try:
        db.commit()
        db.refresh(test_case)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500,detail="Failed to approve test case.")

    return {
        "success": True,
        "message": "Test case approved successfully.",
        "test_case_id": test_case.id,
        "project_id": project_id,
        "review_status": test_case.review_status
    }


@router.patch("/{project_id}/test-cases/{test_case_id}/reject")
def reject_test_case(
    project_id: int,
    test_case_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    project = get_owned_project(db, project_id, current_user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found or access denied.")

    test_case = (
        db.query(TestCase)
        .filter(TestCase.id == test_case_id, TestCase.project_id == project_id)
        .first()
    )
    if test_case is None:
        raise HTTPException(status_code=404, detail="Test case not found.")

    test_case.review_status = "rejected"
    try:
        db.commit()
        db.refresh(test_case)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to reject test case.") from None

    return {
        "success": True,
        "message": "Test case rejected successfully.",
        "test_case_id": test_case.id,
        "project_id": project_id,
        "review_status": test_case.review_status,
    }

@router.post(
    "/{project_id}/change-risk/analyze",
    dependencies=[Depends(limit_requests("change-risk-analysis", limit=5, window_seconds=60))],
)
def analyze_change_risk(
    project_id: int,
    request: ChangeRiskRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db)
):
    # Verify project ownership before running the agent.
    project_service = ProjectService(db)

    try:
        project_service.get_dashboard(current_user, project_id)

    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc)
        ) from exc

 
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc)
        ) from exc

    agent = ChangeRiskAgent(db)

    context = AgentContext(
        user_id=current_user.id,
        project_id=project_id,
        task="change_risk_analysis",
        inputs={
            "change_summary": request.change_summary,
            "change_type": request.change_type,
            "changed_files": request.changed_files,
            "additional_context": request.additional_context
        }
    )

    result = agent.run(context)

    if result.status == "failed":
        raise HTTPException(
            status_code=502,
            detail=result.error
        )

    return {
        "success": True,
        "agent": result.agent_name,
        "status": result.status,
        "analysis": result.data,
        "evidence": result.evidence
    }

@router.post(
    "/{project_id}/test-cases/{test_case_id}/review",
    dependencies=[Depends(limit_requests("test-case-review", limit=5, window_seconds=60))],
)
def review_test_case(
    project_id: int,
    test_case_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db)
):
    agent = ReviewAgent(db)

    context = AgentContext(
        user_id=current_user.id,
        project_id=project_id,
        task="review",
        inputs={
            "test_case_id": test_case_id
        }
    )

    result = agent.run(context)

    if result.status == "failed":
        error = result.error or {}

        if error.get("code") == "REVIEW_TARGET_NOT_FOUND":
            raise HTTPException(status_code=404, detail=error["message"])

        if error.get("code") == "INVALID_TEST_CASE_ID":
            raise HTTPException(status_code=400, detail=error["message"])

        raise HTTPException(status_code=502, detail="Review failed.")

    return {
        "success": True,
        "agent": result.agent_name,
        "status": result.status,
        "review": result.data,
        "evidence": result.evidence,
    }

@router.post(
    "/{project_id}/test-analysis/analyze",
    dependencies=[Depends(limit_requests("test-analysis", limit=5, window_seconds=60))],
)
def analyze_test_executions(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    agent = TestAnalysisAgent(db)

    context = AgentContext(
        user_id=current_user.id,
        project_id=project_id,
        task="test_analysis",
    )

    result = agent.run(context)

    if result.status == "failed":
        error = result.error or {}

        if error.get("code") == "PROJECT_ACCESS_ERROR":
            raise HTTPException(status_code=404, detail=error["message"])

        raise HTTPException(status_code=502, detail="Test analysis failed.")

    return {
        "success": True,
        "agent": result.agent_name,
        "status": result.status,
        "analysis": result.data,
    }

@router.post(
    "/{project_id}/quality-insights/analyze",
    dependencies=[Depends(limit_requests("quality-insights", limit=5, window_seconds=60))],
)
def analyze_quality_insights(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    agent = QualityInsightAgent(db)

    context = AgentContext(
        user_id=current_user.id,
        project_id=project_id,
        task="quality_insights",
    )

    result = agent.run(context)

    if result.status == "failed":
        error = result.error or {}

        if error.get("code") == "PROJECT_ACCESS_ERROR":
            raise HTTPException(status_code=404, detail=error["message"])

        raise HTTPException(
            status_code=502,
            detail="Quality insight analysis failed.",
        )

    return {
        "success": True,
        "agent": result.agent_name,
        "status": result.status,
        "insights": result.data,
    }
