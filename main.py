"""Application entry point for running the scheduler service."""

from backend.database import init_db
from backend.services import JobHunterService
from scheduler.scheduler import build_scheduler


def main() -> None:
    """Initialize the database and start the recurring scheduler."""
    init_db()
    service = JobHunterService()
    scheduler = build_scheduler(service)
    scheduler.start()
    try:
        import time

        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
