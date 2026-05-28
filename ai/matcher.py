"""Evidence-based job analysis and matching logic."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.models import Job


SKILL_CATALOG: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "JavaScript": ("javascript", "js"),
    "TypeScript": ("typescript", "ts"),
    "React": ("react", "reactjs", "react.js"),
    "Node.js": ("node.js", "nodejs"),
    "FastAPI": ("fastapi",),
    "Flask": ("flask",),
    "Django": ("django",),
    "SQL": ("sql",),
    "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",),
    "SQLite": ("sqlite",),
    "MongoDB": ("mongodb", "mongo db"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "AWS": ("aws", "amazon web services"),
    "Azure": ("azure", "microsoft azure"),
    "GCP": ("gcp", "google cloud", "google cloud platform"),
    "Git": ("git", "github", "gitlab", "bitbucket"),
    "CI/CD": ("ci/cd", "ci cd", "continuous integration", "continuous delivery", "continuous deployment"),
    "REST APIs": ("rest api", "rest apis", "restful api", "restful services", "api development"),
    "GraphQL": ("graphql",),
    "Linux": ("linux",),
    "Playwright": ("playwright",),
    "Selenium": ("selenium",),
    "Streamlit": ("streamlit",),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "PyTorch": ("pytorch",),
    "TensorFlow": ("tensorflow",),
    "Redis": ("redis",),
    "Terraform": ("terraform",),
    "Flutter": ("flutter",),
    "React Native": ("react native",),
    "Elasticsearch": ("elasticsearch",),
    "Logstash": ("logstash",),
    "Kibana": ("kibana",),
    "Odoo": ("odoo",),
    "Firebase": ("firebase",),
    "Microservices": ("microservices", "microservice"),
}

RESPONSIBILITY_VERBS = (
    "build",
    "develop",
    "design",
    "maintain",
    "lead",
    "collaborate",
    "implement",
    "optimize",
    "support",
    "deliver",
    "integrate",
    "monitor",
    "architect",
    "improve",
)

PREFERRED_MARKERS = ("nice to have", "preferred", "desirable", "bonus", "ideal")
REQUIRED_MARKERS = ("required", "must have", "requirements", "essential", "you will need", "skills required")
QUALIFICATION_MARKERS = ("qualification", "experience", "degree", "certification")
VISA_PATTERNS = (
    "visa",
    "sponsorship",
    "sponsor",
    "work rights",
    "unrestricted work rights",
    "australian citizen",
    "permanent resident",
    "must have rights to work in australia",
    "no sponsorship available",
)

SECTION_REQUIRED = {"requirements", "qualifications", "tech_stack", "key_skills"}
SECTION_PREFERRED = {"preferred"}
METADATA_REQUIRED_HINTS = ("require", "skill", "stack", "tech", "responsib", "qualif", "tag", "categor", "title")
METADATA_PREFERRED_HINTS = ("preferred", "bonus", "desirable", "nice_to_have")


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
    responsibilities: list[dict[str, Any]] = field(default_factory=list)
    required_skill_items: list[dict[str, Any]] = field(default_factory=list)
    preferred_skill_items: list[dict[str, Any]] = field(default_factory=list)
    qualification_items: list[dict[str, Any]] = field(default_factory=list)
    missing_skill_items: list[dict[str, Any]] = field(default_factory=list)
    visa_analysis: dict[str, Any] = field(default_factory=dict)
    analysis_warnings: list[str] = field(default_factory=list)
    cv_generation_status: str = "Manual only"
    user_profile_used: bool = False


class JobMatcher:
    """Analyze jobs against an optional manually provided CV/profile."""

    def analyze_job(
        self,
        job: Job,
        user_profile_text: str,
        extracted_sections: dict[str, list[str]] | None = None,
        extraction_warnings: list[str] | None = None,
    ) -> MatchResult:
        """Run evidence-based heuristics on the full job description and metadata."""
        sections = extracted_sections or {"general": [job.description]}
        warnings = list(extraction_warnings or [])
        metadata_items = self._extract_skills_from_metadata(job.raw_payload or {})
        section_required_items = self._extract_skills_from_sections(sections, target="required")
        section_preferred_items = self._extract_skills_from_sections(sections, target="preferred")
        title_items = self._extract_skills_from_text(job.title, category="required", source_name="title", confidence=0.9)
        description_items = self._extract_skills_from_text(job.description, category="required", source_name="description", confidence=0.68)

        required_items = self._merge_skill_items(
            section_required_items,
            [item for item in metadata_items if item["category"] != "preferred"],
            title_items,
            description_items,
        )
        preferred_items = self._merge_skill_items(
            section_preferred_items,
            [item for item in metadata_items if item["category"] == "preferred"],
        )

        qualification_items = self._extract_qualifications(sections)
        responsibility_items = self._extract_responsibilities(sections)
        full_text = self._build_full_text(job, sections)
        visa_analysis = self._extract_visa_analysis(full_text)

        if not required_items and not preferred_items:
            warnings.append("No required skills were detected after title, content, and metadata analysis.")
        if visa_analysis["status"] == "Not mentioned":
            warnings.append("No visa or work-rights language was found in the extracted content.")

        profile_text = self._normalize_profile(user_profile_text)
        profile_skills = self._extract_profile_skills(profile_text) if profile_text else set()
        required_names = self._unique_skill_names(required_items)
        preferred_names = self._unique_skill_names(preferred_items)

        missing_items = self._build_missing_skill_items(required_items, preferred_items, profile_skills) if profile_skills else []
        missing_skills = [item["skill"] for item in missing_items]

        score = self._compute_match_score(required_items, preferred_items, profile_skills, bool(profile_text))
        recommended_action = "Apply" if score >= 80 else "Maybe" if score >= 60 else "Skip"
        missing_critical_skills = bool(profile_skills) and len(missing_skills) > max(2, len(required_names) // 2 if required_names else 0)

        explanation_parts = [
            f"Required skills detected: {', '.join(required_names) if required_names else 'none'}",
            f"Preferred skills detected: {', '.join(preferred_names) if preferred_names else 'none'}",
        ]
        if profile_text:
            explanation_parts.append(
                f"Missing skills versus the provided manual CV/profile: {', '.join(missing_skills) if missing_skills else 'none'}"
            )
        else:
            explanation_parts.append("No manual CV/profile was provided, so missing-skills analysis is limited.")
        explanation_parts.append(f"Visa/work-rights analysis: {visa_analysis['status']}")

        return MatchResult(
            required_skills=required_names,
            preferred_skills=preferred_names,
            missing_skills=missing_skills,
            match_score=score,
            ai_explanation=" ".join(explanation_parts),
            recommended_action=recommended_action,
            salary=self._detect_salary(full_text) or job.salary,
            location=job.location,
            visa_requirements=visa_analysis["status"],
            work_type=self._detect_work_type(full_text),
            experience_level=self._detect_experience_level(full_text),
            missing_critical_skills=missing_critical_skills,
            responsibilities=responsibility_items,
            required_skill_items=required_items,
            preferred_skill_items=preferred_items,
            qualification_items=qualification_items,
            missing_skill_items=missing_items,
            visa_analysis=visa_analysis,
            analysis_warnings=warnings,
            cv_generation_status="Manual only",
            user_profile_used=bool(profile_text),
        )

    def _build_full_text(self, job: Job, sections: dict[str, list[str]]) -> str:
        blobs = [job.title, job.description]
        blobs.extend("\n".join(lines) for lines in sections.values())
        blobs.extend(self._flatten_metadata_strings(job.raw_payload or {}))
        return "\n".join(blob for blob in blobs if blob)

    def _extract_skills_from_sections(self, sections: dict[str, list[str]], target: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for section_name, lines in sections.items():
            for line in lines:
                line_target = self._line_target(section_name, line.lower())
                if target == "required" and line_target not in {"required", "general"}:
                    continue
                if target == "preferred" and line_target not in {"preferred", "general"}:
                    continue
                base_confidence = 0.9 if section_name in SECTION_REQUIRED else 0.78
                if target == "preferred":
                    base_confidence = 0.82 if section_name in SECTION_PREFERRED else 0.7
                items.extend(self._extract_skills_from_text(line, target, f"section:{section_name}", base_confidence))
        return self._dedupe_skill_items(items)

    def _extract_skills_from_metadata(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for key_path, text in self._iter_metadata_strings(payload):
            category = self._metadata_category(key_path, text)
            confidence = 0.92 if any(hint in key_path for hint in METADATA_REQUIRED_HINTS) else 0.76
            if category == "preferred":
                confidence = 0.8
            items.extend(self._extract_skills_from_text(text, category, f"metadata:{key_path}", confidence))
        return self._dedupe_skill_items(items)

    def _extract_skills_from_text(
        self,
        text: str,
        category: str,
        source_name: str,
        confidence: float,
    ) -> list[dict[str, Any]]:
        if not text:
            return []
        line_lower = text.lower()
        items: list[dict[str, Any]] = []
        for skill_name, aliases in SKILL_CATALOG.items():
            matched_alias = next((alias for alias in aliases if self._contains_alias(line_lower, alias)), None)
            if matched_alias is None:
                continue
            items.append(
                {
                    "skill": skill_name,
                    "category": category,
                    "evidence_text": text,
                    "confidence_score": min(confidence + (0.04 if line_lower.strip() == matched_alias else 0.0), 0.98),
                    "source": source_name,
                }
            )
        return items

    def _extract_qualifications(self, sections: dict[str, list[str]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for section_name, lines in sections.items():
            if section_name not in {"qualifications", "requirements"}:
                continue
            for line in lines:
                if not any(marker in line.lower() for marker in QUALIFICATION_MARKERS):
                    continue
                items.append(
                    {
                        "skill": line,
                        "category": "qualification",
                        "evidence_text": line,
                        "confidence_score": 0.78 if section_name == "qualifications" else 0.68,
                    }
                )
        return self._dedupe_generic_items(items)

    def _extract_responsibilities(self, sections: dict[str, list[str]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for section_name, lines in sections.items():
            for line in lines:
                if section_name == "responsibilities" or line.lower().startswith(RESPONSIBILITY_VERBS):
                    items.append(
                        {
                            "skill": line,
                            "category": "responsibility",
                            "evidence_text": line,
                            "confidence_score": 0.82 if section_name == "responsibilities" else 0.64,
                        }
                    )
        return self._dedupe_generic_items(items)[:12]

    def _extract_visa_analysis(self, full_text: str) -> dict[str, Any]:
        sentences = re.split(r"(?<=[.!?])\s+", full_text)
        evidence = [sentence.strip() for sentence in sentences if any(term in sentence.lower() for term in VISA_PATTERNS)]
        if not evidence:
            return {"status": "Not mentioned", "evidence": [], "confidence_score": 0.2}

        combined = " ".join(evidence).lower()
        if any(term in combined for term in ("sponsorship available", "visa sponsorship", "can sponsor")):
            status = "Sponsorship likely available"
            confidence = 0.86
        elif any(
            term in combined
            for term in (
                "no sponsorship",
                "unable to sponsor",
                "unrestricted work rights",
                "must have rights to work in australia",
                "australian citizen",
                "permanent resident",
            )
        ):
            if "sponsorship" in combined:
                status = "Sponsorship not available"
                confidence = 0.92
            else:
                status = "Work rights required"
                confidence = 0.88
        else:
            status = "Work rights required"
            confidence = 0.72

        return {"status": status, "evidence": evidence[:4], "confidence_score": confidence}

    def _build_missing_skill_items(
        self,
        required_items: list[dict[str, Any]],
        preferred_items: list[dict[str, Any]],
        profile_skills: set[str],
    ) -> list[dict[str, Any]]:
        missing: list[dict[str, Any]] = []
        for item in required_items + preferred_items:
            if item["skill"].lower() in profile_skills:
                continue
            missing.append(
                {
                    "skill": item["skill"],
                    "category": "missing",
                    "evidence_text": item["evidence_text"],
                    "confidence_score": item["confidence_score"],
                }
            )
        return self._dedupe_skill_items(missing)

    def _compute_match_score(
        self,
        required_items: list[dict[str, Any]],
        preferred_items: list[dict[str, Any]],
        profile_skills: set[str],
        profile_present: bool,
    ) -> float:
        if not profile_present:
            return 55.0 if required_items or preferred_items else 35.0

        required_names = {item["skill"].lower() for item in required_items}
        preferred_names = {item["skill"].lower() for item in preferred_items}
        required_hits = len(required_names & profile_skills)
        preferred_hits = len(preferred_names & profile_skills)

        required_score = 100.0 if not required_names else (required_hits / len(required_names)) * 100
        preferred_score = 100.0 if not preferred_names else (preferred_hits / len(preferred_names)) * 100
        return round((required_score * 0.8) + (preferred_score * 0.2), 2)

    def _extract_profile_skills(self, profile_text: str) -> set[str]:
        items = self._extract_skills_from_text(profile_text, "required", "profile", 0.9)
        return {item["skill"].lower() for item in items}

    def _normalize_profile(self, profile_text: str) -> str:
        placeholder = "# base cv replace this file with your source-of-truth cv in markdown."
        lowered = " ".join(profile_text.lower().split())
        if not profile_text.strip() or placeholder in lowered:
            return ""
        return profile_text

    def _unique_skill_names(self, items: list[dict[str, Any]]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            name = item["skill"]
            if name in seen:
                continue
            seen.add(name)
            ordered.append(name)
        return ordered

    def _line_target(self, section_name: str, line_lower: str) -> str:
        if section_name in SECTION_REQUIRED:
            return "required"
        if section_name in SECTION_PREFERRED:
            return "preferred"
        if any(marker in line_lower for marker in PREFERRED_MARKERS):
            return "preferred"
        if any(marker in line_lower for marker in REQUIRED_MARKERS):
            return "required"
        return "general"

    def _metadata_category(self, key_path: str, text: str) -> str:
        key_lower = key_path.lower()
        text_lower = text.lower()
        if any(marker in key_lower or marker in text_lower for marker in METADATA_PREFERRED_HINTS):
            return "preferred"
        if any(marker in key_lower or marker in text_lower for marker in REQUIRED_MARKERS):
            return "required"
        if any(hint in key_lower for hint in METADATA_REQUIRED_HINTS):
            return "required"
        return "required"

    def _merge_skill_items(self, *item_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        best_by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for group in item_groups:
            for item in group:
                key = (item["skill"], item["category"])
                existing = best_by_key.get(key)
                if existing is None or item["confidence_score"] > existing["confidence_score"]:
                    best_by_key[key] = item
        for group in item_groups:
            for item in group:
                key = (item["skill"], item["category"])
                best = best_by_key[key]
                if any(existing["skill"] == best["skill"] and existing["category"] == best["category"] for existing in merged):
                    continue
                merged.append(best)
        return merged

    def _contains_alias(self, text: str, alias: str) -> bool:
        pattern = re.escape(alias.lower()).replace(r"\ ", r"\s+")
        return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text) is not None

    def _iter_metadata_strings(self, value: Any, key_path: str = "") -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{key_path}.{key}" if key_path else str(key)
                items.extend(self._iter_metadata_strings(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                items.extend(self._iter_metadata_strings(child, f"{key_path}[{index}]"))
        elif isinstance(value, str):
            cleaned = " ".join(value.split())
            if cleaned:
                items.append((key_path.lower(), cleaned))
        return items

    def _flatten_metadata_strings(self, payload: dict[str, Any]) -> list[str]:
        return [text for _, text in self._iter_metadata_strings(payload)]

    def _dedupe_skill_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        ordered: list[dict[str, Any]] = []
        for item in items:
            key = (item["skill"], item["category"])
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    def _dedupe_generic_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        ordered: list[dict[str, Any]] = []
        for item in items:
            key = item["evidence_text"]
            if key in seen:
                continue
            seen.add(key)
            ordered.append(item)
        return ordered

    def _detect_work_type(self, text: str) -> str | None:
        text = text.lower()
        if "remote" in text:
            return "remote"
        if "hybrid" in text:
            return "hybrid"
        if "on-site" in text or "onsite" in text:
            return "onsite"
        return None

    def _detect_experience_level(self, text: str) -> str | None:
        text = text.lower()
        if "junior" in text:
            return "junior"
        if "mid" in text or "intermediate" in text:
            return "mid"
        if "senior" in text:
            return "senior"
        if "lead" in text:
            return "lead"
        return None

    def _detect_salary(self, text: str) -> str | None:
        match = re.search(r"(\$[\d,]+(?:\s*-\s*\$[\d,]+)?)", text)
        return match.group(1) if match else None
