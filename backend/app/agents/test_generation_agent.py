
from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.schemas.test_case_schema import TestCaseGenerationRequest
from app.services.test_case_generation_service import (
    TestCaseGenerationError,
    TestCaseGenerationService,
)

__test__=False

class TestGenerationAgent(BaseAgent):
    name = "test_generation_agent"

    def __init__(self, db):
        self.service = TestCaseGenerationService(db)

    def run(self, context: AgentContext) -> AgentResult:
        request = context.inputs.get("request")

        if not isinstance(request, TestCaseGenerationRequest):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "INVALID_INPUT",
                    "message": ("A valid TestCaseGenerationRequest is required.")
                    })

        try:
            generation_options = {}
            workflow_run_id = context.inputs.get(
                "workflow_run_id",
                context.metadata.get("workflow_id"),
            )
            workflow_attempt_number = context.inputs.get(
                "workflow_attempt_number"
            )
            workflow_task_id = context.metadata.get("task_id")
            reuse_existing_workflow_attempt = context.inputs.get(
                "reuse_existing_workflow_attempt",
                False,
            )
            if (
                workflow_run_id is not None
                or workflow_attempt_number is not None
                or workflow_task_id is not None
            ):
                generation_options = {
                    "workflow_run_id": workflow_run_id,
                    "workflow_attempt_number": workflow_attempt_number,
                    "reuse_existing_workflow_attempt": reuse_existing_workflow_attempt,
                    "workflow_task_id": workflow_task_id,
                }
            test_cases = self.service.generate(
                user_id=context.user_id,
                project_id=context.project_id,
                request=request,
                **generation_options,
            )
            generation_stats = getattr(
                self.service,
                "last_generation_stats",
                {},
            )
            generation_status = generation_stats.get("generation_status")
            generated_count = generation_stats.get("generated_count")
            if not isinstance(generated_count, int):
                generated_count = len(test_cases)
            final_persisted_count = generation_stats.get(
                "final_persisted_count",
                len(test_cases),
            )
            execution_metadata = {
                key: value
                for key, value in {
                    "correlation_id": generation_stats.get("correlation_id"),
                    "workflow_id": generation_stats.get("workflow_id"),
                    "task_id": generation_stats.get("task_id"),
                    "generation_attempt_number": generation_stats.get(
                        "generation_attempt_number"
                    ),
                    "provider_attempts": generation_stats.get(
                        "response_diagnostics"
                    ),
                }.items()
                if value is not None
            }
            if not test_cases or generation_status == "failed":
                diagnostic = generation_stats.get("diagnostic")
                return AgentResult(
                    agent_name=self.name,
                    status="failed",
                    data={
                        "generated_count": generated_count,
                        "final_persisted_count": final_persisted_count,
                        "test_cases": test_cases,
                        "generation_stats": generation_stats,
                        "execution_metadata": execution_metadata,
                    },
                    error={
                        "code": (
                            "NO_USABLE_TEST_CASES"
                            if not test_cases
                            else "GENERATION_FAILED"
                        ),
                        "message": (
                            diagnostic
                            if isinstance(diagnostic, str)
                            else (
                                "No usable test cases were generated from the supplied requirements and evidence."
                                if not test_cases
                                else "Test-case generation did not complete successfully."
                            )
                        ),
                    },
                )

            agent_status = (
                "partial"
                if generation_status == "partial"
                else "success"
            )

            return AgentResult(
                agent_name=self.name,
                status=agent_status,
                data={
                    "generated_count": generated_count,
                    "final_persisted_count": final_persisted_count,
                    "test_cases": test_cases,
                    "generation_stats": generation_stats,
                    "execution_metadata": execution_metadata,
                })

        except PermissionError:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code":"PERMISSION_DENIED",
                    "message":"You do not have permission to generate tests for this project"
                }
            )

        except ValueError as exc:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code":"INVALID_REQUEST",
                    "message": str(exc) or "The test-case generation request could not be processed"
                }
            )

        except TestCaseGenerationError as exc:
            generation_stats = exc.diagnostics.get("generation_stats", {})
            generated_count = generation_stats.get("generated_count", 0)
            final_persisted_count = generation_stats.get(
                "final_persisted_count",
                0,
            )
            return AgentResult(
                agent_name=self.name,
                status="failed",
                data={
                    "generated_count": generated_count,
                    "final_persisted_count": final_persisted_count,
                    "test_cases": [],
                    "generation_stats": generation_stats,
                    "execution_metadata": {
                        key: value
                        for key, value in {
                            "correlation_id": generation_stats.get(
                                "correlation_id"
                            ),
                            "workflow_id": generation_stats.get("workflow_id"),
                            "task_id": generation_stats.get("task_id"),
                            "generation_attempt_number": generation_stats.get(
                                "generation_attempt_number"
                            ),
                            "provider_attempts": generation_stats.get(
                                "response_diagnostics"
                            ),
                        }.items()
                        if value is not None
                    },
                },
                error={
                    "code":"GENERATION_FAILED",
                    "stage": exc.stage,
                    "message": str(exc),
                    "generation_stats": generation_stats,
                }
            )

        except Exception as exc:
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "GENERATION_FAILED",
                    "message": str(exc) or "The test-case generation request could not be processed"
                })
