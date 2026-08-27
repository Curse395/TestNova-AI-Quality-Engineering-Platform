from sqlalchemy import (
    Column,
    Integer,
    Text,
    ForeignKey,
    DateTime,
)
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

from app.database.connection import Base


class SemanticCache(Base):
    __tablename__ = "semantic_cache"

    id = Column(Integer, primary_key=True, index=True)

    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    question = Column(Text, nullable=False)

    question_embedding = Column(
        Vector(384),
        nullable=False,
    )

    answer = Column(Text, nullable=False)

    model = Column(Text, nullable=False)

    hit_count = Column(
        Integer,
        default=0,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    last_accessed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )