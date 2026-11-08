from fastapi import APIRouter, Depends,HTTPException
from sqlalchemy.orm import Session
from app.core.dependencies import CurrentUser
from app.database.connection import get_db
from app.services.chat_service import ChatService
from app.services.chat_history_service import ChatHistoryService

router=APIRouter(prefix="/chat",tags=["Chat"],)

@router.post("/sessions")
def create_chat_session(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    service = ChatHistoryService(db)

    try:
        session = service.create_session(
            user_id=current_user.id,
            project_id=project_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc

    return {
        "id": session.id,
        "project_id": session.project_id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
    }


@router.get("/sessions")
def list_chat_sessions(
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    sessions = ChatHistoryService(db).get_user_sessions(
        user_id=current_user.id,
        project_id=project_id,
    )

    return [
        {
            "id": session.id,
            "project_id": session.project_id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
        for session in sessions
    ]


@router.get("/sessions/{session_id}")
def get_chat_session(
    session_id: int,
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    service = ChatHistoryService(db)

    session = service.get_session(
        session_id=session_id,
        user_id=current_user.id,
        project_id=project_id,
    )

    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    history = service.get_session_history(
        session_id=session_id,
        user_id=current_user.id,
        project_id=project_id,
    )

    return {
        "id": session.id,
        "project_id": session.project_id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": [
            {
                "id": chat.id,
                "question": chat.question,
                "answer": chat.answer,
                "created_at": chat.created_at,
            }
            for chat in history
        ],
    }


@router.delete("/sessions/{session_id}")
def delete_chat_session(
    session_id: int,
    project_id: int,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    deleted = ChatHistoryService(db).delete_session(
        session_id=session_id,
        user_id=current_user.id,
        project_id=project_id,
    )

    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found")

    return {"message": "Chat session deleted successfully"}


@router.post("/")
def chat(
    session_id: int,
    project_id: int,
    question: str,
    current_user: CurrentUser,
    db: Session = Depends(get_db),
):
    try:
        return ChatService(db).chat(
            current_user_id=current_user.id,
            project_id=project_id,
            session_id=session_id,
            question=question,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
