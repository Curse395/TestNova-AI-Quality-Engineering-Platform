from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types
from pydantic import BaseModel, Field

from app.llm.contracts import (
    GenerationParameters,
    LLMConfigurationException,
    LLMError,
    LLMErrorCategory,
    LLMGenerationRequest,
    LLMResponse,
    StructuredOutputConfig,
)
from app.llm.providers.gemini import GeminiProvider
from app.llm.structured_output import validate_structured_output
from app.services.llm_services import LLMService


class OutputSchema(BaseModel):
    name: str = Field(min_length=1)
    count: int = Field(ge=0)


def _request(
    *,
    request_id: str | None = "request-123",
    metadata: dict | None = None,
) -> LLMGenerationRequest:
    return LLMGenerationRequest(
        provider="gemini",
        model="test-model",
        system_prompt="System",
        user_prompt="User",
        generation_parameters=GenerationParameters(
            temperature=0.2,
            max_output_tokens=4096,
            top_p=0.95,
            top_k=40,
        ),
        structured_output=StructuredOutputConfig(
            response_mime_type="application/json"
        ),
        metadata=metadata or {},
        request_id=request_id,
    )


def _client(response=None, error: Exception | None = None):
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return response

    return SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ), calls


def _provider(response=None, error: Exception | None = None):
    client, calls = _client(response=response, error=error)
    return GeminiProvider(
        api_key="test-only-not-a-real-key",
        model_name="test-model",
        client=client,
    ), calls


def test_request_contract_validates_values_and_keeps_optional_metadata():
    request = _request(request_id=None, metadata={"task": "test"})

    assert request.request_id is None
    assert request.metadata == {"task": "test"}
    with pytest.raises(ValueError):
        GenerationParameters(
            temperature=-1,
            max_output_tokens=0,
            top_p=1.1,
            top_k=0,
        )
    with pytest.raises(ValueError):
        LLMGenerationRequest(
            provider=" ",
            model="model",
            system_prompt="system",
            user_prompt="user",
            generation_parameters=request.generation_parameters,
        )


def test_response_and_error_contracts_allow_missing_usage():
    response = LLMResponse(
        provider="gemini",
        model="test-model",
        success=True,
        text="answer",
        stage="complete",
    )
    assert response.usage_metadata is None
    assert response.input_token_count is None
    assert response.output_token_count is None
    assert response.total_token_count is None
    assert response.request_id is None

    error = LLMError(
        category=LLMErrorCategory.TIMEOUT,
        message="Provider request timed out",
        stage="provider_request",
        provider="gemini",
    )
    failure = LLMResponse(
        provider="gemini",
        model="test-model",
        success=False,
        text="",
        stage=error.stage,
        error=error.message,
        error_details=error,
    )
    assert failure.error_details.category is LLMErrorCategory.TIMEOUT


def test_configuration_exception_contains_provider_neutral_error():
    error = LLMConfigurationException("gemini", "Gemini API key is not configured")

    assert error.error.category is LLMErrorCategory.CONFIGURATION
    assert error.error.provider == "gemini"
    assert "Gemini API key is not configured" == str(error)


def test_structured_output_validates_json_and_pydantic_schema():
    result = validate_structured_output('{"name":"suite","count":2}', OutputSchema)

    assert result.success is True
    assert result.value == OutputSchema(name="suite", count=2)
    assert result.error is None


def test_structured_output_reports_json_parse_error_without_repair():
    result = validate_structured_output('{"name":', OutputSchema)

    assert result.success is False
    assert result.value is None
    assert result.error.category is LLMErrorCategory.STRUCTURED_OUTPUT_PARSE
    assert result.error.stage == "structured_output_parse"


def test_structured_output_reports_empty_text_separately():
    result = validate_structured_output("  ", OutputSchema)

    assert result.success is False
    assert result.error.category is LLMErrorCategory.EMPTY_RESPONSE
    assert result.error.stage == "empty_response"


def test_structured_output_reports_sanitized_schema_validation_details():
    result = validate_structured_output(
        '{"name":"","count":-1,"api_key":"do-not-return"}',
        OutputSchema,
    )

    assert result.success is False
    assert result.value is None
    assert result.error.category is LLMErrorCategory.SCHEMA_VALIDATION
    validation_errors = result.error.details["validation_errors"]
    assert {item["path"] for item in validation_errors} == {"name", "count"}
    assert all("do-not-return" not in str(item) for item in validation_errors)


