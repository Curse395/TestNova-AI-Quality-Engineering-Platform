import logging
from sqlalchemy.orm import Session
from app.services.model_service import ModelService
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project

logger=logging.getLogger(__name__)

class RetrievalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search_project_context(self, current_user_id: int, project_id: int, query: str, limit: int = 4,document_ids:list[int] | None=None) -> list[dict[str, object]]:
        project = (
            self.db.query(Project)
            .join(Organization)
            .filter(Project.id == project_id, Organization.owner_id == current_user_id)
            .first()
        )
        if not project:
            raise ValueError("Project not found")

        if document_ids is not None:
            if not document_ids:
                raise ValueError("Select at least one document")

            owned_document_ids={
                row[0]
                for row in (self.db.query(Document.id).filter(Document.project_id==project_id,Document.id.in_(document_ids)).all())
            }

            if owned_document_ids != set(document_ids):
                raise ValueError("one or more selected documents do not belong ti this project")

        model=ModelService.get_embedding_model()
        query_embedding=model.encode(query,normalize_embeddings=True).tolist()

        results = (
    self.db.query(
        DocumentChunk,
        Document,
        DocumentEmbedding.embedding.cosine_distance(query_embedding).label("score")
    )
    .join(DocumentEmbedding, DocumentEmbedding.chunk_id == DocumentChunk.id)
    .join(Document, Document.id == DocumentChunk.document_id)
    .filter(Document.project_id == project.id)
    .order_by(
        DocumentEmbedding.embedding.cosine_distance(query_embedding)
    )
    .limit(limit)
    .all()
)

        logger.info(
            "Project retrieval complete: project_id=%s matched_chunks=%d",
            project_id,
            len(results),
        )
        return [
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "document_name": document.filename,
                "content": chunk.content,
                "score": float(score),
                "has_embedding": True,
            }
            for chunk, document, score in results
        ]
