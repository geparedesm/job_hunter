"""Notification interfaces."""

from __future__ import annotations


class ConsoleNotifier:
    """Console notifier with placeholders for future channels."""

    def send(self, message: str) -> None:
        """Print a notification to stdout."""
        print(message)

    def notify_new_matches(self, job: object) -> str:
        """Build a console message for a new analyzed job."""
        return (
            "New job found\n"
            f"Company: {getattr(job, 'company', 'Unknown')}\n"
            f"Role: {getattr(job, 'title', 'Unknown')}\n"
            f"Match: {getattr(job, 'match_score', 'N/A')}%\n"
            f"Missing: {', '.join(getattr(job, 'missing_skills', [])) or 'None'}\n"
            f"Recommended: {getattr(job, 'recommended_action', 'N/A')}"
        )

    def notify_pending_approval(self, job: object) -> str:
        """Build a pending approval notification."""
        return (
            "Pending approval\n"
            f"Company: {getattr(job, 'company', 'Unknown')}\n"
            f"Role: {getattr(job, 'title', 'Unknown')}\n"
            f"Match: {getattr(job, 'match_score', 'N/A')}%"
        )

    def notify_application_result(self, job: object, result_message: str) -> str:
        """Build a final application automation result notification."""
        return (
            "Application update\n"
            f"Company: {getattr(job, 'company', 'Unknown')}\n"
            f"Role: {getattr(job, 'title', 'Unknown')}\n"
            f"Result: {result_message}"
        )
