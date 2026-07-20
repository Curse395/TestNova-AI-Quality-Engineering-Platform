from sqlalchemy import Column, Integer, String,DateTime
from app.database.connection import Base 
from datetime import datetime
from sqlalchemy.orm import relationship



class User(Base):

    __tablename__="users"

    id = Column(
        Integer,
        primary_key=True,
        index=True)
    
    name=Column(
        String
    )
    email=Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    password_hash=Column(
        String,
        nullable=False 
    )

    created_at=Column(
        DateTime,
        default=datetime.utcnow
    )

    organizations=relationship(
        "Organization",
        back_populates="owner"
    )
    