from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.llm.contracts import (
    GenerationParameters,
    LLMError,
    LLMErrorCategory,
    LLMGenerationRequest,
    LLMResponse,
)
from app.llm.router import LLMRouter
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.telemetry import (
    InMemoryLLMTelemetryService,
)
from app.services.llm_services import LLMService


PARAMETERS = GenerationParameters(
    temperature=0.2,
    max_output_tokens=128,
    top_p=0.95,
    top_k=40,
)


@pytest.fixture(autouse=True)
def disable_retry_sleep_and_file_telemetry(monkeypatch):
    monkeypatch.setattr("app.llm.router.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "app.llm.router.get_default_telemetry_service",
        InMemoryLLMTelemetryService,
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


class FailingTelemetryService:
    def record_request(self, attempts):
        raise RuntimeError("internal collector failure")


def _success(
    provider,
    model,
    *,
    input_tokens=10,
    output_tokens=5,
    total_tokens=15,
    text="generated text",
):
    return LLMResponse(
        provider=provider,
        model=model,
        success=True,
        text=text,
        stage="complete",
        input_token_count=input_tokens,
        output_token_count=output_tokens,
        total_token_count=total_tokens,
        request_id="response-request-id",
    )


def _failure(provider, model, category):
    error = LLMError(
        category=category,
        message="safe provider failure",
        stage="provider_request",
        provider=provider,
        model=model,
    )
    return LLMResponse(
        provider=provider,
        model=model,
        success=False,
        text="",
        stage="provider_request",
        error=error.message,
        error_details=error,
    )


def _request(provider, model, request_id="correlation-id"):
    return LLMGenerationRequest(
        provider=provider,
        model=model,
        system_prompt="system prompt",
        user_prompt="user prompt",
        generation_parameters=PARAMETERS,
        request_id=request_id,
    )


@pytest.mark.parametrize("provider_name", ["gemini", "groq"])
def test_llm_service_collects_successful_provider_telemetry(provider_name):
    model = f"{provider_name}-test-model"
    if provider_name == "gemini":
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=lambda **kwargs: SimpleNamespace(
                    text="generated text",
                    candidates=[],
                    usage_metadata=SimpleNamespace(
                        prompt_token_count=10,
                        candidates_token_count=5,
                        total_token_count=15,
                    ),
                )
            )
        )
        provider = GeminiProvider("test-only-key", model, client=client)
    else:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    message=SimpleNamespace(content="generated text"),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: response,
                )
            )
        )
        provider = GroqProvider(None, model, client=client)
    telemetry = InMemoryLLMTelemetryService()
    service = LLMService(
        provider=provider,
        fallback_enabled=False,
        telemetry_service=telemetry,
    )

    result = service.generate_content("system prompt", "user prompt")

    assert result == {
        "success": True,
        "answer": "generated text",
        "provider": provider_name,
        "model": model,
        "stage": "complete",
        "fallback_configured": False,
        "fallback_attempted": False,
        "fallback_eligible": False,
        "provider_attempt_count": 1,
        "retry_count": 0,
        "input_token_count": 10,
        "output_token_count": 5,
        "total_token_count": 15,
    }
    record = telemetry.get_recent_records()[0]
    assert record.provider == provider_name
    assert record.model == model
    assert record.success is True
    assert record.request_id is None
    assert record.request_timestamp.utcoffset().total_seconds() == 0
    assert record.completion_timestamp >= record.request_timestamp
    assert record.latency_ms >= 0
    assert record.primary_provider == provider_name
    assert record.final_provider == provider_name
    assert record.fallback_attempted is False


@pytest.mark.parametrize(
    "category",
    [LLMErrorCategory.TIMEOUT, LLMErrorCategory.RATE_LIMIT],
)
def test_failed_calls_capture_error_category_and_missing_usage(category):
    provider = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failure("gemini", "gemini-model", category),
            _failure("gemini", "gemini-model", category),
        ],
    )
    telemetry = InMemoryLLMTelemetryService()
    result = LLMRouter(provider, telemetry_service=telemetry).generate(
        _request("gemini", "gemini-model")
    )

    assert result.success is False
    record = telemetry.get_recent_records()[0]
    assert record.success is False
    assert record.error_category == category.value
    assert record.input_token_count is None
    assert record.output_token_count is None
    summary = telemetry.get_summary()
    assert summary.total_input_tokens is None
    assert summary.total_output_tokens is None


