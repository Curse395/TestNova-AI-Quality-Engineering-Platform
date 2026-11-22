import re
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.project_requirement import ProjectRequirement
from app.models.test_case import TestCase
from app.models.test_case_evidence import TestCaseEvidence
from app.models.test_case_requirement import TestCaseRequirement
from app.models.document_embedding import DocumentEmbedding
from app.models.test_execution import TestExecutionRun
from app.services.analytics_service import AnalyticsService
from app.services.project_intelligence_service import ProjectIntelligenceService
from app.services.release_readiness_service import ReleaseReadinessService
from app.services.test_execution_service import TestExecutionService


@dataclass(frozen=True)
class AssistantQuestionPlan:
    intents: tuple[str, ...]
    use_retrieval: bool
    retrieval_similarity: bool = False
    document_follow_up: bool = False
    architecture: bool = False
    conversation: bool = False


class AssistantQuestionRouter:
    """Routes clear project-data questions to existing deterministic services."""

    _ARCHITECTURE_TERMS = (
        "testgenerationagent",
        "knowledgeagent",
        "requirementsanalysisagent",
        "reviewagent",
        "change_risk_agent",
        "qualityinsightagent",
        "testanalysisagent",
        "buganalysisagent",
        "orchestrator",
        "workflow resume",
        "workflow resume mechanism",
        "api endpoint",
        "platform architecture",
        "testnova architecture",
        "testnova platform",
        "gemini rate limit",
        "gemini reaches its rate limit",
        "llm fallback",
        "provider fallback",
        "rate limit fallback",
        "workflow resume",
        "provider timeout",
        "llm timeout",
    )
    _FOLLOW_UP_TERMS = ("its", "their", "that", "those", "what about")

    @classmethod
    def project_history(cls, conversation_history: Iterable[object]) -> tuple[object, ...]:
        history_items = tuple(conversation_history)
        return tuple(
            item
            for index, item in enumerate(history_items)
            if not cls.plan(
                str(getattr(item, "question", "") or ""),
                history_items[index + 1 :],
            ).architecture
        )

    @classmethod
    def plan(
        cls,
        question: str,
        conversation_history: Iterable[object] = (),
    ) -> AssistantQuestionPlan:
        normalized = re.sub(
            r"[\s.!?,]+$",
            "",
            re.sub(r"\s+", " ", question.strip().lower()),
        )
        history_items = tuple(conversation_history)
        latest_question = (
            str(getattr(history_items[0], "question", "") or "")
            if history_items
            else ""
        )
        architecture_follow_up = (
            any(phrase in normalized for phrase in ("what about", "how about", "and the"))
            and bool(latest_question)
            and cls.plan(latest_question).architecture
        )
        project_history = cls.project_history(history_items)
        history_text = " ".join(
            " ".join(
                str(getattr(item, field, "") or "")
                for field in ("question", "answer")
            )
            for item in project_history
        ).lower()

        if normalized in {
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "good morning",
            "good afternoon",
        }:
            return AssistantQuestionPlan((), use_retrieval=False, conversation=True)

        if (
            any(term in normalized for term in cls._ARCHITECTURE_TERMS)
            or (
                "gemini" in normalized
                and any(term in normalized for term in ("rate limit", "timeout"))
            )
            or architecture_follow_up
            or (
                "endpoint" in normalized
                and any(term in normalized for term in ("test case", "test-case", "generation"))
            )
            or ("model" in normalized and "execution history" in normalized)
        ):
            return AssistantQuestionPlan(
                (),
                use_retrieval=False,
                architecture=True,
            )

        if "dimension" in normalized and "embedding" in normalized:
            return AssistantQuestionPlan(
                ("embedding_dimensions",),
                use_retrieval=False,
            )

        retrieval_similarity = (
            "similarity" in normalized
            or "cosine distance" in normalized
        ) and any(
            term in normalized
            for term in ("retrieval", "retrieved", "document", "chunk", "source")
        )
        if retrieval_similarity:
            return AssistantQuestionPlan(
                (),
                use_retrieval=True,
                retrieval_similarity=True,
            )

        document_follow_up = (
            any(term in normalized for term in cls._FOLLOW_UP_TERMS)
            and any(term in normalized for term in ("chunk", "embedding"))
            and "document" in history_text
        )
        document_question = (
            any(term in normalized for term in ("document", "documents", "doc", "embedding", "embeddings", "chunk", "chunks"))
            and any(
                term in normalized
                for term in (
                    "count",
                    "how many",
                    "fewest",
                    "least",
                    "lowest",
                    "most",
                    "highest",
                    "status",
                    "need",
                    "missing",
                    "coverage",
                    "which",
                    "compare",
                    "total",
                    "its",
                    "their",
                )
            )
        ) or document_follow_up

        intents: list[str] = []
        if document_question:
            intents.append("documents")
        if any(term in normalized for term in ("requirement", "traceability", "test coverage")):
            intents.append("requirements")
        if any(term in normalized for term in ("test case", "test cases", "testcase", "testcases")):
            intents.append("test_cases")
        if any(
            term in normalized
            for term in (
                "execution",
                "executions",
                "pass rate",
                "passed",
                "failed",
                "failure",
                "failures",
                "execution history",
            )
        ):
            intents.append("executions")
        if any(term in normalized for term in ("workflow", "workflows", "workflow task")):
            intents.append("workflows")
        if any(term in normalized for term in ("release readiness", "release-ready", "ready for release")):
            intents.append("release_readiness")
        if "quality" in normalized:
            intents.append("quality")

        wants_document_evidence = any(
            phrase in normalized
            for phrase in ("according to", "what does", "explain from", "in the document", "in the docs")
        )
        wants_analysis = any(
            term in normalized
            for term in ("risky", "risk", "ambiguous", "why", "explain", "analyze")
        )
        return AssistantQuestionPlan(
            tuple(dict.fromkeys(intents)),
            use_retrieval=not intents or wants_document_evidence or (wants_analysis and bool(intents)),
            document_follow_up=document_follow_up,
        )


