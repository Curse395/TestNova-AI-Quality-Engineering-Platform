from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.assistant_intelligence_service import (
    AssistantProjectIntelligenceService,
    AssistantQuestionRouter,
)
from app.services.chat_service import ChatService
from app.services.repository_architecture_service import RepositoryArchitectureService


def test_router_distinguishes_embedding_counts_and_similarity():
    counts = AssistantQuestionRouter.plan("Which document has the lowest embeddings?")
    similarity = AssistantQuestionRouter.plan(
        "Which retrieved document has the lowest similarity?"
    )

    assert counts.intents == ("documents",)
    assert counts.use_retrieval is False
    assert similarity.retrieval_similarity is True
    assert similarity.use_retrieval is True


def test_embedding_dimension_question_uses_schema_dimension_not_count():
    analytics = MagicMock()
    analytics.get_project_overview.return_value = {"embeddings": 4}
    service = AssistantProjectIntelligenceService(
        db=MagicMock(),
        analytics=analytics,
        project_intelligence=MagicMock(),
        release_readiness=MagicMock(),
        test_execution=MagicMock(),
    )
    question = "What dimensions do the project embeddings use?"

    data = service.collect(
        AssistantQuestionRouter.plan(question),
        current_user_id=7,
        project_id=22,
        question=question,
    )

    assert data["embedding_dimensions"]["dimensions"] == 384
    assert "vector dimension is" in service.format_answer(data, question).lower()


def test_simple_greeting_does_not_trigger_retrieval_or_provider():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    service = ChatService(db)
    service.history_service.get_session = MagicMock(return_value=object())
    service.history_service.save_chat = MagicMock()
    service.retrieval_service.search_project_context = MagicMock()

    response = service.chat(7, 22, "Hello", 3)

    assert "I can help analyze" in response["answer"]
    assert service.llm_service is None
    service.retrieval_service.search_project_context.assert_not_called()


def test_router_resolves_document_metric_follow_up_from_session_context():
    history = [
        SimpleNamespace(
            question="Which document has the fewest embedding records?",
            answer="Per-document counts: MediTrack.pdf has 2 embedding records.",
        )
    ]

    plan = AssistantQuestionRouter.plan("What about its chunks?", history)

    assert plan.intents == ("documents",)
    assert plan.document_follow_up is True


def test_architecture_follow_ups_remain_separate_from_project_chat_context():
    architecture_message = SimpleNamespace(
        question="How does TestGenerationAgent work?",
        answer="Platform source marker: architecture-only detail.",
    )

    follow_up = AssistantQuestionRouter.plan(
        "What about its retry behavior?",
        [architecture_message],
    )
    project_history = AssistantQuestionRouter.project_history([architecture_message])
    document_question = AssistantQuestionRouter.plan(
        "Which document has the fewest embeddings?",
        [architecture_message],
    )

    assert follow_up.architecture is True
    assert project_history == ()
    assert document_question.document_follow_up is False


def test_project_answer_does_not_send_architecture_history_to_llm():
    db = MagicMock()
    architecture_message = SimpleNamespace(
        question="How does TestGenerationAgent work?",
        answer="Platform source marker: architecture-only detail.",
    )
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        architecture_message
    ]
    service = ChatService(db)
    service.history_service.get_session = MagicMock(return_value=object())
    service.history_service.save_chat = MagicMock()
    service.retrieval_service.search_project_context = MagicMock(return_value=[])
    service._generate_content = MagicMock(
        return_value={"success": True, "answer": "Project evidence is unavailable.", "model": "offline-test"}
    )

    service.chat(7, 22, "What does the uploaded document say about login?", 3)

    user_prompt = service._generate_content.call_args.kwargs["user_prompt"]
    assert "Platform source marker" not in user_prompt


def test_architecture_question_uses_only_approved_platform_sources():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    service = ChatService(db)
    service.history_service.get_session = MagicMock(return_value=object())
    service.history_service.save_chat = MagicMock()
    service.architecture_service.search = MagicMock(
        return_value=[
            {
                "chunk_id": 1,
                "document_id": None,
                "document_name": "backend/app/agents/test_generation_agent.py",
                "source_type": "platform_architecture",
                "content": "The agent composes test-case generation.",
            }
        ]
    )
    service.retrieval_service.search_project_context = MagicMock()
    service._generate_content = MagicMock(
        return_value={"success": True, "answer": "It composes generation.", "model": "offline-test"}
    )

    response = service.chat(7, 22, "How does TestGenerationAgent work?", 3)

    assert response["intelligence"]["kind"] == "platform_architecture"
    assert response["sources"][0]["source_type"] == "platform_architecture"
    service.retrieval_service.search_project_context.assert_not_called()


