from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from app.database.connection import Base


class ProjectRequirement(Base):
    __tablename__ = "project_requirements"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "requirement_key",
            name="uq_project_requirements_project_key",
        ),
        Index("ix_project_requirements_project_id", "project_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    requirement_key = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    classification = Column(String(20), nullable=False, default="explicit")
    evidence_chunk_ids = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


