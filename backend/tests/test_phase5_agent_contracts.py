import json

from app.agents.change_risk_agent import ChangeRiskAgent
from app.agents.contracts import AgentContext
from app.agents.orchestrator import Orchestrator


def test_change_risk_agent_returns_validated_project_scoped_evidence(monkeypatch):
    evidence = [
        {
            "document_id": 8,
            "chunk_id": 21,
            "document_name": "requirements.md",
            "content": "The account session expires after inactivity.",
        }
    ]
    retrieval_calls = []

    class Retrieval:
        def search_project_context(self, **kwargs):
            retrieval_calls.append(kwargs)
            return evidence

    class LLM:
        def generate_content(self, **_kwargs):
            return {
                "success": True,
                "answer": json.dumps(
                    {
                        "risk_level": "High",
                        "risk_score": 81,
                        "confidence": "Medium",
                        "change_summary": "Change session expiration logic.",
                        "affected_areas": ["Authentication"],
                        "risk_factors": ["Session expiry regression"],
                        "potential_impact": ["Users may remain signed in."],
                        "recommended_tests": ["Verify session expiry."],
                        "reasoning": "The changed behavior is explicitly documented.",
                        "limitations": [],
                    }
                ),
            }

    monkeypatch.setattr(
        "app.agents.change_risk_agent.RetrievalService",
        lambda _db: Retrieval(),
    )
    monkeypatch.setattr(
        "app.agents.change_risk_agent.LLMService",
        lambda: LLM(),
    )
    agent = ChangeRiskAgent(db=None)
    result = agent.run(
        AgentContext(
            user_id=4,
            project_id=9,
            task="change_risk_analysis",
            inputs={
                "change_summary": "Change session expiration logic.",
                "change_type": "authentication",
                "changed_files": ["auth/session.py"],
            },
        )
    )

    assert result.status == "success"
    assert result.data["risk_level"] == "High"
    assert result.data["confidence"] == "Medium"
    assert result.data["evidence_count"] == 1
    assert result.evidence == evidence
    assert retrieval_calls[0]["current_user_id"] == 4
    assert retrieval_calls[0]["project_id"] == 9


def test_orchestrator_logs_agent_exception_and_returns_specific_failure(caplog):
    class RaisingAgent:
        name = "raising_agent"

        def run(self, _context):
            raise RuntimeError("internal provider failure")

    orchestrator = Orchestrator()
    orchestrator.register("test_generation", RaisingAgent())
    result = orchestrator.route(
        AgentContext(user_id=1, project_id=1, task="test_generation")
    )

    assert result.status == "failed"
    assert result.error["code"] == "AGENT_EXECUTION_FAILED"
    assert result.error["type"] == "RuntimeError"
    assert "RuntimeError" in result.error["message"]
    assert "internal provider failure" in caplog.text
