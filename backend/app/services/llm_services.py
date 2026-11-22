from app.core.config import settings
from app.llm.contracts import (
    GenerationParameters,
    LLMConfigurationException,
    LLMGenerationRequest,
    LLMProvider,
    LLMResponse,
    StructuredOutputConfig,
)
from app.llm.providers import get_default_provider, get_provider
from app.llm.router import LLMRouter
from app.llm.telemetry import LLMTelemetrySink


class LLMService:
    """Provider-neutral entry point for language model generation."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        fallback_enabled: bool | None = None,
        fallback_provider_name: str | None = None,
        fallback_model_name: str | None = None,
        telemetry_service: LLMTelemetrySink | None = None,
    ) -> None:
        if provider is not None:
            if provider_name is not None and (
                provider_name.strip().lower() != provider.provider_name
            ):
                raise LLMConfigurationException(
                    provider_name,
                    "Injected provider does not match configured provider",
                )
            if model_name is not None and model_name != provider.model_name:
                raise LLMConfigurationException(
                    provider.provider_name,
                    "Injected provider does not match configured model",
                )
            self.provider = provider
        elif provider_name is None and model_name is None:
            self.provider = get_default_provider()
        else:
            selected_provider = (
                provider_name or settings.LLM_PROVIDER
            ).strip().lower()
            self.provider = get_provider(selected_provider, model_name)

        self.provider_name = self.provider.provider_name
        self.model_name = self.provider.model_name
        self.generation_parameters = GenerationParameters(
            temperature=settings.TEMPERATURE,
            max_output_tokens=settings.MAX_OUTPUT_TOKENS,
            top_p=settings.TOP_P,
            top_k=settings.TOP_K,
        )
        self.fallback_enabled = (
            settings.LLM_FALLBACK_ENABLED
            if fallback_enabled is None
            else fallback_enabled
        )
        self.fallback_provider: LLMProvider | None = None
        if self.fallback_enabled:
            selected_fallback = (
                fallback_provider_name or settings.LLM_FALLBACK_PROVIDER
            )
            if selected_fallback is None:
                raise LLMConfigurationException(
                    self.provider_name,
                    "Fallback provider is not configured",
                )
            selected_fallback = selected_fallback.strip().lower()
            if selected_fallback == self.provider_name:
                raise LLMConfigurationException(
                    selected_fallback,
                    "Fallback provider must differ from primary provider",
                )
            selected_fallback_model = (
                fallback_model_name
                if fallback_model_name is not None
                else settings.LLM_FALLBACK_MODEL
            )
            self.fallback_provider = get_provider(
                selected_fallback,
                selected_fallback_model,
            )
        self.router = LLMRouter(
            self.provider,
            self.fallback_provider,
            telemetry_service=telemetry_service,
        )

    def generate(self, request: LLMGenerationRequest) -> LLMResponse:
        return self.router.generate(request)

    def generate_content(
        self,
        system_prompt: str,
        user_prompt: str,
        response_mime_type: str | None = None,
        *,
        metadata: dict[str, object] | None = None,
        request_id: str | None = None,
    ) -> dict[str, object]:
        request = LLMGenerationRequest(
            provider=self.provider_name,
            model=self.model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            generation_parameters=self.generation_parameters,
            structured_output=(
                StructuredOutputConfig(response_mime_type=response_mime_type)
                if response_mime_type is not None
                else None
            ),
            metadata=dict(metadata or {}),
            request_id=request_id,
        )
        response = self.generate(request)
        result: dict[str, object] = {
            "success": response.success,
            "answer": response.text,
            "provider": response.provider,
            "model": response.model,
            "stage": response.stage,
        }
        if response.error is not None:
            result["error"] = response.error
        if response.error_details is not None:
            result["error_category"] = response.error_details.category.value
            result["error_type"] = response.error_details.error_type or ""
        for field in (
            "fallback_configured",
            "fallback_attempted",
            "fallback_succeeded",
            "fallback_eligible",
            "provider_attempt_count",
            "retry_count",
        ):
            value = response.metadata.get(field)
            if isinstance(value, bool):
                result[field] = value
            elif isinstance(value, int) and not isinstance(value, bool):
                result[field] = value
        for field in (
            "primary_provider",
            "primary_model",
            "fallback_reason",
            "primary_failure_stage",
            "primary_error_category",
            "primary_error_type",
            "fallback_provider",
            "fallback_model",
            "fallback_failure_stage",
            "fallback_error_category",
            "fallback_error_type",
        ):
            value = response.metadata.get(field)
            if isinstance(value, str) and value:
                result[field] = value
        retry_diagnostics = response.metadata.get("retry_diagnostics")
        if isinstance(retry_diagnostics, list) and retry_diagnostics:
            result["retry_diagnostics"] = retry_diagnostics
        for field in ("primary_retry_count", "fallback_retry_count"):
            value = response.metadata.get(field)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                result[field] = value
        if response.finish_reason is not None:
            result["finish_reason"] = response.finish_reason
        for field in (
            "input_token_count",
            "output_token_count",
            "total_token_count",
        ):
            value = getattr(response, field)
            if isinstance(value, int) and not isinstance(value, bool):
                result[field] = value
        return result
