from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database.connection import Base


class TestCaseRequirement(Base):
    __test__ = False

    __tablename__ = "test_case_requirements"
    __table_args__ = (
        UniqueConstraint(
            "test_case_id",
            "requirement_id",
            name="uq_test_case_requirements_case_requirement",
        ),
    )

    id = Column(Integer, primary_key=True)
    test_case_id = Column(
        Integer,
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id = Column(
        Integer,
        ForeignKey("project_requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    test_case = relationship("TestCase", back_populates="requirement_links")
    requirement = relationship("ProjectRequirement")

