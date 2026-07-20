from sqlalchemy import Column,Integer,String,ForeignKey,DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.connection import Base

class Project(Base):

    __tablename__="projects"
    id=Column(
        Integer,
        primary_key=True,
        index=True
    )

    name=Column(
        String,
        nullable=False
    )

    description=Column(
        String
    )
    
    organitzation_id=Column(
        Integer,
        ForeignKey("organizations.id")
    )

    created_at=Column(
        DateTime,
        default=datetime.utcnow
    )

    organization=relationship(
        "Organization",
        back_populates="projects"
    )

    documents = relationship("Document", back_populates="project")