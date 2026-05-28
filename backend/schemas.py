"""Pydantic schemas for the API and dashboard layers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobRead(BaseModel):
    """Serializable job response."""

    id: int
    source: str
    company: str
    title: str
    location: str | None = None
    salary: str | None = None
    url: str
    work_type: str | None = None
    experience_level: str | None = None
    visa_requirements: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    base_match_score: float | None = None
    tailored_cv_match_score: float | None = None
    match_score: float | None = None
    ai_explanation: str | None = None
    recommended_action: str | None = None
    status: str
    tailored_cv_path: str | None = None
    cover_letter_path: str | None = None
    documents_generated_at: datetime | None = None
    found_at: datetime

    model_config = {"from_attributes": True}


class StatisticsRead(BaseModel):
    """Statistics used by the dashboard."""

    total_jobs_found: int
    new_jobs: int
    average_match_score: float
    applications_sent: int
    pending_approvals: int
    interviews: int
    rejected: int
    applications_by_status: dict[str, int]
    average_match_score_by_source: dict[str, float]
    top_required_skills: dict[str, int]
    applications_over_time: dict[str, int]


class ActionResponse(BaseModel):
    """Generic action response."""

    success: bool
    message: str
    payload: dict[str, Any] | None = None


class SearchResponse(BaseModel):
    """Result of a search run."""

    discovered: int
    created: int
    analyzed: int
    pending_approval: int
    skipped: int


class TaskRead(BaseModel):
    """Serializable task execution response."""

    task_id: str
    task_name: str
    task_type: str
    status: str
    progress_percentage: int
    current_step: str
    context_json: dict[str, Any] = Field(default_factory=dict)
    start_time: datetime
    finish_time: datetime | None = None
    execution_duration_seconds: float | None = None
    error_message: str = ""
    traceback_summary: str = ""
