
from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult


class Orchestrator:
    """Routes tasks to registered TestNova agents."""

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

        except Exception:
            return AgentResult(
                agent_name=agent.name,
                status="failed",
                error={
                    "code": "AGENT_EXECUTION_FAILED",
                    "message": f"Agent '{agent.name}' failed while executing its task."
                }
            )
