from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.embedding_schema import EmbeddingResponse
from app.services.embedding_service import EmbeddingService

router = APIRouter(prefix="/embeddings", tags=["Embeddings"])


@router.post("/regenerate", response_model=EmbeddingResponse)
def regenerate_embeddings(
    document_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> EmbeddingResponse:
    if document_id is not None:
        document = db.query(Document).join(Project).join(Organization).filter(Document.id == document_id).first()
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        if document.project.organization.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to regenerate embeddings")
        chunk_ids = [chunk.id for chunk in db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).all()]
    else:
        chunk_ids = None

    service = EmbeddingService(db)
    generated = service.generate_embeddings(chunk_ids)
    return EmbeddingResponse(generated=generated)
