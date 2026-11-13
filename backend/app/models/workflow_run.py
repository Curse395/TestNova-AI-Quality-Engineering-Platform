from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', "
            "'partially_completed', 'failed')",
            name="ck_workflow_runs_status",
        ),
        Index("ix_workflow_runs_project_created", "project_id", "created_at"),
        Index("ix_workflow_runs_status", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    initiated_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    workflow_type = Column(String(40), nullable=False)
    status = Column(String(30), nullable=False, default="pending")
    input_data = Column(JSON, nullable=False, default=dict)
    final_output = Column(JSON, nullable=True)
    error_summary = Column(Text, nullable=True)
    generation_attempt_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    project = relationship("Project")
    initiated_by_user = relationship("User")
    tasks = relationship("WorkflowTask", back_populates="workflow")
    generation_runs = relationship(
        "TestCaseGenerationRun",
        back_populates="workflow",
    )
