
import logging

from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.services.test_case_evaluation_service import (
    TestCaseEvaluationService,
)

logger = logging.getLogger(__name__)


class ReviewAgent(BaseAgent):
    """
    Reviews saved test cases using TestNova's existing
    structural, evidence and semantic evaluation service.
    """

    name = "review_agent"

    def __init__(self, db):
        self.service = TestCaseEvaluationService(db)

    def run(self, context: AgentContext) -> AgentResult:
        test_case_id = context.inputs.get("test_case_id")

        if (
            not isinstance(test_case_id, int)
            or isinstance(test_case_id, bool)
            or test_case_id <= 0
        ):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "INVALID_TEST_CASE_ID",
                    "message": "A valid test case ID is required.",
                },
            )

        try:
            evaluation = self.service.evaluate(
                user_id=context.user_id,
                project_id=context.project_id,
                test_case_id=test_case_id,
            )

            findings = evaluation.get("findings", [])
            checks = evaluation.get("checks", {})
            semantic = checks.get("semantic_evaluation")

            has_high = any(
                item.get("severity") == "high"
                for item in findings
            )

            unsupported = (
                isinstance(semantic, dict)
                and (
                    semantic.get("evidence_support") == "unsupported"
                    or semantic.get("expected_result_support") == "unsupported"
                )
            )

            if has_high or unsupported:
                recommendation = "needs_revision"
            elif evaluation.get("evaluation_status") != "completed":
                recommendation = "manual_review_required"
            elif findings:
                recommendation = "needs_revision"
            else:
                recommendation = evaluation.get("recommendation") or "human_review_required"

            return AgentResult(
                agent_name=self.name,
                status="success",
                data={
                    "test_case_id": test_case_id,
                    "project_id": context.project_id,
                    "recommendation": recommendation,
                    "evaluation_status": evaluation.get(
                        "evaluation_status"
                    ),
                    "findings": findings,
                    "checks": checks,
                    "review_status": evaluation.get("review_status"),
                    "requires_human_approval": True,
                    "note": (
                        "This review is advisory. "
                        "No automatic approval or rejection was performed."
                    ),
                },
                evidence=evaluation.get("evidence", []),
            )

        except ValueError:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "REVIEW_TARGET_NOT_FOUND",
                    "message": (
                        "The project or test case could not be accessed."
                    ),
                },
            )

        except Exception:
            logger.exception(
                "Review Agent failed for test case %s",
                test_case_id,
            )

            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "REVIEW_FAILED",
                    "message": "The test case review could not be completed.",
                },
            )
