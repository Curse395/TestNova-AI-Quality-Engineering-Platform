from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.agents.contracts import AgentContext
from app.agents.knowledge_agent import KnowledgeAgent
from app.agents.orchestrator import Orchestrator
from app.core.dependencies import CurrentUser
from app.core.rate_limit import limit_requests
from app.database.connection import get_db


router = APIRouter(prefix="/projects", tags=["Knowledge"])


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=4, ge=1, le=20)
    document_ids: list[int] | None = None
    source_types: list[str] | None = None


@router.post(
    "/{project_id}/knowledge/search",
    dependencies=[Depends(limit_requests("knowledge-agent-search", limit=20, window_seconds=60))],
)
def search_knowledge(project_id:int,request:KnowledgeSearchRequest,current_user:CurrentUser,db:Session=Depends(get_db)):
    orchestrator = Orchestrator()
    orchestrator.register("knowledge_search", KnowledgeAgent(db))

    context = AgentContext(
        user_id=current_user.id,
        project_id=project_id,
        task="knowledge_search",
        inputs={
            "query": request.query,
            "limit": request.limit,
            "document_ids": request.document_ids,
            "source_types": request.source_types,
        }
    )

    result = orchestrator.route(context)

    if result.status == "failed":
        error = result.error or {}
        code = error.get("code")

        if code == "RETRIEVAL_FAILED":
            raise HTTPException(status_code=404, detail=error["message"])

        raise HTTPException(status_code=500, detail="Knowledge search failed.")

    return {
        "success": True,
        "message": "Knowledge search completed.",
        "data": result.data,
        "errors": None
    }