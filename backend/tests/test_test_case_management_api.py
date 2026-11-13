from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api import test_cases as test_cases_api
from app.database.connection import Base
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_requirement import ProjectRequirement
from app.models.test_case import TestCase as CaseModel
from app.models.test_case_evidence import TestCaseEvidence as EvidenceModel
from app.models.test_case_generation_run import (
    TestCaseGenerationRun as GenerationRunModel,
)
from app.models.test_case_requirement import TestCaseRequirement
from app.models.user import User
from app.schemas.test_case_schema import TestCaseUpdate as CaseUpdate
from app.services.test_case_evaluation_service import (
    TestCaseEvaluationService as CaseEvaluationService,
)


@pytest.fixture
def api_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = User(
        id=1,
        name="Owner",
        email="owner@example.test",
        password_hash="not-a-real-password",
    )
    outsider = User(
        id=2,
        name="Outsider",
        email="outsider@example.test",
        password_hash="not-a-real-password",
    )
    organization = Organization(id=1, name="Test Org", owner_id=user.id)
    project = Project(id=1, name="Test Project", organitzation_id=organization.id)
    document = Document(
        id=1,
        filename="requirements.md",
        content_type="text/markdown",
        storage_path="unused",
        project_id=project.id,
        source_type="requirements",
    )
    chunk = DocumentChunk(
        id=1,
        document_id=document.id,
        chunk_index=0,
        content="REQ-AUTH-01: Registered users can sign in.",
    )
    run = GenerationRunModel(
        id=1,
        project_id=project.id,
        created_by_user_id=user.id,
        requirements_prompt="REQ-AUTH-01: Registered users can sign in.",
        requested_categories=["positive", "negative"],
        max_cases=2,
        status="partial",
        requirement_keys=["REQ-AUTH-01"],
        generated_case_count=2,
        duplicate_rejected_count=1,
        invalid_rejected_count=0,
        insufficient_evidence_count=0,
        final_persisted_count=1,
        retry_count=1,
    )
    requirement = ProjectRequirement(
        id=1,
        project_id=project.id,
        requirement_key="REQ-AUTH-01",
        description="Registered users can sign in.",
        evidence_chunk_ids=[chunk.id],
    )
    case = CaseModel(
        id=1,
        project_id=project.id,
        created_by_user_id=user.id,
        title="Sign in with registered account",
        description="Verify successful account authentication.",
        category="positive",
        priority="high",
        severity="critical",
        preconditions="A registered user account exists.",
        steps=[
            {
                "action": "Submit valid credentials.",
                "expected_result": "The account is authenticated.",
            }
        ],
        expected_result="The user reaches the authenticated area.",
        review_status="approved",
        generation_run_id=run.id,
    )
    session.add_all(
        [
            user,
            outsider,
            organization,
            project,
            document,
            chunk,
            run,
            requirement,
            case,
        ]
    )
    session.flush()
    session.add_all(
        [
            EvidenceModel(
                test_case_id=case.id,
                document_id=document.id,
                chunk_id=chunk.id,
            ),
            TestCaseRequirement(
                test_case_id=case.id,
                requirement_id=requirement.id,
            ),
        ]
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _owner():
    return SimpleNamespace(id=1)


def test_case_detail_and_generation_history_expose_traceability_and_accounting(api_db):
    detail = test_cases_api.get_project_test_case(
        1,
        1,
        _owner(),
        api_db,
    )
    history = test_cases_api.list_project_test_case_generation_runs(
        1,
        _owner(),
        api_db,
    )

    assert detail["data"]["severity"] == "critical"
    assert detail["data"]["priority"] == "high"
    assert detail["data"]["requirements"][0]["requirement_key"] == "REQ-AUTH-01"
    assert detail["data"]["evidence"][0]["chunk_id"] == 1
    run = history["data"][0]
    assert run["requested_max_cases"] == 2
    assert run["generated_count"] == 2
    assert run["duplicate_rejected_count"] == 1
    assert run["final_persisted_count"] == 1
    assert run["generation_status"] == "partial"
    assert run["requirement_keys"] == ["REQ-AUTH-01"]
    assert run["requirement_keys_covered"] == ["REQ-AUTH-01"]


def test_project_test_case_list_returns_evidence_and_requirement_traceability(api_db):
    response = test_cases_api.list_project_test_cases(
        1,
        _owner(),
        api_db,
    )

    assert len(response["data"]) == 1
    case = response["data"][0]
    assert case["severity"] == "critical"
    assert case["requirements"][0]["requirement_key"] == "REQ-AUTH-01"
    assert case["evidence"][0] == {
        "document_id": 1,
        "document_name": "requirements.md",
        "source_type": "requirements",
        "chunk_id": 1,
        "source_metadata": {},
        "excerpt": "REQ-AUTH-01: Registered users can sign in.",
    }


def test_project_test_case_and_generation_run_lists_allow_empty_and_enforce_ownership(
    api_db,
):
    api_db.add(Project(id=2, name="Empty Project", organitzation_id=1))
    api_db.commit()

    cases = test_cases_api.list_project_test_cases(
        2,
        _owner(),
        api_db,
    )
    runs = test_cases_api.list_project_test_case_generation_runs(
        2,
        _owner(),
        api_db,
    )

    assert cases["success"] is True
    assert cases["data"] == []
    assert runs["success"] is True
    assert runs["data"] == []

    for endpoint in (
        test_cases_api.list_project_test_cases,
        test_cases_api.list_project_test_case_generation_runs,
    ):
        with pytest.raises(HTTPException) as exc:
            endpoint(1, SimpleNamespace(id=2), api_db)
        assert exc.value.status_code == 404


def test_authorized_update_persists_severity_and_requirements(api_db):
    response = test_cases_api.update_project_test_case(
        1,
        1,
        CaseUpdate(
            priority="critical",
            severity="low",
            requirement_ids=[1],
            description="Updated description.",
        ),
        _owner(),
        api_db,
    )

    case = api_db.query(CaseModel).filter_by(id=1).one()
    assert response["data"]["priority"] == "critical"
    assert response["data"]["severity"] == "low"
    assert response["data"]["requirement_ids"] == [1]
    assert case.review_status == "draft"


def test_update_rejects_requirement_from_another_project(api_db):
    with pytest.raises(HTTPException) as exc:
        test_cases_api.update_project_test_case(
            1,
            1,
            CaseUpdate(requirement_ids=[999]),
            _owner(),
            api_db,
        )

    assert exc.value.status_code == 422
    assert api_db.query(TestCaseRequirement).count() == 1


def test_test_case_management_hides_other_projects_and_owner_data(api_db):
    with pytest.raises(HTTPException) as detail_error:
        test_cases_api.get_project_test_case(
            1,
            1,
            SimpleNamespace(id=2),
            api_db,
        )
    with pytest.raises(HTTPException) as delete_error:
        test_cases_api.delete_project_test_case(
            1,
            1,
            SimpleNamespace(id=2),
            api_db,
        )

    assert detail_error.value.status_code == 404
    assert delete_error.value.status_code == 404
    assert api_db.scalar(select(func.count()).select_from(CaseModel)) == 1


def test_delete_removes_case_links_but_preserves_generation_history(api_db):
    result = test_cases_api.delete_project_test_case(
        1,
        1,
        _owner(),
        api_db,
    )

    assert result["success"] is True
    assert api_db.scalar(select(func.count()).select_from(CaseModel)) == 0
    assert api_db.scalar(select(func.count()).select_from(EvidenceModel)) == 0
    assert api_db.scalar(select(func.count()).select_from(TestCaseRequirement)) == 0
    assert api_db.scalar(select(func.count()).select_from(GenerationRunModel)) == 1


def test_generation_quality_report_measures_coverage_diversity_and_evidence(
    api_db,
    monkeypatch,
):
    service = CaseEvaluationService(api_db)
    monkeypatch.setattr(
        service,
        "evaluate",
        lambda user_id, project_id, test_case_id: {
            "checks": {
                "semantic_evaluation": {
                    "status": "supported",
                    "evidence_support": "supported",
                }
            }
        },
    )

    report = service.evaluate_generation_run(1, 1, 1)

    metrics = report["quality_metrics"]
    assert metrics["requirement_coverage"]["covered_requirement_keys"] == [
        "REQ-AUTH-01"
    ]
    assert metrics["requirement_coverage"]["case_traceability_ratio"] == 1.0
    assert metrics["scenario_diversity"]["category_counts"] == {"positive": 1}
    assert metrics["scenario_diversity"]["requested_category_coverage"] == 0.5
    assert metrics["scenario_diversity"]["distinct_scenario_ratio"] == 1.0
    assert metrics["evidence_accuracy"]["status"] == "assessed"
    assert metrics["evidence_accuracy"]["score"] == 1.0


def test_generation_history_excludes_cases_owned_by_another_project(api_db):
    outsider_organization = Organization(
        id=2,
        name="Outsider Org",
        owner_id=2,
    )
    outsider_project = Project(
        id=2,
        name="Outsider Project",
        organitzation_id=outsider_organization.id,
    )
    api_db.add_all([outsider_organization, outsider_project])
    api_db.add(
        CaseModel(
            id=2,
            project_id=outsider_project.id,
            created_by_user_id=2,
            title="Another project's case",
            description="This case must not appear in the owner's run history.",
            category="negative",
            priority="high",
            severity="critical",
            steps=[
                {
                    "action": "Use another project's test case.",
                    "expected_result": "The projects remain isolated.",
                }
            ],
            expected_result="The case is not included in the other project's history.",
            generation_run_id=1,
        )
    )
    api_db.commit()

    history = test_cases_api.list_project_test_case_generation_runs(
        1,
        _owner(),
        api_db,
    )

    run = history["data"][0]
    assert run["case_count"] == 1
    assert run["category_counts"] == {"positive": 1}
    assert run["requirement_keys_covered"] == ["REQ-AUTH-01"]
