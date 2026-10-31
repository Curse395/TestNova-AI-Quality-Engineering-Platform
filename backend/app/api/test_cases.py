
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.schemas.test_case_schema import TestCaseGenerationRequest
from app.services.test_case_generation_service import TestCaseGenerationService
from app.services.test_case_evaluation_service import TestCaseEvaluationService
from app.agents.test_generation_agent import TestGenerationAgent
from app.services.test_case_evaluation_service import TestCaseEvaluationService
from app.agents.contracts import AgentContext
from app.agents.orchestrator import Orchestrator

router = APIRouter(prefix="/projects",tags=["Test Cases"])


@router.post("/{project_id}/test-cases/generate")
def generate_test_cases(project_id:int,request:TestCaseGenerationRequest,current_user:CurrentUser,db:Session = Depends(get_db)):

    orchestrator=Orchestrator()
    orchestrator.register("test_generation",TestGenerationAgent(db))

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
