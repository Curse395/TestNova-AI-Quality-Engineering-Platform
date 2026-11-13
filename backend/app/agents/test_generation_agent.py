
from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.schemas.test_case_schema import TestCaseGenerationRequest
from app.services.test_case_generation_service import TestCaseGenerationService,TestCaseGenerationError

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
            workflow_run_id = context.inputs.get("workflow_run_id")
            workflow_attempt_number = context.inputs.get(
                "workflow_attempt_number"
            )
            reuse_existing_workflow_attempt = context.inputs.get(
                "reuse_existing_workflow_attempt",
                False,
            )
            if workflow_run_id is not None or workflow_attempt_number is not None:
                generation_options = {
                    "workflow_run_id": workflow_run_id,
                    "workflow_attempt_number": workflow_attempt_number,
                    "reuse_existing_workflow_attempt": reuse_existing_workflow_attempt,
                }
            test_cases = self.service.generate(
                user_id=context.user_id,
                project_id=context.project_id,
                request=request,
                **generation_options,
            )

            return AgentResult(
                agent_name=self.name,
                status="success",
                data={
                    "generated_count": len(test_cases),
                    "test_cases": test_cases,
                    "generation_stats": getattr(
                        self.service,
                        "last_generation_stats",
                        {},
                    ),
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
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code":"GENERATION_FAILED",
                    "stage": exc.stage,
                    "message": str(exc),
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