def test_raised_timeout_is_captured_as_timeout_without_error_message():
    provider = FakeProvider(
        "gemini",
        "gemini-model",
        [
            TimeoutError("sensitive exception details"),
            TimeoutError("sensitive exception details"),
        ],
    )
    telemetry = InMemoryLLMTelemetryService()

    LLMRouter(provider, telemetry_service=telemetry).generate(
        _request("gemini", "gemini-model")
    )

    record = telemetry.get_recent_records()[0]
    assert record.success is False
    assert record.error_category == LLMErrorCategory.TIMEOUT.value
    assert not hasattr(record, "error_message")
    assert "sensitive exception details" not in repr(record)
    assert len(telemetry.get_recent_records()) == 2


def test_fallback_tracks_both_attempts_and_final_provider():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failure("gemini", "gemini-model", LLMErrorCategory.RATE_LIMIT),
            _failure("gemini", "gemini-model", LLMErrorCategory.RATE_LIMIT),
        ],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [_success("groq", "groq-model", input_tokens=20, output_tokens=8)],
    )
    telemetry = InMemoryLLMTelemetryService()
    result = LLMRouter(primary, fallback, telemetry).generate(
        _request("gemini", "gemini-model")
    )

    assert result.success is True
    assert result.provider == "groq"
    records = telemetry.get_recent_records()
    assert len(records) == 3
    assert [record.attempt_number for record in records] == [1, 2, 3]
    assert [record.is_fallback_attempt for record in records] == [False, False, True]
    assert all(record.fallback_attempted for record in records)
    assert all(record.fallback_succeeded for record in records)
    assert all(record.primary_provider == "gemini" for record in records)
    assert all(record.final_provider == "groq" for record in records)
    assert records[0].request_id == "correlation-id"
    assert records[2].request_id == "correlation-id"


def test_fallback_failure_is_recorded_separately_and_request_fails():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failure("gemini", "gemini-model", LLMErrorCategory.TIMEOUT),
            _failure("gemini", "gemini-model", LLMErrorCategory.TIMEOUT),
        ],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [_failure("groq", "groq-model", LLMErrorCategory.PROVIDER_API)],
    )
    telemetry = InMemoryLLMTelemetryService()

    result = LLMRouter(primary, fallback, telemetry).generate(
        _request("gemini", "gemini-model")
    )

    assert result.success is False
    records = telemetry.get_recent_records()
    assert len(records) == 3
    assert all(not record.request_success for record in records)
    summary = telemetry.get_summary()
    assert summary.total_calls == 3
    assert summary.failed_calls == 3
    assert summary.total_requests == 1
    assert summary.failed_requests == 1
    assert summary.fallback_attempts == 1
    assert summary.fallback_successes == 0
    assert summary.fallback_success_rate == 0
    assert all(record.final_provider == "groq" for record in records)


def test_cost_calculation_uses_configured_per_million_token_rates():
    telemetry = InMemoryLLMTelemetryService(
        {
            "gemini": {
                "gemini-model": {
                    "input_per_million_tokens": 2.0,
                    "output_per_million_tokens": 4.0,
                }
            }
        },
        currency="USD",
    )
    provider = FakeProvider(
        "gemini",
        "gemini-model",
        [_success("gemini", "gemini-model", input_tokens=1000, output_tokens=500)],
    )

    LLMRouter(provider, telemetry_service=telemetry).generate(
        _request("gemini", "gemini-model")
    )

    record = telemetry.get_recent_records()[0]
    assert record.estimated_cost == pytest.approx(0.004)
    assert record.estimated_cost_currency == "USD"
    assert record.cost_is_estimate is True
    summary = telemetry.get_summary()
    assert summary.estimated_total_cost == pytest.approx(0.004)
    assert summary.estimated_cost_currency == "USD"
    assert summary.estimated_cost_coverage == 1
    assert summary.estimated_total_cost_is_partial is False


