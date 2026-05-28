"""Frontend-facing data and action services for the Streamlit dashboard."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import streamlit as st
import yaml
from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.models import Application, ApplicationHistory, GeneratedDocument, Job, JobLog, Notification
from backend.services import JobHunterService
from backend.task_manager import TaskManager
from config.loader import PROJECT_ROOT, load_settings


@dataclass(slots=True)
class JobFilters:
    """Dashboard filters for jobs."""

    keyword: str = ""
    source: str = "All sources"
    status: str = "All statuses"
    location: str = ""
    remote_status: str = "All"
    easy_apply_filter: str = "All"
    minimum_match_score: int = 0
    sponsorship_only: bool = False
    required_skills_only: bool = False
    date_from: date | None = None
    date_to: date | None = None


BACKGROUND_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="job-hunter-dashboard")


@st.cache_resource
def get_job_service() -> JobHunterService:
    """Create a reusable service instance for dashboard actions."""
    return JobHunterService()


@st.cache_resource
def get_task_manager() -> TaskManager:
    """Create a reusable task manager instance."""
    return TaskManager()


def _detect_sponsorship(job: Job) -> bool:
    analysis = (job.raw_payload or {}).get("analysis", {})
    visa_analysis = analysis.get("visa_analysis", {})
    status = visa_analysis.get("status", "")
    return status in {"Sponsorship likely available", "Sponsorship not available", "Work rights required"}


def _remote_label(job: Job) -> str:
    if job.is_remote in {"Yes", "No", "Hybrid", "Unknown"}:
        return job.is_remote
    if job.work_mode == "hybrid":
        return "Hybrid"
    if job.work_mode == "remote":
        return "Yes"
    if job.work_mode == "onsite":
        return "No"
    return "Unknown"


def _easy_apply_label(job: Job) -> str:
    if job.easy_apply in {"Yes", "No", "Unknown"}:
        return job.easy_apply
    return "Unknown"


def _has_detected_required_skills(job: Job) -> bool:
    skills = job.required_skills
    if not skills:
        return False
    if isinstance(skills, str):
        normalized = skills.strip().lower()
        return normalized not in {"", "none", "none detected", "unavailable", "n/a"}
    if isinstance(skills, list):
        cleaned = [str(item).strip() for item in skills if str(item).strip()]
        return any(item.lower() not in {"none", "none detected", "unavailable", "n/a"} for item in cleaned)
    return False


def _manual_cv_path() -> Path:
    return PROJECT_ROOT / "data" / "base_cv.md"


def _read_manual_cv_content() -> str:
    path = _manual_cv_path()
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8")
    placeholder = "# Base CV\n\nReplace this file with your source-of-truth CV in markdown."
    return "" if placeholder in content else content


def clear_dashboard_caches() -> None:
    """Clear cached dashboard reads after a state-changing action."""
    get_overview_data.clear()
    get_jobs_data.clear()
    get_job_detail_data.clear()
    get_statistics_data.clear()
    get_application_history_data.clear()
    get_notifications_data.clear()
    get_logs_data.clear()
    get_settings_data.clear()
    get_cv_jobs_data.clear()
    get_cv_preview_data.clear()
    get_interview_jobs_data.clear()
    get_interview_simulation_data.clear()
    get_task_monitor_data.clear()
    get_task_status_counts.clear()
    get_resume_profile_data.clear()
    get_resume_keyword_suggestions.clear()


def _settings_path() -> Path:
    return PROJECT_ROOT / "config" / "settings.yaml"


@st.cache_data(ttl=60)
def get_overview_data() -> dict[str, Any]:
    """Load overview metrics and scheduler/control metadata."""
    service = get_job_service()
    settings = load_settings(_settings_path())
    stats = service.get_statistics()
    with SessionLocal() as session:
        latest_search_log = session.scalar(
            select(JobLog).where(JobLog.event_type == "collector_results").order_by(JobLog.created_at.desc())
        )
        latest_job = session.scalar(select(Job).order_by(Job.found_at.desc()))
        high_match_targets = sum(1 for job in session.scalars(select(Job)).all() if (job.match_score or 0) >= 85)

    last_search = latest_search_log.created_at if latest_search_log else None
    next_search = last_search + timedelta(hours=settings.search_interval_hours) if last_search else None

    source_status = []
    env_map = {
        "adzuna": bool(os.getenv("ADZUNA_APP_ID") and os.getenv("ADZUNA_APP_KEY")),
        "jsearch": bool(os.getenv("JSEARCH_API_KEY")),
        "serpapi": bool(os.getenv("SERPAPI_API_KEY")),
    }
    for source in settings.sources:
        source_status.append({"source": source, "configured": env_map.get(source, False)})

    return {
        "stats": stats,
        "high_match_targets": high_match_targets,
        "last_search_at": last_search,
        "next_search_at": next_search,
        "last_job_found_at": latest_job.found_at if latest_job else None,
        "search_interval_hours": settings.search_interval_hours,
        "active_sources": settings.sources,
        "source_status": source_status,
        "manual_cv_present": bool(_read_manual_cv_content().strip()),
        "scheduler_running_task": next((task for task in get_task_manager().get_running_tasks() if task["task_type"] == "job_search_scheduler"), None),
    }


@st.cache_data(ttl=60)
def get_jobs_data(filters: JobFilters) -> list[dict[str, Any]]:
    """Load jobs with dashboard-specific filtering."""
    with SessionLocal() as session:
        jobs = session.scalars(select(Job).order_by(Job.found_at.desc())).all()

    filtered: list[dict[str, Any]] = []
    for job in jobs:
        sponsorship_detected = _detect_sponsorship(job)
        if filters.keyword:
            haystack = f"{job.company} {job.title} {job.description}".lower()
            if filters.keyword.lower() not in haystack:
                continue
        if filters.source != "All sources" and job.source != filters.source:
            continue
        if filters.status != "All statuses" and job.status != filters.status:
            continue
        location_haystack = " ".join(
            part for part in [job.city, job.state, job.country, job.full_location, job.raw_location, job.location] if part
        ).lower()
        if filters.location and filters.location.lower() not in location_haystack:
            continue
        remote_value = _remote_label(job)
        easy_apply_value = _easy_apply_label(job)
        if filters.remote_status == "Remote only" and remote_value != "Yes":
            continue
        if filters.remote_status == "Hybrid only" and remote_value != "Hybrid":
            continue
        if filters.remote_status == "On-site only" and remote_value != "No":
            continue
        if filters.remote_status == "Unknown" and remote_value != "Unknown":
            continue
        if filters.easy_apply_filter == "Easy Apply only" and easy_apply_value != "Yes":
            continue
        if filters.easy_apply_filter == "Non-Easy Apply" and easy_apply_value != "No":
            continue
        if filters.easy_apply_filter == "Unknown" and easy_apply_value != "Unknown":
            continue
        if (job.match_score or 0) < filters.minimum_match_score:
            continue
        if filters.sponsorship_only and not sponsorship_detected:
            continue
        if filters.required_skills_only and not _has_detected_required_skills(job):
            continue
        if filters.date_from and job.found_at.date() < filters.date_from:
            continue
        if filters.date_to and job.found_at.date() > filters.date_to:
            continue

        filtered.append(
            {
                "id": job.id,
                "company": job.company,
                "role": job.title,
                "source": job.source,
                "location": job.full_location or job.raw_location or job.location or "",
                "city": job.city or "Unknown",
                "state": job.state or "",
                "country": job.country or "",
                "raw_location": job.raw_location or job.location or "",
                "remote_status": remote_value,
                "easy_apply": easy_apply_value,
                "easy_apply_type": job.easy_apply_type or "Unknown",
                "salary": job.salary or "",
                "base_match_score": float(job.base_match_score) if job.base_match_score is not None else (float(job.match_score) if job.match_score is not None else None),
                "tailored_cv_match_score": float(job.tailored_cv_match_score) if job.tailored_cv_match_score is not None else None,
                "match_score": float(job.base_match_score) if job.base_match_score is not None else (float(job.match_score) if job.match_score is not None else None),
                "sponsorship_detected": sponsorship_detected,
                "status": job.status,
                "created_date": job.found_at,
                "url": job.url,
                "recommended_action": job.recommended_action or "",
                "analysis_incomplete": not (job.raw_payload or {}).get("content_extraction", {}).get("is_complete", False),
                "required_skills_detected": _has_detected_required_skills(job),
            }
        )
    return filtered


@st.cache_data(ttl=60)
def get_job_detail_data(job_id: int) -> dict[str, Any]:
    """Load detailed job data for the selected target."""
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        documents = session.scalars(
            select(GeneratedDocument).where(GeneratedDocument.job_id == job_id).order_by(GeneratedDocument.version.desc())
        ).all()
        applications = session.scalars(
            select(Application).where(Application.job_id == job_id).order_by(Application.id.desc())
        ).all()
        history_entries = session.scalars(
            select(ApplicationHistory).where(ApplicationHistory.job_id == job_id).order_by(ApplicationHistory.created_at.desc())
        ).all()

        latest_cv = next((doc for doc in documents if doc.doc_type == "cv"), None)
        latest_cover_letter = next((doc for doc in documents if doc.doc_type == "cover_letter"), None)
        latest_application = applications[0] if applications else None
        analysis = (job.raw_payload or {}).get("analysis", {})
        content_extraction = (job.raw_payload or {}).get("content_extraction", {})
        manual_cv_content = _read_manual_cv_content()

        return {
            "id": job.id,
            "company": job.company,
            "role": job.title,
            "location": job.full_location or job.raw_location or job.location or "",
            "city": job.city or "Unknown",
            "state": job.state or "",
            "country": job.country or "",
            "full_location": job.full_location or job.raw_location or job.location or "",
            "raw_location": job.raw_location or job.location or "",
            "remote_status": _remote_label(job),
            "easy_apply": _easy_apply_label(job),
            "easy_apply_type": job.easy_apply_type or "Unknown",
            "easy_apply_detection_source": job.easy_apply_detection_source or "Unknown",
            "salary": job.salary or "",
            "source": job.source,
            "url": job.url,
            "description": job.description,
            "required_skills": job.required_skills,
            "preferred_skills": job.preferred_skills,
            "missing_skills": job.missing_skills,
            "base_match_score": float(job.base_match_score) if job.base_match_score is not None else (float(job.match_score) if job.match_score is not None else None),
            "tailored_cv_match_score": float(job.tailored_cv_match_score) if job.tailored_cv_match_score is not None else None,
            "match_score": float(job.base_match_score) if job.base_match_score is not None else (float(job.match_score) if job.match_score is not None else None),
            "status": job.status,
            "recommended_action": job.recommended_action or "",
            "ai_explanation": job.ai_explanation or "",
            "work_type": job.work_type or "",
            "experience_level": job.experience_level or "",
            "visa_requirements": job.visa_requirements or "",
            "sponsorship_detected": _detect_sponsorship(job),
            "responsibilities": analysis.get("responsibilities", []),
            "required_skill_items": analysis.get("required_skill_items", []),
            "preferred_skill_items": analysis.get("preferred_skill_items", []),
            "qualification_items": analysis.get("qualification_items", []),
            "missing_skill_items": analysis.get("missing_skill_items", []),
            "visa_analysis": analysis.get("visa_analysis", {"status": "Not mentioned", "evidence": [], "confidence_score": 0.0}),
            "analysis_warnings": analysis.get("analysis_warnings", []),
            "cv_generation_status": analysis.get("cv_generation_status", "Manual only"),
            "analysis_incomplete": not content_extraction.get("is_complete", False),
            "content_extraction_method": content_extraction.get("source_method", "unknown"),
            "manual_cv_content": manual_cv_content,
            "manual_cv_present": bool(manual_cv_content.strip()),
            "generated_cv": latest_cv.content if latest_cv else "",
            "generated_cv_path": latest_cv.file_path if latest_cv else (job.tailored_cv_path or ""),
            "generated_cover_letter": latest_cover_letter.content if latest_cover_letter else "",
            "generated_cover_letter_path": latest_cover_letter.file_path if latest_cover_letter else (job.cover_letter_path or ""),
            "documents_generated_at": job.documents_generated_at,
            "application_status": latest_application.status if latest_application else job.status,
            "application_notes": latest_application.notes if latest_application else "",
            "before_screenshot": latest_application.before_screenshot_path if latest_application else "",
            "after_screenshot": latest_application.after_screenshot_path if latest_application else "",
            "history": [
                {"action": entry.action, "details": entry.details or "", "created_at": entry.created_at}
                for entry in history_entries
            ],
        }


@st.cache_data(ttl=60)
def get_cv_jobs_data() -> list[dict[str, Any]]:
    """Load jobs for the dedicated CV page."""
    with SessionLocal() as session:
        jobs = session.scalars(select(Job).order_by(Job.updated_at.desc(), Job.found_at.desc())).all()

    return [
        {
            "id": job.id,
            "company": job.company,
            "role": job.title,
            "base_match_score": float(job.base_match_score) if job.base_match_score is not None else (float(job.match_score) if job.match_score is not None else None),
            "tailored_cv_match_score": float(job.tailored_cv_match_score) if job.tailored_cv_match_score is not None else None,
            "tailored_cv_path": job.tailored_cv_path or "",
            "documents_generated_at": job.documents_generated_at,
            "has_tailored_cv": bool(job.tailored_cv_path),
        }
        for job in jobs
    ]


@st.cache_data(ttl=60)
def get_cv_preview_data(job_id: int) -> dict[str, Any]:
    """Load base and tailored CV preview content for a selected job."""
    return get_job_service().get_job_cv(job_id)


@st.cache_data(ttl=60)
def get_cv_diff_data(job_id: int) -> dict[str, Any]:
    """Load Git-style CV diff data for a selected job."""
    return get_job_service().get_job_cv_diff(job_id)


@st.cache_data(ttl=60)
def get_interview_jobs_data() -> list[dict[str, Any]]:
    """Load jobs for the Interview Simulator page."""
    with SessionLocal() as session:
        jobs = session.scalars(select(Job).order_by(Job.updated_at.desc(), Job.found_at.desc())).all()

    items: list[dict[str, Any]] = []
    for job in jobs:
        items.append(
            {
                "id": job.id,
                "company": job.company,
                "role": job.title,
                "base_match_score": float(job.base_match_score) if job.base_match_score is not None else (float(job.match_score) if job.match_score is not None else None),
                "tailored_cv_match_score": float(job.tailored_cv_match_score) if job.tailored_cv_match_score is not None else None,
                "has_tailored_cv": bool(job.tailored_cv_path),
                "has_interview_simulation": bool((job.raw_payload or {}).get("interview_simulation")),
            }
        )
    return items


@st.cache_data(ttl=60)
def get_interview_simulation_data(job_id: int) -> dict[str, Any]:
    """Load stored interview simulation data for a selected job."""
    return get_job_service().get_interview_simulation(job_id)


@st.cache_data(ttl=60)
def get_statistics_data() -> dict[str, Any]:
    """Load dashboard statistics with additional derived datasets."""
    overview = get_overview_data()
    with SessionLocal() as session:
        jobs = session.scalars(select(Job).order_by(Job.found_at.asc())).all()
        applications = session.scalars(select(Application).order_by(Application.submitted_at.asc())).all()

    jobs_found_over_time: dict[str, int] = {}
    sponsorship_counts = {"Sponsorship flagged": 0, "No sponsorship detected": 0}
    for job in jobs:
        key = job.found_at.date().isoformat()
        jobs_found_over_time[key] = jobs_found_over_time.get(key, 0) + 1
        sponsorship_counts["Sponsorship flagged" if _detect_sponsorship(job) else "No sponsorship detected"] += 1

    applications_per_week: dict[str, int] = {}
    for app in applications:
        if app.submitted_at is None:
            continue
        iso_year, iso_week, _ = app.submitted_at.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        applications_per_week[key] = applications_per_week.get(key, 0) + 1

    return {
        **overview["stats"],
        "jobs_found_over_time": jobs_found_over_time,
        "sponsorship_counts": sponsorship_counts,
        "applications_per_week": applications_per_week,
    }


@st.cache_data(ttl=60)
def get_application_history_data() -> list[dict[str, Any]]:
    """Load application history entries."""
    with SessionLocal() as session:
        applications = session.scalars(select(Application).order_by(Application.id.desc())).all()
        jobs_by_id = {job.id: job for job in session.scalars(select(Job)).all()}
        docs_by_job: dict[int, list[GeneratedDocument]] = {}
        for doc in session.scalars(select(GeneratedDocument)).all():
            docs_by_job.setdefault(doc.job_id, []).append(doc)

    history = []
    for app in applications:
        job = jobs_by_id.get(app.job_id)
        if job is None:
            continue
        history.append(
            {
                "date": app.submitted_at or job.updated_at,
                "company": job.company,
                "role": job.title,
                "status": app.status,
                "match_score": job.base_match_score if job.base_match_score is not None else job.match_score,
                "notes": app.notes or "",
                "documents_generated": len(docs_by_job.get(job.id, [])),
                "before_screenshot": app.before_screenshot_path or "",
                "after_screenshot": app.after_screenshot_path or "",
                "source": job.source,
            }
        )
    return history


@st.cache_data(ttl=60)
def get_notifications_data(limit: int = 20) -> list[dict[str, Any]]:
    """Load recent notifications."""
    with SessionLocal() as session:
        notifications = session.scalars(select(Notification).order_by(Notification.created_at.desc())).all()[:limit]

    level_map = {
        "new_match": "ALERT",
        "pending_approval": "WAITING",
        "application_result": "RESULT",
    }
    return [
        {
            "level": level_map.get(item.event_type, "INFO"),
            "message": item.message,
            "created_at": item.created_at,
        }
        for item in notifications
    ]


@st.cache_data(ttl=60)
def get_logs_data(limit: int = 200) -> list[dict[str, Any]]:
    """Load recent operational logs."""
    with SessionLocal() as session:
        logs = session.scalars(select(JobLog).order_by(JobLog.created_at.desc())).all()[:limit]

    return [
        {
            "timestamp": log.created_at,
            "level": log.level,
            "event_type": log.event_type,
            "task_id": log.task_id or "",
            "message": log.message,
            "metadata": log.metadata_json or {},
        }
        for log in logs
    ]


@st.cache_data(ttl=2)
def get_task_monitor_data(limit: int = 40) -> dict[str, Any]:
    """Load running and recent task data."""
    task_manager = get_task_manager()
    tasks = task_manager.list_tasks(limit=limit)
    running = [task for task in tasks if task["status"] in {"pending", "running"}]
    failed = [task for task in tasks if task["status"] == "failed"][:10]
    completed = [task for task in tasks if task["status"] == "completed"][:10]
    return {
        "running": running,
        "failed": failed,
        "completed": completed,
        "all": tasks,
    }


@st.cache_data(ttl=2)
def get_task_status_counts() -> dict[str, int]:
    """Summarize task states for quick UI indicators."""
    tasks = get_task_manager().list_tasks(limit=100)
    counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
    for task in tasks:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    return counts


@st.cache_data(ttl=60)
def get_settings_data() -> dict[str, Any]:
    """Load editable dashboard settings."""
    settings = load_settings(_settings_path())
    return {
        "keywords": settings.keywords,
        "locations": settings.locations,
        "minimum_match_score": settings.minimum_match_score,
        "search_interval_hours": settings.search_interval_hours,
        "sponsorship_required": False,
        "blacklist_keywords": settings.blacklist_keywords,
        "blacklist_companies": settings.blacklist_companies,
        "sources": settings.sources,
    }


def save_settings_data(payload: dict[str, Any]) -> None:
    """Persist dashboard settings back to YAML."""
    yaml_payload = {
        "keywords": [item.strip() for item in payload["keywords"] if item.strip()],
        "locations": [item.strip() for item in payload["locations"] if item.strip()],
        "minimum_match_score": int(payload["minimum_match_score"]),
        "search_interval_hours": int(payload["search_interval_hours"]),
        "blacklist_keywords": [item.strip() for item in payload["blacklist_keywords"] if item.strip()],
        "blacklist_companies": [item.strip() for item in payload["blacklist_companies"] if item.strip()],
        "sources": payload["sources"],
    }
    settings_path = _settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(yaml_payload, handle, sort_keys=False)
    clear_dashboard_caches()


def apply_suggested_keywords_to_settings(keywords: list[str]) -> None:
    """Append selected suggested keywords after an explicit UI confirmation."""
    settings = get_settings_data()
    merged_keywords: list[str] = []
    seen: set[str] = set()
    for item in [*settings["keywords"], *keywords]:
        value = item.strip()
        if not value or value.lower() in seen:
            continue
        seen.add(value.lower())
        merged_keywords.append(value)
    payload = {
        "keywords": merged_keywords,
        "locations": settings["locations"],
        "minimum_match_score": settings["minimum_match_score"],
        "search_interval_hours": settings["search_interval_hours"],
        "blacklist_keywords": settings["blacklist_keywords"],
        "blacklist_companies": settings["blacklist_companies"],
        "sources": settings["sources"],
    }
    save_settings_data(payload)


def trigger_search_now() -> dict[str, int]:
    """Trigger a search run and clear caches."""
    result = get_job_service().search_now()
    clear_dashboard_caches()
    return result


def launch_search_now() -> dict[str, Any]:
    """Queue a manual search task in the background."""
    task_manager = get_task_manager()
    existing = task_manager.find_running_task("job_search_scheduler")
    if existing is not None:
        raise ValueError("This task is already running.")
    task = task_manager.create_task(
        "Job search scheduler",
        "job_search_scheduler",
        current_step="Queued from dashboard",
        context={"trigger": "dashboard"},
    )

    def worker() -> None:
        try:
            get_job_service().search_jobs(task_id=str(task["task_id"]))
        finally:
            clear_dashboard_caches()

    BACKGROUND_EXECUTOR.submit(worker)
    clear_dashboard_caches()
    return task


@st.cache_data(ttl=30)
def get_resume_profile_data() -> dict[str, Any]:
    """Load the stored structured resume profile."""
    return get_job_service().get_resume_profile()


@st.cache_data(ttl=30)
def get_resume_keyword_suggestions() -> dict[str, Any]:
    """Load resume-derived keyword suggestions."""
    profile = get_resume_profile_data()
    if not profile:
        return {}
    return {
        "suggested_professions": profile.get("suggested_professions", []),
        "recommended_keywords": profile.get("recommended_keywords", []),
        "suggested_technologies": profile.get("suggested_technologies", []),
        "suggested_seniority_levels": profile.get("suggested_seniority_levels", []),
        "resume_insights": profile.get("resume_insights", {}),
        "analysis_source": profile.get("analysis_source", "fallback"),
    }


def upload_resume_file(filename: str, content: bytes) -> dict[str, Any]:
    """Upload and analyze a resume file."""
    result = get_job_service().upload_resume(filename, content)
    clear_dashboard_caches()
    return result


def analyze_resume_profile() -> dict[str, Any]:
    """Re-run analysis for the stored resume."""
    result = get_job_service().analyze_resume()
    clear_dashboard_caches()
    return result


def suggest_resume_keywords() -> dict[str, Any]:
    """Get smart job keyword suggestions from the resume profile."""
    result = get_job_service().suggest_resume_keywords()
    clear_dashboard_caches()
    return result


def generate_documents(job_id: int) -> dict[str, str]:
    """Document generation is intentionally manual-only."""
    result = get_job_service().generate_documents(job_id)
    clear_dashboard_caches()
    return result


def generate_tailored_cv(job_id: int) -> dict[str, Any]:
    """Generate a tailored CV for a specific job."""
    result = get_job_service().generate_tailored_cv(job_id)
    clear_dashboard_caches()
    return result


def launch_generate_tailored_cv(job_id: int) -> dict[str, Any]:
    """Queue tailored CV generation in the background."""
    task_manager = get_task_manager()
    existing = task_manager.find_running_task("tailored_cv_generation", context={"job_id": job_id})
    if existing is not None:
        raise ValueError("This task is already running.")
    task = task_manager.create_task(
        f"Generate tailored CV for job {job_id}",
        "tailored_cv_generation",
        current_step="Queued from dashboard",
        context={"job_id": job_id},
    )

    def worker() -> None:
        try:
            get_job_service().generate_tailored_cv(job_id, task_id=str(task["task_id"]))
        finally:
            clear_dashboard_caches()

    BACKGROUND_EXECUTOR.submit(worker)
    clear_dashboard_caches()
    return task


def generate_cover_letter(job_id: int) -> dict[str, Any]:
    """Generate a cover letter for a specific job."""
    result = get_job_service().generate_cover_letter(job_id)
    clear_dashboard_caches()
    return result


def launch_generate_cover_letter(job_id: int) -> dict[str, Any]:
    """Queue cover letter generation in the background."""
    task_manager = get_task_manager()
    existing = task_manager.find_running_task("cover_letter_generation", context={"job_id": job_id})
    if existing is not None:
        raise ValueError("This task is already running.")
    task = task_manager.create_task(
        f"Generate cover letter for job {job_id}",
        "cover_letter_generation",
        current_step="Queued from dashboard",
        context={"job_id": job_id},
    )

    def worker() -> None:
        try:
            get_job_service().generate_cover_letter(job_id, task_id=str(task["task_id"]))
        finally:
            clear_dashboard_caches()

    BACKGROUND_EXECUTOR.submit(worker)
    clear_dashboard_caches()
    return task


def recalculate_match(job_id: int) -> dict[str, Any]:
    """Recalculate base and tailored match scores for a specific job."""
    result = get_job_service().recalculate_match(job_id)
    clear_dashboard_caches()
    return result


def launch_recalculate_match(job_id: int) -> dict[str, Any]:
    """Queue match recalculation in the background."""
    task_manager = get_task_manager()
    existing = task_manager.find_running_task("match_score_calculation", context={"job_id": job_id})
    if existing is not None:
        raise ValueError("This task is already running.")
    task = task_manager.create_task(
        f"Recalculate match for job {job_id}",
        "match_score_calculation",
        current_step="Queued from dashboard",
        context={"job_id": job_id},
    )

    def worker() -> None:
        try:
            get_job_service().recalculate_match(job_id, task_id=str(task["task_id"]))
        finally:
            clear_dashboard_caches()

    BACKGROUND_EXECUTOR.submit(worker)
    clear_dashboard_caches()
    return task


def approve_job(job_id: int) -> None:
    """Approve a job."""
    get_job_service().approve_job(job_id)
    clear_dashboard_caches()


def reject_job(job_id: int) -> None:
    """Reject a job."""
    get_job_service().reject_job(job_id)
    clear_dashboard_caches()


def skip_job(job_id: int) -> None:
    """Skip a job."""
    get_job_service().skip_job(job_id)
    clear_dashboard_caches()


def apply_to_job(job_id: int) -> str:
    """Run the assisted application flow."""
    result = get_job_service().apply_to_job(job_id)
    clear_dashboard_caches()
    return result.message


def launch_apply_to_job(job_id: int) -> dict[str, Any]:
    """Queue the assisted application flow in the background."""
    task_manager = get_task_manager()
    existing = task_manager.find_running_task("playwright_automation", context={"job_id": job_id})
    if existing is not None:
        raise ValueError("This task is already running.")
    task = task_manager.create_task(
        f"Run application automation for job {job_id}",
        "playwright_automation",
        current_step="Queued from dashboard",
        context={"job_id": job_id},
    )

    def worker() -> None:
        try:
            get_job_service().apply_to_job(job_id, task_id=str(task["task_id"]))
        finally:
            clear_dashboard_caches()

    BACKGROUND_EXECUTOR.submit(worker)
    clear_dashboard_caches()
    return task


def mark_as_applied(job_id: int) -> None:
    """Manually mark a job as applied."""
    with SessionLocal() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        application = Application(job_id=job_id, status="applied", submitted_at=datetime.utcnow(), notes="Marked as applied manually from dashboard")
        session.add(application)
        job.status = "applied"
        session.add(ApplicationHistory(job_id=job_id, action="marked_applied", details="Marked as applied from dashboard"))
        session.commit()
    clear_dashboard_caches()


def get_download_bytes(path_str: str, fallback_content: str) -> bytes:
    """Read a document file for download, falling back to stored content."""
    if path_str:
        path = Path(path_str)
        if path.exists():
            return path.read_bytes()
    return fallback_content.encode("utf-8")


def export_base_cv_pdf(job_id: int | None = None) -> dict[str, Any]:
    """Export the base CV PDF for the dashboard."""
    path = get_job_service().export_base_cv_pdf(job_id=job_id)
    clear_dashboard_caches()
    return {"path": str(path), "bytes": path.read_bytes()}


def export_job_cv_pdf(job_id: int) -> dict[str, Any]:
    """Export the selected tailored CV PDF for the dashboard."""
    path = get_job_service().export_job_cv_pdf(job_id)
    clear_dashboard_caches()
    return {"path": str(path), "bytes": path.read_bytes()}


def generate_interview_simulation(job_id: int) -> dict[str, Any]:
    """Generate an interview simulation for a specific job."""
    result = get_job_service().generate_interview_simulation(job_id)
    clear_dashboard_caches()
    return result


def launch_generate_interview_simulation(job_id: int) -> dict[str, Any]:
    """Queue interview simulation generation in the background."""
    task_manager = get_task_manager()
    existing = task_manager.find_running_task("interview_simulation_generation", context={"job_id": job_id})
    if existing is not None:
        raise ValueError("This task is already running.")
    task = task_manager.create_task(
        f"Generate interview simulation for job {job_id}",
        "interview_simulation_generation",
        current_step="Queued from dashboard",
        context={"job_id": job_id},
    )

    def worker() -> None:
        try:
            get_job_service().generate_interview_simulation(job_id, task_id=str(task["task_id"]))
        finally:
            clear_dashboard_caches()

    BACKGROUND_EXECUTOR.submit(worker)
    clear_dashboard_caches()
    return task


def export_interview_simulation_pdf(job_id: int) -> dict[str, Any]:
    """Export the selected interview simulation PDF for the dashboard."""
    path = get_job_service().export_interview_simulation_pdf(job_id)
    clear_dashboard_caches()
    return {"path": str(path), "bytes": path.read_bytes()}


def get_interactive_interview_question(job_id: int, question_index: int = 0) -> dict[str, Any]:
    """Load one interview question for interactive mode."""
    return get_job_service().start_interactive_interview(job_id, question_index=question_index)


def evaluate_interview_answer(job_id: int, question_id: str, answer: str) -> dict[str, Any]:
    """Evaluate one interview answer."""
    return get_job_service().evaluate_interview_answer(job_id, question_id, answer)


def is_task_running(task_type: str, *, job_id: int | None = None) -> bool:
    """Return whether a matching task is already running."""
    context = {"job_id": job_id} if job_id is not None else None
    return get_task_manager().find_running_task(task_type, context=context) is not None


def save_manual_cv_content(content: str) -> None:
    """Persist manually provided CV/profile content."""
    path = _manual_cv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    clear_dashboard_caches()
