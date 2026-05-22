"""Scheduler wiring for recurring job searches."""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from backend.services import JobHunterService


def build_scheduler(service: JobHunterService) -> BackgroundScheduler:
    """Build the background scheduler from config."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(service.search_jobs, "interval", hours=service.config.search_interval_hours, id="search_jobs", replace_existing=True)
    return scheduler
