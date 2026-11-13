import logging
import json
import os
import re
import uuid
import zipfile
from pathlib import Path

from enum import Enum
from typing import BinaryIO
from sqlalchemy import or_

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.authorization import get_owned_document, get_owned_project
from app.core.config import settings
from app.core.dependencies import CurrentUser
from app.core.file_storage import (
    UPLOAD_ROOT,
    resolve_document_storage_path as _resolve_document_storage_path,
)
from app.core.responses import ApiResponse
from app.core.rate_limit import limit_requests
from app.database.connection import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.test_case_evidence import TestCaseEvidence
from app.schemas.document_schema import DocumentUploadResponse

router = APIRouter(prefix="/uploads", tags=["Uploads"])
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
MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_OFFICE_COMPRESSION_RATIO = 100
MAX_OFFICE_ARCHIVE_MEMBERS = 10_000


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
    canonical_types = {
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".pdf": "application/pdf",
        ".docx": (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        ".xlsx": (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    }
    return canonical_types[extension]


def _validate_file_content(path: Path, filename: str) -> None:
    extension = Path(filename).suffix.lower()
    try:
        if extension in {".txt", ".csv", ".json"}:
            content = path.read_bytes()
            decoded = content.decode("utf-8-sig")
            if "\x00" in decoded:
                raise ValueError("Binary content is not allowed")
            if extension == ".json":
                json.loads(decoded)
            return

        if extension == ".pdf":
            with path.open("rb") as stream:
                if stream.read(5) != b"%PDF-":
                    raise ValueError("Invalid PDF signature")
            return

        required_member = (
            "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
        )
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            uncompressed_size = sum(member.file_size for member in members)
            if (
                required_member not in archive.namelist()
                or len(members) > MAX_OFFICE_ARCHIVE_MEMBERS
                or uncompressed_size > MAX_OFFICE_UNCOMPRESSED_BYTES
                or any(
                    member.file_size > 0
                    and (
                        member.compress_size == 0
                        or member.file_size
                        > member.compress_size * MAX_OFFICE_COMPRESSION_RATIO
                    )
                    for member in members
                )
            ):
                raise ValueError("Invalid or oversized Office document")
    except (
        OSError,
        UnicodeError,
        zipfile.BadZipFile,
        ValueError,
        RecursionError,
        RuntimeError,
    ) as exc:
        logger.info(
            "Uploaded file content validation failed: extension=%s error_type=%s",
            extension,
            type(exc).__name__,
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=415,
            detail="The uploaded file content is invalid for its file format",
        ) from exc


def _write_upload_stream(source: BinaryIO, path: Path) -> int:
    total_size = 0
    created = False
    try:
        with path.open("xb") as handle:
            created = True
            while True:
                content = source.read(UPLOAD_CHUNK_SIZE)
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
        return total_size
    except Exception:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                logger.error(
                    "Failed upload temporary-file cleanup: error_type=%s",
                    type(cleanup_error).__name__,
                    extra={"error_type": type(cleanup_error).__name__},
                )
        raise


@router.post(
    "/",
    dependencies=[Depends(limit_requests("document-upload", limit=10, window_seconds=60))],
)
def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    source_type: DocumentSourceType = Form(default=DocumentSourceType.DOCUMENT),
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    project = get_owned_project(db, project_id, current_user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    original_filename = _safe_original_filename(file.filename)
    content_type = _validate_upload(original_filename, file.content_type)
    target_dir = UPLOAD_ROOT / str(project.id)
    storage_path = target_dir / f"{uuid.uuid4().hex}{Path(original_filename).suffix.lower()}"
    temporary_path: Path | None = None
    storage_created = False
    committed = False

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        _resolve_document_storage_path(
            str(target_dir / f"{uuid.uuid4().hex}.tmp"),
            project.id,
        )
        temporary_path = target_dir / f".{uuid.uuid4().hex}.upload"
        total_size = _write_upload_stream(file.file, temporary_path)
        _validate_file_content(temporary_path, original_filename)
        os.link(temporary_path, storage_path)
        storage_created = True
        temporary_path.unlink()

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
        logger.info(
            "Document upload completed: project_id=%s document_id=%s size_bytes=%s",
            project.id,
            document.id,
            total_size,
        )
    except HTTPException:
        db.rollback()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        if storage_created and not committed:
            storage_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        for path in (
            temporary_path,
            storage_path if storage_created and not committed else None,
        ):
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
    project = get_owned_project(db, project_id, current_user.id)
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
        document = get_owned_document(
            db,
            document_id,
            current_user.id,
            for_update=True,
        )
        if not document:
            db.rollback()
            raise HTTPException(status_code=404, detail="Document not found")
        if document.processing_status == "processing":
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Document processing is already in progress",
            )

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
