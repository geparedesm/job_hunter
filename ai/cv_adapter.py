"""Tailored CV generation."""

from __future__ import annotations

import os

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional until dependencies are installed
    OpenAI = None  # type: ignore[assignment]

from backend.models import Job
from config.loader import PROJECT_ROOT


class CVAdapter:
    """Generate a tailored markdown CV for a given job."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = OpenAI(api_key=self.api_key) if self.api_key and OpenAI is not None else None

    def generate(self, job: Job, base_cv: str) -> str:
        """Return a tailored CV with a fallback deterministic format."""
        if self.client is not None:
            try:
                return self._generate_with_openai(job, base_cv)
            except Exception:
                pass
        return self._generate_fallback(job, base_cv)

    def _generate_with_openai(self, job: Job, base_cv: str) -> str:
        prompt = (PROJECT_ROOT / "ai" / "prompts" / "adapt_cv.md").read_text(encoding="utf-8")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Target company: {job.company}\n"
                        f"Target role: {job.title}\n"
                        f"Required skills: {', '.join(job.required_skills)}\n"
                        f"Missing skills: {', '.join(job.missing_skills)}\n\n"
                        f"Base CV:\n{base_cv}"
                    ),
                },
            ],
        )
        return response.output_text

    def _generate_fallback(self, job: Job, base_cv: str) -> str:
        matched_focus = ", ".join(job.required_skills[:8]) if job.required_skills else "Python, backend engineering, APIs"
        return (
            f"# Tailored CV for {job.company} - {job.title}\n\n"
            "## Role Alignment Summary\n\n"
            f"- Target role: {job.title}\n"
            f"- Company: {job.company}\n"
            f"- Highlighted skills: {matched_focus}\n"
            f"- Missing skills to address honestly: {', '.join(job.missing_skills) if job.missing_skills else 'None identified'}\n\n"
            "## Base CV\n\n"
            f"{base_cv}\n"
        )
