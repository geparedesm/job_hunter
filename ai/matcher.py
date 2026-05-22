"""Job analysis and matching logic."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional until dependencies are installed
    OpenAI = None  # type: ignore[assignment]

from backend.models import Job
from config.loader import PROJECT_ROOT


KNOWN_SKILLS = [
    "python",
    "fastapi",
    "django",
    "flask",
    "sql",
    "postgresql",
    "sqlite",
    "aws",
    "docker",
    "kubernetes",
    "javascript",
    "typescript",
    "react",
    "node.js",
    "git",
    "ci/cd",
    "redis",
    "graphql",
    "rest",
    "playwright",
]


@dataclass(slots=True)
class MatchResult:
    """Structured job analysis output."""

    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    match_score: float = 0.0
    ai_explanation: str = ""
    recommended_action: str = "Skip"
    salary: str | None = None
    location: str | None = None
    visa_requirements: str | None = None
    work_type: str | None = None
    experience_level: str | None = None
    missing_critical_skills: bool = False


class JobMatcher:
    """Analyze jobs against the base CV using OpenAI with a heuristic fallback."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = OpenAI(api_key=self.api_key) if self.api_key and OpenAI is not None else None

    def analyze_job(self, job: Job, base_cv: str) -> MatchResult:
        """Analyze a job using OpenAI when available, otherwise use heuristics."""
        if self.client is not None:
            try:
                return self._analyze_with_openai(job, base_cv)
            except Exception:
                pass
        return self._analyze_heuristically(job, base_cv)

    def _analyze_with_openai(self, job: Job, base_cv: str) -> MatchResult:
        prompt_path = PROJECT_ROOT / "ai" / "prompts" / "match_job.md"
        system_prompt = prompt_path.read_text(encoding="utf-8")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Base CV:\n"
                        f"{base_cv}\n\n"
                        "Job:\n"
                        f"Company: {job.company}\nTitle: {job.title}\nLocation: {job.location}\n"
                        f"Description:\n{job.description}\n"
                    ),
                },
            ],
        )
        text = response.output_text
        payload = json.loads(text)
        return MatchResult(
            required_skills=payload.get("required_skills", []),
            preferred_skills=payload.get("preferred_skills", []),
            missing_skills=payload.get("missing_skills", []),
            match_score=float(payload.get("match_score", 0)),
            ai_explanation=payload.get("ai_explanation", ""),
            recommended_action=payload.get("recommended_action", "Skip"),
            salary=payload.get("salary"),
            location=payload.get("location", job.location),
            visa_requirements=payload.get("visa_requirements"),
            work_type=payload.get("work_type"),
            experience_level=payload.get("experience_level"),
            missing_critical_skills=bool(payload.get("missing_critical_skills", False)),
        )

    def _analyze_heuristically(self, job: Job, base_cv: str) -> MatchResult:
        description = f"{job.title}\n{job.description}".lower()
        cv_lower = base_cv.lower()

        required_skills = [skill for skill in KNOWN_SKILLS if skill in description]
        preferred_skills = [skill for skill in required_skills if skill in {"aws", "docker", "kubernetes", "react", "typescript"}]
        matched_skills = [skill for skill in required_skills if skill in cv_lower]
        missing_skills = [skill for skill in required_skills if skill not in cv_lower]

        skill_score = 100.0 if not required_skills else (len(matched_skills) / len(required_skills)) * 100
        seniority_penalty = 15 if "senior principal" in description or "principal engineer" in description else 0
        visa_penalty = 20 if "no sponsorship" in description and "visa" in cv_lower else 0
        score = max(0.0, min(100.0, round(skill_score - seniority_penalty - visa_penalty, 2)))

        if score >= 80:
            recommended_action = "Apply"
        elif score >= 60:
            recommended_action = "Maybe"
        else:
            recommended_action = "Skip"

        work_type = self._detect_work_type(description)
        experience_level = self._detect_experience_level(description)
        visa_requirements = self._detect_visa_requirements(description)
        salary = self._detect_salary(job.description) or job.salary
        missing_critical_skills = bool(required_skills) and len(missing_skills) > max(2, len(required_skills) // 2)

        explanation = (
            f"Good match reasons: matched {len(matched_skills)} of {len(required_skills) or 1} detected required skills. "
            f"Missing skills: {', '.join(missing_skills) if missing_skills else 'none identified'}. "
            f"Risk factors: {visa_requirements or 'no major visa requirement detected'}, {experience_level or 'unknown level'}."
        )

        return MatchResult(
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            missing_skills=missing_skills,
            match_score=score,
            ai_explanation=explanation,
            recommended_action=recommended_action,
            salary=salary,
            location=job.location,
            visa_requirements=visa_requirements,
            work_type=work_type,
            experience_level=experience_level,
            missing_critical_skills=missing_critical_skills,
        )

    def _detect_work_type(self, text: str) -> str | None:
        if "remote" in text:
            return "remote"
        if "hybrid" in text:
            return "hybrid"
        if "on-site" in text or "onsite" in text:
            return "onsite"
        return None

    def _detect_experience_level(self, text: str) -> str | None:
        if "junior" in text:
            return "junior"
        if "mid" in text or "intermediate" in text:
            return "mid"
        if "senior" in text:
            return "senior"
        if "lead" in text:
            return "lead"
        return None

    def _detect_visa_requirements(self, text: str) -> str | None:
        match = re.search(r"(visa[^.:\n]+|sponsorship[^.:\n]+)", text)
        return match.group(1).strip() if match else None

    def _detect_salary(self, text: str) -> str | None:
        match = re.search(r"(\$[\d,]+(?:\s*-\s*\$[\d,]+)?)", text)
        return match.group(1) if match else None
