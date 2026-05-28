"""Interview simulation generation and answer evaluation."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, UTC
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional until dependencies are installed
    OpenAI = None  # type: ignore[assignment]

from ai.matcher import SKILL_CATALOG
from backend.models import Job
from config.loader import PROJECT_ROOT


QUESTION_SECTIONS = (
    "HR / Recruiter Screening",
    "Soft Skills Questions",
    "Technical Questions",
    "System Design Questions",
    "Scenario-Based Questions",
    "Behavioral Questions",
    "Problem-Solving Questions",
    "Team Collaboration Questions",
    "Culture Fit Questions",
    "Salary/availability/visa questions",
)


class InterviewSimulator:
    """Generate realistic interview simulations with deterministic fallbacks."""

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.client = OpenAI(api_key=self.api_key) if self.api_key and OpenAI is not None else None

    def generate(self, job: Job, base_cv: str, tailored_cv: str = "") -> dict[str, Any]:
        """Return a structured interview simulation."""
        if self.client is not None:
            try:
                return self._generate_with_openai(job, base_cv, tailored_cv)
            except Exception:
                pass
        return self._generate_fallback(job, base_cv, tailored_cv)

    def evaluate_answer(
        self,
        *,
        job: Job,
        simulation: dict[str, Any],
        question_id: str,
        answer: str,
        base_cv: str,
        tailored_cv: str = "",
    ) -> dict[str, Any]:
        """Evaluate a candidate answer against the generated simulation."""
        question = next((item for item in self._flatten_questions(simulation) if item["id"] == question_id), None)
        if question is None:
            raise ValueError(f"Question {question_id} was not found in this simulation.")
        if self.client is not None:
            try:
                return self._evaluate_with_openai(job, simulation, question, answer, base_cv, tailored_cv)
            except Exception:
                pass
        return self._evaluate_fallback(question, answer)

    def interactive_question(self, simulation: dict[str, Any], question_index: int = 0) -> dict[str, Any]:
        """Return one interview question at a time for interactive mode."""
        questions = self._flatten_questions(simulation)
        if not questions:
            raise ValueError("No interview questions are available.")
        if question_index < 0 or question_index >= len(questions):
            raise ValueError("Question index is out of range.")
        question = questions[question_index]
        return {
            "question_index": question_index,
            "total_questions": len(questions),
            "question": question,
            "remaining_questions": len(questions) - question_index - 1,
        }

    def render_markdown(self, simulation: dict[str, Any]) -> str:
        """Render the simulation as markdown for storage and review."""
        readiness = simulation["readiness_scores"]
        analysis = simulation["resume_analysis"]
        insights = simulation["recruiter_insights"]
        company_context = simulation["company_context"]
        assumptions = simulation.get("assumptions", [])

        lines = [
            f"# Interview Simulator - {simulation['company']} - {simulation['title']}",
            "",
            "## Recruiter Mode",
            "",
            simulation["system_role"],
            "",
            "## Interview Readiness",
            "",
            f"- Overall interview readiness score: {readiness['overall_interview_readiness_score']}",
            f"- Technical fit score: {readiness['technical_fit_score']}",
            f"- Soft skills fit score: {readiness['soft_skills_fit_score']}",
            f"- Hiring confidence score: {readiness['hiring_confidence_score']}",
            "",
            "## Company Context",
            "",
            f"- Company: {simulation['company']}",
            f"- Industry: {company_context['industry']}",
            f"- Interview style: {company_context['interview_style']}",
            f"- Work mode: {company_context['work_mode']}",
            f"- Seniority: {company_context['seniority_level']}",
            f"- Tech stack focus: {', '.join(company_context['tech_stack']) or 'General software engineering'}",
            "",
            "## Resume vs Job Analysis",
            "",
            f"- Strong matches: {', '.join(analysis['strong_matches']) or 'No strong matches detected yet'}",
            f"- Weak areas: {', '.join(analysis['weak_areas']) or 'No major weak areas detected'}",
            f"- Missing skills: {', '.join(analysis['missing_skills']) or 'No explicit missing skills detected'}",
            f"- Seniority fit: {analysis['seniority_fit']}",
            f"- ATS compatibility: {analysis['ats_compatibility']}",
            f"- Potential recruiter concerns: {', '.join(analysis['potential_recruiter_concerns']) or 'No major concerns'}",
            "",
            "## Recruiter Insights",
            "",
            f"- What concerns me as a recruiter: {', '.join(insights['what_concerns_me_as_a_recruiter']) or 'No major blocker.'}",
            f"- What makes you stand out: {', '.join(insights['what_makes_you_stand_out']) or 'Needs stronger differentiation.'}",
            f"- What you should improve before the interview: {', '.join(insights['what_you_should_improve_before_the_interview']) or 'No urgent gaps.'}",
            f"- Most likely rejection reasons: {', '.join(insights['most_likely_rejection_reasons']) or 'Not enough data to predict.'}",
            f"- Most likely hiring reasons: {', '.join(insights['most_likely_hiring_reasons']) or 'Not enough data to predict.'}",
            "",
        ]
        if assumptions:
            lines.extend(["## Inferred Assumptions", ""])
            lines.extend(f"- {item}" for item in assumptions)
            lines.append("")

        for section in simulation["sections"]:
            lines.extend([f"## {section['section_name']}", ""])
            for question in section["questions"]:
                lines.extend(
                    [
                        f"### {question['question']}",
                        "",
                        f"- Difficulty: {question['difficulty_level']}",
                        f"- Candidate confidence score: {question['candidate_confidence_score']}",
                        f"- What recruiters are evaluating: {question['what_recruiters_are_evaluating']}",
                        "",
                        "**Strong example answer**",
                        "",
                        question["strong_example_answer"],
                        "",
                        "**Why the answer is good**",
                        "",
                        question["why_the_answer_is_good"],
                        "",
                        "**Common bad answer**",
                        "",
                        question["common_bad_answer"],
                        "",
                    ]
                )
        return "\n".join(lines).strip() + "\n"

    def _generate_with_openai(self, job: Job, base_cv: str, tailored_cv: str) -> dict[str, Any]:
        prompt = (PROJECT_ROOT / "ai" / "prompts" / "interview_simulator.md").read_text(encoding="utf-8")
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"Company: {job.company}\n"
                        f"Role: {job.title}\n"
                        f"Job description: {job.description}\n"
                        f"Required skills: {', '.join(job.required_skills)}\n"
                        f"Preferred skills: {', '.join(job.preferred_skills)}\n"
                        f"Missing skills: {', '.join(job.missing_skills)}\n"
                        f"Work mode: {job.is_remote or job.work_mode or 'Unknown'}\n"
                        f"Base CV:\n{base_cv}\n\n"
                        f"Tailored CV:\n{tailored_cv or 'Not available'}"
                    ),
                },
            ],
        )
        payload = json.loads(response.output_text)
        if not isinstance(payload, dict):
            raise ValueError("Interview simulator response was not a JSON object.")
        return payload

    def _evaluate_with_openai(
        self,
        job: Job,
        simulation: dict[str, Any],
        question: dict[str, Any],
        answer: str,
        base_cv: str,
        tailored_cv: str,
    ) -> dict[str, Any]:
        prompt = (
            "Act as a senior recruiter and hiring manager from this exact company. "
            "Evaluate the candidate realistically. "
            "Return strict JSON with keys: score, feedback, improved_answer, confidence_analysis, communication_analysis."
        )
        response = self.client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "company": job.company,
                            "role": job.title,
                            "question": question,
                            "candidate_answer": answer,
                            "simulation_summary": simulation["resume_analysis"],
                            "base_cv": base_cv,
                            "tailored_cv": tailored_cv or "",
                        }
                    ),
                },
            ],
        )
        payload = json.loads(response.output_text)
        payload["question_id"] = question["id"]
        return payload

    def _generate_fallback(self, job: Job, base_cv: str, tailored_cv: str) -> dict[str, Any]:
        company_context = self._build_company_context(job)
        analysis = self._build_resume_analysis(job, base_cv, tailored_cv)
        readiness = self._build_readiness_scores(job, analysis)
        sections = self._build_sections(job, analysis, company_context)
        return {
            "company": job.company,
            "title": job.title,
            "generated_at": datetime.now(UTC).isoformat(),
            "system_role": "Acting as a senior recruiter, technical interviewer, and hiring manager from this exact company using only available job data and clearly marked inferences.",
            "company_context": company_context,
            "readiness_scores": readiness,
            "resume_analysis": analysis,
            "recruiter_insights": self._build_recruiter_insights(job, analysis, company_context),
            "sections": sections,
            "assumptions": company_context.get("assumptions", []),
        }

    def _build_company_context(self, job: Job) -> dict[str, Any]:
        text = " ".join(
            part
            for part in [
                job.company,
                job.title,
                job.description,
                job.source,
                (job.raw_payload or {}).get("category", {}).get("label", "") if isinstance(job.raw_payload, dict) else "",
            ]
            if part
        ).lower()
        assumptions: list[str] = []
        if any(term in text for term in ("bank", "finance", "payments", "insurance")):
            industry = "Finance"
            interview_style = "Corporate reliability and architecture focus"
            assumptions.append("Industry inferred from finance-related company or job wording.")
        elif any(term in text for term in ("consult", "client", "stakeholder", "implementation partner")):
            industry = "Consulting"
            interview_style = "Consulting delivery and stakeholder management focus"
            assumptions.append("Company style inferred from consulting-oriented language in the job description.")
        elif any(term in text for term in ("ai", "ml", "data platform", "automation")):
            industry = "AI / Technology"
            interview_style = "AI/tech depth with practical delivery focus"
            assumptions.append("Industry inferred from AI or platform engineering signals in the job description.")
        elif any(term in text for term in ("small squad", "fast-paced", "startup", "scale-up", "high-impact")):
            industry = "Technology"
            interview_style = "Startup execution and ownership focus"
            assumptions.append("Startup-like interview tone inferred from small-squad or fast-paced wording.")
        else:
            industry = "Software / Technology"
            interview_style = "Enterprise delivery and collaboration focus"
            assumptions.append("Industry was not explicit, so software/technology was inferred from the role context.")

        tech_stack = [skill for skill in job.required_skills[:8] if skill]
        if not tech_stack:
            tech_stack = [skill for skill in job.preferred_skills[:5] if skill]

        return {
            "industry": industry,
            "interview_style": interview_style,
            "work_mode": job.is_remote or (job.work_mode.title() if job.work_mode else "Unknown"),
            "seniority_level": job.experience_level or self._infer_seniority(job.title),
            "tech_stack": tech_stack,
            "assumptions": assumptions,
        }

    def _build_resume_analysis(self, job: Job, base_cv: str, tailored_cv: str) -> dict[str, Any]:
        base_skills = self._extract_skills(base_cv)
        tailored_skills = self._extract_skills(tailored_cv)
        candidate_skills = base_skills | tailored_skills
        required = [skill for skill in job.required_skills if skill]
        preferred = [skill for skill in job.preferred_skills if skill]
        strong_matches = [skill for skill in required if skill in candidate_skills]
        missing = [skill for skill in required if skill not in candidate_skills]
        weak_areas = missing[:4] or [skill for skill in preferred if skill not in candidate_skills][:3]
        overlap_ratio = (len(strong_matches) / len(required)) if required else 0.6
        ats_score = int(round(overlap_ratio * 100))
        potential_concerns = []
        if missing:
            potential_concerns.append(f"Missing explicit evidence for: {', '.join(missing[:4])}")
        if "Senior" in job.title and len(strong_matches) < max(2, len(required) // 2):
            potential_concerns.append("Title suggests seniority, but the resume alignment may read closer to mid-level.")
        if not tailored_cv.strip():
            potential_concerns.append("No tailored CV exists yet, so keyword alignment may be weaker than it could be.")
        return {
            "strong_matches": strong_matches[:8],
            "weak_areas": weak_areas,
            "missing_skills": missing,
            "seniority_fit": self._seniority_fit(job.title, strong_matches, missing),
            "potential_recruiter_concerns": potential_concerns,
            "ats_compatibility": f"{ats_score}/100",
            "base_cv_skill_overlap": sorted(base_skills & set(required)),
            "tailored_cv_skill_overlap": sorted(tailored_skills & set(required)),
        }

    def _build_readiness_scores(self, job: Job, analysis: dict[str, Any]) -> dict[str, int]:
        base = int(round(job.base_match_score or job.match_score or 55))
        tailored = int(round(job.tailored_cv_match_score or base))
        technical = max(35, min(98, int(round((base * 0.45) + (tailored * 0.35) + (len(analysis["strong_matches"]) * 4) - (len(analysis["missing_skills"]) * 3)))))
        soft = max(45, min(96, int(round(68 + (5 if "lead" in job.title.lower() or "senior" in job.title.lower() else 0) - (3 if analysis["potential_recruiter_concerns"] else 0)))))
        confidence = max(35, min(96, int(round((technical * 0.55) + (soft * 0.45) - (len(analysis["missing_skills"]) * 2)))))
        overall = max(35, min(98, int(round((technical * 0.5) + (soft * 0.2) + (confidence * 0.3)))))
        return {
            "overall_interview_readiness_score": overall,
            "technical_fit_score": technical,
            "soft_skills_fit_score": soft,
            "hiring_confidence_score": confidence,
        }

    def _build_recruiter_insights(self, job: Job, analysis: dict[str, Any], company_context: dict[str, Any]) -> dict[str, list[str]]:
        missing = analysis["missing_skills"]
        strong = analysis["strong_matches"]
        style = company_context["interview_style"].lower()
        concerns = list(analysis["potential_recruiter_concerns"])
        if "startup" in style:
            concerns.append("I will test whether you can ship under ambiguity and limited process.")
        if "corporate" in style:
            concerns.append("I will look for clear communication around risk, reliability, and stakeholder alignment.")
        standout = strong[:4] or ["Your background shows core software engineering alignment even before tailoring."]
        improve = ([f"Prepare evidence for {skill}" for skill in missing[:3]] if missing else ["Prepare concise STAR stories tied to impact and collaboration."])
        rejection = ([f"Resume does not yet prove {skill} strongly enough." for skill in missing[:3]] if missing else ["Weak communication or vague examples during the interview."])
        hiring = [f"You already align with {skill}." for skill in strong[:3]] or ["The role still shows broad backend fit."]
        return {
            "what_concerns_me_as_a_recruiter": concerns,
            "what_makes_you_stand_out": standout,
            "what_you_should_improve_before_the_interview": improve,
            "most_likely_rejection_reasons": rejection,
            "most_likely_hiring_reasons": hiring,
        }

    def _build_sections(self, job: Job, analysis: dict[str, Any], company_context: dict[str, Any]) -> list[dict[str, Any]]:
        tech_stack = company_context["tech_stack"] or ["backend services", "APIs", "delivery"]
        candidate_confidence = self._candidate_confidence(job, analysis)
        prompt_topic = ", ".join(tech_stack[:3])
        sections: list[dict[str, Any]] = []
        templates = {
            "HR / Recruiter Screening": (
                f"Tell me why you want to join {job.company} as a {job.title}.",
                f"I would explain that the role matches my experience in {prompt_topic}, and that the company's context suggests meaningful problems where I can contribute quickly while continuing to grow.",
                "It connects motivation to the company, the role, and the candidate's proven background.",
                "I just need a job and your stack looks interesting.",
                "Motivation, preparation, communication, and sincerity.",
                "Medium",
            ),
            "Soft Skills Questions": (
                "Describe a time you had to work through ambiguity with cross-functional stakeholders.",
                "I would use a STAR example showing how I clarified goals, aligned engineering and product, documented tradeoffs, and kept delivery moving under uncertainty.",
                "It demonstrates communication, ownership, and practical delivery under pressure.",
                "I usually just keep coding until things become clear.",
                "Communication, ownership, adaptability, and stakeholder management.",
                "Medium",
            ),
            "Technical Questions": (
                f"How would you build and maintain a reliable service using {prompt_topic} for this role?",
                f"I would describe service boundaries, API contracts, observability, testing, rollback strategy, and how I would use {tech_stack[0]} in production with measurable reliability goals.",
                "It shows real engineering depth rather than buzzword-level familiarity.",
                "I know the framework and would just start building endpoints quickly.",
                "Practical technical depth, production thinking, and reliability mindset.",
                "Hard",
            ),
            "System Design Questions": (
                f"Design a scalable architecture for a {job.title.lower()} workflow at {job.company}.",
                "I would identify core entities, request flows, APIs, data stores, failure modes, caching, monitoring, and how the design changes with growth and compliance needs.",
                "It balances architecture, tradeoffs, and scalability thinking.",
                "I would use microservices everywhere because they scale.",
                "Architecture judgment, tradeoff awareness, and scalability.",
                "Hard",
            ),
            "Scenario-Based Questions": (
                "A release caused instability in production. What do you do first?",
                "I would stabilise first: assess severity, communicate impact, roll back or feature-flag if needed, gather telemetry, and then lead a blameless root-cause review with concrete follow-up actions.",
                "It prioritises users, calm execution, and reliable incident handling.",
                "I would immediately start rewriting the affected component.",
                "Operational maturity, prioritisation, and incident response.",
                "Hard",
            ),
            "Behavioral Questions": (
                "Tell me about a difficult engineering decision you made and how you handled disagreement.",
                "I would explain the context, the options considered, the tradeoffs, how I aligned the team, and the measurable outcome after the decision.",
                "It shows mature decision-making and collaborative leadership.",
                "I just pushed for the approach I believed was correct.",
                "Decision quality, collaboration, and influence.",
                "Medium",
            ),
            "Problem-Solving Questions": (
                f"How would you debug a performance bottleneck in a {prompt_topic} service?",
                "I would isolate the issue with metrics and tracing, form hypotheses, reproduce the problem, compare application and database latency, and validate fixes with measurable before/after impact.",
                "It demonstrates a structured debugging mindset.",
                "I would add more CPU and see if it improves.",
                "Analytical thinking, debugging discipline, and performance awareness.",
                "Hard",
            ),
            "Team Collaboration Questions": (
                "How do you keep product, QA, and engineering aligned when deadlines are tight?",
                "I would make scope explicit, surface risks early, agree on decision owners, keep updates concise, and protect delivery by reducing ambiguity rather than hiding it.",
                "It shows strong collaboration habits in real delivery conditions.",
                "I try not to involve too many people because it slows things down.",
                "Collaboration, transparency, and execution under pressure.",
                "Medium",
            ),
            "Culture Fit Questions": (
                f"What working environment helps you do your best work, and how does that fit {job.company}?",
                "I would describe a preference for accountable teams, clear outcomes, and fast feedback loops, while connecting that style to the role's work mode and team context without pretending certainty where details are inferred.",
                "It feels tailored while staying honest about assumptions.",
                "I can work anywhere, I just adapt.",
                "Self-awareness, honesty, and fit with team norms.",
                "Easy",
            ),
            "Salary/availability/visa questions": (
                "What are your availability, salary expectations, and work-rights situation?",
                "I would answer directly with my timeline, a realistic salary range, and a clear work-rights statement that matches the role's location and visa expectations.",
                "Recruiters value concise, low-friction answers here.",
                "I'd rather discuss that much later in the process.",
                "Practical fit, transparency, and hiring logistics.",
                "Easy",
            ),
        }
        for index, section_name in enumerate(QUESTION_SECTIONS, start=1):
            template = templates[section_name]
            sections.append(
                {
                    "section_name": section_name,
                    "questions": [
                        {
                            "id": f"q{index}",
                            "question": template[0],
                            "strong_example_answer": template[1],
                            "why_the_answer_is_good": template[2],
                            "common_bad_answer": template[3],
                            "what_recruiters_are_evaluating": template[4],
                            "difficulty_level": template[5],
                            "candidate_confidence_score": candidate_confidence,
                        }
                    ],
                }
            )
        return sections

    def _evaluate_fallback(self, question: dict[str, Any], answer: str) -> dict[str, Any]:
        answer_words = set(re.findall(r"[a-z0-9\+#\.]+", answer.lower()))
        ideal_words = set(re.findall(r"[a-z0-9\+#\.]+", question["strong_example_answer"].lower()))
        overlap = len(answer_words & ideal_words)
        overlap_score = int(round((overlap / max(1, len(ideal_words))) * 100))
        length_bonus = 10 if len(answer.split()) >= 40 else 0
        score = max(25, min(97, overlap_score + length_bonus))
        feedback = "Your answer covers some relevant points, but it can be stronger."
        if score >= 80:
            feedback = "This answer is strong and recruiter-friendly because it sounds specific, structured, and outcome-oriented."
        elif score >= 60:
            feedback = "This is a reasonable answer, but it needs more concrete impact, structure, or ownership."
        return {
            "question_id": question["id"],
            "score": score,
            "feedback": feedback,
            "improved_answer": question["strong_example_answer"],
            "confidence_analysis": "Confidence improves when your answer includes specifics, tradeoffs, and measurable outcomes.",
            "communication_analysis": "Use a concise STAR-style structure and avoid vague claims without examples.",
        }

    def _flatten_questions(self, simulation: dict[str, Any]) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        for section in simulation.get("sections", []):
            for question in section.get("questions", []):
                enriched = dict(question)
                enriched["section_name"] = section.get("section_name", "")
                questions.append(enriched)
        return questions

    def _extract_skills(self, text: str) -> set[str]:
        lowered = text.lower()
        matched: set[str] = set()
        for skill_name, aliases in SKILL_CATALOG.items():
            if any(alias in lowered for alias in aliases):
                matched.add(skill_name)
        return matched

    def _infer_seniority(self, title: str) -> str:
        lowered = title.lower()
        if any(term in lowered for term in ("principal", "staff", "architect")):
            return "Senior / Principal"
        if any(term in lowered for term in ("lead", "senior")):
            return "Senior"
        if any(term in lowered for term in ("junior", "graduate", "associate")):
            return "Junior"
        return "Mid-level"

    def _seniority_fit(self, title: str, strong_matches: list[str], missing: list[str]) -> str:
        lowered = title.lower()
        if any(term in lowered for term in ("lead", "senior", "principal")):
            if len(missing) <= 2 and len(strong_matches) >= 3:
                return "Likely aligned with senior expectations."
            return "Possibly mid-to-senior fit, but recruiter may probe depth and leadership."
        return "Role appears aligned with hands-on delivery expectations."

    def _candidate_confidence(self, job: Job, analysis: dict[str, Any]) -> int:
        base = int(round(job.tailored_cv_match_score or job.base_match_score or job.match_score or 60))
        adjusted = base - (len(analysis["missing_skills"]) * 3)
        return max(30, min(95, adjusted))