class AssistantProjectIntelligenceService:
    """Builds grounded, read-only answers from existing project analytics."""

    def __init__(
        self,
        db: Session,
        *,
        analytics: AnalyticsService | None = None,
        project_intelligence: ProjectIntelligenceService | None = None,
        release_readiness: ReleaseReadinessService | None = None,
        test_execution: TestExecutionService | None = None,
    ) -> None:
        self.db = db
        self.analytics = analytics or AnalyticsService(db)
        self.project_intelligence = project_intelligence or ProjectIntelligenceService(db)
        self.release_readiness = release_readiness or ReleaseReadinessService(db)
        self.test_execution = test_execution or TestExecutionService(db)

    def collect(
        self,
        plan: AssistantQuestionPlan,
        *,
        current_user_id: int,
        project_id: int,
        question: str,
        conversation_history: Iterable[object] = (),
    ) -> dict[str, Any]:
        data: dict[str, Any] = {}
        for intent in plan.intents:
            if intent == "documents":
                documents = self.analytics.get_document_statistics(
                    current_user_id=current_user_id,
                    project_id=project_id,
                )
                if plan.document_follow_up:
                    prior_text = " ".join(
                        " ".join(
                            str(getattr(item, field, "") or "")
                            for field in ("question", "answer")
                        )
                        for item in conversation_history
                    ).lower()
                    mentioned = [
                        document
                        for document in documents
                        if str(document.get("filename", "")).lower() in prior_text
                    ]
                    if mentioned:
                        documents = mentioned
                data["documents"] = self._document_metrics(documents)
            elif intent == "embedding_dimensions":
                overview = self.analytics.get_project_overview(
                    project_id=project_id,
                    current_user_id=current_user_id,
                )
                vector_type = DocumentEmbedding.__table__.c.embedding.type
                dimensions = getattr(vector_type, "dim", None)
                if not isinstance(dimensions, int) or isinstance(dimensions, bool):
                    raise RuntimeError("The configured embedding vector dimension is unavailable.")
                data["embedding_dimensions"] = {
                    "dimensions": dimensions if overview["embeddings"] else None,
                    "embedding_record_count": overview["embeddings"],
                    "schema_dimensions": dimensions,
                }
            elif intent == "requirements":
                result = self.analytics.get_requirement_traceability(
                    project_id=project_id,
                    current_user_id=current_user_id,
                )
                requirement_rows = (
                    self.db.query(ProjectRequirement)
                    .filter(ProjectRequirement.project_id == project_id)
                    .order_by(ProjectRequirement.requirement_key.asc(), ProjectRequirement.id.asc())
                    .all()
                )
                links = (
                    self.db.query(
                        TestCaseRequirement.requirement_id,
                        TestCase.id,
                        TestCase.title,
                    )
                    .join(TestCase, TestCase.id == TestCaseRequirement.test_case_id)
                    .filter(
                        TestCase.project_id == project_id,
                        TestCaseRequirement.requirement_id.in_(
                            [requirement.id for requirement in requirement_rows]
                        ),
                    )
                    .all()
                    if requirement_rows
                    else []
                )
                case_links: dict[int, list[dict[str, Any]]] = {}
                for requirement_id, case_id, title in links:
                    case_links.setdefault(requirement_id, []).append(
                        {"test_case_id": case_id, "title": title}
                    )
                result["records"] = [
                    {
                        "requirement_id": requirement.id,
                        "requirement_key": requirement.requirement_key,
                        "description": requirement.description,
                        "classification": requirement.classification,
                        "test_cases": case_links.get(requirement.id, []),
                    }
                    for requirement in requirement_rows
                ]
                result["unlinked_requirements"] = [
                    row for row in result["records"] if not row["test_cases"]
                ]
                data["requirements"] = result
            elif intent == "test_cases":
                result = self.analytics.get_test_case_statistics(
                    project_id=project_id,
                    current_user_id=current_user_id,
                )
                normalized_question = question.lower()
                if any(term in normalized_question for term in ("approved", "unapproved", "draft", "rejected")):
                    review_statuses = (
                        ["draft", "rejected"]
                        if "unapproved" in normalized_question
                        else [
                            status
                            for status in ("approved", "draft", "rejected")
                            if status in normalized_question
                        ]
                    )
                    cases = (
                        self.db.query(
                            TestCase.id,
                            TestCase.title,
                            TestCase.review_status,
                            TestCase.priority,
                        )
                        .filter(
                            TestCase.project_id == project_id,
                            TestCase.review_status.in_(review_statuses),
                        )
                        .order_by(TestCase.id.asc())
                        .limit(51)
                        .all()
                        if review_statuses
                        else []
                    )
                    truncated = len(cases) > 50
                    cases = cases[:50]
                    result["matching_cases"] = [
                        {
                            "test_case_id": row.id,
                            "title": row.title,
                            "review_status": row.review_status,
                            "priority": row.priority,
                        }
                        for row in cases
                    ]
                    result["matching_cases_truncated"] = truncated
                if "evidence" in normalized_question:
                    cases_without_evidence = (
                        self.db.query(TestCase.id, TestCase.title)
                        .outerjoin(
                            TestCaseEvidence,
                            TestCaseEvidence.test_case_id == TestCase.id,
                        )
                        .filter(
                            TestCase.project_id == project_id,
                            TestCaseEvidence.id.is_(None),
                        )
                        .order_by(TestCase.id.asc())
                        .limit(51)
                        .all()
                    )
                    truncated = len(cases_without_evidence) > 50
                    result["cases_without_evidence"] = [
                        {"test_case_id": case_id, "title": title}
                        for case_id, title in cases_without_evidence[:50]
                    ]
                    result["cases_without_evidence_truncated"] = truncated
                data["test_cases"] = result
            elif intent == "executions":
                execution_data = self.analytics.get_execution_analytics(
                    project_id=project_id,
                    current_user_id=current_user_id,
                )
                statuses = execution_data["status_counts"]
                counted_runs = statuses["passed"] + statuses["failed"]
                execution_data["pass_rate"] = AnalyticsService.pass_rate(
                    statuses["passed"],
                    statuses["failed"],
                )
                execution_data["pass_rate_denominator"] = counted_runs
                normalized_question = question.lower()
                if any(
                    term in normalized_question
                    for term in (
                        "history",
                        "recent runs",
                        "latest runs",
                        "latest execution",
                        "recent execution",
                    )
                ):
                    execution_data["recent_executions"] = self.test_execution.get_execution_history(
                        user_id=current_user_id,
                        project_id=project_id,
                        limit=10,
                    )["executions"]
                if any(term in normalized_question for term in ("most frequently", "recurring", "repeat failures")):
                    failures = (
                        self.db.query(
                            TestExecutionRun.test_case_id,
                            TestCase.title,
                            func.count(TestExecutionRun.id).label("failure_count"),
                        )
                        .join(
                            TestCase,
                            TestCase.id == TestExecutionRun.test_case_id,
                        )
                        .filter(
                            TestExecutionRun.project_id == project_id,
                            TestCase.project_id == project_id,
                            func.lower(TestExecutionRun.status).in_(("failed", "error")),
                        )
                        .group_by(TestExecutionRun.test_case_id, TestCase.title)
                        .order_by(
                            func.count(TestExecutionRun.id).desc(),
                            TestExecutionRun.test_case_id.asc(),
                        )
                        .all()
                    )
                    max_failures = failures[0][2] if failures else 0
                    execution_data["recurring_failures"] = [
                        {
                            "test_case_id": case_id,
                            "title": title,
                            "failure_count": count,
                        }
                        for case_id, title, count in failures
                        if count == max_failures
                    ]
                data["executions"] = execution_data
            elif intent == "workflows":
                data["workflows"] = self.project_intelligence.get_workflow_monitoring(
                    project_id=project_id,
                    current_user_id=current_user_id,
                    limit=20,
                )
            elif intent == "release_readiness":
                data["release_readiness"] = self.release_readiness.get_project_release_readiness(
                    project_id=project_id,
                    current_user_id=current_user_id,
                )
            elif intent == "quality":
                data["quality"] = {
                    "project_overview": self.analytics.get_project_overview(
                        project_id=project_id,
                        current_user_id=current_user_id,
                    ),
                    "test_cases": self.analytics.get_test_case_statistics(
                        project_id=project_id,
                        current_user_id=current_user_id,
                    ),
                    "requirement_traceability": self.analytics.get_requirement_traceability(
                        project_id=project_id,
                        current_user_id=current_user_id,
                    ),
                    "executions": self.analytics.get_execution_analytics(
                        project_id=project_id,
                        current_user_id=current_user_id,
                    ),
                }
        return data

    @staticmethod
    def _document_metrics(documents: list[dict[str, Any]]) -> dict[str, Any]:
        rows = [
            {
                "document_id": row["document_id"],
                "filename": row["filename"],
                "chunks": int(row["chunks"]),
                "embeddings": int(row["embeddings"]),
                **(
                    {"processing_status": row["processing_status"]}
                    if "processing_status" in row
                    else {}
                ),
                **(
                    {"source_type": row["source_type"]}
                    if "source_type" in row
                    else {}
                ),
            }
            for row in documents
        ]
        if not rows:
            return {
                "records": [],
                "lowest_embedding_count": None,
                "highest_embedding_count": None,
                "lowest_chunk_count": None,
                "highest_chunk_count": None,
                "documents_with_missing_embeddings": [],
            }

        lowest_embeddings = min(row["embeddings"] for row in rows)
        highest_embeddings = max(row["embeddings"] for row in rows)
        lowest_chunks = min(row["chunks"] for row in rows)
        highest_chunks = max(row["chunks"] for row in rows)
        return {
            "records": rows,
            "documents_with_missing_embeddings": [
                row for row in rows if row["embeddings"] < row["chunks"]
            ],
            "lowest_embedding_count": lowest_embeddings,
            "highest_embedding_count": highest_embeddings,
            "documents_with_lowest_embedding_count": [
                row for row in rows if row["embeddings"] == lowest_embeddings
            ],
            "documents_with_highest_embedding_count": [
                row for row in rows if row["embeddings"] == highest_embeddings
            ],
            "lowest_chunk_count": lowest_chunks,
            "highest_chunk_count": highest_chunks,
            "documents_with_lowest_chunk_count": [
                row for row in rows if row["chunks"] == lowest_chunks
            ],
            "documents_with_highest_chunk_count": [
                row for row in rows if row["chunks"] == highest_chunks
            ],
        }

    @staticmethod
    def format_answer(data: dict[str, Any], question: str) -> str:
        sections: list[str] = []
        if "embedding_dimensions" in data:
            result = data["embedding_dimensions"]
            if result["dimensions"] is None:
                sections.append(
                    "No embedding records are available in this project, so the "
                    "stored vector dimensions cannot be confirmed from project data. "
                    f"The embedding schema is configured for {result['schema_dimensions']} dimensions."
                )
            else:
                sections.append(
                    f"Embedding records in this project use {result['dimensions']}-dimensional vectors. "
                    f"This covers {result['embedding_record_count']} records. Vector dimension is "
                    "a schema/model property and is distinct from per-document embedding counts, "
                    "chunk counts, and retrieval similarity."
                )
        if "documents" in data:
            documents = data["documents"]
            rows = documents["records"]
            if not rows:
                sections.append("This project has no document records to compare.")
            else:
                document_text = "\n".join(
                    f"- {row['filename']}: {row['embeddings']} embedding records, "
                    f"{row['chunks']} chunks"
                    + (
                        f", processing status: {row['processing_status']}"
                        if row.get("processing_status")
                        else ""
                    )
                    for row in rows
                )
                lowest_names = ", ".join(
                    row["filename"]
                    for row in documents["documents_with_lowest_embedding_count"]
                )
                lowest_chunk_names = ", ".join(
                    row["filename"]
                    for row in documents["documents_with_lowest_chunk_count"]
                )
                highest_names = ", ".join(
                    row["filename"]
                    for row in documents["documents_with_highest_embedding_count"]
                )
                highest_chunk_names = ", ".join(
                    row["filename"]
                    for row in documents["documents_with_highest_chunk_count"]
                )
                missing_embeddings = documents.get("documents_with_missing_embeddings", [])
                missing_text = (
                    " Incomplete embedding coverage: "
                    + ", ".join(
                        f"{row['filename']} ({row['embeddings']} of {row['chunks']} chunks embedded)"
                        for row in missing_embeddings
                    )
                    + "."
                    if missing_embeddings
                    else " All available chunks have embedding records."
                )
                sections.append(
                    f"Per-document counts for this project:\n{document_text}\n\n"
                    f"Fewest embedding records: {lowest_names} "
                    f"({documents['lowest_embedding_count']}). "
                    f"Most embedding records: {highest_names} "
                    f"({documents['highest_embedding_count']}). "
                    f"Fewest chunks: {lowest_chunk_names} "
                    f"({documents['lowest_chunk_count']}). "
                    f"Most chunks: {highest_chunk_names} "
                    f"({documents['highest_chunk_count']})."
                    f"{missing_text}\n"
                    "Embedding-record counts and chunk counts are separate metrics. "
                    "Retrieval similarity scores are ranking values, not embedding counts. "
                    "Embedding dimensions describe vector length, not the number of records."
                )
        if "requirements" in data:
            result = data["requirements"]
            unlinked = result.get("unlinked_requirements", [])
            unlinked_text = (
                " Unlinked requirements: "
                + ", ".join(row["requirement_key"] for row in unlinked)
                + "."
                if unlinked
                else ""
            )
            sections.append(
                "Requirement traceability: "
                f"{result['explicit_requirements_with_any_case_link']} of "
                f"{result['explicit_requirement_count']} explicit requirements have a test-case link; "
                f"{result['unlinked_explicit_requirement_count']} are unlinked. "
                "A link indicates traceability, not complete test coverage."
                + unlinked_text
            )
        if "test_cases" in data:
            result = data["test_cases"]
            summary = (
                f"Test cases: {result['total_cases']} total; review statuses: "
                f"{result['review_status_counts']}."
            )
            matching_cases = result.get("matching_cases", [])
            if matching_cases:
                summary += " Matching cases: " + "; ".join(
                    f"{case['title']} ({case['review_status']}, {case['priority']})"
                    for case in matching_cases
                ) + "."
            elif "matching_cases" in result:
                summary += " No test cases matched the selected review statuses."
            if result.get("matching_cases_truncated"):
                summary += " The matching-case list is limited to the first 50 records."
            without_evidence = result.get("cases_without_evidence")
            if without_evidence:
                summary += " Cases without linked evidence: " + "; ".join(
                    case["title"] for case in without_evidence
                ) + "."
            elif "cases_without_evidence" in result:
                summary += (
                    " No test cases are available to evaluate for evidence."
                    if result["total_cases"] == 0
                    else " Every project test case has linked evidence."
                )
            if result.get("cases_without_evidence_truncated"):
                summary += " This list is limited to the first 50 records."
            sections.append(summary)
        if "executions" in data:
            result = data["executions"]
            pass_rate = result["pass_rate"]
            rate_text = (
                f"{pass_rate}% across {result['pass_rate_denominator']} passed/failed runs"
                if pass_rate is not None
                else "unavailable because there are no passed or failed runs"
            )
            summary = (
                f"Lifetime executions: {result['total_runs']} total; status counts: "
                f"{result['status_counts']}; pass rate: {rate_text}."
            )
            recent = result.get("recent_executions", [])
            if recent:
                summary += " Latest runs: " + "; ".join(
                    f"run {run.get('id')}: {run.get('status')}"
                    for run in recent
                ) + "."
            recurring = result.get("recurring_failures", [])
            if recurring:
                summary += " Most frequent failures: " + "; ".join(
                    f"{item['title']} ({item['failure_count']} failures)"
                    for item in recurring
                ) + "."
            sections.append(summary)
        if "workflows" in data:
            result = data["workflows"]
            counts: dict[str, int] = {}
            for workflow in result["workflows"]:
                status = str(workflow.get("status", "unknown"))
                counts[status] = counts.get(status, 0) + 1
            workflows = result["workflows"]
            max_failed_tasks = max(
                (workflow.get("failed_task_count", 0) for workflow in workflows),
                default=0,
            )
            highest_failure_workflows = [
                workflow
                for workflow in workflows
                if workflow.get("failed_task_count", 0) == max_failed_tasks
            ]
            sections.append(
                f"Workflow snapshot: {result['workflow_count']} recent workflows; "
                f"statuses: {counts or 'no workflows'}. "
                + (
                    "Most failed tasks among the latest 20 workflow snapshots: "
                    + ", ".join(
                        f"{workflow.get('workflow_type', 'workflow')} "
                        f"#{workflow.get('id')} ({workflow.get('failed_task_count', 0)})"
                        for workflow in highest_failure_workflows
                    )
                    + "."
                    if workflows
                    else ""
                )
            )
        if "release_readiness" in data:
            result = data["release_readiness"]
            assessment = result.get("assessment")
            assessment = assessment if isinstance(assessment, dict) else {}
            sections.append(
                "Release-readiness assessment is based on persisted project evidence: "
                f"{assessment.get('label', 'an assessment was returned')}. "
                f"{assessment.get('explanation', '')}"
            )
        if "quality" in data:
            result = data["quality"]
            overview = result["project_overview"]
            sections.append(
                f"Project overview: {overview['documents']} documents, "
                f"{overview['chunks']} chunks, {overview['embeddings']} embedding records."
            )
        return "\n\n".join(sections) or (
            "No structured project metrics were returned for this question."
        )

    @staticmethod
    def result_payload(data: dict[str, Any], question: str) -> dict[str, Any]:
        return {
            "success": True,
            "answer": AssistantProjectIntelligenceService.format_answer(data, question),
            "model": "project-intelligence",
            "sources": [],
            "intelligence": {
                "kind": "structured_project_data",
                "data": data,
            },
        }

    @staticmethod
    def answer_retrieval_similarity(
        retrieved_chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ranked = [
            chunk
            for chunk in retrieved_chunks
            if isinstance(chunk.get("similarity"), (int, float))
        ]
        if not ranked:
            answer = "No retrieval results with a comparable similarity score were found."
            comparison = []
        else:
            highest = max(float(chunk["similarity"]) for chunk in ranked)
            lowest = min(float(chunk["similarity"]) for chunk in ranked)
            comparison = [
                {
                    "document_name": chunk.get("document_name", "Unknown document"),
                    "chunk_id": chunk.get("chunk_id"),
                    "similarity": float(chunk["similarity"]),
                }
                for chunk in ranked
            ]
            answer = (
                "Among the chunks retrieved for this question, highest similarity: "
                + ", ".join(
                    f"{chunk.get('document_name', 'Unknown document')} "
                    f"(chunk {chunk.get('chunk_id')}, {float(chunk['similarity']):.3f})"
                    for chunk in ranked
                    if float(chunk["similarity"]) == highest
                )
                + "; lowest similarity: "
                + ", ".join(
                    f"{chunk.get('document_name', 'Unknown document')} "
                    f"(chunk {chunk.get('chunk_id')}, {float(chunk['similarity']):.3f})"
                    for chunk in ranked
                    if float(chunk["similarity"]) == lowest
                )
                + ". Similarity is a retrieval-ranking score, not a count of embedding records."
            )
        return {
            "success": True,
            "answer": answer,
            "model": "retrieval-analysis",
            "sources": [],
            "intelligence": {
                "kind": "retrieval_similarity",
                "records": comparison,
            },
        }
