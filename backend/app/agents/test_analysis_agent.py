import logging
from collections import Counter

from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.agents.execution_metrics import summarize_execution_statuses
from app.services.test_execution_service import TestExecutionService
from app.services.llm_services import LLMService

logger = logging.getLogger(__name__)


class TestAnalysisAgent(BaseAgent):

    name = "test_analysis_agent"

    def __init__(self, db):
        self.execution_service = TestExecutionService(db)
        self.llm = LLMService()

    def run(self, context: AgentContext) -> AgentResult:

        try:
            history = self.execution_service.get_execution_history(
                user_id=context.user_id,
                project_id=context.project_id,
                limit=100,
                offset=0,
            )

            executions = history.get("executions", [])

            if not executions:
                return AgentResult(
                    agent_name=self.name,
                    status="partial",
                    data={
                        "message": "No execution history available for analysis.",
                        "total_executions": 0,
                    },
                )

            status_counts = summarize_execution_statuses(executions)

            failed_executions = [
                item for item in executions
                if item.get("status") in ("failed", "error")
            ]

            durations = [
                item["duration_ms"]
                for item in executions
                if isinstance(item.get("duration_ms"), (int, float))
            ]

            average_duration = (
                round(sum(durations) / len(durations), 2)
                if durations else None
            )

            failed_assertions = []

            for execution in executions:
                for assertion in execution.get("assertions") or []:
                    if not assertion.get("passed", False):
                        failed_assertions.append({
                            "execution_id": execution.get("id"),
                            "test_case_id": execution.get("test_case_id"),
                            "check": assertion.get("check"),
                            "expected": assertion.get("expected"),
                            "actual": assertion.get("actual"),
                            "error": assertion.get("error"),
                        })

            failed_test_cases = Counter(
                item.get("test_case_id")
                for item in failed_executions
            )

            analysis_input = {
                "total_executions": len(executions),
                "status_distribution": dict(status_counts),
                "failed_executions": failed_executions,
                "failed_assertions": failed_assertions,
                "average_duration_ms": average_duration,
                "slowest_duration_ms": max(durations) if durations else None,
                "repeated_failure_test_cases": [
                    {
                        "test_case_id": test_case_id,
                        "failure_count": count,
                    }
                    for test_case_id, count in failed_test_cases.items()
                    if test_case_id is not None and count > 1
                ],
            }

            prompt = """
You are TestNova's Test Analysis Agent.

Analyse the supplied API test execution data.

Return valid JSON with these fields:

{
  "overall_quality": "good | needs_attention | poor | insufficient_data",
  "key_findings": [],
  "failure_patterns": [],
  "possible_root_causes": [],
  "performance_observations": [],
  "recommended_actions": [],
  "limitations": []
}

Rules:
- Use only the supplied execution data.
- Do not invent failures, causes, or metrics.
- Clearly distinguish observed facts from possible causes.
- Do not claim a root cause is confirmed without evidence.
- If data is insufficient, say so.
"""

            response = self.llm.generate_content(
                system_prompt=prompt,
                user_prompt=str(analysis_input),
                response_mime_type="application/json",
            )

            if not response.get("success"):
                return AgentResult(
                    agent_name=self.name,
                    status="partial",
                    data={
                        "metrics": analysis_input,
                        "analysis_error": "AI analysis was unavailable.",
                    },
                )

            return AgentResult(
                agent_name=self.name,
                status="success",
                data={
                    "metrics": analysis_input,
                    "analysis": response.get("answer"),
                    "model": response.get("model"),
                },
                evidence=[],
            )

        except ValueError:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "PROJECT_ACCESS_ERROR",
                    "message": "Project could not be accessed.",
                },
            )

        except Exception:
            logger.exception("Test Analysis Agent failed")

            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "TEST_ANALYSIS_FAILED",
                    "message": "Test execution analysis failed.",
                },
            )