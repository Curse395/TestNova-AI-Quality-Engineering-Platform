
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.schemas.test_execution_schema import APIExecutionRequest
from app.services.test_execution_service import TestExecutionService

router = APIRouter(prefix="/projects",tags=["Test Execution"])


@router.post("/{project_id}/test-cases/{test_case_id}/execute-api")
def execute_api_test(
    project_id: int,
    test_case_id: int,
    request: APIExecutionRequest,
    current_user: CurrentUser,
    db: Session = Depends(get_db)
):
    service = TestExecutionService(db)

    try:
        return service.execute_api_test(
            user_id=current_user.id,
            project_id=project_id,
            test_case_id=test_case_id,
            config=request.request
        )

    except ValueError as exc:
        message = str(exc)

        if "access denied" in message.lower():
            raise HTTPException(status_code=403,detail=message) from exc

        if "not found" in message.lower():
            raise HTTPException(status_code=404,detail=message) from exc

        if "approved" in message.lower():
            raise HTTPException(status_code=409,detail=message) from exc

        raise HTTPException(status_code=400,detail=message) from exc
