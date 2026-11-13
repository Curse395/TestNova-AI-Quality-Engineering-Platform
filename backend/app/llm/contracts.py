import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class LLMErrorCategory(str, Enum):
    CONFIGURATION = "configuration"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    PROVIDER_API = "provider_api"
    INVALID_REQUEST = "invalid_request"
    INVALID_RESPONSE = "invalid_response"
    EMPTY_RESPONSE = "empty_response"
    STRUCTURED_OUTPUT_PARSE = "structured_output_parse"
    SCHEMA_VALIDATION = "schema_validation"


@dataclass(frozen=True)
class GenerationParameters:
    temperature: float
    max_output_tokens: int
    top_p: float
    top_k: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
            or self.temperature < 0
        ):
            raise ValueError("Temperature must be a finite non-negative number")
        if (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens < 1
        ):
            raise ValueError("Maximum output tokens must be a positive integer")
        if (
            isinstance(self.top_p, bool)
            or not isinstance(self.top_p, (int, float))
            or not math.isfinite(self.top_p)
            or not 0 < self.top_p <= 1
        ):
            raise ValueError("Top-p must be a finite number in (0, 1]")
        if (
            not isinstance(self.top_k, int)
            or isinstance(self.top_k, bool)
            or self.top_k < 1
        ):
            raise ValueError("Top-k must be a positive integer")


@dataclass(frozen=True)
class StructuredOutputConfig:
    response_mime_type: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.response_mime_type, str)
            or not self.response_mime_type.strip()
        ):
            raise ValueError("Response MIME type cannot be blank")


@dataclass(frozen=True)
class LLMGenerationRequest:
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    generation_parameters: GenerationParameters
    structured_output: StructuredOutputConfig | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("Provider identity cannot be blank")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Model identity cannot be blank")
        if not isinstance(self.system_prompt, str):
            raise TypeError("System prompt must be text")
        if not isinstance(self.user_prompt, str) or not self.user_prompt.strip():
            raise ValueError("User prompt cannot be blank")
        if not isinstance(self.generation_parameters, GenerationParameters):
            raise TypeError("Generation parameters must use GenerationParameters")
        if (
            self.structured_output is not None
            and not isinstance(self.structured_output, StructuredOutputConfig)
        ):
            raise TypeError("Structured output must use StructuredOutputConfig")
        if not isinstance(self.metadata, dict):
            raise TypeError("Request metadata must be a dictionary")
        if self.request_id is not None:
            if not isinstance(self.request_id, str):
                raise TypeError("Request identifier must be text")
            if not self.request_id.strip():
                raise ValueError("Request identifier cannot be blank")


@dataclass(frozen=True)
class LLMError:
    category: LLMErrorCategory
    message: str
    stage: str
    provider: str | None = None
    model: str | None = None
    error_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.category, LLMErrorCategory):
            raise TypeError("Error category must use LLMErrorCategory")
        if not self.message.strip() or not self.stage.strip():
            raise ValueError("Error message and stage cannot be blank")


class LLMConfigurationException(RuntimeError):
    def __init__(self, provider: str, message: str) -> None:
        self.error = LLMError(
            category=LLMErrorCategory.CONFIGURATION,
            message=message,
            stage="configuration",
            provider=provider,
        )
        super().__init__(message)


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    success: bool
    text: str
    stage: str
    error: str | None = None
    error_type: str | None = None
    finish_reason: str | None = None
    usage_metadata: dict[str, int | float | str] | None = None
    input_token_count: int | None = None
    output_token_count: int | None = None
    total_token_count: int | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    error_details: LLMError | None = None

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip() or not self.stage.strip():
            raise ValueError("Response provider, model, and stage cannot be blank")
        if not isinstance(self.text, str):
            raise TypeError("Response text must be a string")
        if self.success and self.error_details is not None:
            raise ValueError("A successful response cannot contain an error")
        if not self.success and self.error_details is None:
            raise ValueError("A failed response must contain standardized error details")
        for field_name in (
            "input_token_count",
            "output_token_count",
            "total_token_count",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer")


class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def generate(self, request: LLMGenerationRequest) -> LLMResponse: ...
