from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.authorization import get_owned_document
from app.core.dependencies import CurrentUser
from app.core.file_storage import resolve_document_storage_path
from app.core.responses import ApiResponse
from app.core.rate_limit import limit_requests
from app.database.connection import get_db
from app.models.document import Document
from app.schemas.document_processing_schema import DocumentProcessingResponse
from app.services.document_processing_service import DocumentProcessingService

router = APIRouter(prefix="/documents", tags=["Document Processing"])


@router.post(
    "/{document_id}/process",
    dependencies=[Depends(limit_requests("document-process", limit=5, window_seconds=60))],
)
def process_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    document = get_owned_document(db, document_id, current_user.id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        document.storage_path = str(
            resolve_document_storage_path(
                document.storage_path,
                document.project_id,
            )
        )
    except HTTPException as exc:
        raise HTTPException(
            status_code=404,
            detail="Document not found",
        ) from exc

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
        document.processing_error = "Document processing failed validation."
        db.commit()
        raise HTTPException(
            status_code=422,
            detail="The document could not be processed.",
        ) from exc
    except Exception as exc:
        db.rollback()
        document.processing_status = "failed"
        document.processing_error = "Document processing failed unexpectedly."
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="The document could not be processed.",
        ) from exc

    document.processing_status = "completed"
    document.processing_error = None
    db.commit()
    payload = DocumentProcessingResponse(**result).model_dump()
    return {"success": True, "message": "Document processed successfully", "data": payload, "errors": None, **payload}
