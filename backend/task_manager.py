"""Persistent task execution manager."""

from __future__ import annotations

import traceback
from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select

from backend.database import SessionLocal
from backend.models import TaskExecution


FINAL_TASK_STATES = {"completed", "failed", "cancelled"}


class TaskManager:
    """Create and update tracked task records."""

    def create_task(
        self,
        task_name: str,
        task_type: str,
        *,
        status: str = "pending",
        progress_percentage: int = 0,
        current_step: str | None = None,
        context: dict | None = None,
        task_id: str | None = None,
    ) -> dict[str, object]:
        """Create a task record."""
        task_id = task_id or uuid4().hex
        with SessionLocal() as session:
            task = TaskExecution(
                task_id=task_id,
                task_name=task_name,
                task_type=task_type,
                status=status,
                progress_percentage=progress_percentage,
                current_step=current_step,
                context_json=context,
            )
            session.add(task)
            session.commit()
        self._console(status, task_name, current_step)
        return {"task_id": task_id, "task_name": task_name, "task_type": task_type, "status": status}

    def update_task_progress(
        self,
        task_id: str,
        *,
        progress_percentage: int | None = None,
        current_step: str | None = None,
        status: str | None = "running",
    ) -> dict[str, object]:
        """Update task progress and step."""
        with SessionLocal() as session:
            task = session.scalar(select(TaskExecution).where(TaskExecution.task_id == task_id))
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            if progress_percentage is not None:
                task.progress_percentage = max(0, min(100, int(progress_percentage)))
            if current_step is not None:
                task.current_step = current_step
            if status is not None and task.status not in FINAL_TASK_STATES:
                task.status = status
            task.updated_at = datetime.utcnow()
            session.commit()
            payload = self._serialize(task)
        if status == "running" or (status is None and payload["status"] == "running"):
            self._console("running", payload["task_name"], current_step or payload["current_step"])
        return payload

    def complete_task(self, task_id: str, *, current_step: str = "Completed") -> dict[str, object]:
        """Mark a task as completed."""
        with SessionLocal() as session:
            task = session.scalar(select(TaskExecution).where(TaskExecution.task_id == task_id))
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            task.status = "completed"
            task.progress_percentage = 100
            task.current_step = current_step
            task.finish_time = datetime.utcnow()
            task.execution_duration_seconds = self._duration_seconds(task.start_time, task.finish_time)
            session.commit()
            payload = self._serialize(task)
        self._console("success", payload["task_name"], current_step)
        return payload

    def fail_task(
        self,
        task_id: str,
        *,
        error_message: str,
        current_step: str,
        traceback_summary: str | None = None,
    ) -> dict[str, object]:
        """Mark a task as failed."""
        with SessionLocal() as session:
            task = session.scalar(select(TaskExecution).where(TaskExecution.task_id == task_id))
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            task.status = "failed"
            task.current_step = current_step
            task.error_message = error_message
            task.traceback_summary = traceback_summary
            task.finish_time = datetime.utcnow()
            task.execution_duration_seconds = self._duration_seconds(task.start_time, task.finish_time)
            session.commit()
            payload = self._serialize(task)
        self._console("failed", payload["task_name"], f"{current_step}: {error_message}")
        return payload

    def cancel_task(self, task_id: str, *, current_step: str = "Cancelled") -> dict[str, object]:
        """Mark a task as cancelled."""
        with SessionLocal() as session:
            task = session.scalar(select(TaskExecution).where(TaskExecution.task_id == task_id))
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            task.status = "cancelled"
            task.current_step = current_step
            task.finish_time = datetime.utcnow()
            task.execution_duration_seconds = self._duration_seconds(task.start_time, task.finish_time)
            session.commit()
            return self._serialize(task)

    def get_task(self, task_id: str) -> dict[str, object]:
        """Get one task."""
        with SessionLocal() as session:
            task = session.scalar(select(TaskExecution).where(TaskExecution.task_id == task_id))
            if task is None:
                raise ValueError(f"Task {task_id} not found")
            return self._serialize(task)

    def list_tasks(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        """List task records."""
        with SessionLocal() as session:
            stmt = select(TaskExecution).order_by(TaskExecution.start_time.desc()).limit(limit)
            if status:
                stmt = stmt.where(TaskExecution.status == status)
            tasks = session.scalars(stmt).all()
            return [self._serialize(task) for task in tasks]

    def get_running_tasks(self) -> list[dict[str, object]]:
        """Return running and pending tasks."""
        with SessionLocal() as session:
            tasks = session.scalars(
                select(TaskExecution)
                .where(TaskExecution.status.in_(["pending", "running"]))
                .order_by(TaskExecution.start_time.desc())
            ).all()
            return [self._serialize(task) for task in tasks]

    def delete_task(self, task_id: str) -> None:
        """Delete a task record."""
        with SessionLocal() as session:
            session.execute(delete(TaskExecution).where(TaskExecution.task_id == task_id))
            session.commit()

    def find_running_task(self, task_type: str, *, context: dict | None = None) -> dict[str, object] | None:
        """Find a running task by type and optional context."""
        for task in self.get_running_tasks():
            if task["task_type"] != task_type:
                continue
            if context:
                task_context = task.get("context_json") or {}
                if any(task_context.get(key) != value for key, value in context.items()):
                    continue
            return task
        return None

    def fail_task_from_exception(self, task_id: str, *, current_step: str, exc: Exception) -> dict[str, object]:
        """Fail a task using an exception object."""
        return self.fail_task(
            task_id,
            error_message=str(exc),
            current_step=current_step,
            traceback_summary=self._summarize_traceback(),
        )

    def _serialize(self, task: TaskExecution) -> dict[str, object]:
        finish_time = task.finish_time or (datetime.utcnow() if task.status in {"pending", "running"} else None)
        duration = task.execution_duration_seconds
        if duration is None and finish_time is not None:
            duration = self._duration_seconds(task.start_time, finish_time)
        return {
            "task_id": task.task_id,
            "task_name": task.task_name,
            "task_type": task.task_type,
            "status": task.status,
            "progress_percentage": task.progress_percentage,
            "current_step": task.current_step or "",
            "context_json": task.context_json or {},
            "start_time": task.start_time,
            "finish_time": task.finish_time,
            "execution_duration_seconds": duration,
            "error_message": task.error_message or "",
            "traceback_summary": task.traceback_summary or "",
        }

    def _duration_seconds(self, start_time: datetime, finish_time: datetime) -> float:
        return round((finish_time - start_time).total_seconds(), 2)

    def _summarize_traceback(self) -> str:
        lines = traceback.format_exc().strip().splitlines()
        return "\n".join(lines[-8:]) if lines else ""

    def _console(self, status: str, task_name: str, detail: str | None) -> None:
        prefix = {
            "pending": "[PENDING]",
            "running": "[RUNNING]",
            "completed": "[SUCCESS]",
            "success": "[SUCCESS]",
            "failed": "[FAILED]",
            "cancelled": "[CANCELLED]",
        }.get(status, "[TASK]")
        message = f"{prefix} {task_name}"
        if detail:
            message = f"{message} - {detail}"
        print(message)
