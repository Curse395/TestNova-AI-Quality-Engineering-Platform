from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database.connection import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)
    processing_status = Column(
        String(20),
        nullable=False,
        default="uploaded",
        server_default="uploaded",
    )
    processing_error = Column(Text, nullable=True)
    source_type = Column(
        String(30),
        nullable=False,
        default="document",
        server_default="document",
    )
    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("users.id", name="fk_documents_uploaded_by_user_id_users"),
        nullable=True,
    )

    project = relationship("Project", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
