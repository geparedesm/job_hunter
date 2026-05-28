"""FastAPI application for the personal AI job hunter."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from backend.schemas import ActionResponse, InterviewAnswerEvaluationRequest, JobRead, SearchResponse, StatisticsRead, TaskRead
from backend.services import JobHunterService
from backend.task_manager import TaskManager

app = FastAPI(title="Personal AI Job Hunter", version="0.1.0")
service = JobHunterService()
task_manager = TaskManager()


@app.get("/health")
def health() -> dict[str, str]:
    """Simple health check."""
    return {"status": "ok"}


@app.get("/tasks", response_model=list[TaskRead])
def list_tasks() -> list[TaskRead]:
    """List tracked tasks."""
    return [TaskRead(**task) for task in task_manager.list_tasks()]


@app.get("/tasks/running", response_model=list[TaskRead])
def list_running_tasks() -> list[TaskRead]:
    """List running or pending tasks."""
    return [TaskRead(**task) for task in task_manager.get_running_tasks()]


@app.get("/tasks/{task_id}", response_model=TaskRead)
def get_task(task_id: str) -> TaskRead:
    """Get a tracked task by id."""
    try:
        return TaskRead(**task_manager.get_task(task_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/tasks/{task_id}", response_model=ActionResponse)
def delete_task(task_id: str) -> ActionResponse:
    """Delete a tracked task by id."""
    task_manager.delete_task(task_id)
    return ActionResponse(success=True, message="Task deleted", payload={"task_id": task_id})


@app.get("/jobs", response_model=list[JobRead])
def list_jobs(
    keyword: str | None = None,
    source: str | None = None,
    status: str | None = None,
    minimum_match_score: float | None = None,
) -> list[JobRead]:
    """List stored jobs."""
    return [JobRead.model_validate(job) for job in service.list_jobs(keyword, source, status, minimum_match_score)]


@app.get("/jobs/{job_id}")
def get_job(job_id: int) -> dict[str, object]:
    """Fetch job details with latest generated documents."""
    try:
        details = service.get_job_details(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "job": JobRead.model_validate(details["job"]).model_dump(),
        "generated_cv": details["generated_cv"],
        "generated_cover_letter": details["generated_cover_letter"],
        "generated_cv_path": details.get("generated_cv_path", ""),
        "generated_cover_letter_path": details.get("generated_cover_letter_path", ""),
    }


@app.post("/search", response_model=SearchResponse)
def search_now() -> SearchResponse:
    """Run an immediate search cycle."""
    return SearchResponse(**service.search_now())


@app.get("/cv/base")
def get_base_cv() -> dict[str, object]:
    """Return the base CV preview payload."""
    payload = service.get_base_cv()
    return payload


@app.get("/jobs/{job_id}/cv")
def get_job_cv(job_id: int) -> dict[str, object]:
    """Return the tailored CV preview payload for a selected job."""
    try:
        return service.get_job_cv(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}/cv/diff")
def get_job_cv_diff(job_id: int) -> dict[str, object]:
    """Return a Git-style diff between base and tailored CV."""
    try:
        return service.get_job_cv_diff(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/cv/base/pdf")
def get_base_cv_pdf(job_id: int | None = None) -> FileResponse:
    """Export the base CV PDF on demand."""
    try:
        path = service.export_base_cv_pdf(job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/jobs/{job_id}/cv/pdf")
def get_job_cv_pdf(job_id: int) -> FileResponse:
    """Export the tailored CV PDF on demand."""
    try:
        path = service.export_job_cv_pdf(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/jobs/{job_id}/interview-simulation")
def get_interview_simulation(job_id: int) -> dict[str, object]:
    """Return the latest interview simulation for a selected job."""
    try:
        return service.get_interview_simulation(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/jobs/{job_id}/interview-simulation/pdf")
def get_interview_simulation_pdf(job_id: int) -> FileResponse:
    """Export the interview simulation PDF on demand."""
    try:
        path = service.export_interview_simulation_pdf(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/jobs/{job_id}/generate", response_model=ActionResponse)
def generate_documents(job_id: int) -> ActionResponse:
    """Document generation is manual-only in this version."""
    try:
        payload = service.generate_documents(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Documents generated", payload=payload)


@app.post("/jobs/{job_id}/generate-cv", response_model=ActionResponse)
def generate_cv(job_id: int) -> ActionResponse:
    """Generate a tailored CV only after an explicit user action."""
    try:
        payload = service.generate_tailored_cv(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Tailored CV generated", payload=payload)


@app.post("/jobs/{job_id}/generate-cover-letter", response_model=ActionResponse)
def generate_cover_letter(job_id: int) -> ActionResponse:
    """Generate a cover letter only after an explicit user action."""
    try:
        payload = service.generate_cover_letter(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Cover letter generated", payload=payload)


@app.post("/jobs/{job_id}/interview-simulation", response_model=ActionResponse)
def generate_interview_simulation(job_id: int) -> ActionResponse:
    """Generate an interview simulation only after an explicit user action."""
    try:
        payload = service.generate_interview_simulation(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Interview simulation generated", payload=payload)


@app.post("/jobs/{job_id}/interview-simulation/interactive", response_model=ActionResponse)
def interactive_interview_question(job_id: int, question_index: int = 0) -> ActionResponse:
    """Return a single interview question for interactive mode."""
    try:
        payload = service.start_interactive_interview(job_id, question_index=question_index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Interactive interview question loaded", payload=payload)


@app.post("/jobs/interview-answer-evaluation", response_model=ActionResponse)
def evaluate_interview_answer(request: InterviewAnswerEvaluationRequest) -> ActionResponse:
    """Evaluate a user answer against the interview simulation."""
    try:
        payload = service.evaluate_interview_answer(request.job_id, request.question_id, request.answer)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Interview answer evaluated", payload=payload)


@app.post("/jobs/{job_id}/recalculate-match", response_model=ActionResponse)
def recalculate_match(job_id: int) -> ActionResponse:
    """Recalculate base and tailored match scores for a job."""
    try:
        payload = service.recalculate_match(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Match scores recalculated", payload=payload)


@app.post("/jobs/backfill-easy-apply", response_model=ActionResponse)
def backfill_easy_apply(source: str = "adzuna", limit: int | None = None) -> ActionResponse:
    """Manually re-check Easy Apply detection for existing jobs."""
    try:
        payload = service.backfill_easy_apply(source=source, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Easy Apply backfill completed", payload=payload)


@app.post("/jobs/{job_id}/approve", response_model=ActionResponse)
def approve_job(job_id: int) -> ActionResponse:
    """Approve a job for later application automation."""
    try:
        job = service.approve_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Job approved", payload={"job_id": job.id, "status": job.status})


@app.post("/jobs/{job_id}/reject", response_model=ActionResponse)
def reject_job(job_id: int) -> ActionResponse:
    """Reject a job."""
    try:
        job = service.reject_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Job rejected", payload={"job_id": job.id, "status": job.status})


@app.post("/jobs/{job_id}/skip", response_model=ActionResponse)
def skip_job(job_id: int) -> ActionResponse:
    """Skip a job."""
    try:
        job = service.skip_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionResponse(success=True, message="Job skipped", payload={"job_id": job.id, "status": job.status})


@app.post("/jobs/{job_id}/apply", response_model=ActionResponse)
def apply_to_job(job_id: int) -> ActionResponse:
    """Run application automation after approval."""
    try:
        result = service.apply_to_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActionResponse(success=True, message=result.message, payload={"status": result.status})


@app.get("/approvals", response_model=list[JobRead])
def pending_approvals() -> list[JobRead]:
    """List pending approvals."""
    return [JobRead.model_validate(job) for job in service.get_pending_approvals()]


@app.get("/statistics", response_model=StatisticsRead)
def statistics() -> StatisticsRead:
    """Return dashboard statistics."""
    return StatisticsRead(**service.get_statistics())


@app.get("/export", response_model=ActionResponse)
def export_csv() -> ActionResponse:
    """Export applications to CSV."""
    path = service.export_applications_csv()
    return ActionResponse(success=True, message="Applications exported", payload={"path": str(path)})
