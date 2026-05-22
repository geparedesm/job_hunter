"""Database setup and session management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.loader import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


class Base(DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""


def _default_database_url() -> str:
    db_path = PROJECT_ROOT / "data" / "job_hunter.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url()
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """Create database tables."""
    from backend.models import Application, ApplicationHistory, CVVersion, GeneratedDocument, Job, JobLog, Notification

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI dependencies."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
