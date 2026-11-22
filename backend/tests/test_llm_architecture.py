from dataclasses import replace
from types import SimpleNamespace

import pytest
from google.genai import types

from app.llm.contracts import (
    GenerationParameters,
    LLMGenerationRequest,
    LLMResponse,
    StructuredOutputConfig,
)
from app.llm.providers import create_provider
from app.llm.providers.gemini import GeminiProvider
from app.services.llm_services import LLMService


PARAMETERS = GenerationParameters(
    temperature=0.2,
    max_output_tokens=4096,
    top_p=0.95,
    top_k=40,
)


def _request(
    *,
    structured_output: StructuredOutputConfig | None = None,
) -> LLMGenerationRequest:
    return LLMGenerationRequest(
        provider="gemini",
        model="gemini-test",
        system_prompt="System instructions",
        user_prompt="User request",
        generation_parameters=PARAMETERS,
        structured_output=structured_output,
    )


def _fake_client(response=None, error: Exception | None = None):
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return response

    return SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content),
    ), calls


def test_provider_contract_carries_prompts_parameters_and_structured_output():
    request = _request(
        structured_output=StructuredOutputConfig("application/json")
    )

    assert request.model == "gemini-test"
    assert request.provider == "gemini"
    assert request.system_prompt == "System instructions"
    assert request.user_prompt == "User request"
    assert request.generation_parameters == PARAMETERS
    assert request.structured_output.response_mime_type == "application/json"


def test_gemini_adapter_maps_request_and_response_without_live_api_call():
    sdk_response = SimpleNamespace(
        text='{"ok":true}',
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
    )
    client, calls = _fake_client(response=sdk_response)
    provider = GeminiProvider(
        api_key="not-a-real-key",
        model_name="configured-model",
        client=client,
    )

    result = provider.generate(
        _request(
            structured_output=StructuredOutputConfig("application/json")
        )
    )

    assert result == LLMResponse(
        provider="gemini",
        model="gemini-test",
        success=True,
        text='{"ok":true}',
        stage="complete",
        finish_reason="STOP",
    )
    assert calls[0]["model"] == "gemini-test"
    assert calls[0]["contents"] == "User request"
    config = calls[0]["config"]
    assert config.system_instruction == "System instructions"
    assert config.response_mime_type == "application/json"
    assert config.temperature == PARAMETERS.temperature
    assert config.max_output_tokens == PARAMETERS.max_output_tokens
    assert config.top_p == PARAMETERS.top_p
    assert config.top_k == PARAMETERS.top_k


def test_gemini_adapter_maps_provider_errors_without_exposing_details():
    client, _ = _fake_client(error=RuntimeError("private response payload"))
    provider = GeminiProvider(
        api_key="not-a-real-key",
        model_name="configured-model",
        client=client,
    )

    result = provider.generate(_request())

    assert result.success is False
    assert result.provider == "gemini"
    assert result.model == "gemini-test"
    assert result.stage == "provider_request"
    assert result.error == "Gemini provider request failed"
    assert result.error_type == "RuntimeError"
    assert "private response payload" not in repr(result)


def test_gemini_adapter_maps_empty_and_unreadable_responses():
    empty_client, _ = _fake_client(
        response=SimpleNamespace(
            text=" ",
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.SAFETY)],
        )
    )
    empty = GeminiProvider("", "configured-model", client=empty_client).generate(
        _request()
    )
    assert empty.success is False
    assert empty.stage == "empty_response"
    assert empty.finish_reason == "SAFETY"

    class UnreadableResponse:
        candidates = [SimpleNamespace(finish_reason=types.FinishReason.OTHER)]

        @property
        def text(self):
            raise RuntimeError("private response payload")

    unreadable_client, _ = _fake_client(response=UnreadableResponse())
    unreadable = GeminiProvider(
        "",
        "configured-model",
        client=unreadable_client,
    ).generate(_request())
    assert unreadable.success is False
    assert unreadable.stage == "response_extraction"
    assert unreadable.finish_reason == "OTHER"
    assert "private response payload" not in repr(unreadable)


def test_provider_factory_selects_configured_gemini(monkeypatch):
    import app.llm.providers as providers

    captured = {}

    class FakeGeminiProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        providers,
        "settings",
        SimpleNamespace(
            LLM_PROVIDER="gemini",
            GEMINI_API_KEY="not-a-real-key",
            GEMINI_MODEL="configured-model",
        ),
    )
    monkeypatch.setattr(providers, "GeminiProvider", FakeGeminiProvider)

    provider = create_provider()

    assert isinstance(provider, FakeGeminiProvider)
    assert captured == {
        "api_key": "not-a-real-key",
        "model_name": "configured-model",
    }


def test_provider_factory_rejects_unimplemented_provider(monkeypatch):
    import app.llm.providers as providers

    monkeypatch.setattr(
        providers,
        "settings",
        SimpleNamespace(LLM_PROVIDER="unknown"),
    )

    with pytest.raises(RuntimeError, match="Unsupported LLM provider"):
        create_provider()


def test_llm_service_injection_and_legacy_generate_content_compatibility(
    monkeypatch,
):
    from app.services import llm_services

    class FakeProvider:
        provider_name = "fake"
        model_name = "fake-model"

        def __init__(self):
            self.request = None

        def generate(self, request):
            self.request = request
            return LLMResponse(
                provider=self.provider_name,
                model=self.model_name,
                success=True,
                text="legacy-compatible answer",
                stage="complete",
            )

    monkeypatch.setattr(
        llm_services,
        "get_default_provider",
        lambda: pytest.fail("Injected provider should bypass default selection"),
    )
    provider = FakeProvider()
    service = LLMService(provider=provider)

    result = service.generate_content(
        system_prompt="System instructions",
        user_prompt="User request",
        response_mime_type="application/json",
    )

    assert result == {
        "success": True,
        "answer": "legacy-compatible answer",
        "provider": "fake",
        "model": "fake-model",
        "stage": "complete",
        "fallback_configured": False,
        "fallback_attempted": False,
        "fallback_eligible": False,
        "provider_attempt_count": 1,
        "retry_count": 0,
    }
    assert provider.request.model == "fake-model"
    assert provider.request.provider == "fake"
    assert provider.request.system_prompt == "System instructions"
    assert provider.request.user_prompt == "User request"
    assert provider.request.structured_output.response_mime_type == "application/json"


def test_llm_service_uses_central_default_provider(monkeypatch):
    from app.services import llm_services

    provider = SimpleNamespace(provider_name="gemini", model_name="configured-model")
    monkeypatch.setattr(llm_services, "get_default_provider", lambda: provider)

    service = LLMService()

    assert service.provider is provider
    assert service.provider_name == "gemini"
    assert service.model_name == "configured-model"


def test_llm_service_standardizes_unexpected_provider_error():
    class RaisingProvider:
        provider_name = "test-provider"
        model_name = "test-model"

        def generate(self, _request):
            raise RuntimeError("private provider response")

    request = replace(
        _request(),
        provider="test-provider",
        model="test-model",
    )
    response = LLMService(provider=RaisingProvider()).generate(request)

    assert response.success is False
    assert response.provider == "test-provider"
    assert response.stage == "provider_request"
    assert response.error == "LLM provider request failed"
    assert "private provider response" not in repr(response)
