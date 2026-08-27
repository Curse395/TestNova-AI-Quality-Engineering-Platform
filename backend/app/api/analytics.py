from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.services.analytics_service import AnalyticsService
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.services.analytics_service import AnalyticsService
from app.core.dependencies import CurrentUser

router=APIRouter(prefix="/analytics",tags=["Analytics"])

@router.get("/overview/{project_id}")
def get_project_overview(
    project_id:int,
    current_user:CurrentUser,
    db:Session=Depends(get_db),
    
):
    
    analytics=AnalyticsService(db)
    return analytics.get_project_overview(current_user_id=current_user.id,project_id=project_id)

@router.get("/documents/{project_id}")
def get_document_statistics(project_id:int,current_user:CurrentUser,db:Session=Depends(get_db)):
    analytics=AnalyticsService(db)
    return analytics.get_document_statistics(current_user_id=current_user.id,project_id=project_id)

router=APIRouter(prefix="/analytics",tags=["Analytics"])

@router.get("/overview/{project_id}")
def get_project_overview(
    project_id:int,
    current_user:CurrentUser,
    db:Session=Depends(get_db),
    
):
    
    analytics=AnalyticsService(db)
    return analytics.get_project_overview(current_user_id=current_user.id,project_id=project_id)

@router.get("/documents/{project_id}")
def get_document_statistics(project_id:int,current_user:CurrentUser,db:Session=Depends(get_db)):
    analytics=AnalyticsService(db)
    return analytics.get_document_statistics(current_user_id=current_user.id,project_id=project_id)