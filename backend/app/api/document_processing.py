from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.document_processing_schema import DocumentProcessingResponse
from app.services.document_processing_service import DocumentProcessingService

router = APIRouter(prefix="/documents", tags=["Document Processing"])


@router.post("/{document_id}/process")
def process_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    document = db.query(Document).join(Project).join(Organization).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.project.organization.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to process this document")

    service = DocumentProcessingService(db)
    payload = DocumentProcessingResponse(**service.process_document(document)).model_dump()
    return {"success": True, "message": "Document processed successfully", "data": payload, "errors": None, **payload}
