from unittest.mock import MagicMock
from app.agents.contracts import AgentContext
from app.agents.knowledge_agent import KnowledgeAgent


def create_agent():
    agent = KnowledgeAgent(db=MagicMock())
    agent.service.search_project_context = MagicMock()
    return agent


def create_context(inputs):
    return AgentContext(
        user_id=1,
        project_id=10,
        task="knowledge_search",
        inputs=inputs
    )


def test_knowledge_agent_successful_retrieval():
    agent = create_agent()

    chunks = [
        {
            "chunk_id": 1,
            "document_id": 5,
            "content": "Login requirements",
            "score": 0.15
        }
    ]

    agent.service.search_project_context.return_value = chunks
    result = agent.run(create_context({"query": "login requirements"}))
    assert result.status == "success"
    assert result.data["retrieved_count"] == 1
    assert result.data["chunks"] == chunks
    assert result.evidence == chunks


def test_knowledge_agent_rejects_empty_query():
    agent = create_agent()
    result = agent.run(create_context({"query": "  "}))
    assert result.status == "failed"
    assert result.error["code"] == "INVALID_QUERY"
    agent.service.search_project_context.assert_not_called()


def test_knowledge_agent_rejects_invalid_limit():
    agent = create_agent()

    result = agent.run(create_context({"query": "login", "limit": 25}))

    assert result.status == "failed"
    assert result.error["code"] == "INVALID_LIMIT"
    agent.service.search_project_context.assert_not_called()


def test_knowledge_agent_rejects_invalid_document_ids():
    agent = create_agent()

    result = agent.run(create_context({"query": "login", "document_ids": []}))

    assert result.status == "failed"
    assert result.error["code"] == "INVALID_DOCUMENT_IDS"
    agent.service.search_project_context.assert_not_called()


def test_knowledge_agent_handles_retrieval_value_error():
    agent = create_agent()
    agent.service.search_project_context.side_effect = ValueError("Access denied")

    result = agent.run(create_context({"query": "login"}))

    assert result.status == "failed"
    assert result.error["code"] == "RETRIEVAL_FAILED"


def test_knowledge_agent_handles_unexpected_error():
    agent = create_agent()
    agent.service.search_project_context.side_effect = RuntimeError("Database error")

    result = agent.run(create_context({"query": "login"}))

    assert result.status == "failed"
    assert result.error["code"] == "KNOWLEDGE_SEARCH_FAILED"


def test_knowledge_agent_handles_no_matching_chunks():
    agent = create_agent()
    agent.service.search_project_context.return_value = []

    result = agent.run(create_context({"query": "unknown feature"}))

    assert result.status == "partial"
    assert result.data["retrieved_count"] == 0
    assert result.evidence == []