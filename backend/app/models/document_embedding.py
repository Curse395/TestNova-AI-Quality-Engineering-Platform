from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database.connection import Base


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    chunk_id = Column(Integer, ForeignKey("document_chunks.id"), nullable=False, unique=True)
    model_name = Column(String, nullable=False)
    embedding_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    chunk = relationship("DocumentChunk", back_populates="embedding")
