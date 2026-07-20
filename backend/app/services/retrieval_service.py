from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project


class RetrievalService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def search_project_context(self, current_user_id: int, project_id: int, query: str, limit: int = 4) -> list[dict[str, object]]:
        project = (
            self.db.query(Project)
            .join(Organization)
            .filter(Project.id == project_id, Organization.owner_id == current_user_id)
            .first()
        )
        if not project:
            raise ValueError("Project not found")

        documents = self.db.query(Document).filter(Document.project_id == project.id).all()
        if not documents:
            return []

        chunks = (
            self.db.query(DocumentChunk)
            .join(Document)
            .filter(Document.project_id == project.id)
            .order_by(DocumentChunk.chunk_index.asc())
            .all()
        )

        scored: list[tuple[float, DocumentChunk]] = []
        normalized_query = query.lower()
        for chunk in chunks:
            content = (chunk.content or "").lower()
            score = content.count(normalized_query) if normalized_query else 0.0
            if score > 0:
                scored.append((float(score), chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[:limit]
        return [
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "score": score,
                "has_embedding": self.db.query(DocumentEmbedding).filter(DocumentEmbedding.chunk_id == chunk.id).first() is not None,
            }
            for score, chunk in selected
        ]
