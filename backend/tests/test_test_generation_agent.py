from unittest.mock import Mock

from app.agents.contracts import AgentContext
from app.agents.test_generation_agent import (
    TestGenerationAgent as GenerationAgent,
)
from app.schemas.test_case_schema import (
    TestCaseGenerationRequest as GenerationRequest,
)
from app.services.test_case_generation_service import (
    TestCaseGenerationError as GenerationError,
)


def test_agent_rejects_invalid_input():
    agent = GenerationAgent(db=Mock())
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
    agent = GenerationAgent(db=db)
    request = Mock(spec=GenerationRequest)
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


def test_agent_propagates_workflow_correlation_and_provider_attempts():
    agent = GenerationAgent(db=Mock())
    request = Mock(spec=GenerationRequest)
    test_cases = [{"id": 14, "title": "Supported scenario"}]
    agent.service.generate = Mock(return_value=test_cases)
    agent.service.last_generation_stats = {
        "generation_status": "completed",
        "generated_count": 1,
        "final_persisted_count": 1,
        "correlation_id": "wf8-task12-gen3-example",
        "workflow_id": 8,
        "task_id": 12,
        "generation_attempt_number": 3,
        "response_diagnostics": [
            {"provider": "gemini", "model": "gemini-test"}
        ],
    }

    result = agent.run(
        AgentContext(
            user_id=1,
            project_id=10,
            task="test_generation",
            inputs={
                "request": request,
                "workflow_attempt_number": 3,
            },
            metadata={"workflow_id": 8, "task_id": 12},
        )
    )

    assert result.status == "success"
    agent.service.generate.assert_called_once_with(
        user_id=1,
        project_id=10,
        request=request,
        workflow_run_id=8,
        workflow_attempt_number=3,
        reuse_existing_workflow_attempt=False,
        workflow_task_id=12,
    )
    assert result.data["execution_metadata"]["correlation_id"] == (
        "wf8-task12-gen3-example"
    )
    assert result.data["execution_metadata"]["provider_attempts"] == [
        {"provider": "gemini", "model": "gemini-test"}
    ]


def test_agent_handles_generation_failure():
    agent = GenerationAgent(db=Mock())
    request = Mock(spec=GenerationRequest)
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


def test_agent_preserves_duplicate_failure_stage_for_workflow_retry():
    agent = GenerationAgent(db=Mock())
    request = Mock(spec=GenerationRequest)
    agent.service.generate = Mock(
        side_effect=GenerationError(
            "existing_case_duplicate",
            "Generated case duplicates existing case ID 16",
        )
    )

    result = agent.run(
        AgentContext(
            user_id=1,
            project_id=10,
            task="test_generation",
            inputs={"request": request},
        )
    )

    assert result.status == "failed"
    assert result.error["stage"] == "existing_case_duplicate"
    assert "ID 16" in result.error["message"]