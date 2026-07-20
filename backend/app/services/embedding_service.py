from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding


class EmbeddingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_embeddings(self, chunk_ids: list[int] | None = None) -> int:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            SentenceTransformer = None

        chunks = self.db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids)) if chunk_ids else self.db.query(DocumentChunk).all()

        count = 0
        for chunk in chunks:
            existing = self.db.query(DocumentEmbedding).filter(DocumentEmbedding.chunk_id == chunk.id).first()
            if existing:
                self.db.delete(existing)

            if SentenceTransformer is not None:
                model = SentenceTransformer("all-MiniLM-L6-v2")
                model.encode([chunk.content], normalize_embeddings=True)
            else:
                _ = chunk.content

            embedding_record = DocumentEmbedding(
                chunk_id=chunk.id,
                model_name="all-MiniLM-L6-v2",
                embedding_text=chunk.content,
            )
            self.db.add(embedding_record)
            count += 1

        self.db.commit()
        return count
