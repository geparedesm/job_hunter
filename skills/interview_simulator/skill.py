"""Clawbot integration surface for the interview simulator skill."""

from __future__ import annotations

from backend.services import JobHunterService


class InterviewSimulatorSkill:
    """Thin wrapper exposing interview simulator actions."""

    def __init__(self) -> None:
        self.service = JobHunterService()

    def generate_interview_simulation(self, job_id: int) -> dict[str, object]:
        """Generate a recruiter-style interview simulator pack."""
        return self.service.generate_interview_simulation(job_id)

    def get_interview_simulation(self, job_id: int) -> dict[str, object]:
        """Return the latest interview simulation for a job."""
        return self.service.get_interview_simulation(job_id)

    def start_interactive_interview(self, job_id: int, question_index: int = 0) -> dict[str, object]:
        """Load one interview question at a time."""
        return self.service.start_interactive_interview(job_id, question_index=question_index)

    def evaluate_interview_answer(self, job_id: int, question_id: str, answer: str) -> dict[str, object]:
        """Evaluate a candidate answer for one interview question."""
        return self.service.evaluate_interview_answer(job_id, question_id, answer)

    def export_interview_pdf(self, job_id: int) -> dict[str, object]:
        """Export the stored interview simulation to PDF."""
        path = self.service.export_interview_simulation_pdf(job_id)
        return {"path": str(path)}
