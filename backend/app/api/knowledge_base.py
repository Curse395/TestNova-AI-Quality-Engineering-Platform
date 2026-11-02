
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_embedding import DocumentEmbedding
from app.models.organization import Organization
from app.models.project import Project
from app.services.retrieval_service import RetrievalService


router = APIRouter(prefix="/projects/{project_id}/knowledge-base",tags=["Knowledge Base"])


def get_owned_project(
    project_id: int,
    current_user_id: int,
    db: Session,
):
    project = (
        db.query(Project)
        .join(Organization)
        .filter(
            Project.id == project_id,
            Organization.owner_id == current_user_id,
        )
        .first()
    )

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found",
        )

    return project


@router.post("/index")
def index_project_documents(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:

    project = get_owned_project(
        project_id,
        current_user.id,
        db,
    )

    document_count = (
        db.query(Document)
        .filter(Document.project_id == project.id)
        .count()
    )

    chunk_count = (
        db.query(DocumentChunk)
        .join(
            Document,
            Document.id == DocumentChunk.document_id,
        )
        .filter(Document.project_id == project.id)
        .count()
    )

    embedding_count = (
        db.query(DocumentEmbedding)
        .join(
            DocumentChunk,
            DocumentChunk.id == DocumentEmbedding.chunk_id,
        )
        .join(
            Document,
            Document.id == DocumentChunk.document_id,
        )
        .filter(Document.project_id == project.id)
        .count()
    )

    return {
        "success": True,
        "message": "Knowledge base status retrieved successfully",
        "data": {
            "project_id": project.id,
            "documents": document_count,
            "chunks": chunk_count,
            "embeddings": embedding_count,
            "ready_for_search": (
                chunk_count > 0 and embedding_count > 0
            ),
        },
        "errors": None,
    }


@router.get("")
def search_project_documents(
    project_id: int,
    query: str,
    limit: int = Query(default=4, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:

    if not query.strip():
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty",
        )

    get_owned_project(
        project_id,
        current_user.id,
        db,
    )

    retrieval_service = RetrievalService(db)

    try:
        results = retrieval_service.search_project_context(
            current_user_id=current_user.id,
            project_id=project_id,
            query=query.strip(),
            limit=limit,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return {
        "success": True,
        "message": "Knowledge base semantic search completed successfully",
        "data": results,
        "errors": None,
    }
