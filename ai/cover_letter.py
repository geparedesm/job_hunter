"""Cover letter generation."""

from __future__ import annotations

import os

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional until dependencies are installed
    OpenAI = None  # type: ignore[assignment]

from backend.models import Job
from config.loader import PROJECT_ROOT


class CoverLetterGenerator:
    """Generate a tailored markdown cover letter."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = OpenAI(api_key=self.api_key) if self.api_key and OpenAI is not None else None

    def generate(self, job: Job, base_cv: str) -> str:
        """Return a tailored cover letter with a deterministic fallback."""
        if self.client is not None:
            try:
                return self._generate_with_openai(job, base_cv)
            except Exception:
                pass
        return self._generate_fallback(job)

    def _generate_with_openai(self, job: Job, base_cv: str) -> str:
        prompt = (PROJECT_ROOT / "ai" / "prompts" / "cover_letter.md").read_text(encoding="utf-8")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Company: {job.company}\n"
                        f"Role: {job.title}\n"
                        f"Description: {job.description}\n"
                        f"Required skills: {', '.join(job.required_skills)}\n\n"
                        f"Base CV:\n{base_cv}"
                    ),
                },
            ],
        )
        return response.output_text

    def _generate_fallback(self, job: Job) -> str:
        return (
            f"# Cover Letter for {job.company}\n\n"
            f"Dear Hiring Team,\n\n"
            f"I am excited to apply for the {job.title} role at {job.company}. "
            f"My background aligns well with the role's focus on {', '.join(job.required_skills[:5]) if job.required_skills else 'software engineering'}.\n\n"
            "I bring practical experience building maintainable backend systems, collaborating across product and engineering, "
            "and adapting quickly to new tools and domains. I would welcome the chance to contribute with a thoughtful, hands-on approach.\n\n"
            "Thank you for your consideration.\n"
        )
