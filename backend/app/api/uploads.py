from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.shemas.document_schema import DocumentUploadRequest, DocumentUploadResponse

router = APIRouter(prefix="/uploads", tags=["Uploads"])
UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


@router.post("/", response_model=DocumentUploadResponse)
def upload_document(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> DocumentUploadResponse:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    target_dir = UPLOAD_ROOT / str(project.id)
    target_dir.mkdir(parents=True, exist_ok=True)

    storage_path = target_dir / file.filename
    with storage_path.open("wb") as handle:
        handle.write(file.file.read())

    document = Document(
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(storage_path),
        project_id=project.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        content_type=document.content_type,
        storage_path=document.storage_path,
        project_id=document.project_id,
    )


@router.get("/project/{project_id}", response_model=list[DocumentUploadResponse])
def list_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> list[DocumentUploadResponse]:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    documents = db.query(Document).filter(Document.project_id == project.id).all()
    return [
        DocumentUploadResponse(
            id=document.id,
            filename=document.filename,
            content_type=document.content_type,
            storage_path=document.storage_path,
            project_id=document.project_id,
        )
        for document in documents
    ]
