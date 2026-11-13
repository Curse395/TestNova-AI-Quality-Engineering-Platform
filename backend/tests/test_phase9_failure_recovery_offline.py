import io
import json
import sys
from types import ModuleType
from types import SimpleNamespace

from fastapi import FastAPI, Request
import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

try:
    import groq  # noqa: F401
except ModuleNotFoundError:
    groq = ModuleType("groq")
    for error_name in (
        "APIConnectionError",
        "APIStatusError",
        "APITimeoutError",
        "AuthenticationError",
        "RateLimitError",
    ):
        setattr(groq, error_name, type(error_name, (Exception,), {}))

    class UnavailableGroqClient:
        def __init__(self, **_):
            raise RuntimeError("Groq is not available in this test environment")

    groq.Groq = UnavailableGroqClient
    sys.modules["groq"] = groq

from app.api import uploads
from app.core.exceptions import register_exception_handlers
from app.llm.contracts import (
    GenerationParameters,
    LLMErrorCategory,
    LLMGenerationRequest,
    LLMResponse,
)
from app.llm.providers import gemini
from app.llm.router import LLMRouter
from app.llm.telemetry import InMemoryLLMTelemetryService
from app.models.document_chunk import DocumentChunk
from app.models.test_case import TestCase as CaseModel
from app.schemas.test_case_schema import (
    TestCaseGenerationRequest as GenerationRequest,
)
from app.services.test_case_generation_service import (
    TestCaseGenerationError as GenerationError,
    TestCaseGenerationService as GenerationService,
)


class EmptyQuery:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def filter(self, *_):
        return self

    def join(self, *_):
        return self

    def order_by(self, *_):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class RecordingSession:
    def __init__(self, existing_cases=()):
        self.existing_cases = list(existing_cases)
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0

    def query(self, model):
        return EmptyQuery(self.existing_cases if model is CaseModel else ())

    def add(self, value):
        self.added.append(value)

    def flush(self):
        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class FailingCommitSession(RecordingSession):
    def __init__(self):
        super().__init__()
        self.next_id = 1

    def query(self, model):
        if model is CaseModel:
            return EmptyQuery(self.existing_cases)
        if model is DocumentChunk:
            return EmptyQuery([SimpleNamespace(id=17)])
        return EmptyQuery()

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self.next_id
                self.next_id += 1

    def commit(self):
        self.commit_count += 1
        raise RuntimeError("offline simulated commit failure")

    def rollback(self):
        self.rollback_count += 1
        self.added.clear()


def _generation_service(session, response):
    service = GenerationService.__new__(GenerationService)
    service.db = session
    service._retrieve_chunks = lambda *_: [
        {
            "chunk_id": 17,
            "document_id": 101,
            "document_name": "requirements.txt",
            "content": "Users can sign in using registered credentials.",
        }
    ]
    service.llm_service = SimpleNamespace(
        generate_content=lambda **_: response() if callable(response) else response
    )
    return service


def _candidate(evidence_chunk_ids=(17,)):
    return {
        "title": "Successful sign in",
        "description": "Verify sign in with valid credentials.",
        "category": "positive",
        "priority": "high",
        "severity": "high",
        "preconditions": "A registered account exists.",
        "steps": [
            {
                "action": "Submit valid credentials.",
                "expected_result": "The credentials are accepted.",
            }
        ],
        "expected_result": "The user reaches the authenticated area.",
        "evidence_chunk_ids": list(evidence_chunk_ids),
        "requirement_keys": [],
    }


def test_upload_stream_does_not_remove_a_preexisting_file(tmp_path):
    existing = tmp_path / "existing.pdf"
    existing.write_bytes(b"existing valid content")

    with pytest.raises(FileExistsError):
        uploads._write_upload_stream(
            io.BytesIO(b"new upload"),
            existing,
        )

    assert existing.read_bytes() == b"existing valid content"


def test_provider_failure_has_bounded_generation_attempts_and_saves_no_rows():
    session = RecordingSession()
    calls = []

    def fail_provider(**_):
        calls.append("call")
        return {
            "success": False,
            "stage": "provider_request",
            "error": "Provider request failed",
        }

    service = _generation_service(session, fail_provider)

    with pytest.raises(GenerationError, match="provider_request"):
        service.generate(
            user_id=7,
            project_id=2,
            request=GenerationRequest(
                requirements_prompt="Generate a sign-in test."
            ),
        )

    assert len(calls) == service.MAX_GENERATION_ATTEMPTS
    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.parametrize(
    "answer",
    [
        json.dumps([{key: value for key, value in _candidate().items() if key != "title"}]),
        json.dumps([_candidate(evidence_chunk_ids=(999,))]),
    ],
)
def test_invalid_generation_output_never_saves_partial_test_cases(answer):
    existing_case = SimpleNamespace(
        id=1,
        title="Existing case",
        expected_result="Existing expected result",
        category="positive",
        requirement_links=[],
    )
    session = RecordingSession(existing_cases=[existing_case])
    service = _generation_service(
        session,
        {"success": True, "answer": answer},
    )

    generated = service.generate(
        user_id=7,
        project_id=2,
        request=GenerationRequest(
            requirements_prompt="Generate a sign-in test.",
            max_cases=1,
        ),
    )

    assert generated == []
    assert session.existing_cases == [existing_case]
    assert all(not isinstance(row, CaseModel) for row in session.added)
    assert session.commit_count == 1


