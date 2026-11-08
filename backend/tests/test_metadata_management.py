import json
from types import SimpleNamespace

from app.core.config import settings
from app.api.uploads import DocumentSourceType
from app.models.document_chunk import DocumentChunk
from app.models.project import Project
from app.models.test_case import TestCase as _TestCase
from app.models.test_case_evidence import TestCaseEvidence as _TestCaseEvidence
from app.models.test_case_generation_run import (
    TestCaseGenerationRun as _TestCaseGenerationRun,
)
from app.models.user import User as _User
from app.schemas.test_case_schema import TestCaseGenerationRequest as GenerationRequest
from app.services.document_processing_service import DocumentProcessingService
from app.services.model_service import ModelService
from app.services.retrieval_service import RetrievalService


class _Query:
    def __init__(self, *, first_result=None, rows=()):
        self.first_result = first_result
        self.rows = rows

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_criteria):
        return self

    def first(self):
        return self.first_result

    def order_by(self, *_orders):
        return self

    def limit(self, _value):
        return self

    def all(self):
        return list(self.rows)


class _RetrievalSession:
    def __init__(self):
        self.project_query = _Query(first_result=SimpleNamespace(id=4))
        chunk = SimpleNamespace(
            id=30,
            document_id=20,
            content="API paths and operations",
            source_metadata={},
        )
        document = SimpleNamespace(
            id=20,
            filename="api-catalogue.json",
            source_type="api_catalogue",
            content_type="application/json",
            uploaded_at=None,
            uploaded_by_user_id=7,
            processing_status="completed",
        )
        self.results_query = _Query(
            rows=[(chunk, document, "test-model", 0.1)]
        )

    def query(self, *entities):
        return self.project_query if entities[0] is Project else self.results_query


class _ProcessingQuery:
    def filter(self, *_criteria):
        return self

    def all(self):
        return []


class _ProcessingSession:
    def __init__(self):
        self.added = []
        self.commits = 0

    def query(self, *_entities):
        return _ProcessingQuery()

    def add(self, item):
        self.added.append(item)

    def delete(self, _item):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _process_file(service, path, *, source_type="document"):
    document = SimpleNamespace(
        id=1,
        filename=path.name,
        storage_path=str(path),
        source_type=source_type,
    )
    service.process_document(document)
    return service.db.added


def test_api_catalogue_source_type_is_accepted_by_upload_retrieval_and_generation(
    monkeypatch,
):
    assert DocumentSourceType("api_catalogue") is DocumentSourceType.API_CATALOGUE
    request = GenerationRequest(
        requirements_prompt="Generate API tests",
        source_types=["api_catalogue"],
    )
    assert request.source_types == ["api_catalogue"]

    monkeypatch.setattr(ModelService, "encode_embedding", lambda _text: [0.1] * 384)
    results = RetrievalService(_RetrievalSession()).search_project_context(
        current_user_id=7,
        project_id=4,
        query="API paths",
        source_types=["api_catalogue"],
    )
    assert len(results) == 1
    assert results[0]["source_type"] == "api_catalogue"


def test_csv_row_locations_are_persisted_with_generated_chunks(tmp_path):
    path = tmp_path / "catalogue.csv"
    path.write_text("id,name\n1,Alice\n2,Bob\n", encoding="utf-8")
    session = _ProcessingSession()

    chunks = _process_file(DocumentProcessingService(session), path)

    assert len(chunks) == 1
    assert chunks[0].source_metadata["source_location"] == {
        "row_start": 1,
        "row_end": 3,
    }


def test_csv_multiline_record_location_stays_with_each_chunk(tmp_path, monkeypatch):
    path = tmp_path / "multiline.csv"
    path.write_text('"alpha\nbeta"\ngamma\n', encoding="utf-8")
    monkeypatch.setattr(settings, "CHUNK_SIZE_WORDS", 1)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP_WORDS", 0)
    session = _ProcessingSession()

    chunks = _process_file(DocumentProcessingService(session), path)

    assert [chunk.content for chunk in chunks] == ["alpha", "beta", "gamma"]
    assert [
        chunk.source_metadata["source_location"] for chunk in chunks
    ] == [
        {"row_start": 1, "row_end": 2},
        {"row_start": 1, "row_end": 2},
        {"row_start": 3, "row_end": 3},
    ]


