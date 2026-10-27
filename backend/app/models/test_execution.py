from datetime import datetime
from sqlalchemy import Column,DateTime,ForeignKey,Index,Integer,JSON,String,Text,Float
from app.database.connection import Base

class TestExecutionRun(Base):
    __tablename__="test_execution_runs"

    __table_args__ = (
        Index("ix_execution_runs_project_id", "project_id"),
        Index("ix_execution_runs_test_case_id", "test_case_id"),
        Index("ix_execution_runs_created_at", "created_at")
    )
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    test_case_id = Column(Integer, ForeignKey("test_cases.id"), nullable=False)
    executed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    execution_type = Column(String(20), nullable=False, default="api")
    status = Column(String(20), nullable=False)
    http_status_code = Column(Integer, nullable=True)
    duration_ms = Column(Float, nullable=True)
    assertions = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    request_snapshot=Column(JSON,nullable=True)
    expected_json_fields=Column(JSON,nullable=True)
    expected_status_code=Column(Integer,nullable=True)
