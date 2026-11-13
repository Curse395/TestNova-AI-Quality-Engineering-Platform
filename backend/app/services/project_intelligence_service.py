import hashlib
import json
import logging
import re
import threading
from collections import Counter, OrderedDict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.llm.structured_output import validate_structured_output
from app.models.organization import Organization
from app.models.project import Project
from app.models.test_execution import TestExecutionRun
from app.models.workflow_run import WorkflowRun
from app.models.workflow_task import WorkflowTask
from app.schemas.quality_summary_schema import QualitySummaryContent
from app.services.analytics_service import AnalyticsService

if TYPE_CHECKING:
    from app.services.llm_services import LLMService

logger = logging.getLogger(__name__)

_SUMMARY_CACHE_LIMIT = 128
_MAX_RISK_FINDINGS = 100
_MAX_SUMMARY_RISK_FINDINGS = 30
_SUMMARY_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|access[_ -]?token|password|secret|"
    r"credential)\b([\"']?\s*[:=]\s*[\"']?)[^\s,\"']+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+\S+")
_PROVIDER_TOKEN = re.compile(r"\b(?:AIza[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{16,})\b")


def _safe_text(value: object, limit: int = 1000) -> str:
    if not isinstance(value, str):
        return ""
    flattened = " ".join(value.split())
    if re.search(r"(?i)traceback \(most recent call last\)|stack trace|sqlalchemy\.", flattened):
        return "Detailed diagnostic information is withheld."
    flattened = _SECRET_ASSIGNMENT.sub(r"\1\2[redacted]", flattened)
    flattened = _BEARER_TOKEN.sub("Bearer [redacted]", flattened)
    flattened = _PROVIDER_TOKEN.sub("[redacted]", flattened)
    return flattened[:limit]