def test_gemini_maps_usage_metadata_and_request_identifier():
    sdk_response = SimpleNamespace(
        text='{"name":"suite","count":2}',
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=7,
            total_token_count=19,
            thoughts_token_count=2,
        ),
        response_id="provider-response-1",
        model_version="gemini-version",
    )
    provider, calls = _provider(sdk_response)

    result = provider.generate(_request(metadata={"purpose": "test"}))

    assert result.success is True
    assert result.finish_reason == "STOP"
    assert result.usage_metadata == {
        "prompt_token_count": 12,
        "candidates_token_count": 7,
        "total_token_count": 19,
        "thoughts_token_count": 2,
    }
    assert result.input_token_count == 12
    assert result.output_token_count == 7
    assert result.total_token_count == 19
    assert result.request_id == "request-123"
    assert result.metadata == {
        "purpose": "test",
        "provider_response_id": "provider-response-1",
        "model_version": "gemini-version",
    }
    assert calls[0]["config"].response_mime_type == "application/json"


def test_gemini_handles_missing_usage_metadata_without_fabrication():
    sdk_response = SimpleNamespace(
        text="answer",
        candidates=[],
        usage_metadata=None,
    )
    provider, _ = _provider(sdk_response)

    result = provider.generate(_request(request_id=None))

    assert result.success is True
    assert result.usage_metadata is None
    assert result.input_token_count is None
    assert result.output_token_count is None
    assert result.total_token_count is None
    assert result.request_id is None


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (errors.APIError(401, {"message": "secret provider payload"}), LLMErrorCategory.AUTHENTICATION),
        (errors.APIError(429, {"message": "secret provider payload"}), LLMErrorCategory.RATE_LIMIT),
        (errors.APIError(504, {"message": "secret provider payload"}), LLMErrorCategory.TIMEOUT),
        (httpx.ReadTimeout("private timeout detail"), LLMErrorCategory.TIMEOUT),
        (RuntimeError("private provider detail"), LLMErrorCategory.PROVIDER_API),
    ],
)
def test_gemini_maps_provider_exception_categories_safely(exception, category):
    provider, _ = _provider(error=exception)

    result = provider.generate(_request())

    assert result.success is False
    assert result.stage == "provider_request"
    assert result.error_details.category is category
    assert result.error == "Gemini provider request failed"
    assert "secret provider payload" not in repr(result)
    assert "private provider detail" not in repr(result)


def test_gemini_empty_and_unreadable_responses_have_standard_errors():
    empty_provider, _ = _provider(
        SimpleNamespace(
            text="",
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.SAFETY)],
        )
    )
    empty = empty_provider.generate(_request())
    assert empty.stage == "empty_response"
    assert empty.error_details.category is LLMErrorCategory.EMPTY_RESPONSE
    assert empty.finish_reason == "SAFETY"

    class Unreadable:
        candidates = []

        @property
        def text(self):
            raise RuntimeError("private extraction details")

    extraction_provider, _ = _provider(Unreadable())
    extraction = extraction_provider.generate(_request())
    assert extraction.stage == "response_extraction"
    assert extraction.error_details.category is LLMErrorCategory.INVALID_RESPONSE
    assert "private extraction details" not in repr(extraction)


def test_legacy_generate_content_preserves_success_and_failure_shapes(monkeypatch):
    from app.services import llm_services

    provider, _ = _provider(
        SimpleNamespace(text="answer", candidates=[], usage_metadata=None)
    )
    monkeypatch.setattr(llm_services, "get_default_provider", lambda: provider)
    telemetry = SimpleNamespace(record_request=lambda _records: None)
    service = LLMService(telemetry_service=telemetry)
    success = service.generate_content("system", "user", "application/json")
    assert success == {
        "success": True,
        "answer": "answer",
        "provider": "gemini",
        "model": "test-model",
        "stage": "complete",
        "fallback_configured": False,
        "fallback_attempted": False,
        "fallback_eligible": False,
        "provider_attempt_count": 1,
        "retry_count": 0,
    }

    failed_provider, _ = _provider(error=RuntimeError("private details"))
    service = LLMService(
        provider=failed_provider,
        telemetry_service=telemetry,
    )
    failure = service.generate_content("system", "user")
    assert failure == {
        "success": False,
        "answer": "",
        "provider": "gemini",
        "model": "test-model",
        "stage": "provider_request",
        "error": "Gemini provider request failed",
        "error_category": "provider_api",
        "error_type": "RuntimeError",
        "fallback_configured": False,
        "fallback_attempted": False,
        "fallback_eligible": False,
        "provider_attempt_count": 1,
        "retry_count": 0,
    }
