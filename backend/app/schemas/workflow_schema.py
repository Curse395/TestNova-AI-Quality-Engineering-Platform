from pydantic import BaseModel, Field

from app.schemas.test_case_schema import (
    DocumentSourceType,
    RequirementDefinition,
    TestCategory,
)


class WorkflowStartRequest(BaseModel):
    workflow_type: str | None = Field(default=None, max_length=40)
    request: str | None = Field(default=None, max_length=10000)
    requirements_prompt: str | None = Field(default=None, min_length=5, max_length=10000)
    document_ids: list[int] | None = None
    source_types: list[DocumentSourceType] | None = None
    max_cases: int = Field(default=5, ge=1, le=20)
    categories: list[TestCategory] = Field(
        min_length=1,
        max_length=4,
        default_factory=lambda: ["positive", "negative", "boundary", "edge"],
    )
    requirements: list[RequirementDefinition] = Field(
        default_factory=list,
        max_length=100,
    )
    change_summary: str | None = Field(default=None, min_length=10, max_length=5000)
    change_type: str = Field(default="general", max_length=100)
    changed_files: list[str] = Field(default_factory=list, max_length=100)
    additional_context: str = Field(default="", max_length=5000)
