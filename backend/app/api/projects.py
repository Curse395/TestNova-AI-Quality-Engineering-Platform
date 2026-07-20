from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.shemas.project_schema import ProjectCreate, ProjectResponse, ProjectUpdate
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("/", response_model=ProjectResponse)
def create_project(
    data: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ProjectResponse:
    service = ProjectService(db)
    try:
        return service.create_project(current_user, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/", response_model=list[ProjectResponse])
def get_my_projects(
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> list[ProjectResponse]:
    service = ProjectService(db)
    return service.list_projects(current_user)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    data: ProjectUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ProjectResponse:
    service = ProjectService(db)
    try:
        return service.update_project(current_user, project_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> dict[str, str]:
    service = ProjectService(db)
    try:
        service.delete_project(current_user, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"message": "Project deleted successfully"}


@router.get("/{project_id}/dashboard")
def project_dashboard(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> dict[str, object]:
    service = ProjectService(db)
    try:
        return service.get_dashboard(current_user, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
