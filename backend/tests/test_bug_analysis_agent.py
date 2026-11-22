import json
from types import SimpleNamespace

import pytest

from app.agents.bug_analysis_agent import BugAnalysisAgent
from app.agents.contracts import AgentContext
from app.services.workflow_service import (
    _dependency_succeeded,
    _jsonable_agent_result,
)


def _reports():
    return [
        {
            "chunk_id": 46,
            "document_id": 11,
            "document_name": "02_MediTrack_Bug_Reports.csv",
            "source_type": "bug_report",
            "source_metadata": {"row_start": 2, "row_end": 3},
            "content": (
                "Bug ID | Title | Severity | Priority | Affected Module | Description\n"
                "BUG-101 | Duplicate booking | High | P1 | Appointments | "
                "A patient can book the same slot twice.\n"
                "BUG-102 | Missing reminder | Medium | P2 | Notifications | "
                "The appointment reminder is not sent."
            ),
        },
        {
            "chunk_id": 47,
            "document_id": 11,
            "document_name": "02_MediTrack_Bug_Reports.csv",
            "source_type": "bug_report",
            "source_metadata": {"row_start": 4, "row_end": 5},
            "content": (
                "BUG-103 | Incorrect status | Low | P3 | Appointments | "
                "A cancelled appointment remains listed as confirmed."
            ),
        },
    ]


def _response(**overrides):
    payload = {
        "bugs": [],
        "observed_behavior": [],
        "expected_behavior": [],
        "related_requirements": [],
        "related_test_cases": [],
        "inferred_relationships": [],
    }
    payload.update(overrides)
    return payload


def _bug(bug_id, chunk_id, **overrides):
    return {
        "bug_id": bug_id,
        "title": f"Title for {bug_id}",
        "description": f"Description for {bug_id}",
        "severity": "High",
        "priority": "P1",
        "affected_module": "Appointments",
        "evidence_chunk_ids": [chunk_id],
        "execution_ids": [],
        **overrides,
    }


def _agent(answer, reports=None):
    llm = SimpleNamespace(
        generate_content=lambda **_: {
            "success": True,
            "answer": answer,
        }
    )
    return BugAnalysisAgent(
        None,
        retrieval_service=SimpleNamespace(
            search_project_context=lambda **_: reports or _reports()
        ),
        execution_service=SimpleNamespace(
            get_execution_history=lambda **_: {"executions": []}
        ),
        llm_service=llm,
    )


def _run(agent, shared_context=None):
    return agent.run(
        AgentContext(
            user_id=4,
            project_id=3,
            task="bug_analysis",
            metadata={"shared_context": shared_context or {}},
        )
    )


def test_extracts_individual_csv_bug_records_and_attaches_source_references():
    reports = _reports()
    answer = _response(
        bugs=[
            _bug(
                "BUG-101",
                46,
                title="Duplicate booking",
                description="A patient can book the same slot twice.",
                severity="High",
                priority="P1",
                affected_module="Appointments",
            ),
            _bug(
                "BUG-102",
                46,
                title="Missing reminder",
                description="The appointment reminder is not sent.",
                severity="Medium",
                priority="P2",
                affected_module="Notifications",
            ),
            _bug(
                "BUG-103",
                47,
                title="Incorrect status",
                description="A cancelled appointment remains listed as confirmed.",
                severity="Low",
                priority="P3",
                affected_module="Appointments",
            ),
        ]
    )

    result = _run(_agent(json.dumps(answer), reports))

    assert result.status == "success"
    assert [bug["bug_id"] for bug in result.data["bugs"]] == [
        "BUG-101",
        "BUG-102",
        "BUG-103",
    ]
    assert result.data["bugs"][0]["severity"] == "High"
    assert result.data["bugs"][1]["priority"] == "P2"
    assert result.data["bugs"][1]["affected_module"] == "Notifications"
    assert result.data["bugs"][0]["classification"] == "source_reported"
    assert result.data["bugs"][0]["evidence_references"] == [
        {
            "document_id": 11,
            "chunk_id": 46,
            "document_name": "02_MediTrack_Bug_Reports.csv",
            "source_type": "bug_report",
            "source_metadata": {"row_start": 2, "row_end": 3},
        }
    ]
    assert [item["chunk_id"] for item in result.data["evidence"]] == [46, 47]
    workflow_output = _jsonable_agent_result(result)
    assert workflow_output["status"] == "completed"
    assert workflow_output["findings"] == result.data["bugs"]


