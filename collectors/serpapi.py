"""SerpApi Google Jobs collector."""

from __future__ import annotations

import os

import httpx

from collectors.apply_utils import detect_easy_apply
from collectors.base import BaseCollector, CollectedJob
from collectors.location_utils import detect_work_mode, normalize_location


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
                    raw_location = item.get("location")
                    location_data = normalize_location(
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
                    apply_url = item.get("related_links", [{}])[0].get("link", item.get("share_link", ""))
                    easy_apply = detect_easy_apply(
                        source=self.source_name,
                        url=apply_url,
                        description=item.get("description", ""),
                        metadata=item,
                    )
                    jobs.append(
                        CollectedJob(
                            source=self.source_name,
                            external_id=item.get("job_id"),
                            title=item.get("title", ""),
                            company=item.get("company_name", "Unknown"),
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
                            salary=item.get("detected_extensions", {}).get("salary"),
                            url=apply_url,
                            raw_payload=item,
                        )
                    )
        return jobs
