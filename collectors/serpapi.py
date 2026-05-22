"""SerpApi Google Jobs collector."""

from __future__ import annotations

import os

import httpx

from collectors.base import BaseCollector, CollectedJob


class SerpApiCollector(BaseCollector):
    """Collect jobs from Google Jobs via SerpApi."""

    source_name = "serpapi"

    def search(self) -> list[CollectedJob]:
        api_key = os.getenv("SERPAPI_API_KEY")
        if not api_key:
            return []

        jobs: list[CollectedJob] = []
        with httpx.Client(timeout=20.0) as client:
            for keyword in self.config.keywords:
                params = {
                    "engine": "google_jobs",
                    "api_key": api_key,
                    "q": keyword,
                    "location": self.config.locations[0] if self.config.locations else "Australia",
                }
                response = client.get("https://serpapi.com/search.json", params=params)
                response.raise_for_status()
                data = response.json()
                for item in data.get("jobs_results", []):
                    jobs.append(
                        CollectedJob(
                            source=self.source_name,
                            external_id=item.get("job_id"),
                            title=item.get("title", ""),
                            company=item.get("company_name", "Unknown"),
                            description=item.get("description", ""),
                            location=item.get("location"),
                            salary=item.get("detected_extensions", {}).get("salary"),
                            url=item.get("related_links", [{}])[0].get("link", item.get("share_link", "")),
                            raw_payload=item,
                        )
                    )
        return jobs
