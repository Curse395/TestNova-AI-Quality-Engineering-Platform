from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ReleaseConcern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    attention: Literal["blocker", "high", "medium", "low", "info"]
    explanation: str
    source: str
    evidence_ids: list[str]
    next_action: str


class ReleaseAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal[
        "ready_for_review",
        "attention_required",
        "blocked",
        "insufficient_evidence",
    ]
    label: str
    explanation: str
    reasons: list[str]


class ReleaseReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: int
    assessment: ReleaseAssessment
    metrics: dict[str, Any]
    concerns: list[ReleaseConcern]
    limitations: list[str]
