"""JSearch API collector."""

from __future__ import annotations

import os

import httpx

from collectors.apply_utils import detect_easy_apply
from collectors.base import BaseCollector, CollectedJob
from collectors.location_utils import detect_work_mode, normalize_location


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
                    raw_location = ", ".join(
                        part for part in [item.get("job_city"), item.get("job_state"), item.get("job_country")] if part
                    ) or item.get("job_location")
                    location_data = normalize_location(
                        city=item.get("job_city"),
                        state=item.get("job_state"),
                        country=item.get("job_country"),
                        full_location=raw_location,
                        raw_location=raw_location,
                        description=item.get("job_description", ""),
                        title=item.get("job_title", ""),
                    )
                    is_remote, work_mode = detect_work_mode(
                        title=item.get("job_title", ""),
                        description=item.get("job_description", ""),
                        location_text=raw_location or "",
                        metadata=item,
                    )
                    easy_apply = detect_easy_apply(
                        source=self.source_name,
                        url=item.get("job_apply_link", ""),
                        description=item.get("job_description", ""),
                        metadata=item,
                    )
                    jobs.append(
                        CollectedJob(
                            source=self.source_name,
                            external_id=item.get("job_id"),
                            title=item.get("job_title", ""),
                            company=item.get("employer_name", "Unknown"),
                            description=item.get("job_description", ""),
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
                            salary=item.get("job_salary"),
                            url=item.get("job_apply_link", ""),
                            raw_payload=item,
                        )
                    )
        return jobs
