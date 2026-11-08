from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.services.analytics_service import AnalyticsService

router=APIRouter(prefix="/analytics",tags=["Analytics"])

@router.get("/overview/{project_id}")
def get_project_overview(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    analytics = AnalyticsService(db)
    try:
        return analytics.get_project_overview(
            current_user_id=current_user.id,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents/{project_id}")
def get_document_statistics(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    analytics = AnalyticsService(db)
    try:
        return analytics.get_document_statistics(
            current_user_id=current_user.id,
            project_id=project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc