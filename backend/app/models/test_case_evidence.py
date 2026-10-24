from datetime import datetime
from sqlalchemy import Column,DateTime,ForeignKey,Integer,UniqueConstraint,Index
from sqlalchemy.orm import relationship
from app.database.connection import Base


class TestCaseEvidence(Base):
    __tablename__="test_case_evidence"
    __table_args__=(UniqueConstraint("test_case_id","chunk_id",name="uq_test_case_evidence_case_chunk"),Index("ix_test_case_evidence_test_case_id", "test_case_id"))

    id=Column(Integer,primary_key=True,index=True)
    test_case_id=Column(Integer,ForeignKey("test_cases.id", ondelete="CASCADE"),nullable=False)
    document_id=Column(Integer,ForeignKey("documents.id"),nullable=False)
    chunk_id=Column(Integer,ForeignKey("document_chunks.id"),nullable=False)
    created_at=Column(DateTime,default=datetime.utcnow,nullable=False)
    test_case=relationship("TestCase",back_populates="evidence")
    document=relationship("Document")
    chunk=relationship("DocumentChunk")