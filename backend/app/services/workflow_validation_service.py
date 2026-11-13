from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.authorization import get_owned_project
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.test_case import TestCase
from app.models.test_case_evidence import TestCaseEvidence
from app.models.test_case_generation_run import TestCaseGenerationRun


class WorkflowValidationService:
    """Deterministic checks that must pass before LLM review can be considered."""

    VALID_CATEGORIES = {"positive", "negative", "boundary", "edge"}
    VALID_PRIORITIES = {"low", "medium", "high", "critical"}
    VALID_SEVERITIES = {"low", "medium", "high", "critical"}
    PLACEHOLDER_EXPECTED_RESULTS = {
        "as expected",
        "n/a",
        "na",
        "none",
        "ok",
        "pass",
        "passed",
        "success",
        "tbd",
        "todo",
        "unknown",
        "works",
    }

    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(str(value or "").lower().split())

    def validate(
        self,
        user_id: int,
        project_id: int,
        test_case_ids: list[int],
    ) -> dict[str, Any]:
        project = get_owned_project(self.db, project_id, user_id)
        if project is None:
            raise ValueError("Project not found or access denied.")
        if not test_case_ids:
            return {
                "valid": False,
                "findings": [{"severity": "high", "check": "generated_cases", "message": "No generated test cases were supplied."}],
                "validated_case_ids": [],
            }

        cases = (
            self.db.query(TestCase)
            .filter(
                TestCase.project_id == project_id,
                TestCase.id.in_(test_case_ids),
            )
            .all()
        )
        cases_by_id = {case.id: case for case in cases}
        findings: list[dict[str, str]] = []
        validated_ids: list[int] = []
        signatures: dict[tuple[str, str], int] = {}
        candidate_generation_run_ids = {
            case.generation_run_id
            for case in cases
            if case.generation_run_id is not None
        }
        workflow_ids = {
            row[0]
            for row in self.db.query(TestCaseGenerationRun.workflow_run_id)
            .filter(
                TestCaseGenerationRun.id.in_(candidate_generation_run_ids),
                TestCaseGenerationRun.workflow_run_id.is_not(None),
            )
            .all()
        } if candidate_generation_run_ids else set()
        same_workflow_generation_ids = {
            row[0]
            for row in self.db.query(TestCaseGenerationRun.id)
            .filter(TestCaseGenerationRun.workflow_run_id.in_(workflow_ids))
            .all()
        } if workflow_ids else set()
        existing_cases_query = self.db.query(TestCase).filter(
            TestCase.project_id == project_id,
            TestCase.id.notin_(test_case_ids),
        )
        if same_workflow_generation_ids:
            existing_cases_query = existing_cases_query.filter(
                or_(
                    TestCase.generation_run_id.is_(None),
                    TestCase.generation_run_id.notin_(same_workflow_generation_ids),
                )
            )
        for existing_case in existing_cases_query.all():
            signature = (
                self._normalize(existing_case.title),
                self._normalize(existing_case.expected_result),
            )
            signatures.setdefault(signature, existing_case.id)

        for case_id in test_case_ids:
            case = cases_by_id.get(case_id)
            if case is None:
                findings.append(
                    {
                        "severity": "high",
                        "check": "project_ownership",
                        "message": f"Test case {case_id} is missing or belongs to another project.",
                    }
                )
                continue
            case_findings = 0

            def add(check: str, message: str, severity: str = "high") -> None:
                nonlocal case_findings
                case_findings += 1
                findings.append(
                    {
                        "severity": severity,
                        "check": check,
                        "message": f"Test case {case.id}: {message}",
                    }
                )

            if not isinstance(case.title, str) or not case.title.strip():
                add("required_fields", "title is empty.")
            if not isinstance(case.description, str) or not case.description.strip():
                add("required_fields", "description is empty.")
            if case.test_type is not None and (
                not isinstance(case.test_type, str)
                or not case.test_type.strip()
                or len(case.test_type) > 60
            ):
                add("test_type", "test type must be a non-empty value of at most 60 characters.")
            if case.category not in self.VALID_CATEGORIES:
                add("category", "category is invalid.")
            if case.priority not in self.VALID_PRIORITIES:
                add("priority", "priority is invalid.")
            if case.severity not in self.VALID_SEVERITIES:
                add("severity", "severity is invalid.")
            if not isinstance(case.expected_result, str) or not case.expected_result.strip():
                add("expected_result", "expected result is missing.")
            elif self._normalize(case.expected_result).strip(" .!?") in (
                self.PLACEHOLDER_EXPECTED_RESULTS
            ):
                add(
                    "expected_result",
                    "expected result must describe an observable outcome, not a placeholder.",
                )

            if not isinstance(case.steps, list) or not case.steps:
                add("steps", "at least one executable step is required.")
            else:
                for index, step in enumerate(case.steps, start=1):
                    if not isinstance(step, dict):
                        add("steps", f"step {index} must be an object.")
                        continue
                    if not isinstance(step.get("action"), str) or not step["action"].strip():
                        add("steps", f"step {index} has no action.")
                    if not isinstance(step.get("expected_result"), str) or not step[
                        "expected_result"
                    ].strip():
                        add("steps", f"step {index} has no expected result.")
                    elif self._normalize(step["expected_result"]).strip(" .!?") in (
                        self.PLACEHOLDER_EXPECTED_RESULTS
                    ):
                        add(
                            "steps",
                            f"step {index} expected result must describe an observable outcome.",
                        )

            links = (
                self.db.query(TestCaseEvidence)
                .filter(TestCaseEvidence.test_case_id == case.id)
                .all()
            )
            if not links:
                add("evidence", "no evidence references are attached.")
            for link in links:
                verified = (
                    self.db.query(DocumentChunk.id)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .filter(
                        DocumentChunk.id == link.chunk_id,
                        DocumentChunk.document_id == link.document_id,
                        Document.project_id == project_id,
                    )
                    .first()
                )
                if verified is None:
                    add(
                        "evidence",
                        f"document/chunk reference {link.document_id}/{link.chunk_id} is invalid for this project.",
                    )

            signature = (
                self._normalize(case.title),
                self._normalize(case.expected_result),
            )
            if signature in signatures:
                add(
                    "duplicate",
                    f"duplicates test case {signatures[signature]} in this workflow.",
                    severity="medium",
                )
            else:
                signatures[signature] = case.id

            if case_findings == 0:
                validated_ids.append(case.id)

        return {
            "valid": not findings,
            "findings": findings,
            "validated_case_ids": validated_ids,
        }
