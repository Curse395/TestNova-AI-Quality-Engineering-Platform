from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse, success_response
from app.database.connection import get_db
from backend.app.schemas.project_schema import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/")
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    service = ProjectService(db)
    try:
        payload = service.create_project(current_user, data)
        return {"success": True, "message": "Project created successfully", "data": payload.model_dump(), "errors": None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/")
def get_my_projects(
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    service = ProjectService(db)
    payload = service.list_projects(current_user)
    return {"success": True, "message": "Projects retrieved successfully", "data": [item.model_dump() for item in payload], "errors": None}


@router.put("/{project_id}")
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    service = ProjectService(db)
    try:
        payload = service.update_project(current_user, project_id, data)
        return {"success": True, "message": "Project updated successfully", "data": payload.model_dump(), "errors": None,
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    service = ProjectService(db)
    try:
        service.delete_project(current_user, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"success": True, "message": "Project deleted successfully", "data": {"message": "Project deleted successfully"}, "errors": None}


@router.get("/{project_id}/dashboard")
def project_dashboard(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    service = ProjectService(db)
    try:
        payload = service.get_dashboard(current_user, project_id)
        return {"success": True, "message": "Dashboard data retrieved successfully", "data": payload, "errors": None, **payload}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
