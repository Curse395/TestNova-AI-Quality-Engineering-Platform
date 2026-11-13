from datetime import datetime

from sqlalchemy import (
    Column,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Text,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.connection import Base


class TestCaseGenerationRun(Base):
    __tablename__ = "test_case_generation_runs"
    __table_args__ = (
        Index("ix_generation_runs_project_id", "project_id"),
        Index("ix_generation_runs_created_at", "created_at"),
        Index(
            "ix_generation_runs_workflow_attempt",
            "workflow_run_id",
            "workflow_attempt_number",
        ),
        UniqueConstraint(
            "workflow_run_id",
            "workflow_attempt_number",
            name="uq_generation_runs_workflow_attempt",
        ),
        CheckConstraint(
            "workflow_attempt_number IS NULL OR workflow_attempt_number > 0",
            name="ck_generation_runs_workflow_attempt_positive",
        ),
    )
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    requirements_prompt = Column(Text, nullable=False)
    requested_categories = Column(JSON, nullable=False)
    requirement_keys = Column(JSON, nullable=False, default=list)
    max_cases = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="completed")
    generated_case_count = Column(Integer, nullable=False, default=0)
    duplicate_rejected_count = Column(Integer, nullable=False, default=0)
    invalid_rejected_count = Column(Integer, nullable=False, default=0)
    insufficient_evidence_count = Column(Integer, nullable=False, default=0)
    final_persisted_count = Column(Integer, nullable=False, default=0)
    retry_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    workflow_run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=True)
    workflow_attempt_number = Column(Integer, nullable=True)
    workflow = relationship("WorkflowRun", back_populates="generation_runs")

    @property
    def requested_max_cases(self) -> int:
        return self.max_cases

    @property
    def generated_count(self) -> int:
        return self.generated_case_count

    @property
    def generation_status(self) -> str:
        return self.status
