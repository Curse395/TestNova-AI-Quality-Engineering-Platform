from __future__ import annotations
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session
from app.services.model_service import ModelService
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding



class EmbeddingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_embeddings(self, chunk_ids: list[int] | None = None) -> int:

        chunks = self.db.query(DocumentChunk).filter(DocumentChunk.id.in_(chunk_ids)) if chunk_ids else self.db.query(DocumentChunk).all()

        count = 0
        for chunk in chunks:

            model=ModelService.get_embedding_model()
            embedding=model.encode(chunk.content,normalize_embeddings=True).tolist()
            existing = (self.db.query(DocumentEmbedding).filter(DocumentEmbedding.chunk_id == chunk.id).first())
            if existing:
                existing.embedding=embedding
                existing.model_name="all-MiniLM-L6-v2"
            else:
                self.db.add(
                    DocumentEmbedding(
                        chunk_id=chunk.id,
                        model_name="all-MiniLM-L6-v2",
                        embedding=embedding,
                    )
                )

            count += 1

        self.db.commit()
        return count
