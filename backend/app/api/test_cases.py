
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field,field_validator
from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.schemas.test_case_schema import TestCaseGenerationRequest
from app.services.project_service import ProjectService
from app.services.test_case_evaluation_service import TestCaseEvaluationService
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
from app.models.project import Project
from app.models.organization import Organization

router = APIRouter(prefix="/projects",tags=["Test Cases"])
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



@router.post("/{project_id}/test-cases/generate")
def generate_test_cases(project_id:int,request:TestCaseGenerationRequest,current_user:CurrentUser,db:Session = Depends(get_db)):

    orchestrator=Orchestrator()
    orchestrator.register("test_generation",TestGenerationAgent(db))
    orchestrator.register("knowledge_search",KnowledgeAgent(db))

    context=AgentContext(user_id=current_user.id,project_id=project_id,task="test_generation",inputs={"request":request})
    result=orchestrator.route(context)

    if result.status !="success":
        error = result.error or {}
        code = error.get("code", "GENERATION_FAILED")
        message = error.get("message", "Test-case generation failed.")

        if code == "PERMISSION_DENIED":
            raise HTTPException(status_code=403, detail=message)
        if code == "INVALID_REQUEST":
            raise HTTPException(status_code=400, detail=message)
        if code == "GENERATION_FAILED":
            raise HTTPException(status_code=502, detail=message)

        raise HTTPException(status_code=500,detail="Test-case generation failed unexpectedly.")

    return {
        "success": True,
        "message": "Test cases generated successfully.",
        "generated_count": result.data["generated_count"],
        "test_cases": result.data["test_cases"]
    }

@router.post("/{project_id}/test-cases/{test_case_id}/evaluate")
def evaluate_test_case(project_id: int,test_case_id:int,current_user:CurrentUser,db:Session = Depends(get_db)):
    service = TestCaseEvaluationService(db)
    try:
        return service.evaluate(user_id=current_user.id,project_id=project_id,test_case_id=test_case_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{project_id}/test-cases/{test_case_id}/approve")
def approve_test_case(project_id:int,test_case_id:int,current_user:CurrentUser,db:Session=Depends(get_db)):
    project = (db.query(Project).join(Organization).filter(Project.id==project_id,Organization.owner_id==current_user.id).first())

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

@router.post("/{project_id}/change-risk/analyze")
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

@router.post("/{project_id}/test-cases/{test_case_id}/review")
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
        "review": result.data
    }

@router.post("/{project_id}/test-analysis/analyze")
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

@router.post("/{project_id}/quality-insights/analyze")
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