"""Database setup and session management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
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
    from backend.models import Application, ApplicationHistory, CVVersion, GeneratedDocument, Job, JobLog, Notification, TaskExecution

    Base.metadata.create_all(bind=engine)
    _upgrade_sqlite_schema()


def _upgrade_sqlite_schema() -> None:
    """Safely add newer columns for existing SQLite databases."""
    if not DATABASE_URL.startswith("sqlite:///"):
        return

    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("jobs")}
    missing_columns = {
        "city": "ALTER TABLE jobs ADD COLUMN city VARCHAR(120)",
        "state": "ALTER TABLE jobs ADD COLUMN state VARCHAR(120)",
        "country": "ALTER TABLE jobs ADD COLUMN country VARCHAR(120)",
        "full_location": "ALTER TABLE jobs ADD COLUMN full_location VARCHAR(255)",
        "raw_location": "ALTER TABLE jobs ADD COLUMN raw_location VARCHAR(255)",
        "is_remote": "ALTER TABLE jobs ADD COLUMN is_remote VARCHAR(20)",
        "work_mode": "ALTER TABLE jobs ADD COLUMN work_mode VARCHAR(20)",
        "easy_apply": "ALTER TABLE jobs ADD COLUMN easy_apply VARCHAR(20)",
        "easy_apply_type": "ALTER TABLE jobs ADD COLUMN easy_apply_type VARCHAR(50)",
        "easy_apply_detection_source": "ALTER TABLE jobs ADD COLUMN easy_apply_detection_source VARCHAR(50)",
        "base_match_score": "ALTER TABLE jobs ADD COLUMN base_match_score FLOAT",
        "tailored_cv_match_score": "ALTER TABLE jobs ADD COLUMN tailored_cv_match_score FLOAT",
        "tailored_cv_path": "ALTER TABLE jobs ADD COLUMN tailored_cv_path VARCHAR(1000)",
        "cover_letter_path": "ALTER TABLE jobs ADD COLUMN cover_letter_path VARCHAR(1000)",
        "documents_generated_at": "ALTER TABLE jobs ADD COLUMN documents_generated_at DATETIME",
    }
    existing_log_columns = {column["name"] for column in inspector.get_columns("job_logs")} if "job_logs" in inspector.get_table_names() else set()
    missing_log_columns = {
        "task_id": "ALTER TABLE job_logs ADD COLUMN task_id VARCHAR(64)",
    }

    with engine.begin() as connection:
        for column_name, ddl in missing_columns.items():
            if column_name in existing_columns:
                continue
            connection.execute(text(ddl))
        for column_name, ddl in missing_log_columns.items():
            if column_name in existing_log_columns:
                continue
            connection.execute(text(ddl))


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI dependencies."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
