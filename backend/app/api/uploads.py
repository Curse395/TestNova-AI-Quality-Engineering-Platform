import logging
import os
import re
import uuid
from pathlib import Path

from enum import Enum

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project
from app.schemas.document_schema import DocumentUploadResponse

router = APIRouter(prefix="/uploads", tags=["Uploads"])
UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"
logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "application/csv", "application/vnd.ms-excel"},
    ".json": {"application/json", "text/json", "text/plain"},
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}
UPLOAD_CHUNK_SIZE = 64 * 1024


class DocumentSourceType(str, Enum):
    DOCUMENT = "document"
    REQUIREMENTS = "requirements"
    BUG_REPORT = "bug_report"
    TEST_LOG = "test_log"
    TECHNICAL_DOCUMENT = "technical_document"


def _safe_original_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="A filename is required")

    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    basename = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()
    if not basename or basename in {".", ".."} or len(basename) > 255:
        raise HTTPException(status_code=400, detail="A valid filename is required")
    return basename


def _validate_upload(filename: str, content_type: str | None) -> str:
    extension = Path(filename).suffix.lower()
    allowed_types = SUPPORTED_MIME_TYPES.get(extension)
    if allowed_types is None:
        raise HTTPException(status_code=415, detail="Unsupported document format")

    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    accepted_types = allowed_types | {"application/octet-stream"}
    if extension in {".docx", ".xlsx"}:
        accepted_types.add("application/zip")
    if extension == ".csv":
        accepted_types.add("text/plain")
    if normalized_type and normalized_type not in accepted_types:
        raise HTTPException(
            status_code=415,
            detail="The uploaded content type does not match the file format",
        )
    return normalized_type or "application/octet-stream"


@router.post("/")
def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    source_type: DocumentSourceType = Form(default=DocumentSourceType.DOCUMENT),
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    original_filename = _safe_original_filename(file.filename)
    content_type = _validate_upload(original_filename, file.content_type)
    target_dir = UPLOAD_ROOT / str(project.id)
    storage_path = target_dir / f"{uuid.uuid4().hex}{Path(original_filename).suffix.lower()}"
    temporary_path: Path | None = None
    committed = False

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = target_dir / f".{uuid.uuid4().hex}.upload"
        total_size = 0
        with temporary_path.open("xb") as handle:
            while True:
                content = file.file.read(UPLOAD_CHUNK_SIZE)
                if not content:
                    break
                total_size += len(content)
                if total_size > settings.MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="The uploaded file exceeds the maximum allowed size",
                    )
                handle.write(content)

        if total_size == 0:
            raise HTTPException(status_code=400, detail="Empty files are not allowed")

        os.replace(temporary_path, storage_path)

        document = Document(
            filename=original_filename,
            content_type=content_type,
            storage_path=str(storage_path),
            project_id=project.id,
            source_type=source_type.value,
            uploaded_by_user_id=current_user.id,
        )
        db.add(document)
        db.commit()
        committed = True
        db.refresh(document)
    except HTTPException:
        db.rollback()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if not committed:
            storage_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        for path in (temporary_path, storage_path if not committed else None):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not clean up failed upload for project_id=%s", project.id)
        logger.exception("Document upload failed for project_id=%s", project.id)
        if isinstance(exc, (OSError, SQLAlchemyError)):
            raise HTTPException(status_code=500, detail="Document upload failed") from exc
        raise

    payload = DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        project_id=document.project_id,
        processing_status=document.processing_status,
        processing_error=document.processing_error,
        source_type=document.source_type,
    ).model_dump()
    return {"success": True, "message": "Document uploaded successfully", "data": payload, "errors": None, **payload}


@router.get("/project/{project_id}")
def list_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    documents = db.query(Document).filter(Document.project_id == project.id).all()
    return {"success": True, "message": "Documents retrieved successfully", "data": [
        DocumentUploadResponse(
            id=document.id,
            filename=document.filename,
            content_type=document.content_type,
            project_id=document.project_id,
            processing_status=document.processing_status,
            processing_error=document.processing_error,
            source_type=document.source_type,
        ).model_dump()
        for document in documents
    ], "errors": None}
