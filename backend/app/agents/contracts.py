from dataclasses import dataclass,field
from typing import Any,Literal

AgentStatus=Literal["success","partial","failed"]

@dataclass
class AgentContext:
    """Shared context passed to TestNova agents."""

    user_id: int
    project_id: int
    task: str
    inputs: dict[str,Any] = field(default_factory=dict)
    metadata: dict[str,Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Standardized result returned by an agent."""

    agent_name: str
    status: AgentStatus
    data: dict[str,Any] = field(default_factory=dict)
    evidence: list[dict[str,Any]] = field(default_factory=list)
    error: dict[str,str] | None = None

    @property
    def success(self) -> bool:
        return self.status=="success"