def test_partial_bug_analysis_status_and_findings_survive_workflow_mapping():
    response = _response(
        bugs=[
            _bug("BUG-101", 46),
            _bug("BUG-999", 46),
        ]
    )

    workflow_output = _jsonable_agent_result(_run(_agent(json.dumps(response))))

    assert workflow_output["status"] == "partial"
    assert [finding["bug_id"] for finding in workflow_output["findings"]] == [
        "BUG-101"
    ]
    assert workflow_output["warnings"]


def test_partial_bug_analysis_with_findings_can_feed_test_generation():
    response = _response(
        bugs=[
            _bug("BUG-101", 46),
            _bug("BUG-999", 46),
        ]
    )
    output = _jsonable_agent_result(_run(_agent(json.dumps(response))))
    task = SimpleNamespace(status="partial", task_type="bug_analysis", output_data=output)

    assert _dependency_succeeded(task, "test_generation") is True
    task.output_data["structured_data"]["bugs"] = []
    assert _dependency_succeeded(task, "test_generation") is False


def test_empty_structured_response_with_bug_evidence_is_failure():
    result = _run(_agent(json.dumps(_response())))

    assert result.status == "failed"
    assert result.error["code"] == "BUG_ANALYSIS_NO_FINDINGS"
    assert result.data["bugs"] == []
    assert len(result.data["evidence"]) == 2


def test_bug_without_evidence_references_is_rejected():
    result = _run(
        _agent(
            json.dumps(
                _response(
                    bugs=[
                        _bug(
                            "BUG-101",
                            46,
                            evidence_chunk_ids=[],
                        )
                    ]
                )
            )
        )
    )

    assert result.status == "failed"
    assert result.error["code"] == "BUG_ANALYSIS_OUTPUT_INVALID"
    assert "uncited claim" in result.data["warnings"][0]


def test_bug_id_must_be_present_in_its_cited_chunk():
    response = _response(
        bugs=[
            _bug("BUG-101", 46),
            _bug("BUG-999", 46),
        ]
    )

    result = _run(_agent(json.dumps(response)))

    assert result.status == "partial"
    assert [bug["bug_id"] for bug in result.data["bugs"]] == ["BUG-101"]
    assert any("bug ID not supported" in warning for warning in result.data["warnings"])


def test_invalid_chunk_citation_does_not_discard_valid_bug_findings():
    response = _response(
        bugs=[
            _bug("BUG-101", 46),
            _bug("BUG-103", 999),
        ]
    )

    result = _run(_agent(json.dumps(response)))

    assert result.status == "partial"
    assert [bug["bug_id"] for bug in result.data["bugs"]] == ["BUG-101"]
    assert any("unsupported chunk citation" in warning for warning in result.data["warnings"])


def test_malformed_llm_response_returns_failure_and_evidence_context():
    result = _run(_agent('{"bugs": ['))

    assert result.status == "failed"
    assert result.error["code"] == "BUG_ANALYSIS_OUTPUT_INVALID"
    assert "valid JSON" in result.error["message"]
    assert result.data["evidence"][0]["chunk_id"] == 46


def test_partial_results_report_rejected_entries_without_losing_valid_findings():
    answer = _response(
        bugs=[
            _bug("BUG-101", 46),
            _bug("BUG-102", 46, severity=7),
        ],
        related_requirements=[
            {
                "requirement_id": "REQ-UNKNOWN",
                "relationship_status": "inferred",
                "evidence_chunk_ids": [46],
                "execution_ids": [],
            }
        ],
    )

    result = _run(_agent(json.dumps(answer)))

    assert result.status == "partial"
    assert [bug["bug_id"] for bug in result.data["bugs"]] == ["BUG-101"]
    assert result.data["related_requirements"] == []
    assert len(result.data["warnings"]) == 2
    assert result.data["warnings"][0] == "bugs contains an invalid severity."
    assert "unsupported requirement relationship" in result.data["warnings"][1]


@pytest.mark.parametrize("answer", ["[]", "not-json", ""])
def test_non_object_and_malformed_outputs_fail_clearly(answer):
    result = _run(_agent(answer))

    assert result.status == "failed"
    assert result.error["code"] == "BUG_ANALYSIS_OUTPUT_INVALID"
    assert result.data["evidence"]


