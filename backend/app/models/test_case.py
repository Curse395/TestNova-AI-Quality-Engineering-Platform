from datetime import datetime
from sqlalchemy import CheckConstraint,Column,Integer,String,DateTime,ForeignKey,Index,JSON,Text
from sqlalchemy.orm import relationship
from app.database.connection import Base

class TestCase(Base):
    __tablename__ ="test_cases"
    __table_args__=(CheckConstraint("category IN ('positive','negative','boundary','edge')",name="ck_test_case_category"),
                    CheckConstraint("priority IN ('low','medium','high','critical')",name="ck_test_cases_priority"),
                    CheckConstraint("review_status IN ('draft','approved','rejected')",name="ck_test_cases_review_status"),
                    Index("ix_test_cases_project_id","project_id"))
    id=Column(Integer,primary_key=True,index=True)
    project_id=Column(Integer,ForeignKey("projects.id"),nullable=False)
    created_by_user_id=Column(Integer,ForeignKey("users.id"),nullable=False)
    title=Column(String(200),nullable=False)
    description=Column(Text,nullable=False)
    category=Column(String(20),nullable=False)
    priority=Column(String(20),nullable=False)
    preconditions=Column(Text,nullable=True)
    steps=Column(JSON,nullable=False)
    expected_result=Column(Text,nullable=False)
    review_status=Column(String(20),nullable=False,default="draft")
    created_at=Column(DateTime,default=datetime.utcnow,nullable=False)
    updated_at=Column(DateTime,default=datetime.utcnow,onupdate=datetime.utcnow,nullable=False)

    project=relationship("Project")
    created_by=relationship("User")
    evidence=relationship("TestCaseEvidence",back_populates="test_case",cascade="all, delete-orphan")