
import logging

from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult

logger = logging.getLogger(__name__)


class Orchestrator:
    """Routes tasks to registered TestNova agents."""

    WORKFLOW_TYPES = {
        "full_qa_workflow",
        "test_generation",
        "bug_analysis",
        "change_risk_analysis",
        "quality_insights",
    }

    WORKFLOW_TEMPLATES = {
        "full_qa_workflow": (
            "requirements_analysis",
            "change_risk_analysis",
            "test_analysis",
            "bug_analysis",
            "quality_insights",
            "test_generation",
            "deterministic_validation",
            "review",
            "aggregation",
        ),
        "test_generation": (
            "requirements_analysis",
            "test_generation",
            "deterministic_validation",
            "review",
            "aggregation",
        ),
        "bug_analysis": ("bug_analysis", "aggregation"),
        "change_risk_analysis": ("change_risk_analysis", "aggregation"),
        "quality_insights": (
            "test_analysis",
            "quality_insights",
            "aggregation",
        ),
    }

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, task: str, agent: BaseAgent) -> None:
        """Register an agent for a task."""
        normalized_task = task.strip().lower()

        if not normalized_task:
            raise ValueError("Task name cannot be empty.")

        if normalized_task in self._agents:
            raise ValueError(
                f"An agent is already registered for task {normalized_task}"
            )

        self._agents[normalized_task] = agent

    @classmethod
    def classify_task(cls, request_data: dict) -> str:
        """Resolve an explicit workflow type or classify common requests safely."""
        requested = request_data.get("workflow_type")
        if requested is not None:
            if not isinstance(requested, str) or requested not in cls.WORKFLOW_TYPES:
                raise ValueError("Unsupported workflow type.")
            return requested

        text = str(request_data.get("request") or request_data.get("prompt") or "")
        normalized = text.lower()
        if any(term in normalized for term in ("bug analysis", "analyze bugs", "defects")):
            return "bug_analysis"
        if any(term in normalized for term in ("change risk", "risk analysis", "changed files")):
            return "change_risk_analysis"
        if any(term in normalized for term in ("quality insight", "quality analytics")):
            return "quality_insights"
        if any(term in normalized for term in ("generate tests", "test generation")):
            return "test_generation"
        return "full_qa_workflow"

    @classmethod
    def workflow_template(cls, workflow_type: str) -> tuple[str, ...]:
        try:
            return cls.WORKFLOW_TEMPLATES[workflow_type]
        except KeyError as exc:
            raise ValueError("Unsupported workflow type.") from exc

    def route(self, context: AgentContext) -> AgentResult:
        """Execute the registered agent for the requested task."""
        task = context.task.strip().lower()
        agent = self._agents.get(task)

        if agent is None:
            return AgentResult(
                agent_name="orchestrator",
                status="failed",
                error={
                    "code": "AGENT_NOT_FOUND",
                    "message": f"No agent registered for task '{task}'."
                }
            )

        try:
            result = agent.run(context)

            if not isinstance(result, AgentResult):
                raise TypeError("Agent must return an AgentResult.")

            return result

        except Exception as exc:
            logger.exception(
                "Agent execution failed: agent_name=%s task=%s",
                agent.name,
                task,
            )
            return AgentResult(
                agent_name=agent.name,
                status="failed",
                error={
                    "code": "AGENT_EXECUTION_FAILED",
                    "type": type(exc).__name__,
                    "message": (
                        f"Agent '{agent.name}' failed while executing its task "
                        f"({type(exc).__name__})."
                    ),
                }
            )
