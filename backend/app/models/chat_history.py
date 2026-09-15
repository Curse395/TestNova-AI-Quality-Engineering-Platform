from  sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from app.database.connection import Base

class ChatHistory(Base):
    __tablename__="chat_history"

    id =Column(Integer,primary_key=True)

    user_id=Column(Integer,ForeignKey("users.id",ondelete="CASCADE"),nullable=False)
    project_id=Column(Integer,ForeignKey("projects.id",ondelete="CASCADE"),nullable=False)
    question = Column(String, nullable=False)
    answer=Column(String,nullable=False)

    created_at=Column(DateTime(timezone=True),server_default=func.now())