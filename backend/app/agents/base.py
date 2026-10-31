
from abc import ABC, abstractmethod
from app.agents.contracts import AgentContext, AgentResult


class BaseAgent(ABC):
    """Common interface for every TestNova agent."""
    name: str

    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult:
        """Execute the task and return a standardized result."""
        raise NotImplementedError
