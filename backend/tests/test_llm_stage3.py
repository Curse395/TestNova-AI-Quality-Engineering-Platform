from types import SimpleNamespace

import httpx
import pytest
from groq import (
    APIStatusError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.contracts import (
    GenerationParameters,
    LLMError,
    LLMErrorCategory,
    LLMGenerationRequest,
    LLMResponse,
    StructuredOutputConfig,
)
from app.llm.providers import gemini
from app.llm.providers.groq import GroqProvider
from app.llm.router import LLMRouter
from app.services.llm_services import LLMService


PARAMETERS = GenerationParameters(
    temperature=0.2,
    max_output_tokens=2048,
    top_p=0.95,
    top_k=40,
)


def _request(
    provider: str = "groq",
    model: str = "groq-test-model",
    *,
    structured_output: StructuredOutputConfig | None = None,
    request_id: str | None = "request-id",
) -> LLMGenerationRequest:
    return LLMGenerationRequest(
        provider=provider,
        model=model,
        system_prompt="System prompt",
        user_prompt="User prompt",
        generation_parameters=PARAMETERS,
        structured_output=structured_output,
        metadata={"operation": "unit-test"},
        request_id=request_id,
    )


def _fake_groq_client(response=None, error: Exception | None = None):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return response

    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    ), calls


def _http_error(error_type, status_code: int):
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return error_type(
        "sensitive provider payload",
        response=response,
        body={"authorization": "sensitive-value"},
    )


def _failed_response(
    provider: str,
    model: str,
    category: LLMErrorCategory,
    *,
    transient: bool = False,
    stage: str = "provider_request",
) -> LLMResponse:
    error = LLMError(
        category=category,
        message="Safe test failure",
        stage=stage,
        provider=provider,
        model=model,
        details={"transient": True} if transient else {},
    )
    return LLMResponse(
        provider=provider,
        model=model,
        success=False,
        text="",
        stage=stage,
        error=error.message,
        error_details=error,
    )


class FakeProvider:
    def __init__(self, provider_name, model_name, responses):
        self.provider_name = provider_name
        self.model_name = model_name
        self.responses = list(responses)
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_groq_request_mapping_success_finish_reason_and_usage():
    response = SimpleNamespace(
        id="groq-response-id",
        model="actual-groq-model",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"ok":true}'),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=13,
            completion_tokens=8,
            total_tokens=21,
        ),
    )
    client, calls = _fake_groq_client(response)
    provider = GroqProvider("not-a-real-key", "configured-model", client=client)

    result = provider.generate(
        _request(
            structured_output=StructuredOutputConfig("application/json")
        )
    )

    assert result.success is True
    assert result.text == '{"ok":true}'
    assert result.finish_reason == "stop"
    assert result.usage_metadata == {
        "prompt_tokens": 13,
        "completion_tokens": 8,
        "total_tokens": 21,
    }
    assert result.input_token_count == 13
    assert result.output_token_count == 8
    assert result.total_token_count == 21
    assert result.request_id == "request-id"
    assert result.metadata["provider_response_id"] == "groq-response-id"
    assert calls[0]["model"] == "groq-test-model"
    assert calls[0]["messages"] == [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "User prompt"},
    ]
    assert calls[0]["temperature"] == PARAMETERS.temperature
    assert calls[0]["top_p"] == PARAMETERS.top_p
    assert calls[0]["max_completion_tokens"] == PARAMETERS.max_output_tokens
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "top_k" not in calls[0]


def test_groq_maps_missing_usage_and_empty_content():
    response = SimpleNamespace(
        id=None,
        choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content=""))],
        usage=None,
    )
    client, _ = _fake_groq_client(response)
    provider = GroqProvider("not-a-real-key", "model", client=client)

    result = provider.generate(_request(request_id="request-id"))

    assert result.success is False
    assert result.stage == "empty_response"
    assert result.error_details.category is LLMErrorCategory.EMPTY_RESPONSE
    assert result.finish_reason == "length"
    assert result.usage_metadata is None
    assert result.input_token_count is None


