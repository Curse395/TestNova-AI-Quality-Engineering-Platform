from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.models.document import Document
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/projects/{project_id}/knowledge-base", tags=["Knowledge Base"])


@router.post("/index")
def index_project_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> dict[str, int]:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    documents = db.query(Document).filter(Document.project_id == project.id).all()
    chunk_count = 0
    for document in documents:
        content = read_text_content(document.storage_path)
        if content:
            chunk_count += max(1, len(content.split()))

    return {"project_id": project.id, "chunks": chunk_count}


@router.get("")
def search_project_documents(
    project_id: int,
    query: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> list[dict[str, str]]:
    project = (
        db.query(Project)
        .join(Organization)
        .filter(Project.id == project_id, Organization.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    results: list[dict[str, str]] = []
    for document in db.query(Document).filter(Document.project_id == project.id).all():
        content = read_text_content(document.storage_path)
        if not content:
            continue
        if query.lower() in content.lower():
            results.append(
                {
                    "document_name": document.filename,
                    "excerpt": content[:200],
                }
            )

    return results


def read_text_content(storage_path: str) -> str:
    try:
        with open(storage_path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        return ""
