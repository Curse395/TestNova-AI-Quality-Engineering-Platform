from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from app.database.connection import get_db
from app.core.dependencies import CurrentUser
from app.services.dashboard_service import DashboardService

router=APIRouter(prefix="/dashboard",tags=["Dashboard"])

@router.get('/')
def get_dashboard(current_user:CurrentUser,db:Session=Depends(get_db)):
    dashboard=DashboardService(db)

    return dashboard.get_dashboard(current_user_id=current_user.id)

@router.get("/insights")
def get_dashboard_insights(current_user:CurrentUser,db:Session=Depends(get_db)):
    service=DashboardService(db)
    return service.get_dashboard_insights(current_user.id)