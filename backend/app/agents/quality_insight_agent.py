import logging

from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.services.analytics_service import AnalyticsService
from app.services.test_execution_service import TestExecutionService
from app.services.llm_services import LLMService

logger = logging.getLogger(__name__)


class QualityInsightAgent(BaseAgent):

    name = "quality_insight_agent"

    def __init__(self, db):
        self.analytics = AnalyticsService(db)
        self.execution_service = TestExecutionService(db)
        self.llm = LLMService()

    def run(self, context: AgentContext) -> AgentResult:

        try:
            overview = self.analytics.get_project_overview(
                project_id=context.project_id,
                current_user_id=context.user_id,
            )

            documents = self.analytics.get_document_statistics(
                current_user_id=context.user_id,
                project_id=context.project_id,
            )

            history = self.execution_service.get_execution_history(
                user_id=context.user_id,
                project_id=context.project_id,
                limit=100,
                offset=0,
            )

            executions = history.get("executions", [])

            status_counts = {
                "passed": 0,
                "failed": 0,
                "error": 0,
                "other": 0,
            }

            for execution in executions:
                status = execution.get("status", "other")
                if status in status_counts:
                    status_counts[status] += 1
                else:
                    status_counts["other"] += 1

            total_executions = len(executions)

            pass_rate = (
                round(status_counts["passed"] / total_executions * 100, 2)
                if total_executions else None
            )

            metrics = {
                "knowledge_health": overview,
                "document_statistics": documents,
                "testing_health": {
                    "total_executions": total_executions,
                    "status_distribution": status_counts,
                    "pass_rate_percentage": pass_rate,
                },
            }

            prompt = """
You are TestNova's Quality Insight Agent.

Analyse the supplied project knowledge and testing metrics.

Return valid JSON with these fields:

{
  "overall_quality": "good | needs_attention | poor | insufficient_data",
  "knowledge_insights": [],
  "testing_insights": [],
  "quality_risks": [],
  "coverage_gaps": [],
  "recommendations": [],
  "limitations": []
}

Rules:
- Use only the supplied data.
- Do not invent metrics or project facts.
- Distinguish observed facts from possible risks.
- Do not claim requirements coverage unless the supplied data supports it.
- If execution data is insufficient, state that clearly.
- Do not automatically modify project records.
"""

            response = self.llm.generate_content(
                system_prompt=prompt,
                user_prompt=str(metrics),
                response_mime_type="application/json",
            )

            if not response.get("success"):
                return AgentResult(
                    agent_name=self.name,
                    status="partial",
                    data={
                        "metrics": metrics,
                        "analysis_error": "AI insights were unavailable.",
                    },
                )

            return AgentResult(
                agent_name=self.name,
                status="success",
                data={
                    "metrics": metrics,
                    "insights": response.get("answer"),
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
            logger.exception("Quality Insight Agent failed")

            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "QUALITY_INSIGHT_FAILED",
                    "message": "Quality insight analysis failed.",
                },
            )