def test_document_metric_follow_up_filters_to_the_prior_document():
    analytics = MagicMock()
    analytics.get_document_statistics.return_value = [
        {"document_id": 1, "filename": "MediTrack.pdf", "chunks": 4, "embeddings": 2},
        {"document_id": 2, "filename": "Other.pdf", "chunks": 8, "embeddings": 5},
    ]
    service = AssistantProjectIntelligenceService(
        db=MagicMock(),
        analytics=analytics,
        project_intelligence=MagicMock(),
        release_readiness=MagicMock(),
        test_execution=MagicMock(),
    )
    history = [
        SimpleNamespace(
            question="Which document has the fewest embedding records?",
            answer="MediTrack.pdf has 2 embedding records.",
        )
    ]

    data = service.collect(
        AssistantQuestionRouter.plan("What about its chunks?", history),
        current_user_id=7,
        project_id=22,
        question="What about its chunks?",
        conversation_history=history,
    )

    assert [row["filename"] for row in data["documents"]["records"]] == ["MediTrack.pdf"]
    assert data["documents"]["records"][0]["chunks"] == 4


def test_document_metrics_report_tied_minima_and_empty_datasets():
    result = AssistantProjectIntelligenceService._document_metrics(
        [
            {"document_id": 1, "filename": "A.pdf", "chunks": 4, "embeddings": 2},
            {"document_id": 2, "filename": "B.pdf", "chunks": 2, "embeddings": 2},
            {"document_id": 3, "filename": "C.pdf", "chunks": 8, "embeddings": 5},
        ]
    )

    assert result["lowest_embedding_count"] == 2
    assert result["highest_embedding_count"] == 5
    assert [
        row["filename"] for row in result["documents_with_highest_embedding_count"]
    ] == ["C.pdf"]
    assert [
        row["filename"] for row in result["documents_with_lowest_embedding_count"]
    ] == ["A.pdf", "B.pdf"]
    assert result["lowest_chunk_count"] == 2
    assert result["highest_chunk_count"] == 8
    assert [
        row["filename"] for row in result["documents_with_highest_chunk_count"]
    ] == ["C.pdf"]
    assert [
        row["filename"] for row in result["documents_with_lowest_chunk_count"]
    ] == ["B.pdf"]
    assert AssistantProjectIntelligenceService._document_metrics([])["records"] == []


def test_document_answer_does_not_conflate_embeddings_chunks_and_similarity():
    response = AssistantProjectIntelligenceService.result_payload(
        {
            "documents": AssistantProjectIntelligenceService._document_metrics(
                [
                    {
                        "document_id": 1,
                        "filename": "README.txt",
                        "chunks": 4,
                        "embeddings": 3,
                        "processing_status": "completed",
                    },
                    {
                        "document_id": 2,
                        "filename": "requirements.pdf",
                        "chunks": 1,
                        "embeddings": 1,
                        "processing_status": "completed",
                    },
                ]
            )
        },
        "Which document has lowest embeddings?",
    )

    assert "requirements.pdf (1)" in response["answer"]
    assert "Embedding-record counts and chunk counts are separate metrics" in response["answer"]
    assert "Retrieval similarity scores are ranking values" in response["answer"]
    assert response["intelligence"]["kind"] == "structured_project_data"


def test_cross_domain_metric_question_keeps_each_structured_result():
    plan = AssistantQuestionRouter.plan(
        "Compare document embedding counts with requirement coverage."
    )
    answer = AssistantProjectIntelligenceService.format_answer(
        {
            "documents": AssistantProjectIntelligenceService._document_metrics(
                [{"document_id": 1, "filename": "A.pdf", "chunks": 2, "embeddings": 2}]
            ),
            "requirements": {
                "explicit_requirements_with_any_case_link": 3,
                "explicit_requirement_count": 4,
                "unlinked_explicit_requirement_count": 1,
                "unlinked_requirements": [{"requirement_key": "REQ-4"}],
            },
        },
        "Compare document embedding counts with requirement coverage.",
    )

    assert plan.intents == ("documents", "requirements")
    assert "A.pdf: 2 embedding records" in answer
    assert "3 of 4 explicit requirements" in answer
    assert "REQ-4" in answer


