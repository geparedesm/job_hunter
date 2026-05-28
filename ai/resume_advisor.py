"""Resume parsing, hybrid skill extraction, and profession suggestion helpers."""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency
    OpenAI = None  # type: ignore[assignment]

from config.loader import PROJECT_ROOT


SKILL_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "Programming Languages": {
        "Python": ("python",),
        "JavaScript": ("javascript", "js"),
        "TypeScript": ("typescript", "ts"),
        "Java": ("java",),
        "C#": ("c#", "c sharp"),
        "C++": ("c++", "cpp"),
        "PHP": ("php",),
        "Ruby": ("ruby",),
        "Go": ("go", "golang"),
        "Swift": ("swift",),
        "Kotlin": ("kotlin",),
    },
    "Frontend": {
        "React": ("react", "reactjs", "react.js"),
        "Next.js": ("next.js", "nextjs"),
        "Vue": ("vue", "vue.js", "vuejs"),
        "Angular": ("angular",),
        "HTML": ("html", "html5"),
        "CSS": ("css", "css3"),
        "Tailwind CSS": ("tailwind css", "tailwind"),
        "Bootstrap": ("bootstrap",),
    },
    "Mobile": {
        "React Native": ("react native", "rn"),
        "Expo": ("expo", "expo go"),
        "Flutter": ("flutter",),
        "Android": ("android",),
        "iOS": ("ios",),
        "SwiftUI": ("swiftui",),
    },
    "Backend": {
        "Node.js": ("node.js", "nodejs", "node"),
        "Express.js": ("express.js", "expressjs", "express"),
        "FastAPI": ("fastapi",),
        "Flask": ("flask",),
        "Django": ("django",),
        "Laravel": ("laravel",),
        "REST APIs": ("rest apis", "rest api", "rest", "restful api"),
        "GraphQL": ("graphql",),
        "Microservices": ("microservices", "microservice"),
    },
    "Databases": {
        "SQL": ("sql",),
        "PostgreSQL": ("postgresql", "postgres", "postgre"),
        "MySQL": ("mysql",),
        "SQLite": ("sqlite",),
        "MongoDB": ("mongodb", "mongo db"),
        "Firebase": ("firebase",),
        "Supabase": ("supabase",),
        "Redis": ("redis",),
    },
    "Cloud": {
        "AWS": ("aws", "amazon web services"),
        "Azure": ("azure",),
        "GCP": ("gcp", "google cloud", "google cloud platform"),
    },
    "DevOps": {
        "Docker": ("docker",),
        "Kubernetes": ("kubernetes", "k8s"),
        "GitHub Actions": ("github actions",),
        "CI/CD": ("ci/cd", "ci cd", "cicd", "continuous integration", "continuous delivery"),
        "Linux": ("linux",),
        "Nginx": ("nginx",),
    },
    "Testing": {
        "Jest": ("jest",),
        "Playwright": ("playwright",),
        "Selenium": ("selenium",),
        "Pytest": ("pytest",),
        "Unit Testing": ("unit testing", "unit tests"),
        "E2E Testing": ("e2e testing", "end to end testing", "end-to-end testing"),
    },
    "AI / Data": {
        "Pandas": ("pandas",),
        "NumPy": ("numpy",),
        "PyTorch": ("pytorch",),
        "TensorFlow": ("tensorflow",),
        "Machine Learning": ("machine learning", "ml"),
        "Data Analysis": ("data analysis",),
    },
    "Tools": {
        "Git": ("git",),
        "GitHub": ("github",),
        "GitLab": ("gitlab",),
        "Jira": ("jira",),
        "Figma": ("figma",),
        "Postman": ("postman",),
        "VS Code": ("vs code", "vscode", "visual studio code"),
    },
    "Methodologies": {
        "Agile": ("agile",),
        "Scrum": ("scrum",),
        "Kanban": ("kanban",),
        "SOLID": ("solid",),
        "Clean Architecture": ("clean architecture",),
    },
    "Soft Skills": {
        "Communication": ("communication", "communicate"),
        "Leadership": ("leadership", "led", "mentored", "managed"),
        "Problem Solving": ("problem solving", "problem-solving", "troubleshooting"),
        "Teamwork": ("teamwork", "collaboration", "collaborate"),
        "Time Management": ("time management", "prioritization", "prioritisation"),
        "Adaptability": ("adaptability", "adaptable"),
        "Customer Service": ("customer service", "customer-facing"),
        "Stakeholder Communication": ("stakeholder communication", "stakeholder management", "stakeholder"),
    },
    "Languages Spoken": {
        "English": ("english",),
        "Spanish": ("spanish",),
        "Portuguese": ("portuguese",),
        "French": ("french",),
        "German": ("german",),
    },
}

