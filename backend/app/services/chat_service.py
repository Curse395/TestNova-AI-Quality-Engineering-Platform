import json

from sqlalchemy.orm import Session

from app.services.retrieval_service import RetrievalService
from app.services.context_builder_service import ContextBuilderService
from app.services.llm_services import LLMService
from app.services.prompt_builder_service import PromptBuilderService
from app.services.chat_history_service import ChatHistoryService
from app.services.assistant_intelligence_service import (
    AssistantProjectIntelligenceService,
    AssistantQuestionRouter,
)
from app.models.chat_history import ChatHistory
from app.services.repository_architecture_service import RepositoryArchitectureService


class ChatService:
    def __init__(self, db: Session):
        self.db = db
        self.retrieval_service = RetrievalService(db)
        self.context_builder = ContextBuilderService()
        self.llm_service: LLMService | None = None
        self.prompt_builder = PromptBuilderService()
        self.history_service = ChatHistoryService(db)
        self.intelligence_service = AssistantProjectIntelligenceService(db)
        self.architecture_service = RepositoryArchitectureService()

    def _generate_content(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, str | bool]:
        if self.llm_service is None:
            self.llm_service = LLMService()
        return self.llm_service.generate_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    def chat(self, current_user_id: int, project_id: int, question: str, session_id: int):
        session = self.history_service.get_session(
            session_id=session_id,
            user_id=current_user_id,
            project_id=project_id,
        )
        if session is None:
            raise ValueError("chat session not found")

        recent_history = (
            self.db.query(ChatHistory)
            .filter(
                ChatHistory.session_id == session_id,
                ChatHistory.user_id == current_user_id,
                ChatHistory.project_id == project_id,
            )
            .order_by(ChatHistory.created_at.desc(), ChatHistory.id.desc())
            .limit(5)
            .all()
        )
        project_history = AssistantQuestionRouter.project_history(recent_history)
        conversation_history = "".join(
            f"User: {chat.question}\nAssistant: {chat.answer}\n\n"
            for chat in reversed(project_history)
        )
        plan = AssistantQuestionRouter.plan(question, recent_history)

        if plan.conversation:
            response = {
                "success": True,
                "answer": (
                    "Hi! I can help analyze the selected project's documents, "
                    "requirements, test cases, execution history, workflows, and "
                    "release evidence."
                ),
                "model": "assistant-router",
                "sources": [],
                "intelligence": {"kind": "conversation"},
            }
        elif plan.architecture:
            retrieved_chunks = self.architecture_service.search(question)
            context_payload = self.context_builder.build_context(retrieved_chunks)
            if not context_payload["sources"]:
                response = {
                    "success": True,
                    "answer": (
                        "I couldn't find supporting material in the approved, "
                        "statically inspected TestNova source files."
                    ),
                    "model": "repository-architecture",
                    "intelligence": {
                        "kind": "platform_architecture",
                        "evidence_available": False,
                    },
                    "sources": [],
                }
            else:
                system_prompt, user_prompt = self.prompt_builder.build_prompt(
                    context=context_payload["context"],
                    conversation_history="",
                    question=question,
                    knowledge_scope="approved, statically inspected TestNova source files",
                )
                response = self._generate_content(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                if not response.get("success"):
                    raise RuntimeError("The assistant could not generate a response.")
                response = {
                    **response,
                    "intelligence": {
                        "kind": "platform_architecture",
                        "evidence_available": True,
                    },
                    "sources": context_payload["sources"],
                }
        elif plan.retrieval_similarity:
            retrieved_chunks = self.retrieval_service.search_project_context(
                current_user_id=current_user_id,
                project_id=project_id,
                query=question,
                limit=5,
            )
            response = self.intelligence_service.answer_retrieval_similarity(
                retrieved_chunks
            )
            context_payload = self.context_builder.build_context(retrieved_chunks)
            response["sources"] = context_payload["sources"]
        elif plan.intents:
            structured_data = self.intelligence_service.collect(
                plan,
                current_user_id=current_user_id,
                project_id=project_id,
                question=question,
                conversation_history=project_history,
            )
            if not plan.use_retrieval:
                response = self.intelligence_service.result_payload(
                    structured_data,
                    question,
                )
            else:
                retrieved_chunks = self.retrieval_service.search_project_context(
                    current_user_id=current_user_id,
                    project_id=project_id,
                    query=question,
                    limit=5,
                )
                context_payload = self.context_builder.build_context(retrieved_chunks)
                system_prompt, user_prompt = self.prompt_builder.build_prompt(
                    context=context_payload["context"],
                    conversation_history=conversation_history,
                    question=question,
                    structured_context=json.dumps(
                        structured_data,
                        ensure_ascii=False,
                        default=str,
                    ),
                )
                response = self._generate_content(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                )
                if not response.get("success"):
                    raise RuntimeError("The assistant could not generate a response.")
                response = {
                    **response,
                    "intelligence": {
                        "kind": "structured_project_data_and_retrieval",
                        "data": structured_data,
                    },
                    "sources": context_payload["sources"],
                }
        else:
            retrieved_chunks = self.retrieval_service.search_project_context(
                current_user_id=current_user_id,
                project_id=project_id,
                query=question,
                limit=5,
            )
            context_payload = self.context_builder.build_context(retrieved_chunks)
            system_prompt, user_prompt = self.prompt_builder.build_prompt(
                context=context_payload["context"],
                conversation_history=conversation_history,
                question=question,
            )
            response = self._generate_content(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            if not response.get("success"):
                raise RuntimeError("The assistant could not generate a response.")
            response = {
                **response,
                "sources": context_payload["sources"],
            }

        self.history_service.save_chat(
            user_id=current_user_id,
            project_id=project_id,
            session_id=session_id,
            question=question,
            answer=str(response["answer"]),
        )
        return response