def test_groq_rejects_unsupported_structured_mime_without_calling_provider():
    client, calls = _fake_groq_client()
    provider = GroqProvider("not-a-real-key", "model", client=client)

    result = provider.generate(
        _request(structured_output=StructuredOutputConfig("text/plain"))
    )

    assert result.success is False
    assert result.stage == "invalid_request"
    assert result.error_details.category is LLMErrorCategory.INVALID_REQUEST
    assert calls == []


@pytest.mark.parametrize(
    ("exception", "category", "transient"),
    [
        (_http_error(AuthenticationError, 401), LLMErrorCategory.AUTHENTICATION, False),
        (_http_error(RateLimitError, 429), LLMErrorCategory.RATE_LIMIT, True),
        (_http_error(APIStatusError, 503), LLMErrorCategory.PROVIDER_API, True),
        (_http_error(APIStatusError, 400), LLMErrorCategory.INVALID_REQUEST, False),
        (
            APITimeoutError(
                request=httpx.Request(
                    "POST", "https://api.groq.com/openai/v1/chat/completions"
                )
            ),
            LLMErrorCategory.TIMEOUT,
            True,
        ),
        (
            APIConnectionError(
                request=httpx.Request(
                    "POST", "https://api.groq.com/openai/v1/chat/completions"
                )
            ),
            LLMErrorCategory.PROVIDER_API,
            True,
        ),
    ],
)
def test_groq_maps_sdk_errors_without_exposing_provider_payload(
    exception,
    category,
    transient,
):
    client, _ = _fake_groq_client(error=exception)
    provider = GroqProvider("not-a-real-key", "model", client=client)

    result = provider.generate(_request())

    assert result.success is False
    assert result.stage == "provider_request"
    assert result.error_details.category is category
    assert result.error_details.details.get("transient", False) is transient
    assert result.error == "Groq provider request failed"
    assert "sensitive provider payload" not in repr(result)
    assert "sensitive-value" not in repr(result)


def test_groq_client_disables_sdk_retries(monkeypatch):
    import app.llm.providers.groq as groq_module

    constructed = {}

    def fake_groq(**kwargs):
        constructed.update(kwargs)
        return object()

    monkeypatch.setattr(groq_module, "Groq", fake_groq)

    GroqProvider("test-only-key", "model")

    assert constructed == {"api_key": "test-only-key", "max_retries": 0}


def test_primary_gemini_factory_does_not_require_groq_key(monkeypatch):
    import app.llm.providers as providers

    captured = {}

    class FakeGemini:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        providers,
        "settings",
        SimpleNamespace(
            LLM_PROVIDER="gemini",
            GEMINI_API_KEY="test-only-key",
            GEMINI_MODEL="gemini-configured",
            GROQ_MODEL="groq-configured",
            GROQ_API_KEY=None,
        ),
    )
    monkeypatch.setattr(providers, "GeminiProvider", FakeGemini)

    result = providers.create_provider()

    assert isinstance(result, FakeGemini)
    assert captured == {
        "api_key": "test-only-key",
        "model_name": "gemini-configured",
    }


def test_settings_keep_gemini_default_and_validate_provider_fallback():
    required = {
        "DATABASE_URL": "sqlite://",
        "GEMINI_API_KEY": "test-only-key",
        "JWT_SECRET_KEY": "test-only-signing-key-not-for-deployment",
    }

    defaults = Settings(**required)
    assert defaults.LLM_PROVIDER == "gemini"
    assert defaults.LLM_FALLBACK_ENABLED is False
    assert defaults.GROQ_API_KEY is None

    with pytest.raises(ValidationError, match="LLM_PROVIDER"):
        Settings(**required, LLM_PROVIDER="unknown")
    with pytest.raises(ValidationError, match="LLM_FALLBACK_PROVIDER"):
        Settings(**required, LLM_FALLBACK_ENABLED=True)
    with pytest.raises(ValidationError, match="must differ"):
        Settings(
            **required,
            LLM_FALLBACK_ENABLED=True,
            LLM_FALLBACK_PROVIDER="gemini",
        )