def _requirement_context():
    return {
        "requirements": {
            "requirements": [
                {
                    "id": "REQ-010",
                    "description": "Appointment slots must not overlap.",
                    "classification": "explicit",
                    "evidence_chunk_ids": [45],
                }
            ]
        },
        "evidence_references": [
            {
                "document_id": 12,
                "chunk_id": 45,
                "document_name": "01_MediTrack_Requirements.pdf",
                "source_type": "requirements",
                "content": "REQ-010: Appointment slots must not overlap.",
                "source_metadata": {"page": 4},
            }
        ],
    }


def test_requirement_and_inferred_relationships_accept_supplied_requirement_evidence():
    reports = _reports()
    answer = _response(
        bugs=[_bug("BUG-101", 46)],
        related_requirements=[
            {
                "requirement_id": "REQ-010",
                "relationship_status": "confirmed",
                "evidence_chunk_ids": [45],
                "execution_ids": [],
            }
        ],
        inferred_relationships=[
            {
                "requirement_id": "REQ-010",
                "relationship_status": "inferred",
                "evidence_chunk_ids": [45],
                "execution_ids": [],
            }
        ],
    )
    agent = _agent(json.dumps(answer), reports)

    result = _run(agent, _requirement_context())

    assert result.status == "success"
    assert result.data["related_requirements"][0]["relationship_status"] == "confirmed"
    assert result.data["inferred_relationships"][0]["relationship_status"] == "inferred"
    assert result.data["related_requirements"][0]["evidence_references"][0] == {
        "document_id": 12,
        "chunk_id": 45,
        "document_name": "01_MediTrack_Requirements.pdf",
        "source_type": "requirements",
        "source_metadata": {"page": 4},
    }
    assert {item["chunk_id"] for item in result.data["evidence"]} == {45, 46, 47}
    assert {item["chunk_id"] for item in result.evidence} == {45, 46, 47}


def test_empty_relationship_arrays_do_not_create_citation_warnings():
    answer = _response(bugs=[_bug("BUG-101", 46)])

    result = _run(_agent(json.dumps(answer)))

    assert result.status == "success"
    assert result.data["related_requirements"] == []
    assert result.data["inferred_relationships"] == []
    assert result.data["warnings"] == []


def test_mixed_relationships_keep_supported_entries_and_reject_unsupported_chunks():
    answer = _response(
        bugs=[_bug("BUG-101", 46)],
        related_requirements=[
            {
                "requirement_id": "REQ-010",
                "relationship_status": "confirmed",
                "evidence_chunk_ids": [45],
                "execution_ids": [],
            },
            {
                "requirement_id": "REQ-010",
                "relationship_status": "inferred",
                "evidence_chunk_ids": [999],
                "execution_ids": [],
            },
        ],
        inferred_relationships=[
            {
                "requirement_id": "REQ-010",
                "relationship_status": "inferred",
                "evidence_chunk_ids": [45],
                "execution_ids": [],
            },
            {
                "requirement_id": "REQ-010",
                "relationship_status": "inferred",
                "evidence_chunk_ids": [999],
                "execution_ids": [],
            },
        ],
    )

    result = _run(_agent(json.dumps(answer)), _requirement_context())

    assert result.status == "partial"
    assert len(result.data["related_requirements"]) == 1
    assert len(result.data["inferred_relationships"]) == 1
    assert sum("unsupported chunk citation" in warning for warning in result.data["warnings"]) == 2
    assert len(result.data["bugs"]) == 1


def test_medi_track_six_bug_findings_complete_without_relationships():
    reports = [
        {
            "chunk_id": chunk_id,
            "document_id": 11,
            "document_name": "02_MediTrack_Bug_Reports.csv",
            "source_type": "bug_report",
            "content": "\n".join(
                f"BUG-{bug_id}: MediTrack sample defect." for bug_id in bug_ids
            ),
        }
        for chunk_id, bug_ids in ((46, [101, 102]), (47, [103, 104]), (48, [105, 106]))
    ]
    answer = _response(
        bugs=[
            _bug(f"BUG-{bug_id}", 46 + ((bug_id - 101) // 2))
            for bug_id in range(101, 107)
        ]
    )

    result = _run(_agent(json.dumps(answer), reports))

    assert result.status == "success"
    assert [item["bug_id"] for item in result.data["bugs"]] == [
        f"BUG-{bug_id}" for bug_id in range(101, 107)
    ]
    assert result.data["warnings"] == []
