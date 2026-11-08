from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project
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

    claimed = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.processing_status != "processing",
        )
        .update(
            {
                Document.processing_status: "processing",
                Document.processing_error: None,
            },
            synchronize_session=False,
        )
    )
    if not claimed:
        raise HTTPException(status_code=409, detail="Document processing is already in progress")
    db.commit()
    db.refresh(document)

    service = DocumentProcessingService(db)
    try:
        result = service.process_document(document)
    except (OSError, ValueError, RuntimeError) as exc:
        db.rollback()
        document.processing_status = "failed"
        document.processing_error = str(exc)
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        document.processing_status = "failed"
        document.processing_error = "Document processing failed unexpectedly."
        db.commit()
        raise

    document.processing_status = "completed"
    document.processing_error = None
    db.commit()
    payload = DocumentProcessingResponse(**result).model_dump()
    return {"success": True, "message": "Document processed successfully", "data": payload, "errors": None, **payload}
