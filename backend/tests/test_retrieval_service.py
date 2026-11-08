from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.retrieval import get_project_context
from app.models.project import Project
from app.services.model_service import ModelService
from app.services.retrieval_service import (
    RetrievalService,
    UnsupportedSourceTypeError,
)


class FakeQuery:
    def __init__(self, *, first_result=None, rows=(), captured=None):
        self.first_result = first_result
        self.rows = rows
        self.captured = captured if captured is not None else {
            "filters": [],
            "orders": [],
            "limit": None,
        }

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *criteria):
        self.captured["filters"].extend(criteria)
        return self

    def first(self):
        return self.first_result

    def order_by(self, *orders):
        self.captured["orders"].extend(orders)
        return self

    def limit(self, value):
        self.captured["limit"] = value
        return self

    def all(self):
        return list(self.rows)


class FakeSession:
    def __init__(self, rows=(), project=True):
        self.captured = {"filters": [], "orders": [], "limit": None}
        self.project_query = FakeQuery(
            first_result=SimpleNamespace(id=4) if project else None
        )
        self.results_query = FakeQuery(rows=rows, captured=self.captured)

    def query(self, *entities):
        if entities[0] is Project:
            return self.project_query
        return self.results_query


def test_retrieval_returns_cosine_similarity_and_metadata(monkeypatch):
    chunk = SimpleNamespace(
        id=30,
        document_id=20,
        content="Acceptance criteria are searchable.",
        source_metadata=None,
    )
    document = SimpleNamespace(
        id=20,
        filename="requirements.md",
        source_type="requirements",
        content_type="text/markdown",
        uploaded_at=None,
        uploaded_by_user_id=7,
        processing_status="completed",
    )
    session = FakeSession(rows=[(chunk, document, "all-MiniLM-L6-v2", 0.2)])
    encoded_queries = []
    monkeypatch.setattr(
        ModelService,
        "encode_embedding",
        lambda text: encoded_queries.append(text) or [0.1] * 384,
    )

    results = RetrievalService(session).search_project_context(
        current_user_id=7,
        project_id=4,
        query="requirements",
        limit=100,
        source_types=["requirements"],
        min_similarity=0.5,
    )

    assert encoded_queries == ["requirements"]
    assert session.captured["limit"] == 20
    assert len(session.captured["orders"]) == 1
    assert len(session.captured["filters"]) == 4
    assert results == [
        {
            "chunk_id": 30,
            "document_id": 20,
            "document_name": "requirements.md",
            "source_type": "requirements",
            "content_type": "text/markdown",
            "uploaded_at": None,
            "uploaded_by_user_id": 7,
            "processing_status": "completed",
            "source_metadata": {},
            "content": "Acceptance criteria are searchable.",
            "score": 0.2,
            "similarity": 0.8,
            "distance": 0.2,
            "embedding_model": "all-MiniLM-L6-v2",
            "has_embedding": True,
        }
    ]


def test_retrieval_returns_empty_list_when_no_rows(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        ModelService,
        "encode_embedding",
        lambda _text: [0.1] * 384,
    )

    assert RetrievalService(session).search_project_context(
        current_user_id=7,
        project_id=4,
        query="not found",
        limit=2,
    ) == []


def test_retrieval_rejects_unauthorized_project_before_encoding(monkeypatch):
    session = FakeSession(project=False)
    monkeypatch.setattr(
        ModelService,
        "encode_embedding",
        lambda _text: pytest.fail("Unauthorized project should not be encoded"),
    )

    with pytest.raises(ValueError, match="Project not found"):
        RetrievalService(session).search_project_context(
            current_user_id=7,
            project_id=4,
            query="secret",
        )


def test_retrieval_rejects_unsupported_source_type_as_validation_error(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        ModelService,
        "encode_embedding",
        lambda _text: pytest.fail("Invalid source type should fail before encoding"),
    )

    with pytest.raises(UnsupportedSourceTypeError, match="source types are unsupported"):
        RetrievalService(session).search_project_context(
            current_user_id=7,
            project_id=4,
            query="requirements",
            source_types=["unknown"],
        )


def test_retrieval_endpoint_returns_400_for_unsupported_source_type(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(
        ModelService,
        "encode_embedding",
        lambda _text: pytest.fail("Invalid source type should fail before encoding"),
    )

    with pytest.raises(HTTPException) as exc_info:
        get_project_context(
            project_id=4,
            query="requirements",
            source_types=["unknown"],
            db=session,
            current_user=SimpleNamespace(id=7),
        )

    assert exc_info.value.status_code == 400


def test_retrieval_endpoint_keeps_404_for_missing_or_unauthorized_project(
    monkeypatch,
):
    session = FakeSession(project=False)
    monkeypatch.setattr(
        ModelService,
        "encode_embedding",
        lambda _text: pytest.fail("Unauthorized project should not be encoded"),
    )

    with pytest.raises(HTTPException) as exc_info:
        get_project_context(
            project_id=4,
            query="requirements",
            db=session,
            current_user=SimpleNamespace(id=7),
        )

    assert exc_info.value.status_code == 404
