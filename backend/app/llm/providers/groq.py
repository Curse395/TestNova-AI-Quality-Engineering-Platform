import logging
from typing import Any

import httpx
from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    Groq,
    RateLimitError,
)

from app.core.config import settings
from app.llm.contracts import (
    LLMConfigurationException,
    LLMError,
    LLMErrorCategory,
    LLMGenerationRequest,
    LLMResponse,
)
from app.llm.retry import retry_after_seconds

logger = logging.getLogger(__name__)


class GroqProvider:
    provider_name = "groq"

    def __init__(
        self,
        api_key: str | None,
        model_name: str,
        client: Any | None = None,
    ) -> None:
        if client is None and not api_key:
            raise LLMConfigurationException(
                self.provider_name,
                "Groq API key is not configured",
            )
        self.model_name = model_name
        self.client = (
            client
            if client is not None
            else Groq(
                api_key=api_key,
                max_retries=0,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        )

    @staticmethod
    def _provider_error(error: Exception) -> tuple[LLMErrorCategory, bool]:
        if isinstance(error, (APITimeoutError, TimeoutError, httpx.TimeoutException)):
            return LLMErrorCategory.TIMEOUT, True
        if isinstance(error, AuthenticationError):
            return LLMErrorCategory.AUTHENTICATION, False
        if isinstance(error, RateLimitError):
            return LLMErrorCategory.RATE_LIMIT, True
        if isinstance(error, APIConnectionError):
            return LLMErrorCategory.PROVIDER_API, True
        if isinstance(error, APIStatusError):
            status_code = error.status_code
            if status_code in {401, 403}:
                return LLMErrorCategory.AUTHENTICATION, False
            if status_code == 429:
                return LLMErrorCategory.RATE_LIMIT, True
            if status_code in {408, 504}:
                return LLMErrorCategory.TIMEOUT, True
            if status_code in {400, 404, 422}:
                return LLMErrorCategory.INVALID_REQUEST, False
            return (
                LLMErrorCategory.PROVIDER_API,
                500 <= status_code < 600,
            )
        return LLMErrorCategory.PROVIDER_API, False

    @staticmethod
    def _usage(response: Any) -> dict[str, int] | None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return None
        fields = {
            "prompt_tokens": "prompt_tokens",
            "completion_tokens": "completion_tokens",
            "total_tokens": "total_tokens",
        }
        counts = {}
        for result_key, source_key in fields.items():
            value = getattr(usage, source_key, None)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                counts[result_key] = value
        return counts or None

    @staticmethod
    def _failure(
        request: LLMGenerationRequest,
        category: LLMErrorCategory,
        message: str,
        stage: str,
        *,
        error_type: str | None = None,
        transient: bool = False,
        retry_after: float | None = None,
    ) -> LLMResponse:
        error = LLMError(
            category=category,
            message=message,
            stage=stage,
            provider="groq",
            model=request.model,
            error_type=error_type,
            details={
                **({"transient": True} if transient else {}),
                **(
                    {"retry_after_seconds": retry_after}
                    if retry_after is not None
                    else {}
                ),
            },
        )
        return LLMResponse(
            provider="groq",
            model=request.model,
            success=False,
            text="",
            stage=stage,
            error=message,
            error_type=error_type,
            request_id=request.request_id,
            metadata=dict(request.metadata),
            error_details=error,
        )

    def generate(self, request: LLMGenerationRequest) -> LLMResponse:
        response_format = None
        if request.structured_output is not None:
            if request.structured_output.response_mime_type != "application/json":
                return self._failure(
                    request,
                    LLMErrorCategory.INVALID_REQUEST,
                    "Groq supports structured output only for application/json.",
                    "invalid_request",
                )
            response_format = {"type": "json_object"}

        parameters = request.generation_parameters
        messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.user_prompt},
        ]
        request_options: dict[str, Any] = {
            "model": request.model or self.model_name,
            "messages": messages,
            "temperature": parameters.temperature,
            "top_p": parameters.top_p,
            "max_completion_tokens": parameters.max_output_tokens,
        }
        if response_format is not None:
            request_options["response_format"] = response_format

        try:
            logger.info("Calling Groq model: %s", request_options["model"])
            response = self.client.chat.completions.create(**request_options)
        except Exception as exc:
            category, transient = self._provider_error(exc)
            logger.error(
                "Groq provider request failed: model=%s error_type=%s",
                request_options["model"],
                type(exc).__name__,
            )
            return self._failure(
                request,
                category,
                "Groq provider request failed",
                "provider_request",
                error_type=type(exc).__name__,
                transient=transient,
                retry_after=retry_after_seconds(exc),
            )

        usage_metadata = self._usage(response)
        choices = getattr(response, "choices", None)
        choice = choices[0] if choices else None
        finish_reason = getattr(choice, "finish_reason", None)
        message = getattr(choice, "message", None)
        text = getattr(message, "content", None)
        metadata = dict(request.metadata)
        response_id = getattr(response, "id", None)
        if isinstance(response_id, str):
            metadata["provider_response_id"] = response_id

        common = {
            "usage_metadata": usage_metadata,
            "input_token_count": (
                usage_metadata.get("prompt_tokens") if usage_metadata else None
            ),
            "output_token_count": (
                usage_metadata.get("completion_tokens") if usage_metadata else None
            ),
            "total_token_count": (
                usage_metadata.get("total_tokens") if usage_metadata else None
            ),
            "request_id": request.request_id or (
                response_id if isinstance(response_id, str) else None
            ),
            "metadata": metadata,
        }
        if not isinstance(text, str):
            error = LLMError(
                category=LLMErrorCategory.INVALID_RESPONSE,
                message="Groq response did not contain text.",
                stage="response_extraction",
                provider=self.provider_name,
                model=request_options["model"],
            )
            return LLMResponse(
                provider=self.provider_name,
                model=request_options["model"],
                success=False,
                text="",
                stage="response_extraction",
                error=error.message,
                finish_reason=finish_reason,
                error_details=error,
                **common,
            )
        if not text.strip():
            error = LLMError(
                category=LLMErrorCategory.EMPTY_RESPONSE,
                message="Groq returned no text content",
                stage="empty_response",
                provider=self.provider_name,
                model=request_options["model"],
            )
            return LLMResponse(
                provider=self.provider_name,
                model=request_options["model"],
                success=False,
                text="",
                stage="empty_response",
                error=error.message,
                finish_reason=finish_reason,
                error_details=error,
                **common,
            )

        return LLMResponse(
            provider=self.provider_name,
            model=request_options["model"],
            success=True,
            text=text,
            stage="complete",
            finish_reason=finish_reason,
            **common,
        )
