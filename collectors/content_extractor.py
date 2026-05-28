"""Utilities for extracting fuller job-post content from job URLs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover - optional until dependencies are installed
    BeautifulSoup = None  # type: ignore[assignment]
    Tag = object  # type: ignore[assignment]


SECTION_PATTERNS: dict[str, tuple[str, ...]] = {
    "about": ("about the role", "about you", "about us", "overview", "summary"),
    "responsibilities": ("responsibilities", "what you'll do", "what you will do", "duties", "key responsibilities"),
    "requirements": ("requirements", "required skills", "must have", "what we're looking for", "what we are looking for"),
    "preferred": ("preferred", "nice to have", "desirable", "bonus points", "ideal"),
    "qualifications": ("qualifications", "experience", "skills and experience", "criteria"),
    "tech_stack": ("tech stack", "technology", "tools", "stack"),
    "visa": ("visa", "sponsorship", "work rights", "citizen", "permanent resident"),
    "general": (),
}


@dataclass(slots=True)
class ExtractionResult:
    """Structured extraction output for a job page."""

    full_text: str
    sections: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    source_method: str = "preview"
    is_complete: bool = False


class JobContentExtractor:
    """Fetch and clean full job-post content with fallbacks."""

    def __init__(self) -> None:
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            )
        }

    def extract(self, url: str, preview_text: str) -> ExtractionResult:
        """Fetch and parse the full job page, falling back safely when needed."""
        warnings: list[str] = []
        html = ""
        try:
            with httpx.Client(headers=self.headers, timeout=20.0, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                html = response.text
        except Exception as exc:
            warnings.append(f"Failed to fetch job page: {exc}")
            return ExtractionResult(
                full_text=self._clean_text(preview_text),
                sections={"general": [self._clean_text(preview_text)]} if preview_text else {},
                warnings=warnings,
                source_method="preview",
                is_complete=False,
            )

        metadata_texts = self._extract_structured_metadata(html)
        if BeautifulSoup is None:
            warnings.append("BeautifulSoup is not installed; using raw HTML text fallback.")
            raw_text = self._clean_text(self._strip_tags(html))
            combined = self._merge_texts([raw_text, *metadata_texts, preview_text])
            return ExtractionResult(
                full_text=combined,
                sections={"general": [combined]},
                warnings=warnings + ["Analysis used a raw-text fallback, so section detection may be incomplete."],
                source_method="raw_html_fallback",
                is_complete=False,
            )

        soup = BeautifulSoup(html, "html.parser")
        self._remove_noise(soup)
        sections = self._extract_sections_from_soup(soup)
        main_text = self._extract_main_text(soup)
        combined = self._merge_texts([main_text, *metadata_texts, preview_text])

        if not combined:
            warnings.append("No visible text could be extracted from the job page.")
            combined = self._clean_text(preview_text)

        if len(combined) < max(400, len(preview_text) + 120):
            warnings.append("Only limited job-page content was extracted; analysis may be incomplete.")

        if "general" not in sections and combined:
            sections["general"] = [combined]

        return ExtractionResult(
            full_text=combined,
            sections=sections,
            warnings=warnings,
            source_method="html_sections" if sections else "visible_text",
            is_complete=bool(sections) and len(combined) >= max(400, len(preview_text)),
        )

    def _extract_structured_metadata(self, html: str) -> list[str]:
        texts: list[str] = []
        for match in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.DOTALL | re.IGNORECASE):
            try:
                payload = json.loads(match)
            except json.JSONDecodeError:
                continue
            for item in payload if isinstance(payload, list) else [payload]:
                if not isinstance(item, dict):
                    continue
                description = item.get("description")
                qualifications = item.get("qualifications")
                responsibilities = item.get("responsibilities")
                for value in (description, qualifications, responsibilities):
                    if isinstance(value, str):
                        texts.append(self._clean_text(self._strip_tags(value)))
        return [text for text in texts if text]

    def _remove_noise(self, soup: BeautifulSoup) -> None:
        for tag in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav", "aside"]):
            tag.decompose()
        noisy_terms = ("cookie", "consent", "footer", "header", "navigation", "recommend", "related jobs", "sign in", "subscribe")
        for tag in soup.find_all(True):
            blob = " ".join(
                filter(
                    None,
                    [
                        tag.get("id"),
                        " ".join(tag.get("class", [])),
                        tag.get("aria-label"),
                    ],
                )
            ).lower()
            if any(term in blob for term in noisy_terms):
                tag.decompose()

    def _extract_sections_from_soup(self, soup: BeautifulSoup) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        headings = soup.find_all(re.compile("^h[1-4]$"))
        for heading in headings:
            heading_text = self._clean_text(heading.get_text(" ", strip=True))
            if not heading_text:
                continue
            section_name = self._classify_heading(heading_text)
            if section_name == "general":
                continue
            collected: list[str] = []
            sibling = heading.next_sibling
            while sibling is not None:
                if isinstance(sibling, Tag) and re.fullmatch(r"h[1-4]", sibling.name or "", flags=0):
                    break
                if isinstance(sibling, Tag):
                    if sibling.name in {"p", "li"}:
                        text = self._clean_text(sibling.get_text(" ", strip=True))
                        if text:
                            collected.append(text)
                    elif sibling.name in {"ul", "ol", "div", "section"}:
                        for child in sibling.find_all(["p", "li"], recursive=True):
                            text = self._clean_text(child.get_text(" ", strip=True))
                            if text:
                                collected.append(text)
                sibling = sibling.next_sibling
            if collected:
                sections.setdefault(section_name, []).extend(self._dedupe_keep_order(collected))
        return {key: self._dedupe_keep_order(value) for key, value in sections.items() if value}

    def _extract_main_text(self, soup: BeautifulSoup) -> str:
        candidate = soup.find("main") or soup.find("article")
        if candidate is None:
            candidates = soup.find_all(["section", "div"])
            scored: list[tuple[int, Tag]] = []
            for item in candidates:
                text = self._clean_text(item.get_text(" ", strip=True))
                if len(text) < 250:
                    continue
                score = len(text)
                if re.search(r"require|responsib|qualif|about the role|experience|tech", text, re.IGNORECASE):
                    score += 500
                scored.append((score, item))
            candidate = max(scored, key=lambda pair: pair[0])[1] if scored else soup.body
        if candidate is None:
            return ""
        lines = [self._clean_text(text) for text in candidate.stripped_strings]
        filtered = [
            line for line in lines
            if len(line) > 2 and not self._looks_like_noise(line)
        ]
        return self._merge_texts(filtered)

    def _classify_heading(self, text: str) -> str:
        lowered = text.lower()
        for section, patterns in SECTION_PATTERNS.items():
            if any(pattern in lowered for pattern in patterns):
                return section
        return "general"

    def _looks_like_noise(self, text: str) -> bool:
        lowered = text.lower()
        if any(term in lowered for term in ("cookie", "privacy policy", "sign in", "apply now", "share this job", "recommended job")):
            return True
        if len(lowered.split()) <= 2 and not re.search(r"[A-Za-z0-9]", lowered):
            return True
        return False

    def _merge_texts(self, texts: list[str]) -> str:
        cleaned = [self._clean_text(text) for text in texts if self._clean_text(text)]
        return "\n".join(self._dedupe_keep_order(cleaned))

    def _clean_text(self, text: str) -> str:
        text = self._strip_tags(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _strip_tags(self, text: str) -> str:
        return re.sub(r"<[^>]+>", " ", text or "")

    def _dedupe_keep_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered
