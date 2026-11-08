from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.dependencies import CurrentUser
from app.core.responses import ApiResponse
from app.database.connection import get_db
from app.services.context_builder_service import ContextBuilderService
from app.services.retrieval_service import (
    RetrievalService,
    UnsupportedSourceTypeError,
)

router = APIRouter(prefix="/retrieval", tags=["Retrieval"])


@router.get("/context")
def get_project_context(
    project_id: int,
    query: str,
    limit: int = Query(default=4, ge=1, le=100),
    source_types: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = None,
) -> ApiResponse:
    try:
        retrieval_service = RetrievalService(db)
        retrieved_chunks = retrieval_service.search_project_context(
            current_user.id,
            project_id,
            query,
            limit=limit,
            source_types=source_types,
        )
    except UnsupportedSourceTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    builder = ContextBuilderService()
    payload = builder.build_context(retrieved_chunks)
    return {"success": True, "message": "Context retrieved successfully", "data": payload, "errors": None, **payload}
