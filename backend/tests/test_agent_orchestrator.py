
from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.agents.orchestrator import Orchestrator


class DummyAgent(BaseAgent):
    name = "dummy_agent"

    def run(self, context: AgentContext) -> AgentResult:
        return AgentResult(
            agent_name=self.name,
            status="success",
            data={"task": context.task},
        )


def test_orchestrator_routes_registered_task():
    orchestrator = Orchestrator()
    orchestrator.register("test_generation", DummyAgent())

    context = AgentContext(
        user_id=1,
        project_id=10,
        task="test_generation",
    )

    result = orchestrator.route(context)

    assert result.success
    assert result.agent_name == "dummy_agent"
    assert result.data["task"] == "test_generation"


def test_orchestrator_handles_unknown_task():
    orchestrator = Orchestrator()

    context = AgentContext(
        user_id=1,
        project_id=10,
        task="unknown_task",
    )

    result = orchestrator.route(context)

    assert result.status == "failed"
    assert result.error["code"] == "AGENT_NOT_FOUND"


def test_orchestrator_rejects_duplicate_registration():
    orchestrator = Orchestrator()
    orchestrator.register("test_generation", DummyAgent())

    try:
        orchestrator.register("test_generation", DummyAgent())
        assert False, "Expected ValueError"
    except ValueError:
        pass
