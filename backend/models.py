"""SQLAlchemy models for the job hunter domain."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Job(Base):
    """A discovered job posting."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    company: Mapped[str] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    salary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    work_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    experience_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    visa_requirements: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    base_match_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    tailored_cv_match_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="found", index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    tailored_cv_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cover_letter_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    documents_generated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    found_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    documents: Mapped[list["GeneratedDocument"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    applications: Mapped[list["Application"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    history_entries: Mapped[list["ApplicationHistory"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Application(Base):
    """An application attempt for a job."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending_approval", index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    before_screenshot_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    after_screenshot_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="applications")


class GeneratedDocument(Base):
    """A generated CV or cover letter version."""

    __tablename__ = "generated_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    doc_type: Mapped[str] = mapped_column(String(50), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    file_path: Mapped[str] = mapped_column(String(1000))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship(back_populates="documents")


class Notification(Base):
    """A record of a notification sent to the user."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(50), default="console")
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship(back_populates="notifications")


class JobLog(Base):
    """Operational logs for searches, filters, and errors."""

    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(20), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ApplicationHistory(Base):
    """Audit trail of job state transitions and user actions."""

    __tablename__ = "application_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    job: Mapped["Job"] = relationship(back_populates="history_entries")


class CVVersion(Base):
    """Versioned source CV records."""

    __tablename__ = "cv_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, index=True)
    content: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskExecution(Base):
    """Centralized task execution tracking."""

    __tablename__ = "task_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_name: Mapped[str] = mapped_column(String(255), index=True)
    task_type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    progress_percentage: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    execution_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    traceback_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
