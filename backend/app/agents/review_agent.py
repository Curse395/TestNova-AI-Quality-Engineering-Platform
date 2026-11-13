
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
            missing_scenarios = [
                item
                for item in findings
                if item.get("check")
                in {"scenario_coverage", "requirement_coverage", "missing_scenarios"}
            ]

            blocking_findings = [
                item
                for item in findings
                if item.get("severity") in {"critical", "high", "medium"}
            ]

            unsupported = (
                isinstance(semantic, dict)
                and (
                    semantic.get("status")
                    in {"unsupported", "contradictory"}
                    or semantic.get("evidence_support") == "unsupported"
                    or semantic.get("evidence_support") == "contradictory"
                    or semantic.get("expected_result_support") == "unsupported"
                    or semantic.get("expected_result_support") == "contradictory"
                )
            )

            if blocking_findings or unsupported:
                recommendation = "needs_revision"
            elif evaluation.get("evaluation_status") != "completed":
                recommendation = "manual_review_required"
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
                    "review_status": evaluation.get("review_status"),
                    "findings": findings,
                    "warnings": [
                        item["message"]
                        for item in findings
                        if item.get("severity") == "low"
                        and isinstance(item.get("message"), str)
                    ],
                    "checks": checks,
                    "missing_scenarios": missing_scenarios,
                    "evidence_quality": {
                        "linked_evidence_count": checks.get(
                            "linked_evidence_count", 0
                        ),
                        "reference_status": checks.get(
                            "evidence_reference_status", "unknown"
                        ),
                        "verified_evidence_count": checks.get(
                            "verified_evidence_count", 0
                        ),
                        "invalid_evidence_chunk_ids": checks.get(
                            "invalid_evidence_chunk_ids", []
                        ),
                        "semantic_support": (
                            semantic.get("status")
                            if isinstance(semantic, dict)
                            else "unavailable"
                        ),
                    },
                    "coverage_observations": {
                        "requirement_coverage": (
                            semantic.get("requirement_coverage")
                            if isinstance(semantic, dict)
                            else "unclear"
                        ),
                        "exact_duplicate_case_ids": checks.get(
                            "exact_duplicate_case_ids", []
                        ),
                    },
                    "actionable_regeneration_feedback": [
                        item["message"]
                        for item in findings
                        if item.get("severity") in {"critical", "high", "medium"}
                        and isinstance(item.get("message"), str)
                    ],
                    "requires_human_approval": True,
                    "note": (
                        "This review is advisory. "
                        "No automatic approval or rejection was performed."
                    ),
                },
                evidence=evaluation.get("evidence", []),
            )

        except ValueError as exc:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "REVIEW_TARGET_NOT_FOUND",
                    "message": str(exc) or "The project or test case could not be accessed.",
                },
            )

        except Exception as exc:
            logger.exception(
                "Review Agent failed for test case %s",
                test_case_id,
            )

            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "REVIEW_FAILED",
                    "message": str(exc) or "The test case review could not be completed.",
                },
            )
