from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal["success", "partial", "failed", "skipped"]
WorkflowStatus = Literal[
    "pending",
    "running",
    "completed",
    "partially_completed",
    "failed",
]
WorkflowTaskStatus = Literal[
    "pending",
    "running",
    "completed",
    "partial",
    "skipped",
    "retrying",
    "failed",
]


class AgentInput(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_id: int
    task_id: int
    project_id: int
    user_id: int
    task_type: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    shared_context: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[dict[str, Any]] = Field(default_factory=list)


class AgentOutput(BaseModel):
    agent_name: str
    status: Literal["completed", "partial", "failed", "skipped"]
    structured_data: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any] | str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any] | str] = Field(default_factory=list)
    execution_metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    project_id: int
    user_id: int
    requirements: dict[str, Any] = Field(default_factory=dict)
    bug_analysis: dict[str, Any] = Field(default_factory=dict)
    generated_test_cases: list[dict[str, Any]] = Field(default_factory=list)
    evaluation_findings: list[dict[str, Any]] = Field(default_factory=list)
    change_risks: dict[str, Any] = Field(default_factory=dict)
    test_analysis: dict[str, Any] = Field(default_factory=dict)
    quality_insights: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[dict[str, Any]] = Field(default_factory=list)
    workflow_metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class AgentContext:
    """Compatibility context used by the existing agent implementations."""

    user_id: int
    project_id: int
    task: str
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Compatibility result used by the existing agent implementations."""

    agent_name: str
    status: AgentStatus
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, str] | None = None

    @property
    def success(self) -> bool:
        return self.status == "success"