def test_json_paths_are_persisted_with_generated_chunks(tmp_path):
    payload = {
        "paths": {"/health": {"get": {"summary": "Health check"}}},
        "servers": [{"url": "https://api.example.test"}],
    }
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    session = _ProcessingSession()
    service = DocumentProcessingService(session)

    assert service.parse_document(str(path)) == json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
    )
    chunks = _process_file(service, path)

    assert '"Health check"' in chunks[0].content
    assert '$["paths"]["/health"]["get"]["summary"]' in (
        chunks[0].source_metadata["source_location"]["json_paths"]
    )
    assert '$["servers"][0]["url"]' in (
        chunks[0].source_metadata["source_location"]["json_paths"]
    )
    assert chunks[0].source_metadata["chunk_index"] == 0


def test_json_path_is_attached_to_the_chunk_containing_its_value(
    tmp_path,
    monkeypatch,
):
    payload = {"paths": {"/health": {"get": {"summary": "Health check"}}}}
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings, "CHUNK_SIZE_WORDS", 1)
    monkeypatch.setattr(settings, "CHUNK_OVERLAP_WORDS", 0)
    session = _ProcessingSession()

    chunks = _process_file(DocumentProcessingService(session), path)

    summary_path = '$["paths"]["/health"]["get"]["summary"]'
    value_chunks = [
        chunk
        for chunk in chunks
        if "Health" in chunk.content or "check" in chunk.content
    ]
    assert value_chunks
    assert all(
        summary_path in chunk.source_metadata["source_location"]["json_paths"]
        for chunk in value_chunks
    )


def test_txt_line_locations_are_persisted_with_generated_chunks(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("first line\nsecond line\nthird line\n", encoding="utf-8")
    session = _ProcessingSession()

    chunks = _process_file(DocumentProcessingService(session), path)

    assert len(chunks) == 1
    assert chunks[0].source_metadata["source_location"] == {
        "line_start": 1,
        "line_end": 3,
    }


def test_pdf_page_and_docx_section_locations_remain_available():
    for filename, text, expected in (
        ("report.pdf", "Page 1:\nPDF content", {"page_numbers": [1]}),
        ("guide.docx", "## Authentication\nGuide content", {"section": "Authentication"}),
    ):
        session = _ProcessingSession()
        service = DocumentProcessingService(session)
        service.parse_document_with_locations = lambda _path, content=text: (content, [])
        chunks = _process_file(service, SimpleNamespace(name=filename), source_type="document")

        assert chunks[0].source_metadata["source_location"] == expected


def test_existing_source_types_remain_supported(monkeypatch):
    monkeypatch.setattr(ModelService, "encode_embedding", lambda _text: [0.1] * 384)
    for source_type in (
        "document",
        "requirements",
        "bug_report",
        "test_log",
        "technical_document",
        "api_catalogue",
    ):
        assert DocumentSourceType(source_type).value == source_type
        GenerationRequest(
            requirements_prompt="Generate source tests",
            source_types=[source_type],
        )
        RetrievalService(_RetrievalSession()).search_project_context(
            current_user_id=7,
            project_id=4,
            query="API paths",
            source_types=[source_type],
        )


def test_source_metadata_is_written_to_document_chunks(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("Acceptance criteria are persisted.", encoding="utf-8")
    session = _ProcessingSession()

    chunks = _process_file(
        DocumentProcessingService(session),
        path,
        source_type="requirements",
    )

    assert all(isinstance(chunk, DocumentChunk) for chunk in chunks)
    assert chunks[0].source_metadata["filename"] == "requirements.txt"
    assert chunks[0].source_metadata["source_type"] == "requirements"
    assert chunks[0].source_metadata["source_location"] == {
        "line_start": 1,
        "line_end": 1,
    }
    assert session.commits == 1
