from typing import Literal

from pydantic import BaseModel, Field, field_validator

__test__ = False
TestCategory = Literal["positive", "negative", "boundary", "edge"]
TestSeverity = Literal["low", "medium", "high", "critical"]
TestPriority = Literal["low", "high", "medium", "critical"]
DocumentSourceType = Literal[
    "document",
    "requirements",
    "bug_report",
    "test_log",
    "technical_document",
    "api_catalogue",
]

_GENERIC_PLACEHOLDERS = {
    "",
    "as required",
    "n/a",
    "na",
    "none",
    "not applicable",
    "ok",
    "pass",
    "passed",
    "success",
    "tbd",
    "todo",
    "unknown",
    "works",
}


def _normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


class RequirementDefinition(BaseModel):
    requirement_key: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=10000)
    evidence_chunk_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("requirement_key", "description")
    @classmethod
    def validate_non_whitespace(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Requirement key and description must not be blank.")
        return cleaned

    @field_validator("evidence_chunk_ids")
    @classmethod
    def validate_evidence_ids(cls, value: list[int]) -> list[int]:
        if any(chunk_id < 1 for chunk_id in value):
            raise ValueError("Evidence chunk IDs must be positive integers.")
        return list(dict.fromkeys(value))


class TestCaseGenerationRequest(BaseModel):
    requirements_prompt: str = Field(min_length=5, max_length=10000)
    document_ids: list[int] | None = None
    source_types: list[DocumentSourceType] | None = None
    max_cases: int = Field(default=5, ge=1, le=20)
    categories: list[TestCategory] = Field(
        min_length=1,
        max_length=4,
        default_factory=lambda: ["positive", "negative", "boundary", "edge"]
    )
    requirements: list[RequirementDefinition] = Field(
        default_factory=list,
        max_length=100,
    )


class TestCaseStep(BaseModel):
    action: str = Field(min_length=1, max_length=2000)
    expected_result: str = Field(min_length=1, max_length=2000)

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Step action must not be blank.")
        return cleaned

    @field_validator("expected_result")
    @classmethod
    def validate_expected_result(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if normalized in _GENERIC_PLACEHOLDERS:
            raise ValueError(
                "Step expected result must describe an observable outcome, not a placeholder."
            )
        return value.strip()


class GeneratedTestCase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1)
    test_type: str | None = Field(default=None, max_length=60)
    category: TestCategory
    priority: TestPriority
    severity: TestSeverity = "medium"
    preconditions: str | None = None
    steps: list[TestCaseStep] = Field(min_length=1, max_length=30)
    expected_result: str = Field(min_length=1)
    evidence_chunk_ids: list[int] = Field(min_length=1)
    requirement_keys: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("title", "description", "test_type")
    @classmethod
    def validate_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Test-case text fields must not be blank.")
        return cleaned

    @field_validator("preconditions")
    @classmethod
    def validate_preconditions(cls, value: str | None) -> str | None:
        if value is None:
            return value
        cleaned = value.strip()
        if not cleaned:
            return ""
        normalized = _normalize_text(cleaned)
        if normalized in _GENERIC_PLACEHOLDERS:
            raise ValueError(
                "Preconditions must describe meaningful setup or explicitly be empty."
            )
        return cleaned

    @field_validator("expected_result")
    @classmethod
    def validate_expected_result(cls, value: str) -> str:
        normalized = _normalize_text(value)
        if normalized in _GENERIC_PLACEHOLDERS:
            raise ValueError(
                "Expected result must describe an observable outcome, not a placeholder."
            )
        return value.strip()

    @field_validator("evidence_chunk_ids")
    @classmethod
    def validate_evidence_chunk_ids(cls, value: list[int]) -> list[int]:
        if any(chunk_id < 1 for chunk_id in value):
            raise ValueError("Evidence chunk IDs must be positive integers.")
        return list(dict.fromkeys(value))

    @field_validator("requirement_keys")
    @classmethod
    def validate_requirement_keys(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Requirement keys must not be blank.")
        return list(dict.fromkeys(cleaned))


class TestCaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    test_type: str | None = Field(default=None, max_length=60)
    category: TestCategory | None = None
    priority: TestPriority | None = None
    severity: TestSeverity | None = None
    preconditions: str | None = None
    steps: list[TestCaseStep] | None = Field(default=None, min_length=1, max_length=30)
    expected_result: str | None = Field(default=None, min_length=1, max_length=10000)
    requirement_ids: list[int] | None = Field(default=None, max_length=100)
    requirement_keys: list[str] | None = Field(default=None, max_length=100)

    @field_validator("title", "description", "test_type")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Text fields must not be blank.")
        return cleaned

    @field_validator("preconditions")
    @classmethod
    def validate_optional_preconditions(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return ""
        if _normalize_text(cleaned) in _GENERIC_PLACEHOLDERS:
            raise ValueError(
                "Preconditions must describe meaningful setup or explicitly be empty."
            )
        return cleaned

    @field_validator("expected_result")
    @classmethod
    def validate_optional_expected_result(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _normalize_text(value) in _GENERIC_PLACEHOLDERS:
            raise ValueError(
                "Expected result must describe an observable outcome, not a placeholder."
            )
        return value.strip()

    @field_validator("requirement_ids")
    @classmethod
    def validate_requirement_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(requirement_id < 1 for requirement_id in value):
            raise ValueError("Requirement IDs must be positive integers.")
        return list(dict.fromkeys(value)) if value is not None else None

    @field_validator("requirement_keys")
    @classmethod
    def validate_requirement_keys(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("Requirement keys must not be blank.")
        return list(dict.fromkeys(cleaned))