def test_missing_pricing_and_usage_remain_unknown():
    telemetry = InMemoryLLMTelemetryService()
    provider = FakeProvider(
        "groq",
        "groq-model",
        [
            _success(
                "groq",
                "groq-model",
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
            )
        ],
    )

    LLMRouter(provider, telemetry_service=telemetry).generate(
        _request("groq", "groq-model")
    )

    record = telemetry.get_recent_records()[0]
    summary = telemetry.get_summary()
    assert record.estimated_cost is None
    assert record.cost_is_estimate is False
    assert summary.total_input_tokens is None
    assert summary.estimated_total_cost is None
    assert summary.estimated_cost_coverage == 0
    assert summary.estimated_total_cost_is_partial is True


def test_telemetry_failure_does_not_change_successful_llm_result():
    provider = FakeProvider(
        "gemini",
        "gemini-model",
        [_success("gemini", "gemini-model")],
    )
    service = LLMService(
        provider=provider,
        fallback_enabled=False,
        telemetry_service=FailingTelemetryService(),
    )

    result = service.generate_content("system", "user")

    assert result["success"] is True
    assert result["answer"] == "generated text"


def test_monitoring_summary_aggregates_attempts_requests_tokens_and_fallbacks():
    primary = FakeProvider(
        "gemini",
        "gemini-model",
        [
            _failure("gemini", "gemini-model", LLMErrorCategory.RATE_LIMIT),
            _failure("gemini", "gemini-model", LLMErrorCategory.RATE_LIMIT),
            _success(
                "gemini",
                "gemini-model",
                input_tokens=7,
                output_tokens=3,
                total_tokens=10,
            ),
        ],
    )
    fallback = FakeProvider(
        "groq",
        "groq-model",
        [_success("groq", "groq-model", input_tokens=20, output_tokens=8)],
    )
    telemetry = InMemoryLLMTelemetryService()
    router = LLMRouter(primary, fallback, telemetry)

    router.generate(_request("gemini", "gemini-model"))
    router.generate(_request("gemini", "gemini-model", request_id="second-request"))

    summary = telemetry.get_summary()
    assert summary.total_calls == 4
    assert summary.successful_calls == 2
    assert summary.failed_calls == 2
    assert summary.success_rate == pytest.approx(0.5)
    assert summary.average_latency_ms is not None
    assert summary.median_latency_ms is not None
    assert summary.provider_model_usage == {
        "gemini/gemini-model": 3,
        "groq/groq-model": 1,
    }
    assert summary.total_requests == 2
    assert summary.successful_requests == 2
    assert summary.fallback_attempts == 1
    assert summary.fallback_successes == 1
    assert summary.fallback_success_rate == 1
    assert summary.total_input_tokens == 27
    assert summary.total_output_tokens == 11
    assert summary.total_tokens == 25


def test_empty_monitor_distinguishes_unavailable_metrics_from_zero():
    summary = InMemoryLLMTelemetryService().get_summary()

    assert summary.total_calls == 0
    assert summary.successful_calls == 0
    assert summary.success_rate is None
    assert summary.average_latency_ms is None
    assert summary.median_latency_ms is None
    assert summary.total_input_tokens is None
    assert summary.estimated_total_cost is None
    assert summary.fallback_success_rate is None


def test_pricing_configuration_is_validated():
    required = {
        "DATABASE_URL": "sqlite://",
        "GEMINI_API_KEY": "test-only-key",
        "JWT_SECRET_KEY": "test-only-signing-key-not-for-deployment",
    }

    settings = Settings(
        **required,
        LLM_PRICING={
            "gemini": {
                "gemini-model": {
                    "input_per_million_tokens": 1,
                    "output_per_million_tokens": 2,
                }
            }
        },
        LLM_PRICING_CURRENCY="usd",
    )
    assert settings.LLM_PRICING["gemini"]["gemini-model"] == {
        "input_per_million_tokens": 1.0,
        "output_per_million_tokens": 2.0,
    }
    assert settings.LLM_PRICING_CURRENCY == "USD"
    with pytest.raises(ValueError, match="CURRENCY is required"):
        Settings(
            **required,
            LLM_PRICING={
                "gemini": {
                    "gemini-model": {
                        "input_per_million_tokens": 1,
                        "output_per_million_tokens": 2,
                    }
                }
            },
        )
    with pytest.raises(ValueError, match="non-negative"):
        Settings(
            **required,
            LLM_PRICING={
                "gemini": {
                    "gemini-model": {
                        "input_per_million_tokens": -1,
                        "output_per_million_tokens": 2,
                    }
                }
            },
        )
