from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.services.chat_service import ChatService
from app.services.chat_history_service import ChatHistoryService

router=APIRouter(prefix="/chat",tags=["Chat"],)

@router.post("/")
def chat(current_user:CurrentUser,project_id:int, question:str,db:Session=Depends(get_db),):
    service=ChatService(db)

    return service.chat(current_user_id=current_user.id,project_id=project_id,question=question,)

@router.get("/history/{project_id}")
def get_chat_history(project_id:int,current_user:CurrentUser,db:Session=Depends(get_db)):
    history=ChatHistoryService(db).get_project_history(user_id=current_user.id,project_id=project_id)

    return(
        {
            "id":chat.id,
            "question":chat.question,
            "answer":chat.answer,
            "created_at":chat.created_at
        }
        for chat in history
    )