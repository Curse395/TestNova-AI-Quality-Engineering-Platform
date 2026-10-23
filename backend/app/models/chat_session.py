from sqlalchemy import Column,Integer,String,ForeignKey,DateTime
from sqlalchemy.sql import func
from app.database.connection import Base

class ChatSession(Base):
    __tablename__="chat_sessions"
    id=Column(Integer,primary_key=True,index=True)
    user_id=Column(Integer,ForeignKey("users.id",ondelete="CASCADE"),nullable=False,index=True)
    project_id=Column(Integer,ForeignKey("projects.id",ondelete="CASCADE"),nullable=False,index=True)
    title=Column(String(200),nullable=False,default="New Chat")
    created_at=Column(DateTime(timezone=True),server_default=func.now())
    updated_at=Column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now(),nullable=False)
