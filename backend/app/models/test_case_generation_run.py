from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Text,
    String,
)
from app.database.connection import Base


class TestCaseGenerationRun(Base):
    __tablename__="test_case_generation_runs"
    __table_args__=(Index("ix_generation_runs_project_id", "project_id"),Index("ix_generation_runs_created_at", "created_at"))
    id=Column(Integer, primary_key=True, index=True)
    project_id=Column(Integer,ForeignKey("projects.id"),nullable=False)
    created_by_user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    requirements_prompt=Column(Text, nullable=False)
    requested_categories=Column(JSON, nullable=False)
    max_cases=Column(Integer, nullable=False)
    status=Column(String(20), nullable=False, default="completed")
    generated_case_count=Column(Integer, nullable=False, default=0)
    created_at=Column(DateTime,nullable=False,default=datetime.utcnow)
