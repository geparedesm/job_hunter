"""Apply-flow normalization helpers for collectors."""

from __future__ import annotations

import re
from typing import Any


EASY_APPLY_URL_PATTERNS = ("easyapply", "quickapply", "oneclick", "one-click", "fastapply")
EASY_APPLY_TEXT_PATTERNS = (
    "easy apply",
    "apply in one click",
    "quick apply",
    "fast apply",
    "fast application process",
    "one-click apply",
)
ADZUNA_EASY_APPLY_PATTERNS = (
    "easy apply",
    "instant apply",
    "apply for this job",
    "send application",
    "directapply",
)
ADZUNA_METADATA_PATTERNS = (
    "reply_to_ad",
    "jobadder.com: xml all ads - easy apply",
    "heading:easy_apply",
    "instant apply",
    "directapply",
)
EXTERNAL_APPLY_TEXT_PATTERNS = ("external apply", "apply on company site", "redirect to employer")
PLATFORM_APPLY_PATTERNS = ("linkedin.com", "seek.com", "indeed.com", "google.com", "adzuna")


def detect_easy_apply(
    *,
    source: str,
    url: str = "",
    description: str = "",
    metadata: Any = None,
    page_text: str = "",
) -> dict[str, str]:
    """Return normalized Easy Apply detection data."""
    url_lower = (url or "").lower()
    metadata_blob = _flatten_metadata(metadata).lower()
    description_lower = (description or "").lower()
    page_text_lower = (page_text or "").lower()

    if source.lower() == "adzuna":
        return _detect_adzuna_easy_apply(
            url_lower=url_lower,
            metadata_blob=metadata_blob,
            description_lower=description_lower,
            page_text_lower=page_text_lower,
        )

    if any(pattern in url_lower for pattern in EASY_APPLY_URL_PATTERNS):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Quick Apply",
            "easy_apply_detection_source": "apply_url_pattern",
        }

    if any(pattern in metadata_blob for pattern in EASY_APPLY_TEXT_PATTERNS):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Easy Apply",
            "easy_apply_detection_source": "api_metadata",
        }

    if any(pattern in description_lower for pattern in EASY_APPLY_TEXT_PATTERNS):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Easy Apply",
            "easy_apply_detection_source": "description_text",
        }

    if any(pattern in metadata_blob for pattern in EXTERNAL_APPLY_TEXT_PATTERNS):
        return {
            "easy_apply": "No",
            "easy_apply_type": "External Apply",
            "easy_apply_detection_source": "api_metadata",
        }

    if any(platform in url_lower for platform in PLATFORM_APPLY_PATTERNS) and "external" not in metadata_blob:
        return {
            "easy_apply": "Unknown",
            "easy_apply_type": "Unknown",
            "easy_apply_detection_source": "platform_apply_flow",
        }

    return {
        "easy_apply": "No",
        "easy_apply_type": "External Apply",
        "easy_apply_detection_source": "fallback",
    }


def _detect_adzuna_easy_apply(
    *,
    url_lower: str,
    metadata_blob: str,
    description_lower: str,
    page_text_lower: str,
) -> dict[str, str]:
    if any(pattern in url_lower for pattern in EASY_APPLY_URL_PATTERNS):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Quick Apply",
            "easy_apply_detection_source": "apply_url_pattern",
        }

    if _contains_direct_apply_flag(metadata_blob):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Easy Apply",
            "easy_apply_detection_source": "adzuna_metadata",
        }

    if any(pattern in metadata_blob for pattern in ADZUNA_METADATA_PATTERNS) or any(
        pattern in metadata_blob for pattern in EASY_APPLY_TEXT_PATTERNS
    ):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Easy Apply",
            "easy_apply_detection_source": "adzuna_metadata",
        }

    if any(pattern in page_text_lower for pattern in ADZUNA_EASY_APPLY_PATTERNS):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Easy Apply",
            "easy_apply_detection_source": "adzuna_html_badge",
        }

    if any(pattern in description_lower for pattern in EASY_APPLY_TEXT_PATTERNS):
        return {
            "easy_apply": "Yes",
            "easy_apply_type": "Easy Apply",
            "easy_apply_detection_source": "description_text",
        }

    if _is_external_apply_url(url_lower):
        return {
            "easy_apply": "No",
            "easy_apply_type": "External Apply",
            "easy_apply_detection_source": "external_apply_url",
        }

    if "adzuna.com" in url_lower:
        return {
            "easy_apply": "Unknown",
            "easy_apply_type": "Unknown",
            "easy_apply_detection_source": "platform_apply_flow",
        }

    return {
        "easy_apply": "No",
        "easy_apply_type": "External Apply",
        "easy_apply_detection_source": "fallback",
    }


def _contains_direct_apply_flag(metadata_blob: str) -> bool:
    normalized = metadata_blob.replace(" ", "")
    direct_apply_markers = (
        "directapplytrue",
        'directapply":"true"',
        "reply_toad1",
        'reply_to_ad":"1"',
        "jobs:ad_details:instant_apply",
        "jobs:rta:confirmation:header",
    )
    return any(marker in normalized for marker in direct_apply_markers)


def _is_external_apply_url(url_lower: str) -> bool:
    if not url_lower:
        return False
    if "adzuna.com" in url_lower:
        return bool(re.search(r"/apply\b", url_lower))
    return True


def _flatten_metadata(value: Any) -> str:
    if isinstance(value, dict):
        parts: list[str] = []
        for key, child in value.items():
            parts.append(str(key))
            parts.append(_flatten_metadata(child))
        return " ".join(part for part in parts if part)
    if isinstance(value, list):
        return " ".join(_flatten_metadata(child) for child in value)
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return ""
