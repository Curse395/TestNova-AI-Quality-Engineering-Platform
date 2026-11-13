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
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class WorkflowTaskAttempt(Base):
    __tablename__ = "workflow_task_attempts"
    __table_args__ = (
        UniqueConstraint(
            "workflow_task_id",
            "attempt_number",
            name="uq_workflow_task_attempt_number",
        ),
        CheckConstraint(
            "attempt_number > 0",
            name="ck_workflow_task_attempt_positive_number",
        ),
        CheckConstraint(
            "status IN ('running', 'interrupted', 'completed', 'partial', 'skipped', "
            "'retrying', 'failed')",
            name="ck_workflow_task_attempt_status",
        ),
        Index(
            "ix_workflow_task_attempts_task_created",
            "workflow_task_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    workflow_task_id = Column(
        Integer, ForeignKey("workflow_tasks.id"), nullable=False
    )
    attempt_number = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)
    output_data = Column(JSON, nullable=True)
    error_details = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    task = relationship("WorkflowTask", back_populates="attempts")
