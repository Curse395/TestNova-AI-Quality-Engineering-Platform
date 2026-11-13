from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SummaryStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    interpretation: bool = False


class QualitySummaryContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_summary: SummaryStatement
    testing_activity: list[SummaryStatement] = Field(max_length=20)
    test_case_quality: list[SummaryStatement] = Field(max_length=20)
    requirement_traceability: list[SummaryStatement] = Field(max_length=20)
    execution_trends: list[SummaryStatement] = Field(max_length=20)
    significant_failures: list[SummaryStatement] = Field(max_length=20)
    identified_risks: list[SummaryStatement] = Field(max_length=20)
    missing_evidence: list[SummaryStatement] = Field(max_length=20)
    recommended_actions: list[SummaryStatement] = Field(max_length=20)
    limitations: list[SummaryStatement] = Field(max_length=20)


class QualityEvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    description: str


class QualitySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    status: Literal["available", "unavailable"]
    summary: QualitySummaryContent | None
    evidence_sources: list[QualityEvidenceSource]
    generated_at: str | None
    cached: bool
    evidence_fingerprint: str
    limitations: list[str]
    error: str | None = None
