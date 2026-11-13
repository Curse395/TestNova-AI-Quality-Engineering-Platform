from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.test_execution import TestExecutionRun
from app.schemas.release_readiness_schema import ReleaseReadinessResponse
from app.services.analytics_service import AnalyticsService
from app.services.project_intelligence_service import ProjectIntelligenceService

_RECENT_EXECUTION_LIMIT = 10
_RECENT_WORKFLOW_LIMIT = 20


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class ReleaseReadinessService:
    """Composes persisted analytics into an explainable release review assessment."""

    def __init__(self, db: Session):
        self.db = db
        self.analytics = AnalyticsService(db)
        self.intelligence = ProjectIntelligenceService(db)

    @staticmethod
    def _concern(
        concern_id: str,
        title: str,
        attention: str,
        explanation: str,
        source: str,
        evidence_ids: list[str],
        next_action: str,
    ) -> dict[str, Any]:
        return {
            "id": concern_id,
            "title": title,
            "attention": attention,
            "explanation": explanation,
            "source": source,
            "evidence_ids": evidence_ids,
            "next_action": next_action,
        }

    @classmethod
    def build_assessment(
        cls,
        *,
        test_cases: dict[str, Any] | None,
        traceability: dict[str, Any] | None,
        executions: dict[str, Any] | None,
        risks: dict[str, Any] | None,
        workflows: dict[str, Any] | None,
        recent_executions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Classify persisted evidence without converting missing data into success."""
        concerns: list[dict[str, Any]] = []
        test_cases = test_cases if isinstance(test_cases, dict) else None
        traceability = traceability if isinstance(traceability, dict) else None
        executions = executions if isinstance(executions, dict) else None
        risks = risks if isinstance(risks, dict) else None
        workflows = workflows if isinstance(workflows, dict) else None
        recent_executions = recent_executions or []

        missing_metrics = [
            name
            for name, value in (
                ("test-case statistics", test_cases),
                ("requirement traceability", traceability),
                ("execution analytics", executions),
                ("risk analytics", risks),
                ("workflow monitoring", workflows),
            )
            if value is None
        ]
        if test_cases is not None:
            review_counts = test_cases.get("review_status_counts")
            if not isinstance(test_cases.get("total_cases"), int):
                missing_metrics.append("test-case total")
            if not isinstance(review_counts, dict) or any(
                not isinstance(review_counts.get(key), int)
                for key in ("approved", "draft", "rejected")
            ):
                missing_metrics.append("test-case review-status counts")
        if traceability is not None and any(
            not isinstance(traceability.get(key), int)
            for key in (
                "explicit_requirement_count",
                "inferred_requirement_count",
                "explicit_requirements_with_any_case_link",
                "explicit_requirements_with_approved_case_link",
                "unlinked_explicit_requirement_count",
            )
        ):
            missing_metrics.append("requirement traceability counts")
        if executions is not None:
            execution_counts = executions.get("status_counts")
            if not isinstance(executions.get("total_runs"), int):
                missing_metrics.append("execution-run total")
            if not isinstance(execution_counts, dict) or any(
                not isinstance(execution_counts.get(key), int)
                for key in ("passed", "failed", "error", "skipped", "other", "missing", "blank")
            ):
                missing_metrics.append("execution status counts")
        if missing_metrics:
            concerns.append(cls._concern(
                "analytics_unavailable",
                "Required project analytics are unavailable",
                "high",
                "Could not obtain: " + ", ".join(missing_metrics) + ".",
                "release_readiness",
                [],
                "Restore access to the missing analytics and reassess the project.",
            ))

        review_counts = test_cases.get("review_status_counts", {}) if test_cases else {}
        approved_cases = review_counts.get("approved")
        draft_cases = review_counts.get("draft")
        rejected_cases = review_counts.get("rejected")

        explicit_count = traceability.get("explicit_requirement_count") if traceability else None
        approved_linked = (
            traceability.get("explicit_requirements_with_approved_case_link")
            if traceability
            else None
        )
        any_linked = (
            traceability.get("explicit_requirements_with_any_case_link")
            if traceability
            else None
        )
        unlinked_explicit = (
            traceability.get("unlinked_explicit_requirement_count")
            if traceability
            else None
        )

        status_counts = executions.get("status_counts", {}) if executions else {}
        total_runs = executions.get("total_runs") if executions else None
        passed = status_counts.get("passed")
        failed = status_counts.get("failed")
        errored = status_counts.get("error")
        determinate_runs = (
            passed + failed
            if isinstance(passed, int) and isinstance(failed, int)
            else 0
        )

        if total_runs == 0:
            concerns.append(cls._concern(
                "execution_history_missing",
                "No execution history is available",
                "high",
                "No persisted execution runs are available; an empty history is not a passing result.",
                "test_execution_runs",
                [],
                "Execute approved test cases and review the persisted results.",
            ))
        elif isinstance(total_runs, int) and total_runs > 0 and determinate_runs == 0:
            concerns.append(cls._concern(
                "execution_status_indeterminate",
                "Execution results are not determinate",
                "high",
                "No run has a recognized passed or failed status, so a pass rate cannot be calculated.",
                "test_execution_runs",
                [f"execution_run:{run['id']}" for run in recent_executions if run.get("id") is not None],
                "Review execution records and persist recognized passed/failed outcomes.",
            ))

        if isinstance(failed, int) and failed > 0:
            concerns.append(cls._concern(
                "failed_executions",
                "Failed execution runs are present",
                "blocker",
                f"{failed} persisted execution run(s) are classified as failed.",
                "test_execution_runs",
                [f"execution_run:{run['id']}" for run in recent_executions if run.get("status_class") == "failed"],
                "Investigate the failures, resolve defects, and rerun affected approved cases.",
            ))
        if isinstance(errored, int) and errored > 0:
            concerns.append(cls._concern(
                "execution_errors",
                "Execution errors are present",
                "blocker",
                f"{errored} persisted execution run(s) are classified as errors.",
                "test_execution_runs",
                [f"execution_run:{run['id']}" for run in recent_executions if run.get("status_class") == "error"],
                "Resolve execution infrastructure or test errors and rerun affected cases.",
            ))

        if test_cases is not None and approved_cases == 0:
            concerns.append(cls._concern(
                "no_approved_cases",
                "No approved test cases",
                "high",
                "The project has no approved test cases to serve as reviewed execution evidence.",
                "test_case_statistics",
                [],
                "Review and approve suitable test cases before relying on execution results.",
            ))
        if isinstance(draft_cases, int) and draft_cases + (rejected_cases or 0) > 0:
            concerns.append(cls._concern(
                "unapproved_test_cases",
                "Test cases remain unapproved",
                "medium",
                f"{draft_cases} draft and {rejected_cases or 0} rejected case(s) are not approved.",
                "test_case_statistics",
                [],
                "Review draft cases and revise or retire rejected cases.",
            ))

        if isinstance(explicit_count, int) and explicit_count == 0:
            concerns.append(cls._concern(
                "explicit_requirements_missing",
                "No explicit requirements are available",
                "high",
                "Requirement traceability cannot be assessed without explicit requirements; inferred requirements are excluded from its denominator.",
                "requirement_traceability",
                [],
                "Record or import explicit project requirements before assessing traceability.",
            ))
        elif (
            isinstance(explicit_count, int)
            and explicit_count > 0
            and isinstance(approved_linked, int)
            and approved_linked < explicit_count
        ):
            linked_without_approved = max((any_linked or 0) - approved_linked, 0)
            concerns.append(cls._concern(
                "requirements_without_approved_case_link",
                "Explicit requirements lack approved-case links",
                "high",
                (
                    f"{explicit_count - approved_linked} of {explicit_count} explicit requirements "
                    f"lack an approved-case link ({unlinked_explicit or 0} have no case link; "
                    f"{linked_without_approved} link only to unapproved cases)."
                ),
                "requirement_traceability",
                [],
                "Link each explicit requirement to at least one approved test case and review the traceability.",
            ))

        high_risks = [
            risk
            for risk in (risks.get("risks", []) if risks else [])
            if risk.get("kind") == "ai_inferred"
            and risk.get("severity") in {"critical", "high"}
        ]
        for risk in high_risks:
            concerns.append(cls._concern(
                f"risk:{risk.get('id', 'unidentified')}",
                "High-severity AI-inferred risk",
                "high",
                risk.get("description") or "A persisted AI-inferred risk is assessed as high severity.",
                "project_risks",
                [item["id"] for item in risk.get("evidence_references", []) if item.get("id")],
                "Review the cited evidence and risk explanation; validate the assessment with the project team.",
            ))

        if risks and risks.get("risk_task_window_truncated"):
            concerns.append(cls._concern(
                "risk_history_truncated",
                "Risk assessment history is bounded",
                "medium",
                "Older change-risk tasks were omitted, so the returned findings are not a complete project history.",
                "project_risks",
                [],
                "Review older risk assessments in workflow history when a complete review is required.",
            ))
        if risks and not risks.get("evidence_available"):
            concerns.append(cls._concern(
                "risk_evidence_unavailable",
                "No persisted risk evidence is available",
                "medium",
                risks.get("unavailable_reason") or "The risk endpoint returned no persisted risk findings.",
                "project_risks",
                [],
                "Consider completing a change-risk assessment; an empty result is not proof of no risk.",
            ))

        workflow_counts = workflows.get("workflow_status_counts", {}) if workflows else {}
        failed_workflows = workflow_counts.get("failed", 0)
        partial_workflows = workflow_counts.get("partially_completed", 0)
        if failed_workflows or partial_workflows:
            concerns.append(cls._concern(
                "workflow_failures",
                "Recent workflows did not all complete",
                "medium",
                f"{failed_workflows} failed and {partial_workflows} partially completed workflow(s) occur in the monitored snapshot.",
                "workflow_monitoring",
                [
                    f"workflow:{workflow['id']}"
                    for workflow in workflows.get("workflows", [])
                    if workflow.get("status") in {"failed", "partially_completed"}
                ],
                "Inspect failed workflow tasks and retry or resolve the underlying workflow issues.",
            ))

        indeterminate_statuses = sum(
            status_counts.get(key, 0)
            for key in ("skipped", "other", "missing", "blank")
        )
        if indeterminate_statuses:
            concerns.append(cls._concern(
                "indeterminate_execution_statuses",
                "Some execution statuses are not pass/fail results",
                "medium",
                f"{indeterminate_statuses} run(s) are skipped, unknown, missing, or blank and are excluded from the pass-rate denominator.",
                "test_execution_runs",
                [
                    f"execution_run:{run['id']}"
                    for run in recent_executions
                    if run.get("status_class") in {"skipped", "other", "missing", "blank"}
                ],
                "Review these runs and persist an accurate outcome where one is available.",
            ))

        required_evidence_missing = bool(
            missing_metrics
            or not isinstance(total_runs, int)
            or total_runs == 0
            or (isinstance(total_runs, int) and total_runs > 0 and determinate_runs == 0)
            or (test_cases is not None and approved_cases == 0)
            or (isinstance(explicit_count, int) and explicit_count == 0)
        )
        blocker_present = any(item["attention"] == "blocker" for item in concerns)
        attention_present = any(
            item["attention"] in {"high", "medium"}
            for item in concerns
        )

        if blocker_present:
            state = "blocked"
            label = "Blocked"
            explanation = "Observed failed or errored execution runs must be addressed before release review."
        elif required_evidence_missing:
            state = "insufficient_evidence"
            label = "Insufficient evidence"
            explanation = "One or more required evidence sources are missing or do not establish reviewed, determinate testing."
        elif attention_present:
            state = "attention_required"
            label = "Attention required"
            explanation = "Persisted evidence identifies unresolved traceability, risk, workflow, or execution concerns."
        else:
            state = "ready_for_review"
            label = "Ready for review"
            explanation = "Available evidence meets the defined review checks; this is not a production-readiness determination."

        reasons = [f"{item['title']}: {item['explanation']}" for item in concerns]
        if not reasons:
            reasons.append(
                "Core evidence is available and no configured blocker or attention condition was detected."
            )
        return {
            "assessment": {
                "state": state,
                "label": label,
                "explanation": explanation,
                "reasons": reasons,
            },
            "concerns": concerns,
        }

    def get_project_release_readiness(
        self,
        project_id: int,
        current_user_id: int,
    ) -> dict[str, Any]:
        if project_id < 1:
            raise ValueError("Project ID must be a positive integer.")
        self.intelligence.require_owned_project(project_id, current_user_id)

        test_cases = self.analytics.get_test_case_statistics(project_id, current_user_id)
        traceability = self.analytics.get_requirement_traceability(project_id, current_user_id)
        executions = self.analytics.get_execution_analytics(project_id, current_user_id)
        execution_trends = self.analytics.get_execution_trends(
            project_id,
            current_user_id,
            bucket="day",
        )
        risks = self.intelligence.get_project_risks(project_id, current_user_id)
        workflow_monitoring = self.intelligence.get_workflow_monitoring(
            project_id,
            current_user_id,
            limit=_RECENT_WORKFLOW_LIMIT,
        )

        recent_rows = (
            self.db.query(
                TestExecutionRun.id,
                TestExecutionRun.status,
                TestExecutionRun.created_at,
            )
            .filter(TestExecutionRun.project_id == project_id)
            .order_by(TestExecutionRun.created_at.desc(), TestExecutionRun.id.desc())
            .limit(_RECENT_EXECUTION_LIMIT)
            .all()
        )
        first_execution_at, latest_execution_at, execution_count = (
            self.db.query(
                func.min(TestExecutionRun.created_at),
                func.max(TestExecutionRun.created_at),
                func.count(TestExecutionRun.id),
            )
            .filter(TestExecutionRun.project_id == project_id)
            .one()
        )
        recent_executions = [
            {
                "id": run_id,
                "status": status,
                "status_class": AnalyticsService.classify_execution_status(status),
                "created_at": _iso_utc(created_at),
            }
            for run_id, status, created_at in recent_rows
        ]
        workflow_status_counts = {
            status: 0
            for status in (
                "pending",
                "running",
                "completed",
                "partially_completed",
                "failed",
                "other",
            )
        }
        failed_task_count = 0
        retried_task_count = 0
        attempt_count = 0
        for workflow in workflow_monitoring["workflows"]:
            status = workflow.get("status")
            workflow_status_counts[status if status in workflow_status_counts else "other"] += 1
            failed_task_count += workflow.get("failed_task_count", 0)
            retried_task_count += workflow.get("retried_task_count", 0)
            attempt_count += sum(
                len(task.get("attempts", []))
                for task in workflow.get("tasks", [])
            )
        workflows = {
            **workflow_monitoring,
            "workflow_status_counts": workflow_status_counts,
            "failed_task_count": failed_task_count,
            "retried_task_count": retried_task_count,
            "attempt_count": attempt_count,
            "sample_limit": _RECENT_WORKFLOW_LIMIT,
        }
        time_range = {
            "first_execution_at": _iso_utc(first_execution_at),
            "latest_execution_at": _iso_utc(latest_execution_at),
            "observed_run_count": execution_count,
        }
        decision = self.build_assessment(
            test_cases=test_cases,
            traceability=traceability,
            executions=executions,
            risks=risks,
            workflows=workflows,
            recent_executions=recent_executions,
        )
        pass_rate = AnalyticsService.pass_rate(
            executions["status_counts"]["passed"],
            executions["status_counts"]["failed"],
        )
        metrics = {
            "test_cases": test_cases,
            "requirement_traceability": traceability,
            "executions": {
                **executions,
                "pass_rate": pass_rate,
                "time_range": time_range,
                "recent_runs": recent_executions,
                "trends": execution_trends,
            },
            "risks": risks,
            "workflows": workflows,
        }
        response = {
            "project_id": project_id,
            **decision,
            "metrics": metrics,
            "limitations": [
                "Ready for review is not a production-readiness or release approval verdict.",
                "Any failed or errored persisted execution run results in Blocked.",
                "High or critical risk severities are AI-assessed categories, not probabilities, and require human review.",
                "Execution history summaries are lifetime totals; recent runs are limited to 10 and workflows to the latest 20 snapshots.",
                "Execution trends cover the trailing 30 days using daily UTC buckets.",
                "Requirement links measure traceability only, not completeness or adequacy of testing.",
            ],
        }
        return ReleaseReadinessResponse.model_validate(response).model_dump()
