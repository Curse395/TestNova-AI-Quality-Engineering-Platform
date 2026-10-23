
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy.sql import func
from app.models.chat_history import ChatHistory
from app.models.chat_session import ChatSession


class ChatHistoryService:

    def __init__(self, db: Session):
        self.db = db

    def create_session(
        self,
        user_id: int,
        project_id: int,
        title: str = "New Chat",
    ) -> ChatSession:
        session = ChatSession(
            user_id=user_id,
            project_id=project_id,
            title=title,
        )

        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)

        return session

    def get_user_sessions(
        self,
        user_id: int,
        project_id: int,
    ) -> list[ChatSession]:
        return (
            self.db.query(ChatSession)
            .filter(
                ChatSession.user_id == user_id,
                ChatSession.project_id == project_id,
            )
            .order_by(desc(ChatSession.updated_at), desc(ChatSession.id))
            .all()
        )

    def get_session(
        self,
        session_id: int,
        user_id: int,
        project_id: int,
    ) -> ChatSession | None:
        return (
            self.db.query(ChatSession)
            .filter(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.project_id == project_id,
            )
            .first()
        )

    def get_session_history(
        self,
        session_id: int,
        user_id: int,
        project_id: int,
    ) -> list[ChatHistory]:
        return (
            self.db.query(ChatHistory)
            .filter(
                ChatHistory.session_id == session_id,
                ChatHistory.user_id == user_id,
                ChatHistory.project_id == project_id,
            )
            .order_by(ChatHistory.created_at.asc(), ChatHistory.id.asc())
            .all()
        )

    def save_chat(
        self,
        user_id: int,
        project_id: int,
        session_id: int,
        question: str,
        answer: str,
    ) -> ChatHistory:
        session = self.get_session(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
        )

        if session is None:
            raise ValueError("Chat session not found.")

        chat = ChatHistory(
            user_id=user_id,
            project_id=project_id,
            session_id=session_id,
            question=question,
            answer=answer,
        )

        self.db.add(chat)
        session.updated_at = func.now()
        self.db.commit()
        self.db.refresh(chat)

        return chat

    def delete_session(
        self,
        session_id: int,
        user_id: int,
        project_id: int,
    ) -> bool:
        session = self.get_session(
            session_id=session_id,
            user_id=user_id,
            project_id=project_id,
        )

        if session is None:
            return False

        self.db.delete(session)
        self.db.commit()

        return True
