"""Adzuna jobs API collector."""

from __future__ import annotations

import os

import httpx

from collectors.base import BaseCollector, CollectedJob


class AdzunaCollector(BaseCollector):
    """Collect jobs from the Adzuna API."""

    source_name = "adzuna"

    def search(self) -> list[CollectedJob]:
        app_id = os.getenv("ADZUNA_APP_ID")
        app_key = os.getenv("ADZUNA_APP_KEY")
        if not app_id or not app_key:
            return []

        jobs: list[CollectedJob] = []
        with httpx.Client(timeout=20.0) as client:
            for keyword in self.config.keywords:
                params = {
                    "app_id": app_id,
                    "app_key": app_key,
                    "results_per_page": 10,
                    "what": keyword,
                    "where": ",".join(self.config.locations) if self.config.locations else "Australia",
                    "content-type": "application/json",
                }
                response = client.get("https://api.adzuna.com/v1/api/jobs/au/search/1", params=params)
                response.raise_for_status()
                data = response.json()
                for item in data.get("results", []):
                    jobs.append(
                        CollectedJob(
                            source=self.source_name,
                            external_id=str(item.get("id")),
                            title=item.get("title", ""),
                            company=(item.get("company") or {}).get("display_name", "Unknown"),
                            description=item.get("description", ""),
                            location=(item.get("location") or {}).get("display_name"),
                            salary=_format_salary(item.get("salary_min"), item.get("salary_max")),
                            url=item.get("redirect_url", ""),
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