def _safe_error(error: object) -> dict[str, str] | None:
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    safe_code = (
        code
        if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code)
        else None
    )
    message = _safe_text(error.get("message"), 500)
    if not safe_code and not message:
        return None
    return {
        **({"code": safe_code} if safe_code else {}),
        "message": message or "Detailed diagnostic information is withheld.",
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _duration_ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    start_utc = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
    end_utc = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
    duration = (end_utc - start_utc).total_seconds() * 1000
    return round(duration) if duration >= 0 else None


def _sort_timestamp(value: datetime | None) -> float:
    if value is None:
        return float("-inf")
    normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return normalized.timestamp()


class EvidenceFingerprintCache:
    """Bounded process-local cache for summaries of identical evidence."""

    def __init__(self, maximum_entries: int = _SUMMARY_CACHE_LIMIT):
        if maximum_entries < 1:
            raise ValueError("Cache size must be positive.")
        self.maximum_entries = maximum_entries
        self._values: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._values.get(fingerprint)
            if value is None:
                return None
            self._values.move_to_end(fingerprint)
            return json.loads(json.dumps(value))

    def put(self, fingerprint: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._values[fingerprint] = json.loads(json.dumps(value))
            self._values.move_to_end(fingerprint)
            while len(self._values) > self.maximum_entries:
                self._values.popitem(last=False)


def _evidence_fingerprint(evidence: dict[str, Any]) -> str:
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProjectIntelligenceService:
    def __init__(
        self,
        db: Session,
        llm_service: "LLMService | None" = None,
        summary_cache: EvidenceFingerprintCache | None = None,
    ):
        self.db = db
        self.llm = llm_service
        self.summary_cache = summary_cache or _DEFAULT_SUMMARY_CACHE

    def require_owned_project(self, project_id: int, current_user_id: int) -> None:
        project = (
            self.db.query(Project)
            .join(Organization)
            .filter(
                Project.id == project_id,
                Organization.owner_id == current_user_id,
            )
            .first()
        )
        if project is None:
            raise ValueError("Project not found")

    @staticmethod
    def _risk_evidence_references(
        workflow_id: int,
        task_id: int,
        references: object,
    ) -> list[dict[str, Any]]:
        evidence = [
            {"id": f"workflow:{workflow_id}:task:{task_id}", "kind": "workflow_task"}
        ]
        if not isinstance(references, list):
            return evidence
        seen: set[tuple[object, object]] = set()
        for item in references[:20]:
            if not isinstance(item, dict):
                continue
            document_id = item.get("document_id")
            chunk_id = item.get("chunk_id")
            if not isinstance(document_id, int) or isinstance(document_id, bool):
                continue
            if not isinstance(chunk_id, int) or isinstance(chunk_id, bool):
                chunk_id = None
            key = (document_id, chunk_id)
            if key in seen:
                continue
            seen.add(key)
            reference = {
                "id": f"document:{document_id}:chunk:{chunk_id}",
                "kind": "document_chunk",
                "document_id": document_id,
            }
            if chunk_id is not None:
                reference["chunk_id"] = chunk_id
            name = _safe_text(item.get("document_name"), 200)
            if name:
                reference["label"] = name
            evidence.append(reference)
        return evidence

    @classmethod
    def build_risk_analytics(
        cls,
        risk_tasks: Iterable[tuple[int, int, object, object, object]],
        execution_status_counts: Iterable[tuple[object, int]],
        recent_executions: Iterable[tuple[int, object]],
    ) -> dict[str, Any]:
        severity_counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "unclassified": 0,
        }
        category_counts: Counter[str] = Counter()
        risks: list[dict[str, Any]] = []
        for workflow_id, task_id, status, output_data, completed_at in risk_tasks:
            if status not in {"completed", "partial"} or not isinstance(output_data, dict):
                continue
            structured = output_data.get("structured_data")
            if not isinstance(structured, dict):
                continue
            risk_level = str(structured.get("risk_level", "")).strip().lower()
            severity = risk_level if risk_level in {
                "critical", "high", "medium", "low"
            } else "unclassified"
            references = cls._risk_evidence_references(
                workflow_id,
                task_id,
                output_data.get("evidence_references"),
            )
            has_document_evidence = any(
                reference["kind"] == "document_chunk"
                for reference in references
            )
            risk_factors = structured.get("risk_factors")
            if not isinstance(risk_factors, list):
                risk_factors = []
            impact = structured.get("potential_impact")
            if not isinstance(impact, list):
                impact = []
            explanation = _safe_text(structured.get("reasoning"), 1000)
            for index, factor in enumerate(risk_factors[:20]):
                description = _safe_text(factor)
                if not description:
                    continue
                risks.append({
                    "id": f"workflow:{workflow_id}:task:{task_id}:risk:{index}",
                    "kind": "ai_inferred",
                    "severity": severity,
                    "category": "change_impact",
                    "description": description,
                    "explanation": explanation or "Identified by the persisted change-risk assessment.",
                    "potential_impact": [
                        text for text in (_safe_text(item, 500) for item in impact[:10]) if text
                    ],
                    "source_workflow_id": workflow_id,
                    "source_task_id": task_id,
                    "assessed_at": _iso(completed_at),
                    "evidence_references": references,
                    "supporting_evidence_available": has_document_evidence,
                    "evidence_note": None if has_document_evidence else (
                        "No document/chunk evidence reference was persisted with this assessment."
                    ),
                    "severity_basis": "AI-assessed category; not a measured probability.",
                })
                severity_counts[severity] += 1
                category_counts["change_impact"] += 1

        status_counts = AnalyticsService.execution_status_counts(execution_status_counts)
        observed_failure_count = status_counts["failed"] + status_counts["error"]
        if observed_failure_count:
            run_ids = []
            for run_id, status in recent_executions:
                if AnalyticsService.classify_execution_status(status) in {"failed", "error"}:
                    run_ids.append(run_id)
                    if len(run_ids) == 20:
                        break
            references = [
                {"id": f"execution_run:{run_id}", "kind": "execution_run"}
                for run_id in run_ids
            ]
            risks.append({
                "id": "observed:execution_failures",
                "kind": "observed_fact",
                "severity": "unclassified",
                "category": "execution_failures",
                "description": (
                    f"{observed_failure_count} persisted execution runs were classified "
                    "as failed or error."
                ),
                "explanation": (
                    "This is an observed execution count, not an inferred impact or "
                    "probability assessment."
                ),
                "potential_impact": [],
                "source_workflow_id": None,
                "source_task_id": None,
                "assessed_at": None,
                "evidence_references": references,
                "supporting_evidence_available": bool(references),
                "evidence_note": None if references else "No execution-run references were available.",
                "severity_basis": "Not assigned; execution status alone does not establish severity.",
                "evidence_reference_count": observed_failure_count,
                "evidence_references_truncated": observed_failure_count > len(references),
            })
            severity_counts["unclassified"] += 1
            category_counts["execution_failures"] += 1

        risk_count = len(risks)
        risks.sort(
            key=lambda risk: (
                0
                if risk["kind"] == "ai_inferred"
                and risk["severity"] in {"critical", "high"}
                else 1
                if risk["kind"] == "observed_fact"
                else 2
            )
        )
        returned_risks = risks[:_MAX_RISK_FINDINGS]
        return {
            "risk_count": risk_count,
            "returned_risk_count": len(returned_risks),
            "risk_findings_truncated": risk_count > len(returned_risks),
            "severity_counts": severity_counts,
            "category_counts": dict(sorted(category_counts.items())),
            "high_priority_risks": [
                risk for risk in returned_risks
                if risk["kind"] == "ai_inferred"
                and risk["severity"] in {"critical", "high"}
            ],
            "risks": returned_risks,
            "evidence_available": bool(risks),
            "supporting_evidence_available": any(
                risk["supporting_evidence_available"]
                for risk in returned_risks
            ),
            "limitations": [
                "Change-impact findings are AI-inferred from persisted ChangeRiskAgent outputs.",
                "Severity labels are agent assessments, not probabilities or calibrated measurements.",
                "Execution failures are observed facts with unclassified severity.",
                "Only the latest 20 failed/error run IDs are attached as evidence references.",
                "At most 100 risk findings are returned; counts include all findings in the queried task window.",
            ],
            "unavailable_reason": None if risks else (
                "No persisted change-risk findings or failed/error execution records exist."
            ),
        }

    def get_project_risks(self, project_id: int, current_user_id: int) -> dict[str, Any]:
        self.require_owned_project(project_id, current_user_id)
        risk_tasks = (
            self.db.query(
                WorkflowRun.id,
                WorkflowTask.id,
                WorkflowTask.status,
                WorkflowTask.output_data,
                WorkflowTask.completed_at,
            )
            .join(WorkflowTask, WorkflowTask.workflow_run_id == WorkflowRun.id)
            .filter(
                WorkflowRun.project_id == project_id,
                WorkflowTask.task_type == "change_risk_analysis",
            )
            .order_by(WorkflowTask.completed_at.desc(), WorkflowTask.id.desc())
            .limit(101)
            .all()
        )
        risk_task_window_truncated = len(risk_tasks) > 100
        risk_tasks = risk_tasks[:100]
        status_counts = (
            self.db.query(TestExecutionRun.status, func.count(TestExecutionRun.id))
            .filter(TestExecutionRun.project_id == project_id)
            .group_by(TestExecutionRun.status)
            .all()
        )
        recent_executions = (
            self.db.query(TestExecutionRun.id, TestExecutionRun.status)
            .filter(TestExecutionRun.project_id == project_id)
            .order_by(TestExecutionRun.created_at.desc(), TestExecutionRun.id.desc())
            .limit(100)
            .all()
        )
        result = self.build_risk_analytics(
            risk_tasks,
            status_counts,
            recent_executions,
        )
        return {
            "project_id": project_id,
            "risk_task_count": len(risk_tasks),
            "risk_task_window_truncated": risk_task_window_truncated,
            **result,
        }

    @staticmethod
    def _safe_workflow_monitoring(workflow: WorkflowRun) -> dict[str, Any]:
        tasks = sorted(
            workflow.tasks or [],
            key=lambda task: (_sort_timestamp(task.created_at), task.id),
        )
        started_tasks = sorted(
            (task for task in tasks if task.started_at is not None),
            key=lambda task: (_sort_timestamp(task.started_at), task.id),
        )
        execution_order = {
            task.id: index
            for index, task in enumerate(started_tasks, start=1)
        }
        task_payloads = []
        for order, task in enumerate(tasks, start=1):
            attempts = sorted(task.attempts or [], key=lambda attempt: attempt.attempt_number)
            task_payloads.append({
                "id": task.id,
                "plan_order": order,
                "execution_order": execution_order.get(task.id),
                "agent_name": _safe_text(task.agent_name, 100),
                "task_type": _safe_text(task.task_type, 100),
                "status": task.status,
                "attempt_count": task.attempt_count,
                "started_at": _iso(task.started_at),
                "completed_at": _iso(task.completed_at),
                "duration_ms": _duration_ms(task.started_at, task.completed_at),
                "error": _safe_error(task.error_details),
                "attempts": [
                    {
                        "attempt_number": attempt.attempt_number,
                        "status": attempt.status,
                        "started_at": _iso(attempt.started_at),
                        "completed_at": _iso(attempt.completed_at),
                        "duration_ms": _duration_ms(
                            attempt.started_at,
                            attempt.completed_at,
                        ),
                        "error": _safe_error(attempt.error_details),
                    }
                    for attempt in attempts
                ],
            })
        return {
            "id": workflow.id,
            "workflow_type": _safe_text(workflow.workflow_type, 100),
            "status": workflow.status,
            "created_at": _iso(workflow.created_at),
            "started_at": _iso(workflow.started_at),
            "completed_at": _iso(workflow.completed_at),
            "duration_ms": _duration_ms(workflow.started_at, workflow.completed_at),
            "error_summary": _safe_text(workflow.error_summary, 500) or None,
            "tasks": task_payloads,
            "task_count": len(task_payloads),
            "failed_task_count": sum(task["status"] == "failed" for task in task_payloads),
            "retried_task_count": sum(task["attempt_count"] > 1 for task in task_payloads),
            "snapshot_only": True,
            "task_execution_order_basis": "started_at; concurrent tasks may overlap",
        }

    def get_workflow_monitoring(
        self,
        project_id: int,
        current_user_id: int,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("Workflow monitoring limit must be between 1 and 100.")
        self.require_owned_project(project_id, current_user_id)
        workflows = (
            self.db.query(WorkflowRun)
            .filter(WorkflowRun.project_id == project_id)
            .options(
                selectinload(WorkflowRun.tasks).selectinload(WorkflowTask.attempts)
            )
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(limit)
            .all()
        )
        return {
            "project_id": project_id,
            "snapshot_only": True,
            "workflow_count": len(workflows),
            "workflows": [
                self._safe_workflow_monitoring(workflow)
                for workflow in workflows
            ],
        }

    def _summary_evidence(
        self,
        project_id: int,
        current_user_id: int,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        analytics = AnalyticsService(self.db)
        test_cases = analytics.get_test_case_statistics(project_id, current_user_id)
        traceability = analytics.get_requirement_traceability(project_id, current_user_id)
        executions = analytics.get_execution_analytics(project_id, current_user_id)
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=30)
        trends = analytics.get_execution_trends(
            project_id,
            current_user_id,
            start=start,
            end=end,
            bucket="day",
        )
        risks = self.get_project_risks(project_id, current_user_id)
        summary_risks = {
            "risk_count": risks["risk_count"],
            "returned_risk_count": min(
                risks["risk_count"],
                _MAX_SUMMARY_RISK_FINDINGS,
            ),
            "risk_findings_truncated": (
                risks["risk_findings_truncated"]
                or risks["risk_count"] > _MAX_SUMMARY_RISK_FINDINGS
            ),
            "severity_counts": risks["severity_counts"],
            "category_counts": risks["category_counts"],
            "evidence_available": risks["evidence_available"],
            "unavailable_reason": risks["unavailable_reason"],
            "risk_task_window_truncated": risks["risk_task_window_truncated"],
            "risks": risks["risks"][:_MAX_SUMMARY_RISK_FINDINGS],
        }
        evidence = {
            "test_case_statistics": test_cases,
            "requirement_traceability": traceability,
            "execution_summary": executions,
            "execution_trends": trends,
            "risk_findings": summary_risks,
        }
        sources = [
            {"id": "test_case_statistics", "description": "Persisted test-case counts and distributions."},
            {"id": "requirement_traceability", "description": "Persisted explicit/inferred requirement links."},
            {"id": "execution_summary", "description": "Persisted execution-run totals and durations."},
            {"id": "execution_trends", "description": "Persisted execution runs for the last 30 complete UTC days."},
            {"id": "risk_findings", "description": "Persisted change-risk findings and observed failures."},
        ]
        for risk in summary_risks["risks"]:
            sources.append({
                "id": risk["id"],
                "description": _safe_text(risk["description"], 500),
            })
            sources.extend(
                {"id": reference["id"], "description": reference["kind"]}
                for reference in risk["evidence_references"]
            )
        sources = list({source["id"]: source for source in sources}.values())
        return evidence, sources

    @staticmethod
    def validate_summary_references(
        summary: QualitySummaryContent,
        allowed_evidence_ids: set[str],
    ) -> None:
        statements = [summary.overall_summary]
        for field_name in (
            "testing_activity",
            "test_case_quality",
            "requirement_traceability",
            "execution_trends",
            "significant_failures",
            "identified_risks",
            "missing_evidence",
            "recommended_actions",
            "limitations",
        ):
            statements.extend(getattr(summary, field_name))
        for statement in statements:
            if not set(statement.evidence_ids).issubset(allowed_evidence_ids):
                raise ValueError("Summary references evidence outside the supplied project data.")

    @staticmethod
    def sanitize_summary(summary: QualitySummaryContent) -> QualitySummaryContent:
        payload = summary.model_dump()
        fields = (
            "overall_summary",
            "testing_activity",
            "test_case_quality",
            "requirement_traceability",
            "execution_trends",
            "significant_failures",
            "identified_risks",
            "missing_evidence",
            "recommended_actions",
            "limitations",
        )
        for field_name in fields:
            values = payload[field_name]
            statements = [values] if field_name == "overall_summary" else values
            for item in statements:
                item["statement"] = _safe_text(item["statement"], 1200)
        return QualitySummaryContent.model_validate(payload)

    def generate_quality_summary(
        self,
        project_id: int,
        current_user_id: int,
    ) -> dict[str, Any]:
        self.require_owned_project(project_id, current_user_id)
        evidence, sources = self._summary_evidence(project_id, current_user_id)
        fingerprint = _evidence_fingerprint(
            {"project_id": project_id, "evidence": evidence}
        )
        cached = self.summary_cache.get(fingerprint)
        if cached is not None:
            return {
                **cached,
                "project_id": project_id,
                "cached": True,
                "evidence_fingerprint": fingerprint,
            }

        system_prompt = (
            "You are TestNova's evidence-grounded quality summarizer. Return only "
            "JSON matching the supplied JSON Schema. Every statement must cite one or "
            "more supplied evidence IDs. Use only supplied evidence. Mark "
            "interpretation=true for inferences; observed metrics are not "
            "interpretations. Requirement links are traceability only, never proof "
            "of complete testing. State missing evidence explicitly. Do not invent "
            "defects, risks, requirements, behavior, or test results. Never provide "
            "a release-readiness verdict, confidence score, or production-ready claim. "
            "Recommended actions must be framed as suggestions, not facts.\n\n"
            "JSON Schema:\n"
            + json.dumps(QualitySummaryContent.model_json_schema(), sort_keys=True)
        )
        user_prompt = json.dumps(
            {"project_id": project_id, "evidence": evidence, "sources": sources},
            sort_keys=True,
            default=str,
        )
        llm = self.llm
        if llm is None:
            from app.services.llm_services import LLMService

            llm = LLMService()
        response = llm.generate_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_mime_type="application/json",
        )
        if not response.get("success") or not isinstance(response.get("answer"), str):
            logger.warning(
                "Quality summary generation returned an unsuccessful LLM response for project_id=%s",
                project_id,
            )
            return self._summary_unavailable(project_id, sources, fingerprint)
        validated = validate_structured_output(
            response["answer"],
            QualitySummaryContent,
        )
        if not validated.success or validated.value is None:
            logger.warning(
                "Quality summary response failed structured validation for project_id=%s",
                project_id,
            )
            return self._summary_unavailable(project_id, sources, fingerprint)
        safe_summary = self.sanitize_summary(validated.value)
        try:
            self.validate_summary_references(
                safe_summary,
                {source["id"] for source in sources},
            )
        except ValueError:
            logger.warning(
                "Quality summary referenced evidence outside the supplied project data for project_id=%s",
                project_id,
            )
            return self._summary_unavailable(project_id, sources, fingerprint)
        response_data = {
            "project_id": project_id,
            "status": "available",
            "summary": safe_summary.model_dump(),
            "evidence_sources": sources,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "evidence_fingerprint": fingerprint,
            "limitations": [
                "AI interpretation is based only on the listed aggregate evidence.",
                "Requirement traceability does not establish complete or adequate testing.",
                "No release-readiness or production-readiness determination is made.",
                "Evidence IDs are validated, but semantic entailment of AI wording is not automatically verified.",
                "Failure error text is excluded from summary inputs to avoid exposing sensitive diagnostics.",
            ],
        }
        cache_value = {
            key: value
            for key, value in response_data.items()
            if key not in {"project_id", "cached"}
        }
        self.summary_cache.put(fingerprint, cache_value)
        return response_data

    @staticmethod
    def _summary_unavailable(
        project_id: int,
        sources: list[dict[str, str]],
        fingerprint: str,
    ) -> dict[str, Any]:
        return {
            "project_id": project_id,
            "status": "unavailable",
            "summary": None,
            "evidence_sources": sources,
            "generated_at": None,
            "cached": False,
            "evidence_fingerprint": fingerprint,
            "limitations": [
                "A validated AI summary could not be generated from the available evidence.",
                "No summary claims or release-readiness conclusions are available.",
            ],
            "error": "Quality summary is temporarily unavailable.",
        }


_DEFAULT_SUMMARY_CACHE = EvidenceFingerprintCache()
