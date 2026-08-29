from __future__ import annotations
from sentence_transformers import SentenceTransformer
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

        if chunk_ids:
            project_id=(self.db.query(Document.project_id).join(DocumentChunk,Document.id==DocumentChunk.document_id).filter(DocumentChunk.id.in_(chunk_ids)).distinct().first()[0])
            document_count=(self.db.query(func.count(Document.id)).filter(Document.project_id==project_id).scalar())
            chunk_count=(self.db.query(func.count(DocumentChunk.id)).join(Document, Document.id==DocumentChunk.document_id).filter(Document.project_id==project_id).scalar())
            embedding_count=(self.db.query(func.count(DocumentEmbedding.id)).join(DocumentChunk, DocumentChunk.id==DocumentEmbedding.chunk_id).join(Document, Document.id==DocumentChunk.document_id).filter(Document.project_id==project_id).scalar())
            ProjectActivityService(self.db).record_activity(project_id=project_id,documents=document_count,chunks=chunk_count,embeddings=embedding_count)
            

                
                
                
                
        return count
