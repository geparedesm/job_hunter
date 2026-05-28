"""Location and remote-work normalization helpers for collectors."""

from __future__ import annotations

import re
from typing import Any


AU_STATE_ALIASES = {
    "wa": "WA",
    "western australia": "WA",
    "nsw": "NSW",
    "new south wales": "NSW",
    "vic": "VIC",
    "victoria": "VIC",
    "qld": "QLD",
    "queensland": "QLD",
    "sa": "SA",
    "south australia": "SA",
    "tas": "TAS",
    "tasmania": "TAS",
    "act": "ACT",
    "australian capital territory": "ACT",
    "nt": "NT",
    "northern territory": "NT",
}

VAGUE_LOCATION_VALUES = {"australia", "remote", "various locations", "not specified", "multiple locations", "unknown"}
REMOTE_TERMS = ("remote", "work from home", "wfh", "anywhere", "distributed team", "distributed", "home based")
HYBRID_TERMS = ("hybrid", "flexible location", "part remote", "partially remote")
AU_STATE_NAMES = {
    "new south wales",
    "victoria",
    "queensland",
    "western australia",
    "south australia",
    "tasmania",
    "northern territory",
    "australian capital territory",
}


def normalize_location(
    *,
    city: str | None = None,
    state: str | None = None,
    country: str | None = None,
    full_location: str | None = None,
    raw_location: str | None = None,
    description: str = "",
    title: str = "",
) -> dict[str, str]:
    """Normalize city/state/country/full location with fallbacks."""
    original = _clean(raw_location) or _clean(full_location) or ""
    full = _clean(full_location) or original
    city_value = _clean(city)
    state_value = _normalize_state(state)
    country_value = _normalize_country(country, full, original)

    if full:
        parsed = _parse_location_text(full)
        city_value = _sanitize_city(city_value) or parsed["city"]
        state_value = state_value or parsed["state"]
        country_value = country_value or parsed["country"]

    if not city_value and original:
        parsed_original = _parse_location_text(original)
        city_value = parsed_original["city"]
        state_value = state_value or parsed_original["state"]
        country_value = country_value or parsed_original["country"]

    city_value = _sanitize_city(city_value)

    remote_blob = " ".join(part for part in [title, description, full, original] if part).lower()
    if not city_value:
        if "remote" in remote_blob:
            city_value = "Remote"
        else:
            city_value = "Unknown"

    full_location_value = _build_display_location(city_value, country_value, full or original)
    if not full_location_value:
        full_location_value = original or "Unknown"

    return {
        "city": city_value,
        "state": state_value or "",
        "country": country_value or "",
        "full_location": full_location_value,
        "display_location": full_location_value,
        "raw_location": original or full_location_value,
    }


def detect_work_mode(*, title: str = "", description: str = "", location_text: str = "", metadata: Any = None) -> tuple[str, str]:
    """Return `(is_remote, work_mode)` using structured and textual signals."""
    blob = " ".join(str(item) for item in [title, description, location_text, _flatten_metadata(metadata)] if item).lower()
    if any(term in blob for term in HYBRID_TERMS):
        return "Hybrid", "hybrid"
    if any(term in blob for term in REMOTE_TERMS):
        return "Yes", "remote"
    if any(term in blob for term in ("on-site", "onsite", "in office", "office based")):
        return "No", "onsite"
    return "Unknown", "unknown"


def _parse_location_text(text: str) -> dict[str, str]:
    cleaned = _clean(text)
    if not cleaned:
        return {"city": "", "state": "", "country": ""}

    tokens = [token.strip() for token in re.split(r"[,/|-]+", cleaned) if token.strip()]
    city = ""
    state = ""
    country = ""

    for token in tokens:
        lowered = token.lower()
        if lowered in AU_STATE_ALIASES:
            state = AU_STATE_ALIASES[lowered]
            continue
        if lowered in {"australia", "australian"}:
            country = "Australia"
            continue
        if lowered in AU_STATE_NAMES:
            state = AU_STATE_ALIASES[lowered]
            continue
        if not city and lowered not in VAGUE_LOCATION_VALUES and "remote" not in lowered and lowered != "australia":
            city = token.title() if token.islower() else token

    if not country and state:
        country = "Australia"

    return {"city": _sanitize_city(city), "state": state, "country": country}


def _normalize_state(value: str | None) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return ""
    return AU_STATE_ALIASES.get(cleaned.lower(), cleaned.upper() if len(cleaned) <= 3 else cleaned)


def _normalize_country(country: str | None, full_location: str, raw_location: str) -> str:
    cleaned = _clean(country)
    if cleaned:
        return "Australia" if cleaned.lower() in {"au", "australia", "australian"} else cleaned
    blob = " ".join(part for part in [full_location, raw_location] if part).lower()
    return "Australia" if "australia" in blob or any(alias in blob for alias in AU_STATE_ALIASES) else ""


def _build_display_location(city: str, country: str, fallback: str) -> str:
    if city in {"Remote", "Unknown"}:
        return ", ".join(part for part in [city, country or "Australia"] if part)
    if city:
        return ", ".join(part for part in [city, country] if part)
    return fallback


def _sanitize_city(value: str | None) -> str:
    cleaned = _clean(value)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in AU_STATE_NAMES or lowered in AU_STATE_ALIASES or lowered in {"australia", "australian"}:
        return ""
    return cleaned


def _flatten_metadata(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_metadata(child) for child in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_metadata(child) for child in value)
    if isinstance(value, str):
        return value
    return ""


def _clean(value: str | None) -> str:
    return " ".join((value or "").split()).strip()