def test_similarity_comparison_reports_tied_minimum_scores():
    response = AssistantProjectIntelligenceService.answer_retrieval_similarity(
        [
            {"document_name": "A.pdf", "chunk_id": 1, "similarity": 0.9},
            {"document_name": "B.pdf", "chunk_id": 2, "similarity": 0.1},
            {"document_name": "C.pdf", "chunk_id": 3, "similarity": 0.1},
        ]
    )

    assert "A.pdf (chunk 1, 0.900)" in response["answer"]
    assert "B.pdf (chunk 2, 0.100)" in response["answer"]
    assert "C.pdf (chunk 3, 0.100)" in response["answer"]
    assert "not a count of embedding records" in response["answer"]


def test_execution_pass_rate_is_deterministic_and_project_scoped():
    analytics = MagicMock()
    analytics.get_execution_analytics.return_value = {
        "total_runs": 7,
        "status_counts": {
            "passed": 3,
            "failed": 1,
            "error": 2,
            "skipped": 1,
            "other": 0,
            "missing": 0,
            "blank": 0,
        },
    }
    service = AssistantProjectIntelligenceService(
        db=MagicMock(),
        analytics=analytics,
        project_intelligence=MagicMock(),
        release_readiness=MagicMock(),
        test_execution=MagicMock(),
    )

    result = service.collect(
        AssistantQuestionRouter.plan("What was the test execution pass rate?"),
        current_user_id=7,
        project_id=22,
        question="What was the test execution pass rate?",
    )

    assert result["executions"]["pass_rate"] == 75
    assert result["executions"]["pass_rate_denominator"] == 4
    analytics.get_execution_analytics.assert_called_once_with(
        project_id=22,
        current_user_id=7,
    )


def test_structured_data_tool_errors_propagate():
    analytics = MagicMock()
    analytics.get_document_statistics.side_effect = RuntimeError("offline test failure")
    service = AssistantProjectIntelligenceService(
        db=MagicMock(),
        analytics=analytics,
        project_intelligence=MagicMock(),
        release_readiness=MagicMock(),
        test_execution=MagicMock(),
    )

    with pytest.raises(RuntimeError, match="offline test failure"):
        service.collect(
            AssistantQuestionRouter.plan("Which document has the fewest embeddings?"),
            current_user_id=7,
            project_id=22,
            question="Which document has the fewest embeddings?",
        )


def test_structured_chat_skips_retrieval_and_provider_calls():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    service = ChatService(db)
    service.history_service.get_session = MagicMock(return_value=object())
    service.history_service.save_chat = MagicMock()
    service.retrieval_service.search_project_context = MagicMock()
    service.intelligence_service.collect = MagicMock(
        return_value={
            "documents": AssistantProjectIntelligenceService._document_metrics(
                [
                    {
                        "document_id": 10,
                        "filename": "small.pdf",
                        "chunks": 1,
                        "embeddings": 1,
                    }
                ]
            )
        }
    )

    response = service.chat(7, 22, "Which document has the lowest embeddings?", 3)

    assert "small.pdf (1)" in response["answer"]
    assert service.llm_service is None
    service.retrieval_service.search_project_context.assert_not_called()
    service.history_service.save_chat.assert_called_once()


def test_general_rag_response_preserves_source_citations():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    service = ChatService(db)
    service.history_service.get_session = MagicMock(return_value=object())
    service.history_service.save_chat = MagicMock()
    service.retrieval_service.search_project_context = MagicMock(
        return_value=[
            {
                "chunk_id": 5,
                "document_id": 8,
                "document_name": "requirements.pdf",
                "content": "The save action requires confirmation.",
                "source_metadata": {"page_numbers": [2]},
                "similarity": 0.8,
            }
        ]
    )
    service._generate_content = MagicMock(
        return_value={
            "success": True,
            "answer": "The save action requires confirmation.",
            "model": "offline-test",
        }
    )

    response = service.chat(
        7,
        22,
        "What does the project documentation say about saving?",
        3,
    )

    assert response["sources"][0]["document_name"] == "requirements.pdf"
    assert response["sources"][0]["source_metadata"]["page_numbers"] == [2]
    service.history_service.save_chat.assert_called_once()


def test_architecture_search_is_allowlisted_and_redacts_values(tmp_path: Path):
    source = tmp_path / "backend" / "app" / "agents" / "test_generation_agent.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        'class TestGenerationAgent:\n'
        '    api_key = "sample-value"\n'
        '    token = "example-text"\n',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("API_KEY=not-indexed", encoding="utf-8")

    results = RepositoryArchitectureService(tmp_path).search(
        "How does TestGenerationAgent work?"
    )

    assert results
    assert results[0]["source_type"] == "platform_architecture"
    assert "sample-value" not in results[0]["content"]
    assert "example-text" not in results[0]["content"]
    assert "not-indexed" not in results[0]["content"]
    assert results[0]["document_name"] == "backend/app/agents/test_generation_agent.py"
