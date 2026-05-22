"""Playwright-based application automation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.loader import PROJECT_ROOT


@dataclass(slots=True)
class ApplicationAutomationResult:
    """Result of an application automation attempt."""

    status: str
    message: str
    before_screenshot_path: Path | None = None
    after_screenshot_path: Path | None = None


class ApplicationAutomation:
    """Application automation that only runs after explicit approval."""

    def apply(self, job: object, cv_path: Path, cover_letter_path: Path) -> ApplicationAutomationResult:
        """Attempt automation and fall back to assisted mode when needed."""
        if not getattr(job, "url", None):
            return ApplicationAutomationResult(status="failed", message="Missing job URL")

        slug = _slugify(f"{getattr(job, 'company', 'company')}_{getattr(job, 'title', 'role')}")
        target_dir = PROJECT_ROOT / "applications" / slug
        target_dir.mkdir(parents=True, exist_ok=True)
        before = target_dir / "before_submit.png"
        after = target_dir / "after_submit.png"

        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return ApplicationAutomationResult(
                status="approved",
                message="Playwright not installed. Open the job page manually to complete the application.",
            )

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(getattr(job, "url"), wait_until="domcontentloaded", timeout=30000)
                page.screenshot(path=str(before), full_page=True)
                page.screenshot(path=str(after), full_page=True)
                browser.close()
            return ApplicationAutomationResult(
                status="approved",
                message=(
                    f"Application page opened and screenshots captured. Review manually before submitting. "
                    f"Prepared CV: {cv_path.name}, cover letter: {cover_letter_path.name}."
                ),
                before_screenshot_path=before,
                after_screenshot_path=after,
            )
        except Exception as exc:
            return ApplicationAutomationResult(
                status="failed",
                message=f"Automation error: {exc}",
                before_screenshot_path=before if before.exists() else None,
                after_screenshot_path=after if after.exists() else None,
            )


def _slugify(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")
