import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.llm.contracts import (
    LLMError,
    LLMErrorCategory,
    LLMGenerationRequest,
    LLMProvider,
    LLMResponse,
)
from app.llm.telemetry import (
    LLMCallTelemetry,
    LLMTelemetrySink,
    get_default_telemetry_service,
)

logger = logging.getLogger(__name__)

_FALLBACK_CATEGORIES = {
    LLMErrorCategory.RATE_LIMIT,
    LLMErrorCategory.TIMEOUT,
    LLMErrorCategory.EMPTY_RESPONSE,
    LLMErrorCategory.INVALID_RESPONSE,
}
_MAX_RETRIES_PER_PROVIDER = 1
_BASE_RETRY_DELAY_SECONDS = 0.25
_MAX_RETRY_DELAY_SECONDS = 30.0


class LLMRouter:
    def __init__(
        self,
        primary_provider: LLMProvider,
        fallback_provider: LLMProvider | None = None,
        telemetry_service: LLMTelemetrySink | None = None,
    ) -> None:
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.telemetry_service = (
            telemetry_service
            if telemetry_service is not None
            else get_default_telemetry_service()
        )

    @staticmethod
    def _provider_failure(
        provider: LLMProvider,
        request: LLMGenerationRequest,
        error_type: str,
        category: LLMErrorCategory = LLMErrorCategory.PROVIDER_API,
        transient: bool = False,
    ) -> LLMResponse:
        return LLMResponse(
            provider=provider.provider_name,
            model=request.model,
            success=False,
            text="",
            stage="provider_request",
            error="LLM provider request failed",
            error_type=error_type,
            request_id=request.request_id,
            metadata=dict(request.metadata),
            error_details=LLMError(
                category=category,
                message="LLM provider request failed",
                stage="provider_request",
                provider=provider.provider_name,
                model=request.model,
                error_type=error_type,
                details={"transient": True} if transient else {},
            ),
        )

    @classmethod
    def _call_provider(
        cls,
        provider: LLMProvider,
        request: LLMGenerationRequest,
    ) -> LLMResponse:
        try:
            response = provider.generate(request)
        except TimeoutError as exc:
            return cls._provider_failure(
                provider,
                request,
                type(exc).__name__,
                category=LLMErrorCategory.TIMEOUT,
                transient=True,
            )
        except Exception as exc:
            return cls._provider_failure(
                provider,
                request,
                type(exc).__name__,
            )
        if not isinstance(response, LLMResponse):
            return cls._provider_failure(
                provider,
                request,
                "InvalidProviderResponse",
                category=LLMErrorCategory.INVALID_RESPONSE,
            )
        return response

    @classmethod
    def _timed_call(
        cls,
        provider: LLMProvider,
        request: LLMGenerationRequest,
        *,
        attempt_number: int,
        is_fallback_attempt: bool,
    ) -> tuple[LLMResponse, LLMCallTelemetry]:
        request_timestamp = datetime.now(timezone.utc)
        started = time.perf_counter()
        response = cls._call_provider(provider, request)
        completion_timestamp = datetime.now(timezone.utc)
        latency_ms = (time.perf_counter() - started) * 1000
        error = response.error_details
        return response, LLMCallTelemetry(
            provider=provider.provider_name,
            model=request.model,
            request_timestamp=request_timestamp,
            completion_timestamp=completion_timestamp,
            latency_ms=latency_ms,
            success=response.success,
            error_category=error.category.value if error is not None else None,
            input_token_count=response.input_token_count,
            output_token_count=response.output_token_count,
            total_token_count=response.total_token_count,
            request_id=request.request_id or response.request_id,
            attempt_number=attempt_number,
            is_fallback_attempt=is_fallback_attempt,
            fallback_attempted=False,
            fallback_succeeded=False,
            primary_provider=provider.provider_name,
            primary_model=request.model,
            final_provider=response.provider,
            final_model=response.model,
            request_success=response.success,
        )

    def _record_telemetry(
        self,
        attempts: list[LLMCallTelemetry],
        final_response: LLMResponse,
        *,
        fallback_attempted: bool,
        fallback_succeeded: bool,
    ) -> None:
        records = [
            replace(
                attempt,
                fallback_attempted=fallback_attempted,
                fallback_succeeded=fallback_succeeded,
                primary_provider=self.primary_provider.provider_name,
                primary_model=self.primary_provider.model_name,
                final_provider=attempts[-1].provider,
                final_model=attempts[-1].model,
                request_success=final_response.success,
            )
            for attempt in attempts
        ]
        try:
            self.telemetry_service.record_request(records)
        except Exception as exc:
            logger.error(
                "LLM telemetry collection failed: error_type=%s",
                type(exc).__name__,
            )

    @staticmethod
    def _is_fallback_eligible(response: LLMResponse) -> bool:
        if response.success or response.error_details is None:
            return False
        category = response.error_details.category
        if category in _FALLBACK_CATEGORIES:
            return True
        return (
            category == LLMErrorCategory.PROVIDER_API
            and response.error_details.details.get("transient") is True
        )

    @classmethod
    def _retry_delay(
        cls,
        response: LLMResponse,
        retry_number: int,
    ) -> float:
        error = response.error_details
        retry_after = (
            error.details.get("retry_after_seconds")
            if error is not None
            else None
        )
        if (
            isinstance(retry_after, (int, float))
            and not isinstance(retry_after, bool)
            and retry_after >= 0
        ):
            return min(float(retry_after), _MAX_RETRY_DELAY_SECONDS)
        return min(
            _BASE_RETRY_DELAY_SECONDS * (2 ** (retry_number - 1)),
            _MAX_RETRY_DELAY_SECONDS,
        )

    @classmethod
    def _attempt_provider(
        cls,
        provider: LLMProvider,
        request: LLMGenerationRequest,
        *,
        first_attempt_number: int,
        is_fallback_attempt: bool,
    ) -> tuple[LLMResponse, list[LLMCallTelemetry], list[dict[str, Any]]]:
        attempts: list[LLMCallTelemetry] = []
        retry_diagnostics: list[dict[str, Any]] = []
        response: LLMResponse | None = None

        for retry_number in range(_MAX_RETRIES_PER_PROVIDER + 1):
            response, telemetry = cls._timed_call(
                provider,
                request,
                attempt_number=first_attempt_number + retry_number,
                is_fallback_attempt=is_fallback_attempt,
            )
            attempts.append(telemetry)
            if (
                response.success
                or not cls._is_fallback_eligible(response)
                or retry_number >= _MAX_RETRIES_PER_PROVIDER
            ):
                break

            delay = cls._retry_delay(response, retry_number + 1)
            error = response.error_details
            reason = (
                error.category.value
                if error is not None
                else LLMErrorCategory.PROVIDER_API.value
            )
            retry_diagnostics.append(
                {
                    "provider": provider.provider_name,
                    "attempt_number": first_attempt_number + retry_number,
                    "reason": reason,
                    "delay_seconds": delay,
                    "fallback_attempt": is_fallback_attempt,
                }
            )
            logger.warning(
                "Retrying LLM provider request: provider=%s model=%s "
                "attempt=%s reason=%s delay_seconds=%s",
                provider.provider_name,
                request.model,
                retry_number + 1,
                reason,
                delay,
            )
            time.sleep(delay)

        if response is None:
            raise RuntimeError("Provider attempt loop did not execute")
        return response, attempts, retry_diagnostics

    @staticmethod
    def _failure_diagnostics(response: LLMResponse) -> dict[str, str]:
        error = response.error_details
        diagnostics = {
            "stage": response.stage,
            "error_type": response.error_type or "",
        }
        if error is not None:
            diagnostics["error_category"] = error.category.value
            diagnostics["error_type"] = error.error_type or diagnostics["error_type"]
        return diagnostics

    @staticmethod
    def _invalid_request(
        request: LLMGenerationRequest,
        message: str,
    ) -> LLMResponse:
        error = LLMError(
            category=LLMErrorCategory.INVALID_REQUEST,
            message=message,
            stage="invalid_request",
            provider=request.provider,
            model=request.model,
        )
        return LLMResponse(
            provider=request.provider,
            model=request.model,
            success=False,
            text="",
            stage="invalid_request",
            error=message,
            request_id=request.request_id,
            metadata=dict(request.metadata),
            error_details=error,
        )

    def generate(self, request: LLMGenerationRequest) -> LLMResponse:
        if (
            request.provider != self.primary_provider.provider_name
            or request.model != self.primary_provider.model_name
        ):
            return self._invalid_request(
                request,
                "Request provider/model does not match the selected primary.",
            )

        primary_response, primary_attempts, retry_diagnostics = self._attempt_provider(
            self.primary_provider,
            request,
            first_attempt_number=1,
            is_fallback_attempt=False,
        )
        fallback_eligible = self._is_fallback_eligible(primary_response)
        if (
            primary_response.success
            or self.fallback_provider is None
            or not fallback_eligible
        ):
            primary_response = replace(
                primary_response,
                metadata={
                    **primary_response.metadata,
                    "fallback_configured": self.fallback_provider is not None,
                    "fallback_attempted": False,
                    "fallback_eligible": fallback_eligible,
                    "provider_attempt_count": len(primary_attempts),
                    "retry_count": len(retry_diagnostics),
                    "primary_retry_count": len(retry_diagnostics),
                    "fallback_retry_count": 0,
                    "retry_diagnostics": retry_diagnostics,
                },
            )
            self._record_telemetry(
                primary_attempts,
                primary_response,
                fallback_attempted=False,
                fallback_succeeded=False,
            )
            return primary_response

        fallback_request = replace(
            request,
            provider=self.fallback_provider.provider_name,
            model=self.fallback_provider.model_name,
        )
        logger.warning(
            "Using configured LLM fallback: primary=%s fallback=%s",
            self.primary_provider.provider_name,
            self.fallback_provider.provider_name,
        )
        fallback_response, fallback_attempts, fallback_retries = self._attempt_provider(
            self.fallback_provider,
            fallback_request,
            first_attempt_number=len(primary_attempts) + 1,
            is_fallback_attempt=True,
        )
        retry_diagnostics.extend(fallback_retries)
        primary_diagnostics = self._failure_diagnostics(primary_response)
        fallback_diagnostics = self._failure_diagnostics(fallback_response)
        all_attempts = [*primary_attempts, *fallback_attempts]
        fallback_metadata = {
            **fallback_response.metadata,
            "fallback_configured": True,
            "fallback_attempted": True,
            "fallback_succeeded": fallback_response.success,
            "provider_attempt_count": len(all_attempts),
            "retry_count": len(retry_diagnostics),
            "primary_retry_count": len(primary_attempts) - 1,
            "fallback_retry_count": len(fallback_attempts) - 1,
            "retry_diagnostics": retry_diagnostics,
            "primary_provider": self.primary_provider.provider_name,
            "primary_model": self.primary_provider.model_name,
            "primary_failure_stage": primary_diagnostics["stage"],
            "primary_error_category": primary_diagnostics.get("error_category", ""),
            "primary_error_type": primary_diagnostics["error_type"],
            "fallback_reason": primary_diagnostics.get("error_category", ""),
            "fallback_provider": self.fallback_provider.provider_name,
            "fallback_model": self.fallback_provider.model_name,
        }
        if fallback_response.success:
            fallback_response = replace(
                fallback_response,
                metadata=fallback_metadata,
            )
            self._record_telemetry(
                all_attempts,
                fallback_response,
                fallback_attempted=True,
                fallback_succeeded=True,
            )
            return fallback_response

        primary_error = primary_response.error_details
        fallback_error = fallback_response.error_details
        combined_error = LLMError(
            category=(
                fallback_error.category
                if fallback_error is not None
                else LLMErrorCategory.PROVIDER_API
            ),
            message="Primary and fallback LLM providers failed",
            stage=primary_response.stage,
            provider=self.primary_provider.provider_name,
            model=self.primary_provider.model_name,
            details={
                "primary_failure_stage": primary_response.stage,
                "primary_error_category": (
                    primary_error.category.value if primary_error is not None else None
                ),
                "fallback_provider": self.fallback_provider.provider_name,
                "fallback_model": self.fallback_provider.model_name,
                "fallback_failure_stage": fallback_response.stage,
                "fallback_error_category": (
                    fallback_error.category.value if fallback_error is not None else None
                ),
                "primary_error_type": primary_diagnostics["error_type"],
                "fallback_error_type": fallback_diagnostics["error_type"],
            },
        )
        response = LLMResponse(
            provider=self.primary_provider.provider_name,
            model=self.primary_provider.model_name,
            success=False,
            text="",
            stage=primary_response.stage,
            error="Primary and fallback LLM providers failed",
            error_type=(
                fallback_response.error_type or primary_response.error_type
            ),
            request_id=request.request_id,
            metadata={
                **request.metadata,
                "fallback_configured": True,
                "fallback_attempted": True,
                "fallback_succeeded": False,
                "provider_attempt_count": len(all_attempts),
                "retry_count": len(retry_diagnostics),
                "primary_retry_count": len(primary_attempts) - 1,
                "fallback_retry_count": len(fallback_attempts) - 1,
                "retry_diagnostics": retry_diagnostics,
                "primary_provider": self.primary_provider.provider_name,
                "primary_model": self.primary_provider.model_name,
                "primary_failure_stage": primary_diagnostics["stage"],
                "primary_error_category": primary_diagnostics.get(
                    "error_category", ""
                ),
                "primary_error_type": primary_diagnostics["error_type"],
                "fallback_provider": self.fallback_provider.provider_name,
                "fallback_model": self.fallback_provider.model_name,
                "fallback_failure_stage": fallback_response.stage,
                "fallback_error_category": fallback_diagnostics.get(
                    "error_category", ""
                ),
                "fallback_error_type": fallback_diagnostics["error_type"],
                "fallback_reason": primary_diagnostics.get("error_category", ""),
            },
            error_details=combined_error,
        )
        self._record_telemetry(
            all_attempts,
            response,
            fallback_attempted=True,
            fallback_succeeded=False,
        )
        return response
