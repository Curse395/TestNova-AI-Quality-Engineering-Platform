from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.schemas.quality_summary_schema import QualitySummaryResponse
from app.schemas.release_readiness_schema import ReleaseReadinessResponse
from app.services.analytics_service import AnalyticsService
from app.services.project_intelligence_service import ProjectIntelligenceService
from app.services.release_readiness_service import ReleaseReadinessService

router=APIRouter(prefix="/analytics",tags=["Analytics"])


def _raise_analytics_error(exc: ValueError) -> None:
    status_code = 404 if str(exc) == "Project not found" else 422
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


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
        _raise_analytics_error(exc)


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
        _raise_analytics_error(exc)


@router.get("/test-cases/{project_id}")
def get_test_case_statistics(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        return AnalyticsService(db).get_test_case_statistics(
            project_id=project_id,
            current_user_id=current_user.id,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.get("/coverage/{project_id}")
def get_requirement_traceability(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        return AnalyticsService(db).get_requirement_traceability(
            project_id=project_id,
            current_user_id=current_user.id,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.get("/executions/{project_id}")
def get_execution_analytics(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None, alias="to"),
):
    try:
        return AnalyticsService(db).get_execution_analytics(
            project_id=project_id,
            current_user_id=current_user.id,
            start=from_,
            end=to,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.get("/execution-trends/{project_id}")
def get_execution_trends(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None, alias="to"),
    bucket: Literal["day", "week", "month"] = Query(default="day"),
):
    try:
        return AnalyticsService(db).get_execution_trends(
            project_id=project_id,
            current_user_id=current_user.id,
            start=from_,
            end=to,
            bucket=bucket,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.get("/risks/{project_id}")
def get_project_risks(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        return ProjectIntelligenceService(db).get_project_risks(
            project_id=project_id,
            current_user_id=current_user.id,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.get("/workflows/{project_id}")
def get_workflow_monitoring(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        return ProjectIntelligenceService(db).get_workflow_monitoring(
            project_id=project_id,
            current_user_id=current_user.id,
            limit=limit,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.post(
    "/quality-summary/{project_id}",
    response_model=QualitySummaryResponse,
)
def generate_quality_summary(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        return ProjectIntelligenceService(db).generate_quality_summary(
            project_id=project_id,
            current_user_id=current_user.id,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)


@router.get(
    "/release-readiness/{project_id}",
    response_model=ReleaseReadinessResponse,
)
def get_project_release_readiness(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        return ReleaseReadinessService(db).get_project_release_readiness(
            project_id=project_id,
            current_user_id=current_user.id,
        )
    except ValueError as exc:
        _raise_analytics_error(exc)