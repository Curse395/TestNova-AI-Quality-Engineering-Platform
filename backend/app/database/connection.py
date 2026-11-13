from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings
import logging

engine=create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal=sessionmaker(bind=engine,autoflush=False,autocommit=False)
Base=declarative_base()
logger = logging.getLogger(__name__)

def get_db():
    db=SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except SQLAlchemyError as rollback_error:
            logger.error(
                "Database session rollback failed: error_type=%s",
                type(rollback_error).__name__,
                extra={"error_type": type(rollback_error).__name__},
            )
        raise
    finally:
        db.close()