def test_provider_factory_selects_groq_and_rejects_missing_key(monkeypatch):
    import app.llm.providers as providers

    monkeypatch.setattr(
        providers,
        "settings",
        SimpleNamespace(
            LLM_PROVIDER="gemini",
            GEMINI_API_KEY="test-only-key",
            GEMINI_MODEL="gemini-configured",
            GROQ_MODEL="groq-configured",
            GROQ_API_KEY=None,
        ),
    )
    with pytest.raises(RuntimeError, match="Groq API key is not configured"):
        providers.create_provider("groq")

    captured = {}

    class FakeGroq:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(providers, "GroqProvider", FakeGroq)
    result = providers.create_provider("groq", "explicit-groq-model")
    assert isinstance(result, FakeGroq)
    assert captured == {
        "api_key": None,
        "model_name": "explicit-groq-model",
    }


def test_invalid_provider_and_model_configuration_are_rejected(monkeypatch):
    import app.llm.providers as providers

    monkeypatch.setattr(
        providers,
        "settings",
        SimpleNamespace(
            LLM_PROVIDER="gemini",
            GEMINI_API_KEY="test-only-key",
            GEMINI_MODEL="gemini-configured",
            GROQ_MODEL="groq-configured",
            GROQ_API_KEY=None,
        ),
    )
    with pytest.raises(RuntimeError, match="Unsupported LLM provider"):
        providers.create_provider("unknown")
    with pytest.raises(RuntimeError, match="model is not configured"):
        providers.create_provider("gemini", " ")


def test_llm_service_explicit_provider_and_model_override(monkeypatch):
    from app.services import llm_services

    selected = {}
    provider = FakeProvider("groq", "explicit-model", [])

    def fake_get_provider(name, model):
        selected.update(provider=name, model=model)
        return provider

    monkeypatch.setattr(llm_services, "get_provider", fake_get_provider)
    service = LLMService(provider_name="groq", model_name="explicit-model")

    assert service.provider is provider
    assert selected == {"provider": "groq", "model": "explicit-model"}


def test_router_fallback_disabled_never_constructs_or_calls_fallback():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failed_response(
                "gemini",
                "gemini-model",
                LLMErrorCategory.RATE_LIMIT,
            )
        ],
    )
    router = LLMRouter(primary)

    result = router.generate(_request("gemini", "gemini-model"))

    assert result.error_details.category is LLMErrorCategory.RATE_LIMIT
    assert len(primary.calls) == 1


@pytest.mark.parametrize(
    "category",
    [LLMErrorCategory.RATE_LIMIT, LLMErrorCategory.TIMEOUT],
)
def test_router_fallback_success_after_eligible_failure(category):
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [_failed_response("gemini", "gemini-model", category)],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [
            LLMResponse(
                provider="groq",
                model="groq-model",
                success=True,
                text="fallback answer",
                stage="complete",
                request_id="request-id",
            )
        ],
    )
    router = LLMRouter(primary, fallback)

    result = router.generate(_request("gemini", "gemini-model"))

    assert result.success is True
    assert result.provider == "groq"
    assert result.model == "groq-model"
    assert result.text == "fallback answer"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
    assert fallback.calls[0].provider == "groq"
    assert fallback.calls[0].model == "groq-model"


def test_router_classifies_raised_timeout_as_eligible_and_falls_back_once():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [TimeoutError("private timeout details")],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [
            LLMResponse(
                provider="groq",
                model="groq-model",
                success=True,
                text="fallback answer",
                stage="complete",
            )
        ],
    )

    result = LLMRouter(primary, fallback).generate(
        _request("gemini", "gemini-model")
    )

    assert result.success is True
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_router_preserves_timeout_category_for_raised_timeout():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [TimeoutError("private timeout details")],
    )

    result = LLMRouter(primary).generate(_request("gemini", "gemini-model"))

    assert result.success is False
    assert result.error_details.category is LLMErrorCategory.TIMEOUT
    assert result.error == "LLM provider request failed"


def test_gemini_sdk_retries_are_disabled_for_bounded_fallback(monkeypatch):
    client_options = {}
    fake_client = object()

    def create_client(**kwargs):
        client_options.update(kwargs)
        return fake_client

    monkeypatch.setattr(gemini.genai, "Client", create_client)
    provider = gemini.GeminiProvider("test-key", "gemini-test-model")

    assert provider.client is fake_client
    assert client_options["http_options"].retry_options.attempts == 1


