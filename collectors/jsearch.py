"""JSearch API collector."""

from __future__ import annotations

import os

import httpx

from collectors.base import BaseCollector, CollectedJob


class JSearchCollector(BaseCollector):
    """Collect jobs from JSearch via RapidAPI."""

    source_name = "jsearch"

    def search(self) -> list[CollectedJob]:
        api_key = os.getenv("JSEARCH_API_KEY")
        if not api_key:
            return []

        jobs: list[CollectedJob] = []
        headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        with httpx.Client(timeout=20.0, headers=headers) as client:
            for keyword in self.config.keywords:
                query = f"{keyword} in {' OR '.join(self.config.locations or ['Australia'])}"
                response = client.get("https://jsearch.p.rapidapi.com/search", params={"query": query, "page": 1, "num_pages": 1})
                response.raise_for_status()
                data = response.json()
                for item in data.get("data", []):
                    jobs.append(
                        CollectedJob(
                            source=self.source_name,
                            external_id=item.get("job_id"),
                            title=item.get("job_title", ""),
                            company=item.get("employer_name", "Unknown"),
                            description=item.get("job_description", ""),
                            location=item.get("job_city") or item.get("job_country"),
                            salary=item.get("job_salary"),
                            url=item.get("job_apply_link", ""),
                            raw_payload=item,
                        )
                    )
        return jobs
