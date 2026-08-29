from sqlalchemy import Column,Integer,ForeignKey,DateTime,String
from sqlalchemy.sql import func
from app.database.connection import Base

class ProjecActivity(Base):

    __tablename__="project_activities"
    id=Column(Integer,primary_key=True)
    activity_type=Column(String(50),nullable=False,default="index")
    project_id=Column(Integer,ForeignKey("projects.id",ondelete="CASCADE"),nullable=False)
    documents=Column(Integer,default=0)
    chunks=Column(Integer,default=0)
    embeddings=Column(Integer,default=0)
    created_at=Column(DateTime(timezone=True),server_default=func.now())