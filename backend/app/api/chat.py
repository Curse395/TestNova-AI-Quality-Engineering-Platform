from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.services.chat_service import ChatService

router=APIRouter(prefix="/chat",tags=["Chat"],)

@router.post("/")
def chat(current_user:CurrentUser,project_id:int, question:str,db:Session=Depends(get_db),):
    service=ChatService(db)

    return service.chat(current_user_id=current_user.id,project_id=project_id,question=question,)