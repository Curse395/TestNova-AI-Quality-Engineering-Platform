from sqlalchemy.orm import Session
from app.models.chat_history import ChatHistory

class ChatHistoryService:

    def __init__(self,db:Session):
        self.db=db

    def save_chat(self,user_id:int,project_id:int,question:str,answer:str):

        chat=ChatHistory(user_id=user_id,project_id=project_id,question=question,answer=answer)
        self.db.add(chat)
        self.db.commit()

    def get_project_history(self,user_id:int, project_id:int):
        return(
            self.db.query(ChatHistory).filter(ChatHistory.user_id==user_id,ChatHistory.project_id==project_id).order_by(ChatHistory.created_at.desc()).all()
        )

    def get_recent_history(self,user_id:int,project_id:int,limit:int=5):
        return (
            self.db.query(ChatHistory).filter(ChatHistory.user_id==user_id,ChatHistory.project_id==project_id).order_by(ChatHistory.created_at.desc()).limit(limit).all()
        )