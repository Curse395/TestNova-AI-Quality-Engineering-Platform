from app.agents.execution_metrics import summarize_execution_statuses


def test_summarize_execution_statuses_preserves_known_and_unknown_statuses():
    executions = [
        {"status": "passed"},
        {"status": "failed"},
        {"status": "passed"},
        {"status": "custom"},
        {},
    ]

    assert summarize_execution_statuses(executions) == {
        "passed": 2,
        "failed": 1,
        "custom": 1,
        "unknown": 1,
    }


def test_summarize_execution_statuses_supports_agent_specific_fallback():
    assert summarize_execution_statuses([{}], unknown_status="other") == {
        "other": 1,
    }
