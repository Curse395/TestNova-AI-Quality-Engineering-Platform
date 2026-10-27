
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.schemas.test_case_schema import TestCaseGenerationRequest
from app.services.test_case_generation_service import TestCaseGenerationService
from app.services.test_case_evaluation_service import TestCaseEvaluationService

router = APIRouter(
    prefix="/projects",
    tags=["Test Cases"],
)


@router.post("/{project_id}/test-cases/generate")
def generate_test_cases(
    project_id: int,
    request: TestCaseGenerationRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        service = TestCaseGenerationService(db)
        test_cases = service.generate(
            user_id=current_user.id,
            project_id=project_id,
            request=request,
        )

        return {
            "success": True,
            "message": "Test cases generated successfully.",
            "generated_count": len(test_cases),
            "test_cases": test_cases,
        }

    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@router.post("/{project_id}/test-cases/{test_case_id}/evaluate")
def evaluate_test_case(project_id:int,test_case_id:int,current_user:CurrentUser,db:Session=Depends(get_db)):
    service=TestCaseEvaluationService(db)

    try:
        return service.evaluate(user_id=current_user.id,project_id=project_id,test_case_id=test_case_id)

    except ValueError as exc:
        raise HTTPException(status_code=404,detail=str(exc))from exc