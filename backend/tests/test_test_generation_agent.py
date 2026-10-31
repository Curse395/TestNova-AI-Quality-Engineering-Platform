from unittest.mock import Mock

from app.agents.contracts import AgentContext
from app.agents.test_generation_agent import TestGenerationAgent
from app.schemas.test_case_schema import TestCaseGenerationRequest


def test_agent_rejects_invalid_input():
    agent = TestGenerationAgent(db=Mock())
    context = AgentContext(
        user_id=1,
        project_id=10,
        task="test_generation",
        inputs={"request": "invalid"},
    )

    result = agent.run(context)

    assert result.status == "failed"
    assert result.error["code"] == "INVALID_INPUT"


def test_agent_returns_generated_test_cases():
    db = Mock()
    agent = TestGenerationAgent(db=db)
    request = Mock(spec=TestCaseGenerationRequest)
    expected_cases = [{"id": 1, "title": "Login test"}]

    agent.service.generate = Mock(return_value=expected_cases)

    context = AgentContext(
        user_id=1,
        project_id=10,
        task="test_generation",
        inputs={"request": request},
    )

    result = agent.run(context)

    assert result.status == "success"
    assert result.data["generated_count"] == 1
    assert result.data["test_cases"] == expected_cases
    agent.service.generate.assert_called_once_with(
        user_id=1,
        project_id=10,
        request=request,
    )


def test_agent_handles_generation_failure():
    agent = TestGenerationAgent(db=Mock())
    request = Mock(spec=TestCaseGenerationRequest)
    agent.service.generate = Mock(side_effect=RuntimeError("generation error"))

    context = AgentContext(
        user_id=1,
        project_id=10,
        task="test_generation",
        inputs={"request": request},
    )

    result = agent.run(context)

    assert result.status == "failed"
    assert result.error["code"] == "GENERATION_FAILED"