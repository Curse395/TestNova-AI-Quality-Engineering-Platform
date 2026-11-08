import pytest

from app.services.context_builder_service import ContextBuilderService


def test_context_deduplicates_chunks_and_preserves_source_attribution():
    chunks = [
        {
            "chunk_id": 1,
            "document_id": 10,
            "document_name": "requirements.pdf",
            "source_type": "requirements",
            "source_metadata": {"page_numbers": [2]},
            "content": "The save action shows a confirmation.",
            "similarity": 0.8,
        },
        {
            "chunk_id": 1,
            "document_id": 10,
            "document_name": "requirements.pdf",
            "content": "The save action shows a confirmation.",
        },
        {
            "chunk_id": 2,
            "document_id": 11,
            "document_name": "acceptance.txt",
            "content": "The save action shows a confirmation.",
        },
    ]

    payload = ContextBuilderService().build_context(chunks, token_budget=100)

    assert payload["chunk_count"] == 2
    assert payload["sources"][0]["chunk_id"] == 1
    assert payload["sources"][0]["source_metadata"]["page_numbers"] == [2]
    assert payload["sources"][0]["excerpt"] == "The save action shows a confirmation."
    assert "document_id=10; chunk_id=1" in payload["context"]
    assert "document_id=11; chunk_id=2" in payload["context"]
    assert payload["context"].count("The save action shows a confirmation.") == 2


def test_context_skips_unavailable_metadata_and_respects_budget():
    payload = ContextBuilderService().build_context(
        [
            {"chunk_id": 1, "content": "A" * 100},
            {
                "chunk_id": 2,
                "document_id": 3,
                "document_name": "small.txt",
                "source_metadata": None,
                "content": "short content",
            },
        ],
        token_budget=25,
    )

    assert payload["chunk_count"] == 1
    assert payload["sources"][0]["source_metadata"] == {}
    with pytest.raises(ValueError, match="at least one"):
        ContextBuilderService().build_context([], token_budget=0)
