
import json
import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.contracts import AgentContext, AgentResult
from app.services.retrieval_service import RetrievalService
from app.services.llm_services import LLMService


logger = logging.getLogger(__name__)


class ChangeRiskAgent(BaseAgent):
    """
    Analyses project changes, retrieves supporting QA evidence,
    and identifies potential quality risks.
    """

    name = "change_risk_agent"

    VALID_RISK_LEVELS = {
        "low", "medium", "high", "critical"
    }

    def __init__(self, db):
        self.retrieval_service = RetrievalService(db)
        self.llm_service = LLMService()

    @staticmethod
    def _parse_response(response_text: str) -> dict[str, Any]:
        """Parse and validate the JSON returned by Gemini."""

        text = response_text.strip()

        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3].strip()

        result = json.loads(text)

        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object.")

        return result

    def run(self, context: AgentContext) -> AgentResult:

        inputs = context.inputs

        change_summary = inputs.get("change_summary")
        changed_files = inputs.get("changed_files", [])
        change_type = inputs.get("change_type", "general")
        additional_context = inputs.get("additional_context", "")

        if not isinstance(change_summary, str) or not change_summary.strip():
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "INVALID_CHANGE_SUMMARY",
                    "message": "A valid change summary is required."
                }
            )

        if (
            not isinstance(changed_files, list)
            or any(
                not isinstance(item, str) or not item.strip()
                for item in changed_files
            )
        ):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "INVALID_CHANGED_FILES",
                    "message": "Changed files must be a list of valid strings."
                }
            )

        if not isinstance(additional_context, str):
            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "INVALID_ADDITIONAL_CONTEXT",
                    "message": "Additional context must be text."
                }
            )

        query = (
            f"Change summary: {change_summary}. "
            f"Change type: {change_type}. "
            f"Changed files: {', '.join(changed_files)}. "
            "Find related requirements, affected functionality, "
            "known defects, risks and regression testing requirements."
        )

        try:
            evidence = self.retrieval_service.search_project_context(
                current_user_id=context.user_id,
                project_id=context.project_id,
                query=query,
                limit=6
            )

            evidence_text = "\n\n".join(
                [
                    (
                        f"Document: {item['document_name']}\n"
                        f"Chunk ID: {item['chunk_id']}\n"
                        f"Content: {item['content']}"
                    )
                    for item in evidence
                ]
            )

            if not evidence_text:
                evidence_text = "No supporting project documents were retrieved."

            system_prompt = """
You are TestNova's Change Risk Agent.

Your job is to analyse software changes and identify quality risks.

Use the supplied change information and retrieved project evidence.

Important rules:
1. Never invent changed files, requirements or defects.
2. Distinguish confirmed evidence from potential risks.
3. Do not claim a component is affected without explaining why.
4. If evidence is insufficient, clearly mention the limitation.
5. Risk score must be an integer from 0 to 100.
6. Risk level must be Low, Medium, High or Critical.
7. Recommendations must be relevant to the supplied change.

Return ONLY valid JSON in this exact structure:

{
  "risk_level": "Low",
  "risk_score": 0,
  "confidence": "Low",
  "change_summary": "",
  "affected_areas": [],
  "risk_factors": [],
  "potential_impact": [],
  "recommended_tests": [],
  "reasoning": "",
  "limitations": []
}
"""

            user_prompt = f"""
PROJECT ID: {context.project_id}

CHANGE TYPE:
{change_type}

CHANGE SUMMARY:
{change_summary}

CHANGED FILES:
{json.dumps(changed_files, ensure_ascii=False)}

ADDITIONAL CONTEXT:
{additional_context}

RETRIEVED PROJECT EVIDENCE:
{evidence_text}

Analyse the change and return the requested JSON.
"""

            llm_response = self.llm_service.generate_content(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_mime_type="application/json"
            )

            if not llm_response.get("success"):
                return AgentResult(
                    agent_name=self.name,
                    status="failed",
                    error={
                        "code": "RISK_ANALYSIS_FAILED",
                        "message": "The LLM could not complete the risk analysis."
                    }
                )

            analysis = self._parse_response(
                llm_response["answer"]
            )

            risk_level = str(
                analysis.get("risk_level", "")
            ).lower()

            if risk_level not in self.VALID_RISK_LEVELS:
                raise ValueError("Invalid risk level returned by the model.")

            risk_score = analysis.get("risk_score")

            if (
                not isinstance(risk_score, int)
                or isinstance(risk_score, bool)
                or not 0 <= risk_score <= 100
            ):
                raise ValueError("Invalid risk score returned by the model.")

            confidence = str(analysis.get("confidence", "")).lower()
            if confidence not in {"low", "medium", "high"}:
                raise ValueError("Invalid confidence returned by the model.")

            expected_lists = [
                "affected_areas",
                "risk_factors",
                "potential_impact",
                "recommended_tests",
                "limitations"
            ]

            for field in expected_lists:
                if not isinstance(analysis.get(field), list) or any(
                    not isinstance(item, str) for item in analysis[field]
                ):
                    raise ValueError(
                        f"Invalid analysis field: {field}"
                    )

            result_data = {
                **analysis,
                "risk_level": risk_level.capitalize(),
                "risk_score": risk_score,
                "confidence": confidence.capitalize(),
                "evidence_count": len(evidence),
                "model": llm_response.get("model")
            }

            return AgentResult(
                agent_name=self.name,
                status="success" if evidence else "partial",
                data=result_data,
                evidence=evidence
            )

        except Exception as exc:
            logger.exception(
                "Change Risk Agent failed for project %s",
                context.project_id
            )

            return AgentResult(
                agent_name=self.name,
                status="failed",
                error={
                    "code": "CHANGE_RISK_AGENT_ERROR",
                    "message": "Change risk analysis could not be completed."
                }
            )