@pytest.mark.parametrize(
    "category",
    [
        LLMErrorCategory.AUTHENTICATION,
        LLMErrorCategory.CONFIGURATION,
        LLMErrorCategory.INVALID_REQUEST,
        LLMErrorCategory.STRUCTURED_OUTPUT_PARSE,
        LLMErrorCategory.SCHEMA_VALIDATION,
    ],
)
def test_router_never_falls_back_for_ineligible_failures(category):
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [_failed_response("gemini", "gemini-model", category)],
    )
    fallback = FakeProvider("groq", "groq-model", [])
    router = LLMRouter(primary, fallback)

    result = router.generate(_request("gemini", "gemini-model"))

    assert result.success is False
    assert result.error_details.category is category
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_router_does_not_fallback_after_successful_invalid_json():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            LLMResponse(
                provider="gemini",
                model="gemini-model",
                success=True,
                text="{invalid json",
                stage="complete",
            )
        ],
    )
    fallback = FakeProvider("groq", "groq-model", [])
    router = LLMRouter(primary, fallback)

    result = router.generate(_request("gemini", "gemini-model"))

    assert result.success is True
    assert result.text == "{invalid json"
    assert fallback.calls == []


def test_router_invalid_provider_model_request_does_not_call_fallback():
    primary = FakeProvider("gemini", "gemini-model", [])
    fallback = FakeProvider("groq", "groq-model", [])
    router = LLMRouter(primary, fallback)

    result = router.generate(_request("gemini", "wrong-model"))

    assert result.success is False
    assert result.stage == "invalid_request"
    assert result.error_details.category is LLMErrorCategory.INVALID_REQUEST
    assert primary.calls == []
    assert fallback.calls == []


def test_router_attempts_fallback_at_most_once_and_reports_both_failures():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failed_response(
                "gemini",
                "gemini-model",
                LLMErrorCategory.RATE_LIMIT,
            )
        ],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [
            _failed_response(
                "groq",
                "groq-model",
                LLMErrorCategory.PROVIDER_API,
                transient=True,
            )
        ],
    )
    router = LLMRouter(primary, fallback)

    result = router.generate(_request("gemini", "gemini-model"))

    assert result.success is False
    assert result.stage == "provider_request"
    assert result.error == "Primary and fallback LLM providers failed"
    assert result.error_details.details["primary_failure_stage"] == "provider_request"
    assert result.error_details.details["fallback_failure_stage"] == "provider_request"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_llm_service_legacy_wrapper_returns_fallback_success_shape(monkeypatch):
    from app.services import llm_services

    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failed_response(
                "gemini",
                "gemini-model",
                LLMErrorCategory.RATE_LIMIT,
            )
        ],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [
            LLMResponse(
                provider="groq",
                model="groq-model",
                success=True,
                text="fallback result",
                stage="complete",
            )
        ],
    )
    monkeypatch.setattr(
        llm_services,
        "get_provider",
        lambda provider_name, model_name: fallback,
    )
    service = LLMService(
        provider=primary,
        fallback_enabled=True,
        fallback_provider_name="groq",
    )

    result = service.generate_content("system", "user")

    assert result == {
        "success": True,
        "answer": "fallback result",
        "model": "groq-model",
        "stage": "complete",
    }


def test_router_falls_back_only_for_marked_transient_provider_api_error():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failed_response(
                "gemini",
                "gemini-model",
                LLMErrorCategory.PROVIDER_API,
            )
        ],
    )
    fallback = FakeProvider("groq", "groq-model", [])

    result = LLMRouter(primary, fallback).generate(
        _request("gemini", "gemini-model")
    )

    assert result.error_details.category is LLMErrorCategory.PROVIDER_API
    assert fallback.calls == []


def test_router_falls_back_for_marked_transient_provider_api_error():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failed_response(
                "gemini",
                "gemini-model",
                LLMErrorCategory.PROVIDER_API,
                transient=True,
            )
        ],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [
            LLMResponse(
                provider="groq",
                model="groq-model",
                success=True,
                text="fallback result",
                stage="complete",
            )
        ],
    )

    result = LLMRouter(primary, fallback).generate(
        _request("gemini", "gemini-model")
    )

    assert result.success is True
    assert result.provider == "groq"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1