def test_malformed_provider_output_raises_without_saving_rows():
    session = RecordingSession()
    service = _generation_service(
        session,
        {"success": True, "answer": "{not json"},
    )

    with pytest.raises(GenerationError, match="json_parse"):
        service.generate(
            user_id=7,
            project_id=2,
            request=GenerationRequest(
                requirements_prompt="Generate a sign-in test."
            ),
        )

    assert session.added == []
    assert session.commit_count == 0


def test_generation_commit_failure_rolls_back_pending_rows():
    session = FailingCommitSession()
    service = _generation_service(
        session,
        {"success": True, "answer": json.dumps([_candidate()])},
    )

    with pytest.raises(GenerationError, match="persistence") as failure:
        service.generate(
            user_id=7,
            project_id=2,
            request=GenerationRequest(
                requirements_prompt="Generate a sign-in test.",
                max_cases=1,
            ),
        )

    assert session.rollback_count == 1
    assert session.added == []
    assert session.commit_count == 1, repr(failure.value.__cause__)


def test_gemini_timeout_is_bounded_and_returns_a_sanitized_failure(monkeypatch, caplog):
    captured = {}

    class FakeClient:
        models = SimpleNamespace(
            generate_content=lambda **_: (_ for _ in ()).throw(
                httpx.ReadTimeout("private prompt and credential details")
            )
        )

    provider = gemini.GeminiProvider(
        api_key="offline-placeholder",
        model_name="offline-model",
        client=FakeClient(),
    )
    request = LLMGenerationRequest(
        provider="gemini",
        model="offline-model",
        system_prompt="private system prompt",
        user_prompt="private user prompt",
        generation_parameters=GenerationParameters(
            temperature=0.2,
            max_output_tokens=10,
            top_p=0.9,
            top_k=10,
        ),
    )

    result = provider.generate(request)

    assert result.success is False
    assert result.error_details.category is LLMErrorCategory.TIMEOUT
    assert result.error == "Gemini provider request failed"
    assert "private prompt" not in caplog.text
    assert "credential details" not in str(result)

    def create_client(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr(gemini.settings, "LLM_TIMEOUT_SECONDS", 0.25)
    monkeypatch.setattr(gemini.genai, "Client", create_client)
    gemini.GeminiProvider(api_key="offline-placeholder", model_name="offline-model")
    assert captured["http_options"].timeout == 250
    assert captured["http_options"].retry_options.attempts == 1


def test_network_interruption_uses_only_one_fallback_attempt():
    class InterruptedClient:
        models = SimpleNamespace(
            generate_content=lambda **_: (_ for _ in ()).throw(
                httpx.ConnectError("private connection details")
            )
        )

    class FallbackProvider:
        provider_name = "groq"
        model_name = "fallback-model"

        def __init__(self):
            self.calls = 0

        def generate(self, request):
            self.calls += 1
            return LLMResponse(
                provider=self.provider_name,
                model=request.model,
                success=True,
                text="offline fallback result",
                stage="complete",
                request_id=request.request_id,
            )

    primary = gemini.GeminiProvider(
        api_key="offline-placeholder",
        model_name="primary-model",
        client=InterruptedClient(),
    )
    fallback = FallbackProvider()
    request = LLMGenerationRequest(
        provider="gemini",
        model="primary-model",
        system_prompt="private system prompt",
        user_prompt="private user prompt",
        generation_parameters=GenerationParameters(
            temperature=0.2,
            max_output_tokens=10,
            top_p=0.9,
            top_k=10,
        ),
    )

    result = LLMRouter(
        primary,
        fallback,
        telemetry_service=InMemoryLLMTelemetryService(),
    ).generate(request)

    assert result.success is True
    assert result.provider == "groq"
    assert fallback.calls == 1


def test_database_error_response_does_not_expose_exception_details(caplog):
    import asyncio

    app = FastAPI()
    register_exception_handlers(app)
    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/protected",
            "raw_path": b"/protected",
            "query_string": b"",
            "headers": [],
            "client": ("192.0.2.1", 1234),
            "server": ("test", 80),
        }
    )
    handler = app.exception_handlers[SQLAlchemyError]
    error = SQLAlchemyError("offline dsn contains password=private-value")

    response = asyncio.run(handler(request, error))

    assert response.status_code == 500
    assert b"Database operation failed" in response.body
    assert b"private-value" not in response.body
    assert "private-value" not in caplog.text