ALL_SKILLS = {skill: aliases for category in SKILL_GROUPS.values() for skill, aliases in category.items()}
SKILL_TO_CATEGORY = {skill: category for category, items in SKILL_GROUPS.items() for skill in items}
SECTION_HEADINGS = {
    "summary": ("summary", "profile", "professional summary", "about"),
    "experience": ("experience", "work experience", "employment", "career"),
    "projects": ("projects", "personal projects", "key projects"),
    "skills": ("skills", "technical skills", "technologies", "tools", "tech stack"),
    "education": ("education", "studies", "academic background"),
    "certifications": ("certifications", "certificates", "licenses"),
    "languages": ("languages", "spoken languages"),
}
SENIORITY_MARKERS = [
    ("Principal", ("principal", "staff", "architect")),
    ("Lead", ("lead", "tech lead", "engineering manager")),
    ("Senior", ("senior", "sr.", "sr ", "5+ years", "6+ years", "7+ years", "8+ years")),
    ("Mid-level", ("mid-level", "mid level", "3+ years", "4+ years")),
    ("Junior", ("junior", "graduate", "entry level", "1+ years", "2+ years")),
]
INDUSTRY_HINTS = {
    "FinTech": ("bank", "payments", "fintech", "financial"),
    "HealthTech": ("health", "medical", "patient"),
    "E-commerce": ("e-commerce", "ecommerce", "retail"),
    "SaaS": ("saas", "b2b", "product platform"),
    "AI / Data": ("machine learning", "artificial intelligence", "data platform"),
    "Consulting": ("consulting", "client delivery", "consultant"),
}
PROFESSION_RULES: list[dict[str, Any]] = [
    {"title": "React Native Developer", "keywords": ["React Native Developer", "Junior React Native Developer"], "match_any": {"React Native", "Expo"}, "missing": {"TypeScript"}},
    {"title": "Mobile Developer", "keywords": ["Mobile Developer"], "match_any": {"React Native", "Flutter", "Android", "iOS", "Expo"}, "missing": {"TypeScript"}},
    {"title": "Mobile App Developer", "keywords": ["Mobile Developer", "Mobile App Developer"], "match_any": {"React Native", "Flutter", "Android", "iOS", "Expo"}, "missing": {"Swift", "Kotlin"}},
    {"title": "Expo Developer", "keywords": ["Expo Developer"], "match_any": {"Expo"}, "missing": {"React Native"}},
    {"title": "Frontend Developer", "keywords": ["Frontend Developer", "React Developer"], "match_any": {"React", "Next.js", "Vue", "Angular", "HTML", "CSS"}, "missing": {"TypeScript"}},
    {"title": "Full Stack Developer", "keywords": ["Full Stack Developer", "Software Engineer"], "match_all": {"React", "Node.js"}, "missing": {"Docker", "PostgreSQL"}},
    {"title": "Backend Developer", "keywords": ["Backend Developer", "API Developer"], "match_any": {"Node.js", "FastAPI", "Flask", "Django", "Express.js"}, "missing": {"REST APIs", "Docker"}},
    {"title": "TypeScript Developer", "keywords": ["TypeScript Developer"], "match_any": {"TypeScript"}, "missing": {"Node.js", "React"}},
    {"title": "Node.js Developer", "keywords": ["Node.js Developer"], "match_any": {"Node.js", "Express.js"}, "missing": {"TypeScript"}},
    {"title": "Software Engineer", "keywords": ["Software Engineer", "Graduate Software Engineer"], "match_any": {"Python", "JavaScript", "TypeScript", "Java", "Go"}, "missing": {"Git", "SQL"}},
    {"title": "Web Developer", "keywords": ["Web Developer"], "match_any": {"HTML", "CSS", "JavaScript", "React"}, "missing": {"REST APIs"}},
]


