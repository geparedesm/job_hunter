"""Core orchestration service for the personal AI job hunter."""

from __future__ import annotations

import csv
import difflib
import json
import logging
import os
import re
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai.cover_letter import CoverLetterGenerator
from ai.cv_adapter import CVAdapter
from ai.interview_simulator import InterviewSimulator
from ai.matcher import JobMatcher, MatchResult
from ai.resume_advisor import ResumeAdvisor
from automation.apply import ApplicationAutomation, ApplicationAutomationResult
from backend.database import SessionLocal, init_db
from backend.models import Application, ApplicationHistory, CVVersion, GeneratedDocument, Job, JobLog, Notification
from backend.pdf_utils import markdown_to_plain_text, write_simple_pdf
from backend.task_manager import TaskManager
from collectors.adzuna import AdzunaCollector
from collectors.apply_utils import detect_easy_apply
from collectors.base import CollectedJob
from collectors.content_extractor import JobContentExtractor
from collectors.jsearch import JSearchCollector
from collectors.serpapi import SerpApiCollector
from config.loader import PROJECT_ROOT, AppConfig, load_settings
from notifications.notifier import ConsoleNotifier

load_dotenv(PROJECT_ROOT / ".env")

LOGGER = logging.getLogger("job_hunter")


def _configure_logging() -> None:
    logs_dir = PROJECT_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    file_handler = logging.FileHandler(logs_dir / "job_hunter.log", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(file_handler)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


@dataclass(slots=True)
class SearchSummary:
    """Summary of a collector run."""

    discovered: int = 0
    created: int = 0
    analyzed: int = 0
    pending_approval: int = 0
    skipped: int = 0


class JobHunterService:
    """Orchestrates collection, analysis, document generation, and approvals."""

    def __init__(self, config: AppConfig | None = None) -> None:
        _configure_logging()
        init_db()
        self.config = config or load_settings()
        self.matcher = JobMatcher()
        self.cv_adapter = CVAdapter()
        self.cover_letter_generator = CoverLetterGenerator()
        self.interview_simulator = InterviewSimulator()
        self.resume_advisor = ResumeAdvisor()
        self.notifier = ConsoleNotifier()
        self.automation = ApplicationAutomation()
        self.content_extractor = JobContentExtractor()
        self.task_manager = TaskManager()

    def _session(self, session: Session | None = None) -> Session:
        return session or SessionLocal()

    def _collectors(self) -> list[Any]:
        collector_map = {
            "adzuna": AdzunaCollector(self.config),
            "jsearch": JSearchCollector(self.config),
            "serpapi": SerpApiCollector(self.config),
        }
        return [collector_map[source] for source in self.config.sources if source in collector_map]

    def _base_cv_path(self) -> Path:
        return PROJECT_ROOT / "data" / "base_cv.md"

    def _base_cv_content(self, session: Session) -> str:
        path = self._base_cv_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("# Base CV\n\nAdd your source CV content here.\n", encoding="utf-8")
        content = path.read_text(encoding="utf-8")
        latest = session.scalar(select(func.max(CVVersion.version)))
        if latest is None:
            session.add(CVVersion(version=1, content=content, source_path=str(path)))
            session.commit()
        return content

    def _require_base_cv_content(self, session: Session) -> str:
        content = self._base_cv_content(session)
        if not content.strip() or "Replace this file with your source-of-truth CV in markdown." in content:
            raise ValueError("A base CV is required before generating tailored documents.")
        return content

    def _log(
        self,
        session: Session,
        level: str,
        event_type: str,
        message: str,
        metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        LOGGER.log(getattr(logging, level.upper(), logging.INFO), "%s | %s", event_type, message)
        session.add(JobLog(level=level.upper(), event_type=event_type, task_id=task_id, message=message, metadata_json=metadata))
        session.commit()

    def _history(self, session: Session, job_id: int, action: str, details: str | None = None) -> None:
        session.add(ApplicationHistory(job_id=job_id, action=action, details=details))
        session.commit()

    def _notify(self, session: Session, event_type: str, message: str, job_id: int | None = None, task_id: str | None = None) -> None:
        self.notifier.send(message)
        session.add(Notification(job_id=job_id, channel="console", event_type=event_type, message=message))
        session.commit()
        if task_id:
            self._log(session, "info", "notification_sent", message.splitlines()[0], {"job_id": job_id, "event_type": event_type}, task_id=task_id)

    def _ensure_task(
        self,
        task_id: str | None,
        *,
        task_name: str,
        task_type: str,
        context: dict[str, Any] | None = None,
        start_step: str = "Starting",
    ) -> str:
        if task_id is None:
            created = self.task_manager.create_task(task_name, task_type, current_step=start_step, context=context)
            task_id = str(created["task_id"])
        self.task_manager.update_task_progress(task_id, progress_percentage=1, current_step=start_step, status="running")
        return task_id

    def _job_exists(self, session: Session, collected_job: CollectedJob) -> Job | None:
        if collected_job.external_id:
            stmt = select(Job).where(
                (Job.url == collected_job.url)
                | ((Job.external_id == collected_job.external_id) & (Job.source == collected_job.source))
            )
        else:
            stmt = select(Job).where(Job.url == collected_job.url)
        return session.scalar(stmt)

    def _easy_apply_rank(self, value: str | None) -> int:
        if value in {"Yes", "No"}:
            return 2
        if value == "Unknown":
            return 1
        return 0

    def _refresh_easy_apply_detection(
        self,
        job: Job,
        *,
        description: str,
        metadata: dict[str, Any],
        page_text: str = "",
    ) -> None:
        detected = detect_easy_apply(
            source=job.source,
            url=job.url,
            description=description,
            metadata=metadata,
            page_text=page_text,
        )
        current_rank = self._easy_apply_rank(job.easy_apply)
        detected_rank = self._easy_apply_rank(detected["easy_apply"])
        if detected_rank < current_rank:
            return
        if detected_rank == current_rank and job.easy_apply_detection_source and job.easy_apply != "Unknown":
            return
        job.easy_apply = detected["easy_apply"]
        job.easy_apply_type = detected["easy_apply_type"]
        job.easy_apply_detection_source = detected["easy_apply_detection_source"]

    def _is_blacklisted(self, job: CollectedJob) -> tuple[bool, str | None]:
        combined = f"{job.title} {job.description}".lower()
        company_name = job.company.lower()
        for keyword in self.config.blacklist_keywords:
            if keyword.lower() in combined:
                return True, f"blacklisted keyword: {keyword}"
        for company in self.config.blacklist_companies:
            if company.lower() == company_name:
                return True, f"blacklisted company: {company}"
        return False, None

    def _location_compatible(self, location: str | None, city: str | None = None, state: str | None = None, country: str | None = None, work_mode: str | None = None) -> bool:
        if not self.config.locations:
            return True
        if work_mode in {"remote", "hybrid"}:
            return True
        haystack = " ".join(part for part in [city, state, country, location] if part).lower()
        if not haystack:
            return False
        return any(config_location.lower() in haystack for config_location in self.config.locations)

    def _persist_job(self, session: Session, collected_job: CollectedJob) -> Job:
        raw_payload = dict(collected_job.raw_payload)
        raw_payload["preview_description"] = collected_job.description
        job = Job(
            external_id=collected_job.external_id,
            source=collected_job.source,
            company=collected_job.company,
            title=collected_job.title,
            description=collected_job.description,
            location=collected_job.location,
            city=collected_job.city,
            state=collected_job.state,
            country=collected_job.country,
            full_location=collected_job.full_location or collected_job.location,
            raw_location=collected_job.raw_location or collected_job.location,
            is_remote=collected_job.is_remote,
            work_mode=collected_job.work_mode,
            easy_apply=collected_job.easy_apply,
            easy_apply_type=collected_job.easy_apply_type,
            easy_apply_detection_source=collected_job.easy_apply_detection_source,
            salary=collected_job.salary,
            url=collected_job.url,
            raw_payload=raw_payload,
            status="found",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        self._history(session, job.id, "found", f"Collected from {job.source}")
        return job

    def _job_output_dir(self, job: Job) -> Path:
        output_dir = PROJECT_ROOT / "generated" / _slugify(f"{job.company}_{job.title}")
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _pdf_output_dir(self) -> Path:
        output_dir = PROJECT_ROOT / "generated" / "pdfs"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _resume_dir(self) -> Path:
        output_dir = PROJECT_ROOT / "data" / "resumes"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _resume_profile_path(self) -> Path:
        return self._resume_dir() / "resume_profile.json"

    def _resume_text_path(self) -> Path:
        return self._resume_dir() / "parsed_resume.txt"

    def _resume_latest_file_path(self, filename: str) -> Path:
        safe_name = _slugify(Path(filename).stem) or "resume"
        suffix = Path(filename).suffix.lower() or ".txt"
        return self._resume_dir() / f"{safe_name}{suffix}"

    def get_resume_profile(self) -> dict[str, Any]:
        """Return the stored structured resume profile, if any."""
        profile_path = self._resume_profile_path()
        if not profile_path.exists():
            return {}
        return json.loads(profile_path.read_text(encoding="utf-8"))

    def upload_resume(self, filename: str, content: bytes, task_id: str | None = None) -> dict[str, Any]:
        """Store a resume locally, parse it, and generate AI suggestions."""
        task_id = self._ensure_task(
            task_id,
            task_name="Resume upload and analysis",
            task_type="resume_upload_analysis",
            context={"filename": filename},
            start_step="Uploading resume...",
        )
        with self._session() as session:
            try:
                self.task_manager.update_task_progress(task_id, progress_percentage=10, current_step="Uploading resume...")
                stored_path = self._resume_latest_file_path(filename)
                stored_path.write_bytes(content)

                self.task_manager.update_task_progress(task_id, progress_percentage=28, current_step="Extracting text...")
                parsed_text = self.resume_advisor.extract_text(filename, content)
                self._resume_text_path().write_text(parsed_text, encoding="utf-8")

                self.task_manager.update_task_progress(task_id, progress_percentage=52, current_step="Detecting skills...")
                profile = self.resume_advisor.analyze(parsed_text, filename=filename)

                self.task_manager.update_task_progress(task_id, progress_percentage=72, current_step="Generating suggested professions...")
                self.task_manager.update_task_progress(task_id, progress_percentage=88, current_step="Updating keyword suggestions...")
                profile_payload = {
                    **profile,
                    "original_filename": filename,
                    "stored_file_path": str(stored_path),
                    "parsed_text_path": str(self._resume_text_path()),
                    "parsed_text": parsed_text,
                    "uploaded_at": datetime.utcnow().isoformat(),
                }
                self._resume_profile_path().write_text(json.dumps(profile_payload, indent=2), encoding="utf-8")

                self.task_manager.complete_task(task_id, current_step="Completed")
                self._log(
                    session,
                    "info",
                    "resume_profile_updated",
                    f"Resume uploaded and analyzed: {filename}",
                    {"filename": filename, "stored_file_path": str(stored_path)},
                    task_id=task_id,
                )
                self._notify(session, "resume_profile_updated", f"[SUCCESS] Resume analyzed: {filename}", task_id=task_id)
                return profile_payload
            except Exception as exc:
                self.task_manager.fail_task(task_id, error_message=str(exc), current_step="Resume upload failed", traceback_summary=traceback.format_exc(limit=6))
                self._log(session, "error", "resume_profile_failed", str(exc), {"filename": filename}, task_id=task_id)
                raise

    def analyze_resume(self, task_id: str | None = None) -> dict[str, Any]:
        """Re-analyze the stored resume text and refresh smart suggestions."""
        profile = self.get_resume_profile()
        stored_file_path = profile.get("stored_file_path")
        if not stored_file_path:
            raise ValueError("Upload a resume first.")
        file_path = Path(stored_file_path)
        if not file_path.exists():
            raise ValueError("The stored resume file no longer exists.")
        task_id = self._ensure_task(
            task_id,
            task_name="Resume profile analysis",
            task_type="resume_profile_analysis",
            context={"filename": profile.get("original_filename", file_path.name)},
            start_step="Uploading resume...",
        )
        try:
            content = file_path.read_bytes()
            return self.upload_resume(profile.get("original_filename", file_path.name), content, task_id=task_id)
        except Exception as exc:
            self.task_manager.fail_task(task_id, error_message=str(exc), current_step="Resume analysis failed", traceback_summary=traceback.format_exc(limit=6))
            raise

    def suggest_resume_keywords(self, task_id: str | None = None) -> dict[str, Any]:
        """Return smart role and keyword suggestions derived from the stored resume."""
        task_id = self._ensure_task(
            task_id,
            task_name="Resume keyword suggestions",
            task_type="resume_keyword_suggestions",
            start_step="Updating keyword suggestions...",
        )
        with self._session() as session:
            try:
                profile = self.get_resume_profile()
                if not profile:
                    raise ValueError("Upload and analyze a resume first.")
                self.task_manager.update_task_progress(task_id, progress_percentage=55, current_step="Updating keyword suggestions...")
                payload = {
                    "suggested_professions": profile.get("suggested_professions", []),
                    "recommended_keywords": profile.get("recommended_keywords", []),
                    "suggested_technologies": profile.get("suggested_technologies", []),
                    "suggested_seniority_levels": profile.get("suggested_seniority_levels", []),
                    "resume_insights": profile.get("resume_insights", {}),
                    "analysis_source": profile.get("analysis_source", "fallback"),
                }
                self.task_manager.complete_task(task_id, current_step="Keyword suggestions ready")
                self._log(session, "info", "resume_keyword_suggestions", "Resume keyword suggestions generated", payload, task_id=task_id)
                return payload
            except Exception as exc:
                self.task_manager.fail_task(task_id, error_message=str(exc), current_step="Keyword suggestion failed", traceback_summary=traceback.format_exc(limit=6))
                self._log(session, "error", "resume_keyword_suggestions_failed", str(exc), task_id=task_id)
                raise

    def _interview_output_dir(self, job: Job) -> Path:
        output_dir = PROJECT_ROOT / "generated" / "interviews" / _slugify(f"{job.id}_{job.company}_{job.title}")
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _safe_cv_pdf_name(self, label: str, job: Job | None = None) -> str:
        if job is None:
            return f"{_slugify(label)}.pdf"
        company_slug = _slugify(job.company)
        title_slug = _slugify(job.title)
        if label == "tailored_cv":
            return f"tailored_cv_{job.id}_{company_slug}_{title_slug}.pdf"
        if label == "base_cv":
            return f"base_cv_{job.id}_{company_slug}_{title_slug}.pdf"
        return f"{_slugify(label)}_{job.id}_{company_slug}_{title_slug}.pdf"

    def _safe_interview_file_name(self, label: str, job: Job, extension: str) -> str:
        company_slug = _slugify(job.company)
        title_slug = _slugify(job.title)
        return f"{_slugify(label)}_{job.id}_{company_slug}_{title_slug}.{extension}"

    def _next_document_version(self, session: Session, job_id: int, doc_type: str) -> int:
        versions = session.scalars(
            select(GeneratedDocument.version).where(
                GeneratedDocument.job_id == job_id,
                GeneratedDocument.doc_type == doc_type,
            )
        ).all()
        return (max(versions) if versions else 0) + 1

    def _create_generated_document(
        self,
        session: Session,
        job: Job,
        doc_type: str,
        content: str,
        file_name: str,
        output_dir: Path | None = None,
    ) -> GeneratedDocument:
        output_path = (output_dir or self._job_output_dir(job)) / file_name
        output_path.write_text(content, encoding="utf-8")
        document = GeneratedDocument(
            job_id=job.id,
            doc_type=doc_type,
            version=self._next_document_version(session, job.id, doc_type),
            file_path=str(output_path),
            content=content,
        )
        session.add(document)
        return document

    def _latest_document(self, session: Session, job_id: int, doc_type: str) -> GeneratedDocument | None:
        return session.scalar(
            select(GeneratedDocument)
            .where(GeneratedDocument.job_id == job_id, GeneratedDocument.doc_type == doc_type)
            .order_by(GeneratedDocument.version.desc())
        )

    def _job_sections(self, job: Job) -> dict[str, list[str]]:
        raw_payload = job.raw_payload or {}
        content_extraction = raw_payload.get("content_extraction", {})
        sections = content_extraction.get("sections", {})
        return sections if isinstance(sections, dict) else {"general": [job.description]}

    def get_base_cv(self) -> dict[str, Any]:
        """Return the base CV content and source path."""
        session = self._session()
        try:
            content = self._base_cv_content(session)
            return {"content": content, "path": str(self._base_cv_path())}
        finally:
            session.close()

    def get_job_cv(self, job_id: int) -> dict[str, Any]:
        """Return CV preview data for a selected job."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            base_cv = self._base_cv_content(session)
            generated_cv_content = ""
            if job.tailored_cv_path and Path(job.tailored_cv_path).exists():
                generated_cv_content = Path(job.tailored_cv_path).read_text(encoding="utf-8")
            else:
                latest_cv = session.scalar(
                    select(GeneratedDocument)
                    .where(GeneratedDocument.job_id == job.id, GeneratedDocument.doc_type == "cv")
                    .order_by(GeneratedDocument.version.desc())
                )
                if latest_cv is not None:
                    generated_cv_content = latest_cv.content
            return {
                "job_id": job.id,
                "company": job.company,
                "title": job.title,
                "base_match_score": job.base_match_score if job.base_match_score is not None else job.match_score,
                "tailored_cv_match_score": job.tailored_cv_match_score,
                "tailored_cv_path": job.tailored_cv_path or "",
                "documents_generated_at": job.documents_generated_at,
                "base_cv_content": base_cv,
                "tailored_cv_content": generated_cv_content,
            }
        finally:
            session.close()

    def get_job_cv_diff(self, job_id: int) -> dict[str, Any]:
        """Return Git-style diff data between the base and tailored CV."""
        cv_data = self.get_job_cv(job_id)
        base_lines = cv_data["base_cv_content"].splitlines()
        tailored_lines = cv_data["tailored_cv_content"].splitlines()
        unified = list(
            difflib.unified_diff(
                base_lines,
                tailored_lines,
                fromfile="original_cv.md",
                tofile="tailored_cv.md",
                lineterm="",
            )
        )
        return {
            **cv_data,
            "diff_lines": unified,
            "has_tailored_cv": bool(cv_data["tailored_cv_content"].strip()),
        }

    def export_base_cv_pdf(self, job_id: int | None = None, task_id: str | None = None) -> Path:
        """Export the base CV to PDF only when explicitly requested."""
        session = self._session()
        try:
            content = self._base_cv_content(session)
            job = session.get(Job, job_id) if job_id is not None else None
            task_id = self._ensure_task(
                task_id,
                task_name="Export base CV PDF" if job is None else f"Export base CV PDF for {job.company} - {job.title}",
                task_type="pdf_export",
                context={"job_id": job.id} if job is not None else {"base_cv": True},
                start_step="Preparing base CV PDF",
            )
            filename = self._safe_cv_pdf_name("base_cv", job)
            self.task_manager.update_task_progress(task_id, progress_percentage=60, current_step="Rendering PDF...")
            path = write_simple_pdf(
                markdown_to_plain_text(content),
                self._pdf_output_dir() / filename,
                title="Base CV",
            )
            self.task_manager.complete_task(task_id, current_step="Completed")
            return path
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="PDF export failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            session.close()

    def export_job_cv_pdf(self, job_id: int, task_id: str | None = None) -> Path:
        """Export a tailored CV to PDF only when explicitly requested."""
        cv_data = self.get_job_cv(job_id)
        content = cv_data["tailored_cv_content"]
        if not content.strip():
            raise ValueError("No tailored CV exists for this job yet.")
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Export tailored CV PDF for {job.company} - {job.title}",
                task_type="pdf_export",
                context={"job_id": job.id, "tailored": True},
                start_step="Preparing tailored CV PDF",
            )
            self.task_manager.update_task_progress(task_id, progress_percentage=60, current_step="Rendering PDF...")
            path = write_simple_pdf(
                markdown_to_plain_text(content),
                self._pdf_output_dir() / self._safe_cv_pdf_name("tailored_cv", job),
                title=f"Tailored CV - {job.company} - {job.title}",
            )
            self.task_manager.complete_task(task_id, current_step="Completed")
            return path
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="PDF export failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            session.close()

    def get_interview_simulation(self, job_id: int) -> dict[str, Any]:
        """Return the latest stored interview simulation payload for a job."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            latest_markdown = self._latest_document(session, job.id, "interview_simulation_md")
            latest_json = self._latest_document(session, job.id, "interview_simulation_json")
            payload: dict[str, Any] = {}
            if latest_json is not None:
                payload = json.loads(latest_json.content)
            elif isinstance(job.raw_payload, dict):
                payload = (job.raw_payload or {}).get("interview_simulation", {})
            return {
                "job_id": job.id,
                "company": job.company,
                "title": job.title,
                "base_match_score": job.base_match_score if job.base_match_score is not None else job.match_score,
                "tailored_cv_match_score": job.tailored_cv_match_score,
                "simulation": payload,
                "markdown_content": latest_markdown.content if latest_markdown is not None else "",
                "markdown_path": latest_markdown.file_path if latest_markdown is not None else "",
                "json_path": latest_json.file_path if latest_json is not None else "",
                "documents_generated_at": job.documents_generated_at,
            }
        finally:
            session.close()

    def generate_interview_simulation(self, job_id: int, session: Session | None = None, task_id: str | None = None) -> dict[str, Any]:
        """Generate and persist interview simulation outputs on demand."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Generate interview simulation for {job.company} - {job.title}",
                task_type="interview_simulation_generation",
                context={"job_id": job.id},
                start_step="Loading job and CV context",
            )
            base_cv = self._require_base_cv_content(session)
            tailored_cv = ""
            if job.tailored_cv_path and Path(job.tailored_cv_path).exists():
                tailored_cv = Path(job.tailored_cv_path).read_text(encoding="utf-8")
            elif self._latest_document(session, job.id, "cv") is not None:
                tailored_cv = self._latest_document(session, job.id, "cv").content  # type: ignore[union-attr]

            self.task_manager.update_task_progress(task_id, progress_percentage=25, current_step="Comparing CVs against the job...")
            simulation = self.interview_simulator.generate(job, base_cv, tailored_cv)
            markdown_content = self.interview_simulator.render_markdown(simulation)
            json_content = json.dumps(simulation, indent=2, ensure_ascii=True)

            self.task_manager.update_task_progress(task_id, progress_percentage=70, current_step="Saving interview outputs...")
            output_dir = self._interview_output_dir(job)
            markdown_doc = self._create_generated_document(
                session,
                job,
                "interview_simulation_md",
                markdown_content,
                self._safe_interview_file_name("interview_simulation", job, "md"),
                output_dir=output_dir,
            )
            json_doc = self._create_generated_document(
                session,
                job,
                "interview_simulation_json",
                json_content,
                self._safe_interview_file_name("interview_simulation", job, "json"),
                output_dir=output_dir,
            )

            raw_payload = dict(job.raw_payload or {})
            raw_payload["interview_simulation"] = simulation
            job.raw_payload = raw_payload
            job.documents_generated_at = datetime.utcnow()
            session.commit()
            self._history(session, job.id, "generated_interview_simulation", f"Generated interview simulation version {markdown_doc.version}")
            self.task_manager.complete_task(task_id, current_step="Completed")
            return {
                "simulation": simulation,
                "markdown_path": markdown_doc.file_path,
                "json_path": json_doc.file_path,
            }
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="Interview simulation failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            if owns_session:
                session.close()

    def export_interview_simulation_pdf(self, job_id: int, task_id: str | None = None) -> Path:
        """Export the latest interview simulation to PDF on demand."""
        simulation_data = self.get_interview_simulation(job_id)
        content = simulation_data["markdown_content"]
        if not content.strip():
            raise ValueError("No interview simulation exists for this job yet.")
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Export interview simulation PDF for {job.company} - {job.title}",
                task_type="pdf_export",
                context={"job_id": job.id, "interview_simulation": True},
                start_step="Preparing interview simulation PDF",
            )
            self.task_manager.update_task_progress(task_id, progress_percentage=60, current_step="Rendering PDF...")
            path = write_simple_pdf(
                markdown_to_plain_text(content),
                self._interview_output_dir(job) / self._safe_interview_file_name("interview_simulation", job, "pdf"),
                title=f"Interview Simulation - {job.company} - {job.title}",
            )
            self.task_manager.complete_task(task_id, current_step="Completed")
            return path
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="PDF export failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            session.close()

    def start_interactive_interview(self, job_id: int, question_index: int = 0) -> dict[str, Any]:
        """Return one interview question at a time for the selected job."""
        simulation_data = self.get_interview_simulation(job_id)
        simulation = simulation_data["simulation"]
        if not simulation:
            generated = self.generate_interview_simulation(job_id)
            simulation = generated["simulation"]
        question_payload = self.interview_simulator.interactive_question(simulation, question_index=question_index)
        return {
            "job_id": job_id,
            "company": simulation_data["company"],
            "title": simulation_data["title"],
            **question_payload,
        }

    def evaluate_interview_answer(self, job_id: int, question_id: str, answer: str) -> dict[str, Any]:
        """Evaluate an interview answer for a selected job."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            simulation_data = self.get_interview_simulation(job_id)
            simulation = simulation_data["simulation"]
            if not simulation:
                raise ValueError("Generate an interview simulation before evaluating answers.")
            base_cv = self._require_base_cv_content(session)
            tailored_cv = ""
            if job.tailored_cv_path and Path(job.tailored_cv_path).exists():
                tailored_cv = Path(job.tailored_cv_path).read_text(encoding="utf-8")
            evaluation = self.interview_simulator.evaluate_answer(
                job=job,
                simulation=simulation,
                question_id=question_id,
                answer=answer,
                base_cv=base_cv,
                tailored_cv=tailored_cv,
            )
            return evaluation
        finally:
            session.close()

    def _apply_filters(self, session: Session, job: Job, match_result: MatchResult) -> tuple[bool, str | None]:
        if job.is_duplicate:
            return False, "duplicate detected"
        if not self._location_compatible(job.full_location or job.location, job.city, job.state, job.country, job.work_mode):
            return False, "location incompatible"
        if match_result.match_score < self.config.minimum_match_score:
            return False, "minimum match score not met"
        if match_result.missing_critical_skills:
            return False, "missing critical skills"
        already_applied = session.scalar(select(Application).where(Application.job_id == job.id))
        if already_applied is not None:
            return False, "already applied"
        return True, None

    def search_jobs(self, task_id: str | None = None) -> SearchSummary:
        """Run collectors, analyze new jobs, and generate pending approvals."""
        task_id = self._ensure_task(
            task_id,
            task_name="Job search scheduler",
            task_type="job_search_scheduler",
            context={"source_count": len(self._collectors())},
            start_step="Preparing collectors",
        )
        session = self._session()
        should_close = session is not None
        try:
            summary = SearchSummary()
            collectors = self._collectors()
            total_collectors = max(1, len(collectors))
            self.task_manager.update_task_progress(task_id, progress_percentage=5, current_step="Searching jobs...")
            for collector_index, collector in enumerate(collectors, start=1):
                try:
                    collected_jobs = collector.search()
                    self._log(
                        session,
                        "info",
                        "collector_results",
                        f"{collector.source_name}: {len(collected_jobs)} jobs discovered",
                        task_id=task_id,
                    )
                except Exception as exc:
                    self._log(session, "error", "collector_failure", f"{collector.source_name}: {exc}", task_id=task_id)
                    continue

                summary.discovered += len(collected_jobs)
                self.task_manager.update_task_progress(
                    task_id,
                    progress_percentage=min(30, 5 + int((collector_index / total_collectors) * 25)),
                    current_step=f"Found {summary.discovered} jobs",
                )
                total_jobs = max(1, len(collected_jobs))
                for job_index, collected_job in enumerate(collected_jobs, start=1):
                    blacklisted, reason = self._is_blacklisted(collected_job)
                    if blacklisted:
                        self._log(session, "info", "job_rejected", f"{collected_job.company} {collected_job.title}", {"reason": reason}, task_id=task_id)
                        summary.skipped += 1
                        continue

                    existing = self._job_exists(session, collected_job)
                    if existing:
                        summary.skipped += 1
                        continue

                    job = self._persist_job(session, collected_job)
                    summary.created += 1
                    self.task_manager.update_task_progress(
                        task_id,
                        progress_percentage=min(85, 30 + int((job_index / total_jobs) * 50)),
                        current_step=f"Analyzing jobs... {job.company} / {job.title}",
                    )
                    match_result = self._analyze_job(session, job, parent_task_id=task_id)
                    summary.analyzed += 1
                    allowed, filter_reason = self._apply_filters(session, job, match_result)
                    if not allowed:
                        job.status = "skipped"
                        session.commit()
                        self._history(session, job.id, "skipped", filter_reason)
                        self._log(session, "info", "job_skipped", f"{job.company} {job.title}", {"reason": filter_reason}, task_id=task_id)
                        summary.skipped += 1
                        continue

                    job.status = "pending_approval"
                    session.commit()
                    self._history(session, job.id, "pending_approval", "Analysis completed; manual CV required")
                    self._notify(session, "pending_approval", self.notifier.notify_pending_approval(job), job.id, task_id=task_id)
                    summary.pending_approval += 1
            self.task_manager.update_task_progress(task_id, progress_percentage=95, current_step="Saving results...")
            self.task_manager.complete_task(task_id, current_step="Completed")
            return summary
        except Exception as exc:
            self.task_manager.fail_task(
                task_id,
                error_message=str(exc),
                current_step="Job search failed",
                traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
            )
            raise
        finally:
            if should_close:
                session.close()

    def _analyze_job(self, session: Session, job: Job, parent_task_id: str | None = None, task_id: str | None = None) -> MatchResult:
        context = {"job_id": job.id, "source": job.source, "parent_task_id": parent_task_id}
        task_id = self._ensure_task(
            task_id,
            task_name=f"Analyze job {job.company} - {job.title}",
            task_type="job_analysis",
            context=context,
            start_step="Loading base CV",
        )
        manual_cv = self._base_cv_content(session)
        try:
            self.task_manager.update_task_progress(task_id, progress_percentage=10, current_step="Extracting job content")
            extraction_result = self.content_extractor.extract(job.url, job.description)
            preview_description = (job.raw_payload or {}).get("preview_description", job.description)
            if extraction_result.full_text:
                job.description = extraction_result.full_text
            raw_payload = dict(job.raw_payload or {})
            raw_payload["content_extraction"] = {
                "source_method": extraction_result.source_method,
                "warnings": extraction_result.warnings,
                "is_complete": extraction_result.is_complete,
                "sections": extraction_result.sections,
                "preview_description": preview_description,
            }
            self._refresh_easy_apply_detection(
                job,
                description=job.description,
                metadata=raw_payload,
                page_text=extraction_result.full_text,
            )

            self.task_manager.update_task_progress(task_id, progress_percentage=35, current_step="Extracting skills...")
            self.task_manager.update_task_progress(task_id, progress_percentage=60, current_step="Calculating match score...")
            match_result = self.matcher.analyze_job(
                job,
                manual_cv,
                extracted_sections=extraction_result.sections,
                extraction_warnings=extraction_result.warnings,
            )

            raw_payload["analysis"] = {
                "required_skill_items": match_result.required_skill_items,
                "preferred_skill_items": match_result.preferred_skill_items,
                "qualification_items": match_result.qualification_items,
                "responsibilities": match_result.responsibilities,
                "missing_skill_items": match_result.missing_skill_items,
                "visa_analysis": match_result.visa_analysis,
                "analysis_warnings": match_result.analysis_warnings,
                "cv_generation_status": match_result.cv_generation_status,
                "user_profile_used": match_result.user_profile_used,
            }
            job.required_skills = match_result.required_skills
            job.preferred_skills = match_result.preferred_skills
            job.missing_skills = match_result.missing_skills
            job.base_match_score = match_result.match_score
            job.tailored_cv_match_score = job.tailored_cv_match_score
            job.match_score = match_result.match_score
            job.ai_explanation = match_result.ai_explanation
            job.recommended_action = match_result.recommended_action
            job.salary = job.salary or match_result.salary
            job.work_type = match_result.work_type
            job.experience_level = match_result.experience_level
            job.visa_requirements = match_result.visa_requirements
            job.raw_payload = raw_payload
            job.status = "analyzed"
            job.analyzed_at = datetime.utcnow()
            self.task_manager.update_task_progress(task_id, progress_percentage=90, current_step="Saving analysis results...")
            session.commit()
            self._history(session, job.id, "analyzed", f"Match score {match_result.match_score}")
            self._notify(session, "new_match", self.notifier.notify_new_matches(job), job.id, task_id=task_id)
            self.task_manager.complete_task(task_id, current_step="Completed")
            return match_result
        except Exception as exc:
            self.task_manager.fail_task(
                task_id,
                error_message=str(exc),
                current_step="Job analysis failed",
                traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
            )
            raise

    def analyze_jobs(self) -> int:
        """Analyze all jobs still in found status."""
        task_id = self._ensure_task(
            None,
            task_name="Analyze queued jobs",
            task_type="job_analysis_batch",
            start_step="Loading found jobs",
        )
        session = self._session()
        try:
            jobs = session.scalars(select(Job).where(Job.status == "found")).all()
            total_jobs = max(1, len(jobs))
            for index, job in enumerate(jobs, start=1):
                self.task_manager.update_task_progress(
                    task_id,
                    progress_percentage=min(95, int((index / total_jobs) * 100)),
                    current_step=f"Analyzing {job.company} / {job.title}",
                )
                self._analyze_job(session, job, parent_task_id=task_id)
            self.task_manager.complete_task(task_id, current_step="Completed")
            return len(jobs)
        except Exception as exc:
            self.task_manager.fail_task(
                task_id,
                error_message=str(exc),
                current_step="Batch analysis failed",
                traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
            )
            raise
        finally:
            session.close()

    def backfill_easy_apply(self, source: str = "adzuna", limit: int | None = None) -> dict[str, int | str]:
        """Re-check and update Easy Apply values for existing jobs."""
        task_id = self._ensure_task(
            None,
            task_name=f"Backfill Easy Apply ({source})",
            task_type="easy_apply_backfill",
            context={"source": source, "limit": limit},
            start_step="Loading jobs",
        )
        session = self._session()
        try:
            stmt = select(Job).where(Job.source == source).order_by(Job.found_at.desc())
            jobs = session.scalars(stmt).all()
            if limit is not None:
                jobs = jobs[:limit]
            total = max(1, len(jobs))
            updated = 0
            processed = 0
            for index, job in enumerate(jobs, start=1):
                processed += 1
                self.task_manager.update_task_progress(
                    task_id,
                    progress_percentage=min(90, int((index / total) * 100)),
                    current_step=f"Checking {job.company} / {job.title}",
                )
                previous = (job.easy_apply, job.easy_apply_type, job.easy_apply_detection_source)
                raw_payload = dict(job.raw_payload or {})
                preview_description = raw_payload.get("preview_description", job.description)
                page_text = ""
                if job.source == "adzuna" and self._easy_apply_rank(job.easy_apply) < 2:
                    extraction = self.content_extractor.extract(job.url, preview_description)
                    raw_payload["content_extraction"] = {
                        "source_method": extraction.source_method,
                        "warnings": extraction.warnings,
                        "is_complete": extraction.is_complete,
                        "sections": extraction.sections,
                        "preview_description": preview_description,
                    }
                    page_text = extraction.full_text
                    if extraction.full_text:
                        job.description = extraction.full_text
                self._refresh_easy_apply_detection(
                    job,
                    description=job.description,
                    metadata=raw_payload,
                    page_text=page_text,
                )
                job.raw_payload = raw_payload
                current = (job.easy_apply, job.easy_apply_type, job.easy_apply_detection_source)
                if current != previous:
                    updated += 1
                session.commit()

            self.task_manager.complete_task(task_id, current_step="Completed")
            return {
                "source": source,
                "processed": processed,
                "updated": updated,
            }
        except Exception as exc:
            self.task_manager.fail_task(
                task_id,
                error_message=str(exc),
                current_step="Backfill failed",
                traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
            )
            raise
        finally:
            session.close()

    def generate_documents(self, job_id: int, session: Session | None = None) -> dict[str, str]:
        """Backward-compatible manual generation entrypoint."""
        cv_payload = self.generate_tailored_cv(job_id, session=session)
        cover_payload = self.generate_cover_letter(job_id, session=session)
        return {
            "cv_path": cv_payload["path"],
            "cover_letter_path": cover_payload["path"],
        }

    def generate_tailored_cv(self, job_id: int, session: Session | None = None, task_id: str | None = None) -> dict[str, str | float]:
        """Generate a tailored CV only when explicitly requested."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Generate tailored CV for {job.company} - {job.title}",
                task_type="tailored_cv_generation",
                context={"job_id": job.id},
                start_step="Loading base CV",
            )
            base_cv = self._require_base_cv_content(session)
            self.task_manager.update_task_progress(task_id, progress_percentage=25, current_step="Generating tailored CV...")
            content = self.cv_adapter.generate(job, base_cv)
            self.task_manager.update_task_progress(task_id, progress_percentage=70, current_step="Saving tailored CV...")
            document = self._create_generated_document(session, job, "cv", content, "tailored_cv.md")
            job.tailored_cv_path = document.file_path
            job.documents_generated_at = datetime.utcnow()
            self.task_manager.update_task_progress(task_id, progress_percentage=90, current_step="Calculating tailored match score...")
            score = self._recalculate_tailored_match_for_job(session, job, tailored_cv_content=content, commit=False)
            session.commit()
            self._history(session, job.id, "generated_cv", f"Generated tailored CV version {document.version}")
            self.task_manager.complete_task(task_id, current_step="Completed")
            return {"path": document.file_path, "content": content, "tailored_cv_match_score": score}
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="Tailored CV generation failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            if owns_session:
                session.close()

    def generate_cover_letter(self, job_id: int, session: Session | None = None, task_id: str | None = None) -> dict[str, str]:
        """Generate a tailored cover letter only when explicitly requested."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Generate cover letter for {job.company} - {job.title}",
                task_type="cover_letter_generation",
                context={"job_id": job.id},
                start_step="Loading base CV",
            )
            base_cv = self._require_base_cv_content(session)
            self.task_manager.update_task_progress(task_id, progress_percentage=30, current_step="Generating cover letter...")
            content = self.cover_letter_generator.generate(job, base_cv)
            self.task_manager.update_task_progress(task_id, progress_percentage=80, current_step="Saving cover letter...")
            document = self._create_generated_document(session, job, "cover_letter", content, "cover_letter.md")
            job.cover_letter_path = document.file_path
            job.documents_generated_at = datetime.utcnow()
            session.commit()
            self._history(session, job.id, "generated_cover_letter", f"Generated cover letter version {document.version}")
            self.task_manager.complete_task(task_id, current_step="Completed")
            return {"path": document.file_path, "content": content}
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="Cover letter generation failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            if owns_session:
                session.close()

    def recalculate_match(self, job_id: int, session: Session | None = None, task_id: str | None = None) -> dict[str, float | None]:
        """Recalculate stored match scores for the job."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Recalculate match for {job.company} - {job.title}",
                task_type="match_score_calculation",
                context={"job_id": job.id},
                start_step="Loading base CV",
            )
            base_cv = self._base_cv_content(session)
            self.task_manager.update_task_progress(task_id, progress_percentage=35, current_step="Calculating base match score...")
            base_result = self.matcher.analyze_job(job, base_cv, extracted_sections=self._job_sections(job))
            job.base_match_score = base_result.match_score
            job.match_score = base_result.match_score
            tailored_score = job.tailored_cv_match_score
            if job.tailored_cv_path:
                tailored_path = Path(job.tailored_cv_path)
                if tailored_path.exists():
                    tailored_content = tailored_path.read_text(encoding="utf-8")
                    self.task_manager.update_task_progress(task_id, progress_percentage=75, current_step="Calculating tailored CV match score...")
                    tailored_score = self._recalculate_tailored_match_for_job(session, job, tailored_content, commit=False)
            session.commit()
            self._history(session, job.id, "recalculated_match", f"Base {job.base_match_score}, tailored {tailored_score}")
            self.task_manager.complete_task(task_id, current_step="Completed")
            return {
                "base_match_score": job.base_match_score,
                "tailored_cv_match_score": tailored_score,
            }
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="Match score calculation failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            if owns_session:
                session.close()

    def _recalculate_tailored_match_for_job(
        self,
        session: Session,
        job: Job,
        tailored_cv_content: str,
        commit: bool = True,
    ) -> float:
        result = self.matcher.analyze_job(job, tailored_cv_content, extracted_sections=self._job_sections(job))
        job.tailored_cv_match_score = result.match_score
        if commit:
            session.commit()
        return result.match_score

    def get_pending_approvals(self) -> list[Job]:
        """Return jobs waiting for explicit user approval."""
        session = self._session()
        try:
            return session.scalars(
                select(Job).where(Job.status == "pending_approval").order_by(func.coalesce(Job.base_match_score, Job.match_score).desc())
            ).all()
        finally:
            session.close()

    def approve_job(self, job_id: int) -> Job:
        """Mark a job as approved for later application automation."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            job.status = "approved"
            session.commit()
            self._history(session, job.id, "approved", "User approved job")
            return job
        finally:
            session.close()

    def reject_job(self, job_id: int) -> Job:
        """Reject a job from the approval queue."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            job.status = "rejected"
            session.commit()
            self._history(session, job.id, "rejected", "User rejected job")
            return job
        finally:
            session.close()

    def skip_job(self, job_id: int) -> Job:
        """Skip a job without approving or rejecting it permanently."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            job.status = "skipped"
            session.commit()
            self._history(session, job.id, "skipped", "User skipped job")
            return job
        finally:
            session.close()

    def apply_to_job(self, job_id: int, task_id: str | None = None) -> ApplicationAutomationResult:
        """Run Playwright automation after explicit approval."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            if job.status != "approved":
                raise ValueError("Job must be approved before application automation can run")
            task_id = self._ensure_task(
                task_id,
                task_name=f"Run application automation for {job.company} - {job.title}",
                task_type="playwright_automation",
                context={"job_id": job.id},
                start_step="Validating approval and documents",
            )

            manual_cv_path = self._base_cv_path()
            manual_cv_content = manual_cv_path.read_text(encoding="utf-8") if manual_cv_path.exists() else ""
            if (
                not manual_cv_content.strip()
                or "Replace this file with your source-of-truth CV in markdown." in manual_cv_content
            ):
                raise ValueError("A manual CV is required before applying")

            self.task_manager.update_task_progress(task_id, progress_percentage=35, current_step="Launching Playwright automation...")
            result = self.automation.apply(
                job=job,
                cv_path=Path(job.tailored_cv_path) if job.tailored_cv_path else manual_cv_path,
                cover_letter_path=Path(job.cover_letter_path) if job.cover_letter_path else None,
            )
            self.task_manager.update_task_progress(task_id, progress_percentage=85, current_step="Saving application result...")
            application = Application(
                job_id=job.id,
                status=result.status,
                submitted_at=datetime.utcnow() if result.status == "applied" else None,
                before_screenshot_path=str(result.before_screenshot_path) if result.before_screenshot_path else None,
                after_screenshot_path=str(result.after_screenshot_path) if result.after_screenshot_path else None,
                notes=result.message,
            )
            session.add(application)
            job.status = result.status
            session.commit()
            self._history(session, job.id, "apply_attempt", result.message)
            self._notify(session, "application_result", self.notifier.notify_application_result(job, result.message), job.id, task_id=task_id)
            if result.status == "failed":
                self.task_manager.fail_task(task_id, error_message=result.message, current_step="Automation failed")
            else:
                self.task_manager.complete_task(task_id, current_step="Completed")
            return result
        except Exception as exc:
            if task_id:
                self.task_manager.fail_task(
                    task_id,
                    error_message=str(exc),
                    current_step="Playwright automation failed",
                    traceback_summary="\n".join(traceback.format_exc().splitlines()[-8:]),
                )
            raise
        finally:
            session.close()

    def list_jobs(
        self,
        keyword: str | None = None,
        source: str | None = None,
        status: str | None = None,
        minimum_match_score: float | None = None,
    ) -> list[Job]:
        """Return filtered jobs for the API and dashboard."""
        session = self._session()
        try:
            stmt = select(Job).order_by(Job.found_at.desc())
            if keyword:
                like_pattern = f"%{keyword}%"
                stmt = stmt.where((Job.title.ilike(like_pattern)) | (Job.company.ilike(like_pattern)))
            if source:
                stmt = stmt.where(Job.source == source)
            if status:
                stmt = stmt.where(Job.status == status)
            if minimum_match_score is not None:
                stmt = stmt.where(func.coalesce(Job.base_match_score, Job.match_score) >= minimum_match_score)
            return session.scalars(stmt).all()
        finally:
            session.close()

    def get_job_details(self, job_id: int) -> dict[str, Any]:
        """Return a job and its latest generated documents."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            documents = session.scalars(
                select(GeneratedDocument).where(GeneratedDocument.job_id == job.id).order_by(GeneratedDocument.version.desc())
            ).all()
            latest_cv = next((doc.content for doc in documents if doc.doc_type == "cv"), "")
            latest_cover = next((doc.content for doc in documents if doc.doc_type == "cover_letter"), "")
            latest_cv_path = next((doc.file_path for doc in documents if doc.doc_type == "cv"), job.tailored_cv_path or "")
            latest_cover_path = next((doc.file_path for doc in documents if doc.doc_type == "cover_letter"), job.cover_letter_path or "")
            return {
                "job": job,
                "generated_cv": latest_cv,
                "generated_cover_letter": latest_cover,
                "generated_cv_path": latest_cv_path,
                "generated_cover_letter_path": latest_cover_path,
            }
        finally:
            session.close()

    def get_statistics(self) -> dict[str, Any]:
        """Compute dashboard statistics and chart datasets."""
        session = self._session()
        try:
            jobs = session.scalars(select(Job)).all()
            applications = session.scalars(select(Application)).all()

            total_jobs_found = len(jobs)
            new_jobs = sum(1 for job in jobs if job.found_at >= datetime.utcnow() - timedelta(days=1))
            scored_jobs = [job.base_match_score if job.base_match_score is not None else job.match_score for job in jobs if (job.base_match_score is not None or job.match_score is not None)]
            average_match_score = round(sum(scored_jobs) / len(scored_jobs), 2) if scored_jobs else 0.0
            applications_sent = sum(1 for app in applications if app.status == "applied")
            pending_approvals = sum(1 for job in jobs if job.status == "pending_approval")
            interviews = sum(1 for app in applications if app.status == "interview")
            rejected = sum(1 for job in jobs if job.status == "rejected")

            applications_by_status = dict(Counter(job.status for job in jobs))

            match_by_source: defaultdict[str, list[float]] = defaultdict(list)
            for job in jobs:
                score = job.base_match_score if job.base_match_score is not None else job.match_score
                if score is not None:
                    match_by_source[job.source].append(score)
            average_match_score_by_source = {
                source: round(sum(values) / len(values), 2) for source, values in match_by_source.items()
            }

            top_required_skills = dict(Counter(skill for job in jobs for skill in job.required_skills).most_common(10))
            applications_over_time = dict(Counter(app.submitted_at.date().isoformat() for app in applications if app.submitted_at))

            return {
                "total_jobs_found": total_jobs_found,
                "new_jobs": new_jobs,
                "average_match_score": average_match_score,
                "applications_sent": applications_sent,
                "pending_approvals": pending_approvals,
                "interviews": interviews,
                "rejected": rejected,
                "applications_by_status": applications_by_status,
                "average_match_score_by_source": average_match_score_by_source,
                "top_required_skills": top_required_skills,
                "applications_over_time": applications_over_time,
            }
        finally:
            session.close()

    def export_applications_csv(self) -> Path:
        """Export application history to CSV."""
        session = self._session()
        try:
            export_path = PROJECT_ROOT / "applications" / "applications_history.csv"
            export_path.parent.mkdir(parents=True, exist_ok=True)
            jobs_by_id = {job.id: job for job in session.scalars(select(Job)).all()}
            applications = session.scalars(select(Application)).all()
            with export_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Company", "Role", "Date", "Match", "Status", "Source"])
                for app in applications:
                    job = jobs_by_id.get(app.job_id)
                    if job is None:
                        continue
                    writer.writerow(
                        [
                            job.company,
                            job.title,
                            app.submitted_at.isoformat() if app.submitted_at else "",
                            job.base_match_score if job.base_match_score is not None else job.match_score or "",
                            app.status,
                            job.source,
                        ]
                    )
            return export_path
        finally:
            session.close()

    def search_now(self) -> dict[str, int]:
        """Manual trigger for an immediate search run."""
        summary = self.search_jobs()
        return asdict(summary)
