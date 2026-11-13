import logging
from typing import Any

from google import genai
from google.genai import errors
from google.genai import types
import httpx

from app.core.config import settings
from app.llm.contracts import (
    LLMError,
    LLMErrorCategory,
    LLMConfigurationException,
    LLMGenerationRequest,
    LLMResponse,
)

logger = logging.getLogger(__name__)


class GeminiProvider:
    provider_name = "gemini"

    def __init__(
        self,
        api_key: str,
        model_name: str,
        client: Any | None = None,
    ) -> None:
        if client is None and not api_key:
            raise LLMConfigurationException(
                self.provider_name,
                "Gemini API key is not configured",
            )
        self.model_name = model_name
        self.client = (
            client
            if client is not None
            else genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=int(settings.LLM_TIMEOUT_SECONDS * 1000),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        )

    @staticmethod
    def _finish_reason(response: Any) -> str | None:
        candidates = getattr(response, "candidates", None)
        candidate = candidates[0] if candidates else None
        reason = getattr(candidate, "finish_reason", None)
        if reason is None:
            return None
        return getattr(reason, "name", str(reason))

    @staticmethod
    def _error_category(error: Exception) -> tuple[LLMErrorCategory, bool]:
        if isinstance(error, (TimeoutError, httpx.TimeoutException)):
            return LLMErrorCategory.TIMEOUT, True
        if isinstance(error, httpx.NetworkError):
            return LLMErrorCategory.PROVIDER_API, True
        if isinstance(error, errors.APIError):
            if error.code in {401, 403}:
                return LLMErrorCategory.AUTHENTICATION, False
            if error.code == 429:
                return LLMErrorCategory.RATE_LIMIT, True
            if error.code in {408, 504}:
                return LLMErrorCategory.TIMEOUT, True
            if error.code in {400, 404, 422}:
                return LLMErrorCategory.INVALID_REQUEST, False
            return (
                LLMErrorCategory.PROVIDER_API,
                500 <= error.code < 600,
            )
        return LLMErrorCategory.PROVIDER_API, False

    @staticmethod
    def _token_count(usage: Any, field: str) -> int | None:
        value = getattr(usage, field, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    @classmethod
    def _usage_metadata(cls, response: Any) -> dict[str, int | float | str] | None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return None

        fields = {
            "prompt_token_count": "prompt_token_count",
            "candidates_token_count": "candidates_token_count",
            "total_token_count": "total_token_count",
            "thoughts_token_count": "thoughts_token_count",
            "cached_content_token_count": "cached_content_token_count",
        }
        counts = {
            output_name: count
            for output_name, source_name in fields.items()
            if (count := cls._token_count(usage, source_name)) is not None
        }
        return counts or None

    def generate(self, request: LLMGenerationRequest) -> LLMResponse:
        model_name = request.model or self.model_name
        parameters = request.generation_parameters
        response_mime_type = (
            request.structured_output.response_mime_type
            if request.structured_output is not None
            else None
        )
        config = types.GenerateContentConfig(
            temperature=parameters.temperature,
            top_p=parameters.top_p,
            top_k=parameters.top_k,
            max_output_tokens=parameters.max_output_tokens,
            system_instruction=request.system_prompt,
            response_mime_type=response_mime_type,
        )

        try:
            logger.info("Calling Gemini model: %s", model_name)
            response = self.client.models.generate_content(
                model=model_name,
                contents=request.user_prompt,
                config=config,
            )
        except Exception as exc:
            category, transient = self._error_category(exc)
            error = LLMError(
                category=category,
                message="Gemini provider request failed",
                stage="provider_request",
                provider=self.provider_name,
                model=model_name,
                error_type=type(exc).__name__,
                details={"transient": True} if transient else {},
            )
            logger.error(
                "Gemini provider request failed: model=%s error_type=%s",
                model_name,
                type(exc).__name__,
            )
            return LLMResponse(
                provider=self.provider_name,
                model=model_name,
                success=False,
                text="",
                stage="provider_request",
                error="Gemini provider request failed",
                error_type=type(exc).__name__,
                request_id=request.request_id,
                metadata=dict(request.metadata),
                error_details=error,
            )

        finish_reason = self._finish_reason(response)
        usage_metadata = self._usage_metadata(response)
        metadata = dict(request.metadata)
        provider_response_id = getattr(response, "response_id", None)
        model_version = getattr(response, "model_version", None)
        if isinstance(provider_response_id, str):
            metadata["provider_response_id"] = provider_response_id
        if isinstance(model_version, str):
            metadata["model_version"] = model_version
        request_id = request.request_id or (
            provider_response_id
            if isinstance(provider_response_id, str)
            else None
        )
        try:
            answer = response.text
        except Exception as exc:
            error = LLMError(
                category=LLMErrorCategory.INVALID_RESPONSE,
                message="Gemini response text could not be extracted",
                stage="response_extraction",
                provider=self.provider_name,
                model=model_name,
                error_type=type(exc).__name__,
            )
            logger.error(
                "Gemini response text extraction failed: model=%s "
                "error_type=%s finish_reason=%s",
                model_name,
                type(exc).__name__,
                finish_reason,
            )
            return LLMResponse(
                provider=self.provider_name,
                model=model_name,
                success=False,
                text="",
                stage="response_extraction",
                error="Gemini response text could not be extracted",
                error_type=type(exc).__name__,
                finish_reason=finish_reason,
                usage_metadata=usage_metadata,
                input_token_count=(
                    usage_metadata.get("prompt_token_count")
                    if usage_metadata
                    else None
                ),
                output_token_count=(
                    usage_metadata.get("candidates_token_count")
                    if usage_metadata
                    else None
                ),
                total_token_count=(
                    usage_metadata.get("total_token_count")
                    if usage_metadata
                    else None
                ),
                request_id=request_id,
                metadata=metadata,
                error_details=error,
            )

        if not isinstance(answer, str) or not answer.strip():
            error = LLMError(
                category=LLMErrorCategory.EMPTY_RESPONSE,
                message="Gemini returned no text content",
                stage="empty_response",
                provider=self.provider_name,
                model=model_name,
            )
            logger.warning(
                "Gemini returned no text: model=%s finish_reason=%s",
                model_name,
                finish_reason,
            )
            return LLMResponse(
                provider=self.provider_name,
                model=model_name,
                success=False,
                text="",
                stage="empty_response",
                error="Gemini returned no text content",
                finish_reason=finish_reason,
                usage_metadata=usage_metadata,
                input_token_count=(
                    usage_metadata.get("prompt_token_count")
                    if usage_metadata
                    else None
                ),
                output_token_count=(
                    usage_metadata.get("candidates_token_count")
                    if usage_metadata
                    else None
                ),
                total_token_count=(
                    usage_metadata.get("total_token_count")
                    if usage_metadata
                    else None
                ),
                request_id=request_id,
                metadata=metadata,
                error_details=error,
            )

        logger.info(
            "Gemini response received: model=%s characters=%d finish_reason=%s",
            model_name,
            len(answer),
            finish_reason,
        )
        return LLMResponse(
            provider=self.provider_name,
            model=model_name,
            success=True,
            text=answer,
            stage="complete",
            finish_reason=finish_reason,
            usage_metadata=usage_metadata,
            input_token_count=(
                usage_metadata.get("prompt_token_count")
                if usage_metadata
                else None
            ),
            output_token_count=(
                usage_metadata.get("candidates_token_count")
                if usage_metadata
                else None
            ),
            total_token_count=(
                usage_metadata.get("total_token_count")
                if usage_metadata
                else None
            ),
            request_id=request_id,
            metadata=metadata,
        )
