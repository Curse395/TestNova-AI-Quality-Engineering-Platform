from sqlalchemy import Column,Integer,String,ForeignKey,DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.connection import Base

class Organization(Base):
    __tablename__="organizations"

    id=Column(
        Integer,
        primary_key=True,
        index=True)
    
    name=Column(
        String,
        nullable=False)
    
    owner_id =Column(
        Integer,
        ForeignKey("users.id")
    )
    
    created_at=Column(
        DateTime,
        default=datetime.utcnow
    )

    owner=relationship(
        "User",
        back_populates="organizations"
    )

    projects=relationship(
        "Project",
        back_populates="organization"
    )