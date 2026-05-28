"""Core orchestration service for the personal AI job hunter."""

from __future__ import annotations

import csv
import logging
import os
import re
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
from ai.matcher import JobMatcher, MatchResult
from automation.apply import ApplicationAutomation, ApplicationAutomationResult
from backend.database import SessionLocal, init_db
from backend.models import Application, ApplicationHistory, CVVersion, GeneratedDocument, Job, JobLog, Notification
from backend.pdf_utils import markdown_to_plain_text, write_simple_pdf
from collectors.adzuna import AdzunaCollector
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
        self.notifier = ConsoleNotifier()
        self.automation = ApplicationAutomation()
        self.content_extractor = JobContentExtractor()

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

    def _log(self, session: Session, level: str, event_type: str, message: str, metadata: dict[str, Any] | None = None) -> None:
        LOGGER.log(getattr(logging, level.upper(), logging.INFO), "%s | %s", event_type, message)
        session.add(JobLog(level=level.upper(), event_type=event_type, message=message, metadata_json=metadata))
        session.commit()

    def _history(self, session: Session, job_id: int, action: str, details: str | None = None) -> None:
        session.add(ApplicationHistory(job_id=job_id, action=action, details=details))
        session.commit()

    def _notify(self, session: Session, event_type: str, message: str, job_id: int | None = None) -> None:
        self.notifier.send(message)
        session.add(Notification(job_id=job_id, channel="console", event_type=event_type, message=message))
        session.commit()

    def _job_exists(self, session: Session, collected_job: CollectedJob) -> Job | None:
        if collected_job.external_id:
            stmt = select(Job).where(
                (Job.url == collected_job.url)
                | ((Job.external_id == collected_job.external_id) & (Job.source == collected_job.source))
            )
        else:
            stmt = select(Job).where(Job.url == collected_job.url)
        return session.scalar(stmt)

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

    def _location_compatible(self, location: str | None) -> bool:
        if not self.config.locations:
            return True
        if not location:
            return False
        location_lower = location.lower()
        return any(config_location.lower() in location_lower for config_location in self.config.locations)

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

    def _safe_cv_pdf_name(self, label: str, job: Job | None = None) -> str:
        if job is None:
            return f"{_slugify(label)}.pdf"
        return f"job_{job.id}_{_slugify(job.company)}_{_slugify(job.title)}_{_slugify(label)}.pdf"

    def _next_document_version(self, session: Session, job_id: int, doc_type: str) -> int:
        versions = session.scalars(
            select(GeneratedDocument.version).where(
                GeneratedDocument.job_id == job_id,
                GeneratedDocument.doc_type == doc_type,
            )
        ).all()
        return (max(versions) if versions else 0) + 1

    def _create_generated_document(self, session: Session, job: Job, doc_type: str, content: str, file_name: str) -> GeneratedDocument:
        output_path = self._job_output_dir(job) / file_name
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

    def export_base_cv_pdf(self, job_id: int | None = None) -> Path:
        """Export the base CV to PDF only when explicitly requested."""
        session = self._session()
        try:
            content = self._base_cv_content(session)
            job = session.get(Job, job_id) if job_id is not None else None
            filename = self._safe_cv_pdf_name("base_cv", job)
            return write_simple_pdf(
                markdown_to_plain_text(content),
                self._pdf_output_dir() / filename,
                title="Base CV",
            )
        finally:
            session.close()

    def export_job_cv_pdf(self, job_id: int) -> Path:
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
            return write_simple_pdf(
                markdown_to_plain_text(content),
                self._pdf_output_dir() / self._safe_cv_pdf_name("tailored_cv", job),
                title=f"Tailored CV - {job.company} - {job.title}",
            )
        finally:
            session.close()

    def _apply_filters(self, session: Session, job: Job, match_result: MatchResult) -> tuple[bool, str | None]:
        if job.is_duplicate:
            return False, "duplicate detected"
        if not self._location_compatible(job.location):
            return False, "location incompatible"
        if match_result.match_score < self.config.minimum_match_score:
            return False, "minimum match score not met"
        if match_result.missing_critical_skills:
            return False, "missing critical skills"
        already_applied = session.scalar(select(Application).where(Application.job_id == job.id))
        if already_applied is not None:
            return False, "already applied"
        return True, None

    def search_jobs(self) -> SearchSummary:
        """Run collectors, analyze new jobs, and generate pending approvals."""
        session = self._session()
        should_close = session is not None
        try:
            summary = SearchSummary()
            for collector in self._collectors():
                try:
                    collected_jobs = collector.search()
                    self._log(
                        session,
                        "info",
                        "collector_results",
                        f"{collector.source_name}: {len(collected_jobs)} jobs discovered",
                    )
                except Exception as exc:
                    self._log(session, "error", "collector_failure", f"{collector.source_name}: {exc}")
                    continue

                summary.discovered += len(collected_jobs)
                for collected_job in collected_jobs:
                    blacklisted, reason = self._is_blacklisted(collected_job)
                    if blacklisted:
                        self._log(session, "info", "job_rejected", f"{collected_job.company} {collected_job.title}", {"reason": reason})
                        summary.skipped += 1
                        continue

                    existing = self._job_exists(session, collected_job)
                    if existing:
                        summary.skipped += 1
                        continue

                    job = self._persist_job(session, collected_job)
                    summary.created += 1
                    match_result = self._analyze_job(session, job)
                    summary.analyzed += 1
                    allowed, filter_reason = self._apply_filters(session, job, match_result)
                    if not allowed:
                        job.status = "skipped"
                        session.commit()
                        self._history(session, job.id, "skipped", filter_reason)
                        self._log(session, "info", "job_skipped", f"{job.company} {job.title}", {"reason": filter_reason})
                        summary.skipped += 1
                        continue

                    job.status = "pending_approval"
                    session.commit()
                    self._history(session, job.id, "pending_approval", "Analysis completed; manual CV required")
                    self._notify(session, "pending_approval", self.notifier.notify_pending_approval(job), job.id)
                    summary.pending_approval += 1
            return summary
        finally:
            if should_close:
                session.close()

    def _analyze_job(self, session: Session, job: Job) -> MatchResult:
        manual_cv = self._base_cv_content(session)
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
        session.commit()
        self._history(session, job.id, "analyzed", f"Match score {match_result.match_score}")
        self._notify(session, "new_match", self.notifier.notify_new_matches(job), job.id)
        return match_result

    def analyze_jobs(self) -> int:
        """Analyze all jobs still in found status."""
        session = self._session()
        try:
            jobs = session.scalars(select(Job).where(Job.status == "found")).all()
            for job in jobs:
                self._analyze_job(session, job)
            return len(jobs)
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

    def generate_tailored_cv(self, job_id: int, session: Session | None = None) -> dict[str, str | float]:
        """Generate a tailored CV only when explicitly requested."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            base_cv = self._require_base_cv_content(session)
            content = self.cv_adapter.generate(job, base_cv)
            document = self._create_generated_document(session, job, "cv", content, "tailored_cv.md")
            job.tailored_cv_path = document.file_path
            job.documents_generated_at = datetime.utcnow()
            score = self._recalculate_tailored_match_for_job(session, job, tailored_cv_content=content, commit=False)
            session.commit()
            self._history(session, job.id, "generated_cv", f"Generated tailored CV version {document.version}")
            return {"path": document.file_path, "content": content, "tailored_cv_match_score": score}
        finally:
            if owns_session:
                session.close()

    def generate_cover_letter(self, job_id: int, session: Session | None = None) -> dict[str, str]:
        """Generate a tailored cover letter only when explicitly requested."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            base_cv = self._require_base_cv_content(session)
            content = self.cover_letter_generator.generate(job, base_cv)
            document = self._create_generated_document(session, job, "cover_letter", content, "cover_letter.md")
            job.cover_letter_path = document.file_path
            job.documents_generated_at = datetime.utcnow()
            session.commit()
            self._history(session, job.id, "generated_cover_letter", f"Generated cover letter version {document.version}")
            return {"path": document.file_path, "content": content}
        finally:
            if owns_session:
                session.close()

    def recalculate_match(self, job_id: int, session: Session | None = None) -> dict[str, float | None]:
        """Recalculate stored match scores for the job."""
        owns_session = session is None
        session = self._session(session)
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            base_cv = self._base_cv_content(session)
            base_result = self.matcher.analyze_job(job, base_cv, extracted_sections=self._job_sections(job))
            job.base_match_score = base_result.match_score
            job.match_score = base_result.match_score
            tailored_score = job.tailored_cv_match_score
            if job.tailored_cv_path:
                tailored_path = Path(job.tailored_cv_path)
                if tailored_path.exists():
                    tailored_content = tailored_path.read_text(encoding="utf-8")
                    tailored_score = self._recalculate_tailored_match_for_job(session, job, tailored_content, commit=False)
            session.commit()
            self._history(session, job.id, "recalculated_match", f"Base {job.base_match_score}, tailored {tailored_score}")
            return {
                "base_match_score": job.base_match_score,
                "tailored_cv_match_score": tailored_score,
            }
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

    def apply_to_job(self, job_id: int) -> ApplicationAutomationResult:
        """Run Playwright automation after explicit approval."""
        session = self._session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Job {job_id} not found")
            if job.status != "approved":
                raise ValueError("Job must be approved before application automation can run")

            manual_cv_path = self._base_cv_path()
            manual_cv_content = manual_cv_path.read_text(encoding="utf-8") if manual_cv_path.exists() else ""
            if (
                not manual_cv_content.strip()
                or "Replace this file with your source-of-truth CV in markdown." in manual_cv_content
            ):
                raise ValueError("A manual CV is required before applying")

            result = self.automation.apply(
                job=job,
                cv_path=Path(job.tailored_cv_path) if job.tailored_cv_path else manual_cv_path,
                cover_letter_path=Path(job.cover_letter_path) if job.cover_letter_path else None,
            )
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
            self._notify(session, "application_result", self.notifier.notify_application_result(job, result.message), job.id)
            return result
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