class ResumeAdvisor:
    """Analyze resumes locally with an optional OpenAI refinement layer."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = OpenAI(api_key=self.api_key) if self.api_key and OpenAI is not None else None

    def extract_text(self, filename: str, content: bytes) -> str:
        """Extract plaintext from a resume file while preserving structure."""
        suffix = Path(filename).suffix.lower()
        if suffix in {".txt", ".md", ".markdown"}:
            return self._normalize_whitespace(content.decode("utf-8", errors="ignore"))
        if suffix == ".docx":
            return self._extract_docx_text(content)
        if suffix == ".pdf":
            return self._extract_pdf_text(content)
        return self._normalize_whitespace(content.decode("utf-8", errors="ignore"))

    def analyze(self, text: str, *, filename: str = "") -> dict[str, Any]:
        """Return structured resume analysis, grouped skills, and profession scoring."""
        text = text.strip()
        if not text:
            raise ValueError("The uploaded resume could not be parsed into text.")
        fallback = self._analyze_with_fallback(text=text, filename=filename)
        if self.client is not None:
            try:
                payload = self._analyze_with_openai(text=text, filename=filename)
                payload["analysis_source"] = "openai"
                return self._normalize_payload(payload, fallback=fallback)
            except Exception:
                pass
        fallback["analysis_source"] = "fallback"
        return fallback

    def _analyze_with_openai(self, *, text: str, filename: str) -> dict[str, Any]:
        prompt = (PROJECT_ROOT / "ai" / "prompts" / "resume_advisor.md").read_text(encoding="utf-8")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Filename: {filename or 'resume'}\n\nResume text:\n{text}"},
            ],
        )
        payload = json.loads(response.output_text)
        if not isinstance(payload, dict):
            raise ValueError("Resume advisor response was not a JSON object.")
        return payload

    def _analyze_with_fallback(self, *, text: str, filename: str) -> dict[str, Any]:
        sections = self._split_sections(text)
        normalized_text = self._normalize_for_matching(text)
        extracted_skill_hits = self._extract_skill_hits(text=text, sections=sections, normalized_text=normalized_text)
        skill_groups = self._group_skills(extracted_skill_hits)
        all_skills = self._flatten_skill_groups(skill_groups)
        job_titles = self._extract_job_titles(text, sections)
        seniority_level = self._detect_seniority(text, job_titles)
        industries = self._detect_industries(normalized_text)
        education = self._extract_section_lines(sections, "education")
        certifications = self._extract_section_lines(sections, "certifications")
        work_experience = self._extract_experience_lines(text, sections)
        profession_matches = self._score_professions(skill_groups, job_titles, seniority_level, industries)
        suggested_professions = [item["role_title"] for item in profession_matches]
        suggested_technologies = [skill for skill in all_skills if SKILL_TO_CATEGORY.get(skill) not in {"Soft Skills", "Languages Spoken"}][:16]
        recommended_keywords = self._build_recommended_keywords(
            profession_matches,
            seniority_level,
            suggested_technologies=suggested_technologies,
        )
        suggested_seniority_levels = self._suggest_seniority_levels(seniority_level)
        summary = self._build_professional_summary(sections, job_titles, all_skills, seniority_level)
        ai_skill_count = len(set(suggested_technologies))

        return {
            "professional_summary": summary,
            "technical_skills": [skill for skill in all_skills if SKILL_TO_CATEGORY.get(skill) not in {"Soft Skills", "Languages Spoken"}],
            "soft_skills": skill_groups.get("Soft Skills", []),
            "frameworks": [skill for skill in all_skills if skill in {"React", "Next.js", "Vue", "Angular", "React Native", "Expo", "Flutter", "FastAPI", "Flask", "Django", "Express.js", "Laravel"}],
            "programming_languages": skill_groups.get("Programming Languages", []),
            "tools_platforms": [
                skill
                for category in ("Cloud", "DevOps", "Testing", "Tools", "Databases")
                for skill in skill_groups.get(category, [])
            ],
            "work_experience": work_experience,
            "industries": industries,
            "seniority_level": seniority_level,
            "job_titles": job_titles,
            "certifications": certifications,
            "education": education,
            "suggested_professions": suggested_professions,
            "profession_matches": profession_matches,
            "recommended_keywords": recommended_keywords,
            "suggested_technologies": suggested_technologies,
            "suggested_seniority_levels": suggested_seniority_levels,
            "skill_groups": skill_groups,
            "detected_sections": {name: lines[:20] for name, lines in sections.items() if lines},
            "resume_insights": {
                "top_strengths": self._top_strengths(skill_groups, seniority_level),
                "most_marketable_skills": suggested_technologies[:10],
                "missing_high_demand_skills": [skill for skill in ("TypeScript", "React", "Node.js", "Docker", "AWS", "CI/CD", "REST APIs", "PostgreSQL") if skill not in all_skills][:8],
                "ats_optimization_score": self._estimate_ats_score(text, all_skills, job_titles, sections),
                "suggested_career_focus": suggested_professions[0] if suggested_professions else "Software Engineer",
                "suggested_industries": industries or ["Software", "SaaS"],
            },
            "debug": {
                "extracted_raw_text_length": len(text),
                "detected_sections": sorted([name for name, values in sections.items() if values]),
                "extraction_method": "hybrid_resume_parser",
                "parsed_skill_count": len(extracted_skill_hits),
                "ai_skill_count": ai_skill_count,
                "final_normalized_skill_count": len(all_skills),
            },
            "assumptions": self._build_assumptions(filename, industries, seniority_level, all_skills),
        }

    def _normalize_payload(self, payload: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(fallback)
        normalized["professional_summary"] = str(payload.get("professional_summary") or fallback["professional_summary"]).strip()
        normalized["seniority_level"] = str(payload.get("seniority_level") or fallback["seniority_level"]).strip() or "Unknown"
        normalized["industries"] = self._clean_list(payload.get("industries") or fallback["industries"])
        normalized["job_titles"] = self._clean_list(payload.get("job_titles") or fallback["job_titles"])
        normalized["certifications"] = self._clean_list(payload.get("certifications") or fallback["certifications"])
        normalized["education"] = self._clean_list(payload.get("education") or fallback["education"])
        normalized["work_experience"] = self._clean_list(payload.get("work_experience") or fallback["work_experience"])
        normalized["suggested_seniority_levels"] = self._clean_list(payload.get("suggested_seniority_levels") or fallback["suggested_seniority_levels"])
        normalized["assumptions"] = self._clean_list(payload.get("assumptions") or fallback["assumptions"])

        incoming_skills = self._clean_list(payload.get("technical_skills") or [])
        incoming_soft = self._clean_list(payload.get("soft_skills") or [])
        combined_skill_groups = {category: list(values) for category, values in fallback["skill_groups"].items()}
        self._merge_skills_into_groups(combined_skill_groups, incoming_skills + incoming_soft)
        normalized["skill_groups"] = {category: self._clean_list(values) for category, values in combined_skill_groups.items() if values}
        normalized["technical_skills"] = [skill for skill in self._flatten_skill_groups(normalized["skill_groups"]) if SKILL_TO_CATEGORY.get(skill) not in {"Soft Skills", "Languages Spoken"}]
        normalized["soft_skills"] = normalized["skill_groups"].get("Soft Skills", [])
        normalized["programming_languages"] = normalized["skill_groups"].get("Programming Languages", [])
        normalized["frameworks"] = [skill for skill in normalized["technical_skills"] if skill in fallback["frameworks"] or SKILL_TO_CATEGORY.get(skill) in {"Frontend", "Mobile", "Backend"}]
        normalized["tools_platforms"] = [
            skill
            for category in ("Cloud", "DevOps", "Testing", "Tools", "Databases")
            for skill in normalized["skill_groups"].get(category, [])
        ]

        incoming_profession_titles = self._clean_list(payload.get("suggested_professions") or [])
        normalized["profession_matches"] = self._merge_profession_matches(
            fallback["profession_matches"],
            incoming_profession_titles,
            normalized["technical_skills"],
        )
        normalized["suggested_professions"] = [item["role_title"] for item in normalized["profession_matches"]]
        normalized["recommended_keywords"] = self._clean_list(
            payload.get("recommended_keywords")
            or self._build_recommended_keywords(
                normalized["profession_matches"],
                normalized["seniority_level"],
                suggested_technologies=normalized["technical_skills"],
            )
        )
        normalized["suggested_technologies"] = self._clean_list(payload.get("suggested_technologies") or normalized["technical_skills"][:16])
        normalized["detected_sections"] = fallback["detected_sections"]
        insights = payload.get("resume_insights") if isinstance(payload.get("resume_insights"), dict) else {}
        normalized["resume_insights"] = {
            "top_strengths": self._clean_list(insights.get("top_strengths") or fallback["resume_insights"]["top_strengths"]),
            "most_marketable_skills": self._clean_list(insights.get("most_marketable_skills") or fallback["resume_insights"]["most_marketable_skills"]),
            "missing_high_demand_skills": self._clean_list(insights.get("missing_high_demand_skills") or fallback["resume_insights"]["missing_high_demand_skills"]),
            "ats_optimization_score": int(insights.get("ats_optimization_score") or fallback["resume_insights"]["ats_optimization_score"]),
            "suggested_career_focus": str(insights.get("suggested_career_focus") or fallback["resume_insights"]["suggested_career_focus"]).strip(),
            "suggested_industries": self._clean_list(insights.get("suggested_industries") or fallback["resume_insights"]["suggested_industries"]),
        }
        normalized["debug"] = fallback["debug"]
        return normalized

    def _extract_docx_text(self, content: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                xml_content = archive.read("word/document.xml")
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("The DOCX file could not be parsed.") from exc
        root = ElementTree.fromstring(xml_content)
        paragraphs: list[str] = []
        for paragraph in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            texts = [node.text or "" for node in paragraph.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
        return self._normalize_whitespace("\n".join(paragraphs))

    def _extract_pdf_text(self, content: bytes) -> str:
        extracted_pages: list[str] = []
        for module_name in ("pypdf", "PyPDF2"):
            try:
                module = __import__(module_name)
                reader = module.PdfReader(io.BytesIO(content))
                extracted_pages = [(page.extract_text() or "").strip() for page in reader.pages]
                break
            except Exception:
                extracted_pages = []
        if any(extracted_pages):
            return self._normalize_whitespace("\n\n".join(page for page in extracted_pages if page))
        matches = re.findall(rb"\(([^()]*)\)", content)
        decoded = [self._decode_pdf_literal(match) for match in matches]
        extracted = "\n".join(item for item in decoded if item and len(item.strip()) > 2)
        if extracted.strip():
            return self._normalize_whitespace(extracted)
        raise ValueError("The PDF file could not be parsed into text.")

    def _decode_pdf_literal(self, value: bytes) -> str:
        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            text = value.decode("latin-1", errors="ignore")
        text = text.replace("\\n", "\n").replace("\\r", "\n").replace("\\t", " ")
        return re.sub(r"\\([()\\\\])", r"\1", text).strip()

    def _normalize_whitespace(self, text: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.replace("\r", "\n").split("\n")]
        output: list[str] = []
        blank_pending = False
        for line in lines:
            if not line:
                if output and not blank_pending:
                    output.append("")
                blank_pending = True
                continue
            output.append(line)
            blank_pending = False
        return "\n".join(output).strip()

    def _normalize_for_matching(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.lower())

    def _split_sections(self, text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = defaultdict(list)
        current = "general"
        for raw_line in text.splitlines():
            line = raw_line.strip().strip("-*")
            if not line:
                continue
            heading = self._match_heading(line)
            if heading:
                current = heading
                continue
            sections[current].append(line)
        return dict(sections)

    def _match_heading(self, line: str) -> str | None:
        normalized = re.sub(r"[:#]+$", "", line.strip().lower())
        for name, aliases in SECTION_HEADINGS.items():
            if normalized in aliases:
                return name
        return None

    def _extract_skill_hits(self, *, text: str, sections: dict[str, list[str]], normalized_text: str) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        lines_with_source: list[tuple[str, str]] = [("general", line) for line in text.splitlines() if line.strip()]
        for section_name, lines in sections.items():
            lines_with_source.extend((section_name, line) for line in lines)
        for section_name, line in lines_with_source:
            lowered = line.lower()
            for skill_name, aliases in ALL_SKILLS.items():
                alias = next((item for item in aliases if self._contains_alias(lowered, item)), None)
                if alias is None:
                    continue
                hits.append(
                    {
                        "skill": skill_name,
                        "category": SKILL_TO_CATEGORY[skill_name],
                        "source_section": section_name,
                        "evidence_text": line,
                    }
                )
        return self._dedupe_skill_hits(hits, normalized_text)

    def _dedupe_skill_hits(self, hits: list[dict[str, Any]], normalized_text: str) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for item in hits:
            skill = self._normalize_skill_name(item["skill"])
            if skill not in best:
                best[skill] = {**item, "skill": skill}
                continue
            current_priority = self._section_priority(item["source_section"])
            best_priority = self._section_priority(best[skill]["source_section"])
            if current_priority > best_priority:
                best[skill] = {**item, "skill": skill}
        if "Expo" in normalized_text and "Expo" not in best:
            best["Expo"] = {"skill": "Expo", "category": "Mobile", "source_section": "general", "evidence_text": "Expo"}
        return list(best.values())

    def _section_priority(self, section_name: str) -> int:
        return {
            "skills": 5,
            "projects": 4,
            "experience": 4,
            "summary": 3,
            "general": 2,
            "education": 1,
            "certifications": 1,
            "languages": 1,
        }.get(section_name, 0)

    def _group_skills(self, hits: list[dict[str, Any]]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for hit in hits:
            grouped[hit["category"]].append(hit["skill"])
        return {category: self._clean_list(values) for category, values in grouped.items()}

    def _flatten_skill_groups(self, skill_groups: dict[str, list[str]]) -> list[str]:
        ordered: list[str] = []
        for category in SKILL_GROUPS:
            ordered.extend(skill_groups.get(category, []))
        return self._clean_list(ordered)

    def _extract_job_titles(self, text: str, sections: dict[str, list[str]]) -> list[str]:
        title_hints = ("engineer", "developer", "architect", "manager", "lead", "consultant", "specialist")
        lines = sections.get("experience", []) + sections.get("summary", []) + [line.strip() for line in text.splitlines() if line.strip()]
        titles = [line for line in lines if any(hint in line.lower() for hint in title_hints) and len(line.split()) <= 12]
        return self._clean_list(titles[:12])

    def _extract_experience_lines(self, text: str, sections: dict[str, list[str]]) -> list[str]:
        lines = sections.get("experience", []) or [line.strip() for line in text.splitlines() if line.strip()]
        matches = [
            line
            for line in lines
            if re.search(r"\b(20\d{2}|19\d{2}|present|\d+\+?\s+years?)\b", line.lower()) or any(
                marker in line.lower() for marker in ("engineer", "developer", "lead", "manager", "architect")
            )
        ]
        return self._clean_list(matches[:12])

    def _extract_section_lines(self, sections: dict[str, list[str]], section_name: str) -> list[str]:
        return self._clean_list(sections.get(section_name, [])[:12])

    def _detect_industries(self, normalized_text: str) -> list[str]:
        return [industry for industry, markers in INDUSTRY_HINTS.items() if any(marker in normalized_text for marker in markers)]

    def _detect_seniority(self, text: str, job_titles: list[str]) -> str:
        lowered = f"{text}\n" + "\n".join(job_titles)
        lowered = lowered.lower()
        for seniority, markers in SENIORITY_MARKERS:
            if any(marker in lowered for marker in markers):
                return seniority
        return "Unknown"

    def _score_professions(
        self,
        skill_groups: dict[str, list[str]],
        job_titles: list[str],
        seniority_level: str,
        industries: list[str],
    ) -> list[dict[str, Any]]:
        all_skills = set(self._flatten_skill_groups(skill_groups))
        title_text = " ".join(job_titles).lower()
        matches: list[dict[str, Any]] = []
        for rule in PROFESSION_RULES:
            required_any = set(rule.get("match_any", set()))
            required_all = set(rule.get("match_all", set()))
            matched = sorted((required_any | required_all) & all_skills)
            if required_any and not (required_any & all_skills):
                continue
            if required_all and not required_all.issubset(all_skills):
                continue
            title_bonus = 8 if any(token in title_text for token in rule["title"].lower().split()) else 0
            seniority_bonus = 6 if seniority_level in {"Junior", "Graduate"} and any("Junior" in key or "Graduate" in key for key in rule["keywords"]) else 0
            confidence = min(96, 42 + len(matched) * 12 + title_bonus + seniority_bonus)
            missing = sorted(skill for skill in rule.get("missing", set()) if skill not in all_skills)[:4]
            reason = f"Fits because the resume shows {', '.join(matched[:4]) or 'relevant engineering skills'}"
            if industries:
                reason += f" and aligns with {industries[0]}-adjacent experience."
            else:
                reason += "."
            matches.append(
                {
                    "role_title": rule["title"],
                    "confidence_score": confidence,
                    "matched_skills": matched[:8],
                    "missing_skills": missing,
                    "reason": reason,
                    "suggested_search_keyword": rule["keywords"][0],
                }
            )
        if not matches and all_skills:
            matches.append(
                {
                    "role_title": "Software Engineer",
                    "confidence_score": 58,
                    "matched_skills": sorted(list(all_skills))[:8],
                    "missing_skills": [],
                    "reason": "Fits because the resume shows transferable software engineering skills.",
                    "suggested_search_keyword": "Software Engineer",
                }
            )
        return sorted(matches, key=lambda item: item["confidence_score"], reverse=True)

    def _build_recommended_keywords(
        self,
        profession_matches: list[dict[str, Any]],
        seniority_level: str,
        *,
        suggested_technologies: list[str],
    ) -> list[str]:
        keywords: list[str] = []
        for match in profession_matches:
            keywords.append(match["suggested_search_keyword"])
            if seniority_level in {"Junior", "Graduate"}:
                keywords.append(f"{seniority_level} {match['role_title']}")
        keywords.extend(suggested_technologies[:10])
        return self._clean_list(keywords)

    def _suggest_seniority_levels(self, detected: str) -> list[str]:
        if detected == "Unknown":
            return ["Junior", "Mid-level", "Senior"]
        nearby = [detected]
        if detected == "Junior":
            nearby.append("Graduate")
        if detected == "Mid-level":
            nearby.extend(["Junior", "Senior"])
        if detected == "Senior":
            nearby.extend(["Lead", "Principal"])
        return self._clean_list(nearby)

    def _build_professional_summary(self, sections: dict[str, list[str]], job_titles: list[str], skills: list[str], seniority_level: str) -> str:
        if sections.get("summary"):
            return " ".join(sections["summary"][:3])[:420]
        if job_titles:
            return f"{seniority_level if seniority_level != 'Unknown' else 'Experienced'} {job_titles[0]} profile with strengths in {', '.join(skills[:6]) or 'software engineering'}."
        return "Software engineering profile detected from the uploaded resume."

    def _top_strengths(self, skill_groups: dict[str, list[str]], seniority_level: str) -> list[str]:
        strengths = (
            skill_groups.get("Programming Languages", [])[:3]
            + skill_groups.get("Frontend", [])[:2]
            + skill_groups.get("Backend", [])[:2]
            + skill_groups.get("Soft Skills", [])[:2]
        )
        if seniority_level != "Unknown":
            strengths.append(f"{seniority_level}-level positioning")
        return self._clean_list(strengths)

    def _estimate_ats_score(self, text: str, skills: list[str], job_titles: list[str], sections: dict[str, list[str]]) -> int:
        score = 45
        if len(skills) >= 10:
            score += 18
        if job_titles:
            score += 8
        if sections.get("experience"):
            score += 8
        if sections.get("skills"):
            score += 10
        if sections.get("education"):
            score += 5
        if re.search(r"\b\d+%|\b\d+\+?\s+years?\b", text.lower()):
            score += 8
        return min(score, 97)

    def _build_assumptions(self, filename: str, industries: list[str], seniority_level: str, all_skills: list[str]) -> list[str]:
        assumptions: list[str] = []
        if filename:
            assumptions.append(f"Filename context used: {filename}")
        if not industries:
            assumptions.append("Suggested industries were inferred from the skill mix because the resume did not state a clear domain.")
        if seniority_level == "Unknown":
            assumptions.append("Seniority level was inferred conservatively because clear years-of-experience markers were limited.")
        if not all_skills:
            assumptions.append("Keyword suggestions rely on partial text parsing because no structured skill section was found.")
        return assumptions

    def _merge_skills_into_groups(self, skill_groups: dict[str, list[str]], skills: list[str]) -> None:
        for skill in skills:
            normalized = self._normalize_skill_name(skill)
            category = SKILL_TO_CATEGORY.get(normalized)
            if category is None:
                continue
            skill_groups.setdefault(category, []).append(normalized)

    def _merge_profession_matches(
        self,
        fallback_matches: list[dict[str, Any]],
        incoming_titles: list[str],
        skills: list[str],
    ) -> list[dict[str, Any]]:
        merged = {item["role_title"].lower(): item for item in fallback_matches}
        for title in incoming_titles:
            key = title.lower()
            if key in merged:
                continue
            merged[key] = {
                "role_title": title,
                "confidence_score": 60,
                "matched_skills": skills[:6],
                "missing_skills": [],
                "reason": "Added from AI suggestions and supported by the detected skill set.",
                "suggested_search_keyword": title,
            }
        return sorted(merged.values(), key=lambda item: item["confidence_score"], reverse=True)

    def _normalize_skill_name(self, skill: str) -> str:
        aliases = {
            "JS": "JavaScript",
            "TS": "TypeScript",
            "RN": "React Native",
            "Node": "Node.js",
            "Postgres": "PostgreSQL",
            "CI CD": "CI/CD",
            "REST": "REST APIs",
            "Expo Go": "Expo",
            "Tailwind": "Tailwind CSS",
        }
        cleaned = skill.strip()
        return aliases.get(cleaned, cleaned)

    def _contains_alias(self, text: str, alias: str) -> bool:
        escaped = re.escape(alias.lower())
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None

    def _clean_list(self, values: list[Any]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = str(value).strip()
            if not item:
                continue
            normalized = self._normalize_skill_name(item)
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(normalized)
        return cleaned
