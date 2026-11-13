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


class WorkflowTask(Base):
    __tablename__ = "workflow_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'skipped', "
            "'retrying', 'failed')",
            name="ck_workflow_tasks_status",
        ),
        Index("ix_workflow_tasks_workflow_created", "workflow_run_id", "created_at"),
        Index("ix_workflow_tasks_status", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workflow_run_id = Column(
        Integer, ForeignKey("workflow_runs.id"), nullable=False
    )
    agent_name = Column(String(100), nullable=False)
    task_type = Column(String(60), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    depends_on_task_ids = Column(JSON, nullable=False, default=list)
    input_data = Column(JSON, nullable=False, default=dict)
    output_data = Column(JSON, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    error_details = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    workflow = relationship("WorkflowRun", back_populates="tasks")
    attempts = relationship("WorkflowTaskAttempt", back_populates="task")
