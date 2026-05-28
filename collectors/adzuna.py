"""Adzuna jobs API collector."""

from __future__ import annotations

import os

import httpx

from collectors.apply_utils import detect_easy_apply
from collectors.base import BaseCollector, CollectedJob
from collectors.location_utils import detect_work_mode, normalize_location


class AdzunaCollector(BaseCollector):
    """Collect jobs from the Adzuna API."""

    source_name = "adzuna"

    def search(self) -> list[CollectedJob]:
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            return []

        jobs: list[CollectedJob] = []
        seen_keys: set[str] = set()
        search_locations = self.config.locations or ["Australia"]
        with httpx.Client(timeout=20.0) as client:
            for keyword in self.config.keywords:
                for location in search_locations:
                    params = {
                        "app_id": app_id,
                        "app_key": app_key,
                        "results_per_page": 10,
                        "what": keyword,
                        "where": location,
                        "content-type": "application/json",
                    }
                    response = client.get("https://api.adzuna.com/v1/api/jobs/au/search/1", params=params)
                    response.raise_for_status()
                    data = response.json()
                    for item in data.get("results", []):
                        external_id = str(item.get("id"))
                        url = item.get("redirect_url", "")
                        dedupe_key = external_id or url
                        if dedupe_key in seen_keys:
                            continue
                        seen_keys.add(dedupe_key)
                        raw_location = (item.get("location") or {}).get("display_name")
                        location_data = normalize_location(
                            city=(item.get("location") or {}).get("area", [None, None, None])[1] if isinstance((item.get("location") or {}).get("area"), list) and len((item.get("location") or {}).get("area", [])) > 1 else None,
                            state=(item.get("location") or {}).get("area", [None, None, None])[0] if isinstance((item.get("location") or {}).get("area"), list) and (item.get("location") or {}).get("area") else None,
                            country="Australia",
                            full_location=raw_location,
                            raw_location=raw_location,
                            description=item.get("description", ""),
                            title=item.get("title", ""),
                        )
                        is_remote, work_mode = detect_work_mode(
                            title=item.get("title", ""),
                            description=item.get("description", ""),
                            location_text=raw_location or "",
                            metadata=item,
                        )
                        easy_apply = detect_easy_apply(
                            source=self.source_name,
                            url=url,
                            description=item.get("description", ""),
                            metadata=item,
                        )
                        jobs.append(
                            CollectedJob(
                                source=self.source_name,
                                external_id=external_id,
                                title=item.get("title", ""),
                                company=(item.get("company") or {}).get("display_name", "Unknown"),
                                description=item.get("description", ""),
                                location=location_data["full_location"],
                                city=location_data["city"],
                                state=location_data["state"],
                                country=location_data["country"],
                                full_location=location_data["full_location"],
                                raw_location=location_data["raw_location"],
                                is_remote=is_remote,
                                work_mode=work_mode,
                                easy_apply=easy_apply["easy_apply"],
                                easy_apply_type=easy_apply["easy_apply_type"],
                                easy_apply_detection_source=easy_apply["easy_apply_detection_source"],
                                salary=_format_salary(item.get("salary_min"), item.get("salary_max")),
                                url=url,
                                raw_payload=item,
                            )
                        )
        return jobs


def _format_salary(salary_min: float | None, salary_max: float | None) -> str | None:
    if salary_min and salary_max:
        return f"{int(salary_min):,} - {int(salary_max):,}"
    if salary_min:
        return f"From {int(salary_min):,}"
    if salary_max:
        return f"Up to {int(salary_max):,}"
    return None
