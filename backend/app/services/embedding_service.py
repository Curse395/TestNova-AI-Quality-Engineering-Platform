from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from app.services.model_service import ModelService
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.document import Document
from app.services.project_activity_service import ProjectActivityService



class EmbeddingService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def generate_embeddings(
        self,
        *,
        project_id: int,
        chunk_ids: list[int] | None = None,
    ) -> int:
        if chunk_ids == []:
            return 0

        chunks_query = (
            self.db.query(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.project_id == project_id)
        )
        if chunk_ids is not None:
            chunks_query = chunks_query.filter(DocumentChunk.id.in_(chunk_ids))
        chunks = chunks_query.all()

        count = 0
        if not chunks:
            return 0

        model = ModelService.get_embedding_model()
        try:
            for chunk in chunks:
                embedding = model.encode(
                    chunk.content,
                    normalize_embeddings=True,
                ).tolist()
                if len(embedding) != ModelService.EMBEDDING_DIMENSIONS:
                    raise ValueError("Embedding model returned an unexpected vector dimension")

                existing = (
                    self.db.query(DocumentEmbedding)
                    .filter(DocumentEmbedding.chunk_id == chunk.id)
                    .first()
                )
                if existing:
                    existing.embedding = embedding
                    existing.model_name = ModelService.EMBEDDING_MODEL_NAME
                else:
                    self.db.add(
                        DocumentEmbedding(
                            chunk_id=chunk.id,
                            model_name=ModelService.EMBEDDING_MODEL_NAME,
                            embedding=embedding,
                        )
                    )

                count += 1

            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        document_count = (
            self.db.query(func.count(Document.id))
            .filter(Document.project_id == project_id)
            .scalar()
        )
        chunk_count = (
            self.db.query(func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.project_id == project_id)
            .scalar()
        )
        embedding_count = (
            self.db.query(func.count(DocumentEmbedding.id))
            .join(DocumentChunk, DocumentChunk.id == DocumentEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .filter(Document.project_id == project_id)
            .scalar()
        )
        ProjectActivityService(self.db).record_activity(
            project_id=project_id,
            documents=document_count,
            chunks=chunk_count,
            embeddings=embedding_count,
        )
        return count
