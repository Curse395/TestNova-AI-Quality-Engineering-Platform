from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.document_processing_schema import DocumentProcessingResponse
from app.services.document_processing_service import DocumentProcessingService

router = APIRouter(prefix="/documents", tags=["Document Processing"])


@router.post("/{document_id}/process", response_model=DocumentProcessingResponse)
def process_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> DocumentProcessingResponse:
    document = db.query(Document).join(Project).join(Organization).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.project.organization.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to process this document")

    service = DocumentProcessingService()
    raw_text = service.parse_document(document.storage_path)
    normalized_text = service.normalize_text(raw_text)
    chunks = service.chunk_text(normalized_text)

    existing_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).all()
    for chunk in existing_chunks:
        db.delete(chunk)

    for index, chunk_text in enumerate(chunks):
        chunk = DocumentChunk(document_id=document.id, chunk_index=index, content=chunk_text)
        db.add(chunk)

    db.commit()
    return DocumentProcessingResponse(document_id=document.id, chunk_count=len(chunks))
