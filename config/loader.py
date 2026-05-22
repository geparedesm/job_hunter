"""Configuration loading helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


@dataclass(slots=True)
class AppConfig:
    """Typed configuration loaded from YAML."""

    keywords: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    minimum_match_score: int = 75
    search_interval_hours: int = 12
    blacklist_keywords: list[str] = field(default_factory=list)
    blacklist_companies: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=lambda: ["adzuna", "jsearch", "serpapi"])


def load_settings(path: Path | None = None) -> AppConfig:
    """Load the YAML config into a typed dataclass."""
    settings_path = path or DEFAULT_SETTINGS_PATH
    if not settings_path.exists():
        return AppConfig()

    with settings_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}

    return AppConfig(
        keywords=list(raw.get("keywords", [])),
        locations=list(raw.get("locations", [])),
        minimum_match_score=int(raw.get("minimum_match_score", 75)),
        search_interval_hours=int(raw.get("search_interval_hours", 12)),
        blacklist_keywords=list(raw.get("blacklist_keywords", [])),
        blacklist_companies=list(raw.get("blacklist_companies", [])),
        sources=list(raw.get("sources", ["adzuna", "jsearch", "serpapi"])),
    )
