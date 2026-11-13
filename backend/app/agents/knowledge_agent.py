from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.services.retrieval_service import RetrievalService


class KnowledgeAgent(BaseAgent):
    name = "knowledge_agent"

    def __init__(self, db):
        self.service = RetrievalService(db)

    def run(self, context: AgentContext) -> AgentResult:
        query = context.inputs.get("query")
        limit = context.inputs.get("limit", 4)

        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code":"INVALID_LIMIT",
                    "message":"Retrival limit must be between 1 and 20"
                }
            )


        document_ids = context.inputs.get("document_ids")

        if document_ids is not None and (not isinstance(document_ids,list) or not document_ids or  any(not isinstance(doc_id,int)or isinstance(doc_id,bool)or doc_id <= 0 for doc_id in document_ids)):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code":"INVALID_DOCUMENT_IDS",
                    "message":"Document IDs must be a non-empty list of positive integers."
                }
            )

        if not isinstance(query, str) or not query.strip():
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "INVALID_QUERY",
                    "message": "A valid search query is required"
                })

        try:
            results = self.service.search_project_context(
                current_user_id=context.user_id,
                project_id=context.project_id,
                query=query.strip(),
                limit=limit,
                document_ids=document_ids,
                source_types=context.inputs.get("source_types"))

            return AgentResult(
                agent_name=self.name,
                status="success" if results else "partial",
                data={
                    "query": query,
                    "retrieved_count": len(results),
                    "chunks": results
                },
                evidence=results,
            )

        except ValueError as exc:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "RETRIEVAL_FAILED",
                    "message": str(exc) or "The project or selected documents could not be accessed."
                })

        except Exception as exc:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "KNOWLEDGE_SEARCH_FAILED",
                    "message": str(exc) or "Knowledge retrieval failed unexpectedly."
                })