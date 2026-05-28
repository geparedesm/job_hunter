"""Clawbot integration surface for the job hunter skill."""

from __future__ import annotations

from backend.services import JobHunterService


class JobHunterSkill:
    """Thin wrapper exposing the approved Clawbot API."""

    def __init__(self) -> None:
        self.service = JobHunterService()

    def run_search(self) -> dict[str, int]:
        """Run a search cycle."""
        return self.service.search_now()

    def analyze_jobs(self) -> int:
        """Analyze queued jobs."""
        return self.service.analyze_jobs()

    def get_pending_approvals(self) -> list[dict[str, object]]:
        """Return jobs waiting for approval."""
        return [
            {
                "id": job.id,
                "company": job.company,
                "title": job.title,
                "match_score": job.match_score,
                "status": job.status,
            }
            for job in self.service.get_pending_approvals()
        ]

    def approve_job(self, job_id: int) -> dict[str, object]:
        """Approve a job for application automation."""
        job = self.service.approve_job(job_id)
        return {"id": job.id, "status": job.status}

    def reject_job(self, job_id: int) -> dict[str, object]:
        """Reject a job."""
        job = self.service.reject_job(job_id)
        return {"id": job.id, "status": job.status}

    def generate_documents(self, job_id: int) -> dict[str, str]:
        """Document generation is manual-only in this version."""
        raise ValueError("CV and cover letter generation are manual-only. Upload or edit them yourself.")

    def apply_to_job(self, job_id: int) -> dict[str, object]:
        """Run gated application automation."""
        result = self.service.apply_to_job(job_id)
        return {"status": result.status, "message": result.message}

    def get_statistics(self) -> dict[str, object]:
        """Return dashboard statistics."""
        return self.service.get_statistics()

    def search_now(self) -> dict[str, int]:
        """Alias for the manual search trigger."""
        return self.service.search_now()
