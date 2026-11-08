import logging
import os
import re
import uuid
from pathlib import Path

from enum import Enum
from sqlalchemy import or_

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_case_evidence import TestCaseEvidence
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
    API_CATALOGUE = "api_catalogue"


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


def _resolve_document_storage_path(storage_path: str, project_id: int) -> Path:
    try:
        upload_root = UPLOAD_ROOT.resolve()
        resolved_path = Path(storage_path).resolve()
        relative_path = resolved_path.relative_to(upload_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The document storage path is outside the upload directory",
        ) from exc

    if (
        len(relative_path.parts) != 2
        or relative_path.parts[0] != str(project_id)
        or Path(storage_path).is_symlink()
        or (upload_root / str(project_id)).is_symlink()
        or (resolved_path.exists() and not resolved_path.is_file())
    ):
        raise HTTPException(
            status_code=400,
            detail="The document storage path is not a valid uploaded file",
        )

    return resolved_path


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
        uploaded_at=document.uploaded_at,
        uploaded_by_user_id=document.uploaded_by_user_id,
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
            uploaded_at=document.uploaded_at,
            uploaded_by_user_id=document.uploaded_by_user_id,
            processing_status=document.processing_status,
            processing_error=document.processing_error,
            source_type=document.source_type,
        ).model_dump()
        for document in documents
    ], "errors": None}


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    try:
        document = (
            db.query(Document)
            .join(Project, Document.project_id == Project.id)
            .join(Organization, Project.organitzation_id == Organization.id)
            .filter(
                Document.id == document_id,
                Organization.owner_id == current_user.id,
            )
            .first()
        )
        if not document:
            db.rollback()
            raise HTTPException(status_code=404, detail="Document not found")

        try:
            storage_path = _resolve_document_storage_path(
                document.storage_path,
                document.project_id,
            )
        except HTTPException:
            db.rollback()
            raise

        chunk_ids = [
            chunk_id
            for (chunk_id,) in db.query(DocumentChunk.id)
            .filter(DocumentChunk.document_id == document.id)
            .all()
        ]
        filename = document.filename

        db.query(TestCaseEvidence).filter(
            or_(
                TestCaseEvidence.document_id == document.id,
                TestCaseEvidence.chunk_id.in_(chunk_ids),
            )
        ).delete(synchronize_session=False)
        if chunk_ids:
            db.query(DocumentEmbedding).filter(
                DocumentEmbedding.chunk_id.in_(chunk_ids)
            ).delete(synchronize_session=False)
            db.query(DocumentChunk).filter(
                DocumentChunk.id.in_(chunk_ids)
            ).delete(synchronize_session=False)
        db.delete(document)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("Document deletion failed for document_id=%s", document_id)
        raise HTTPException(
            status_code=500,
            detail="Document could not be deleted",
        ) from exc

    file_cleanup_warning = None
    try:
        storage_path.unlink()
    except FileNotFoundError:
        file_cleanup_warning = (
            "The database record was deleted, but the uploaded file was already missing."
        )
    except OSError:
        logger.exception(
            "Could not remove uploaded file for document_id=%s",
            document_id,
        )
        file_cleanup_warning = (
            "The document and related database records were deleted, "
            "but the uploaded file could not be removed."
        )

    message = (
        "Document deleted successfully"
        if file_cleanup_warning is None
        else "Document records deleted; file cleanup requires attention"
    )
    return {
        "success": True,
        "message": message,
        "data": {
            "document_id": document_id,
            "filename": filename,
            "file_cleanup_warning": file_cleanup_warning,
        },
        "errors": None,
    }
