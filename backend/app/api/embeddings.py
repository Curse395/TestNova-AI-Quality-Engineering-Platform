from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.schemas.embedding_schema import EmbeddingResponse
from app.services.embedding_service import EmbeddingService

router = APIRouter(prefix="/embeddings", tags=["Embeddings"])


@router.post("/regenerate")
def regenerate_embeddings(
    project_id: int,
    document_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if document_id is not None:
        document = (
            db.query(Document)
            .filter(Document.id == document_id, Document.project_id == project.id)
            .first()
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        chunk_ids = [
            row[0]
            for row in db.query(DocumentChunk.id)
            .filter(DocumentChunk.document_id == document.id)
            .all()
        ]
    else:
        chunk_ids = None

    service = EmbeddingService(db)
    generated = service.generate_embeddings(project_id=project.id, chunk_ids=chunk_ids)
    payload = EmbeddingResponse(generated=generated).model_dump()
    return {"success": True, "message": "Embeddings generated successfully", "data": payload, "errors": None, **payload}
