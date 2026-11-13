import json
import re
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.llm.contracts import LLMError, LLMErrorCategory

TModel = TypeVar("TModel", bound=BaseModel)

_SENSITIVE_VALUE = re.compile(
    r"(?i)(api[_ -]?key|authorization|access[_ -]?token|password)"
    r"([\"']?\s*[:=]\s*[\"']?)[^\s,\"']+"
)


class StructuredOutputResult(BaseModel, Generic[TModel]):
    model_config = ConfigDict(frozen=True, extra="forbid")

    success: bool
    value: TModel | None = None
    error: LLMError | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "StructuredOutputResult[TModel]":
        if self.success and (self.value is None or self.error is not None):
            raise ValueError("A successful result requires a value and no error")
        if not self.success and (self.value is not None or self.error is None):
            raise ValueError("A failed result requires an error and no value")
        return self


def _sanitize_validation_message(message: str) -> str:
    sanitized = _SENSITIVE_VALUE.sub(r"\1\2[redacted]", message)
    sanitized = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", sanitized)
    return sanitized[:300]


def validate_structured_output(
    text: str,
    schema: type[TModel],
) -> StructuredOutputResult[TModel]:
    if not isinstance(text, str) or not text.strip():
        error = LLMError(
            category=LLMErrorCategory.EMPTY_RESPONSE,
            message="Generated text is empty.",
            stage="empty_response",
        )
        return StructuredOutputResult(success=False, error=error)

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        error = LLMError(
            category=LLMErrorCategory.STRUCTURED_OUTPUT_PARSE,
            message="Generated text is not valid JSON.",
            stage="structured_output_parse",
        )
        return StructuredOutputResult(success=False, error=error)

    try:
        value = schema.model_validate(parsed)
    except ValidationError as exc:
        details = {
            "validation_errors": [
                {
                    "path": ".".join(str(part) for part in item["loc"]),
                    "code": str(item["type"]),
                    "message": _sanitize_validation_message(str(item["msg"])),
                }
                for item in exc.errors(
                    include_input=False,
                    include_context=False,
                    include_url=False,
                )
            ]
        }
        error = LLMError(
            category=LLMErrorCategory.SCHEMA_VALIDATION,
            message="Generated JSON does not match the requested schema.",
            stage="schema_validation",
            details=details,
        )
        return StructuredOutputResult(success=False, error=error)

    return StructuredOutputResult(success=True, value=value)