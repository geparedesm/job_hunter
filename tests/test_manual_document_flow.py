from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai.matcher import JobMatcher
from backend.models import GeneratedDocument, Job
from collectors.base import CollectedJob
from collectors.content_extractor import ExtractionResult


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    import backend.api as api_module
    import backend.database as database_module
    import backend.services as services_module
    import dashboard.services as dashboard_services

    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(services_module, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(dashboard_services, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(services_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(dashboard_services, "PROJECT_ROOT", tmp_path)

    database_module.Base.metadata.create_all(bind=engine)
    database_module.init_db()

    service = services_module.JobHunterService()
    monkeypatch.setattr(service, "_base_cv_path", lambda: tmp_path / "base_cv.md")
    monkeypatch.setattr(api_module, "service", service)
    dashboard_services.clear_dashboard_caches()

    return {
        "service": service,
        "SessionLocal": TestingSessionLocal,
        "tmp_path": tmp_path,
        "client": TestClient(api_module.app),
        "dashboard_services": dashboard_services,
    }


def _write_base_cv(service, content: str) -> None:
    path = service._base_cv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_job(session_factory, **overrides) -> Job:
    job = Job(
        source=overrides.get("source", "adzuna"),
        company=overrides.get("company", "Example Co"),
        title=overrides.get("title", "Backend Developer"),
        description=overrides.get(
            "description",
            "Build backend services with Python, Docker, and REST APIs.",
        ),
        url=overrides.get("url", f"https://example.com/jobs/{overrides.get('slug', '1')}"),
        location=overrides.get("location", "Perth"),
        status=overrides.get("status", "pending_approval"),
        required_skills=overrides.get("required_skills", []),
        preferred_skills=overrides.get("preferred_skills", []),
        missing_skills=overrides.get("missing_skills", []),
        raw_payload=overrides.get("raw_payload", {}),
        found_at=overrides.get("found_at", datetime.now(timezone.utc).replace(tzinfo=None)),
    )
    with session_factory() as session:
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def test_required_skills_extraction_from_plain_description():
    matcher = JobMatcher()
    job = Job(
        source="manual",
        company="Signal Labs",
        title="Senior Python Backend Engineer",
        description="We build APIs with Python, FastAPI, Docker, PostgreSQL, and AWS.",
        url="https://example.com/plain-description",
        raw_payload={},
    )
    result = matcher.analyze_job(
        job,
        "Python and FastAPI",
        extracted_sections={
            "requirements": [
                "Strong Python and FastAPI experience",
                "Hands-on with Docker and PostgreSQL",
            ],
            "responsibilities": ["Build REST APIs and deploy to AWS"],
        },
    )

    assert {"Python", "FastAPI", "Docker", "PostgreSQL", "AWS", "REST APIs"}.issubset(set(result.required_skills))


def test_required_skills_extraction_from_structured_metadata():
    matcher = JobMatcher()
    job = Job(
        source="jsearch",
        company="MetaStack",
        title="Platform Engineer",
        description="",
        url="https://example.com/metadata",
        raw_payload={
            "job_highlights": {
                "Qualifications": ["TypeScript", "Node.js", "AWS"],
                "Benefits": ["Remote"],
            },
            "job_required_skills": ["GraphQL", "Docker"],
            "job_tags": ["Kubernetes"],
        },
    )

    result = matcher.analyze_job(job, "TypeScript", extracted_sections={"general": ["Platform engineering role"]})

    assert {"TypeScript", "Node.js", "AWS", "GraphQL", "Docker", "Kubernetes"}.issubset(set(result.required_skills))


def test_dashboard_filter_hides_jobs_without_required_skills(isolated_env):
    session_factory = isolated_env["SessionLocal"]
    dashboard_services = isolated_env["dashboard_services"]

    _create_job(
        session_factory,
        slug="with-skills",
        required_skills=["Python", "Docker"],
        raw_payload={"content_extraction": {"is_complete": True}},
    )
    _create_job(
        session_factory,
        slug="without-skills",
        required_skills=[],
        raw_payload={"content_extraction": {"is_complete": True}},
    )

    dashboard_services.get_jobs_data.clear()
    jobs = dashboard_services.get_jobs_data(
        dashboard_services.JobFilters(minimum_match_score=0, required_skills_only=True)
    )

    assert len(jobs) == 1
    assert jobs[0]["required_skills_detected"] is True


def test_manual_cv_generation_endpoint(isolated_env, monkeypatch):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")
    job = _create_job(
        session_factory,
        slug="generate-cv",
        raw_payload={
            "content_extraction": {
                "sections": {
                    "requirements": ["Python", "Docker", "React"],
                }
            }
        },
    )

    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        service._analyze_job(session, stored_job)

    monkeypatch.setattr(service.cv_adapter, "generate", lambda job, base_cv: "# Tailored CV\n\nPython\nDocker\nReact\n")

    response = client.post(f"/jobs/{job.id}/generate-cv")

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["path"].endswith("tailored_cv.md")

    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        documents = session.scalars(select(GeneratedDocument).where(GeneratedDocument.job_id == job.id)).all()
        assert stored_job.tailored_cv_path
        assert Path(stored_job.tailored_cv_path).exists()
        assert stored_job.tailored_cv_match_score is not None
        assert any(doc.doc_type == "cv" for doc in documents)


def test_manual_cover_letter_generation_endpoint(isolated_env, monkeypatch):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")
    job = _create_job(session_factory, slug="cover-letter")
    monkeypatch.setattr(service.cover_letter_generator, "generate", lambda job, base_cv: "# Cover Letter\n\nHello team.\n")

    response = client.post(f"/jobs/{job.id}/generate-cover-letter")

    assert response.status_code == 200
    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        documents = session.scalars(
            select(GeneratedDocument).where(GeneratedDocument.job_id == job.id, GeneratedDocument.doc_type == "cover_letter")
        ).all()
        assert stored_job.cover_letter_path
        assert Path(stored_job.cover_letter_path).exists()
        assert documents


def test_match_score_before_and_after_tailored_cv_generation(isolated_env, monkeypatch):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")
    job = _create_job(
        session_factory,
        slug="recalculate",
        raw_payload={
            "content_extraction": {
                "sections": {
                    "requirements": ["Python", "Docker", "React"],
                    "responsibilities": ["Build REST APIs"],
                }
            }
        },
    )

    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        service._analyze_job(session, stored_job)
        base_score = stored_job.base_match_score

    monkeypatch.setattr(service.cv_adapter, "generate", lambda job, base_cv: "# Tailored CV\n\nPython\nDocker\nReact\nREST APIs\n")
    generate_response = client.post(f"/jobs/{job.id}/generate-cv")
    recalc_response = client.post(f"/jobs/{job.id}/recalculate-match")

    assert generate_response.status_code == 200
    assert recalc_response.status_code == 200

    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        assert stored_job.base_match_score == base_score
        assert stored_job.tailored_cv_match_score is not None
        assert stored_job.tailored_cv_match_score > stored_job.base_match_score


def test_scheduler_search_does_not_generate_documents(isolated_env, monkeypatch):
    service = isolated_env["service"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")

    class FakeCollector:
        source_name = "fake"

        def search(self):
            return [
                CollectedJob(
                    source="adzuna",
                    external_id="ext-1",
                    title="Python Developer",
                    company="Safe Search Co",
                    description="Python Docker REST APIs",
                    location="Perth",
                    salary=None,
                    url="https://example.com/scheduler-job",
                    raw_payload={"tags": ["Python", "Docker"]},
                )
            ]

    monkeypatch.setattr(service, "_collectors", lambda: [FakeCollector()])
    monkeypatch.setattr(
        service.content_extractor,
        "extract",
        lambda url, preview_text: ExtractionResult(
            full_text=preview_text,
            sections={"requirements": [preview_text]},
            warnings=[],
            source_method="test",
            is_complete=True,
        ),
    )
    monkeypatch.setattr(service.cv_adapter, "generate", lambda *args, **kwargs: pytest.fail("scheduler generated a CV"))
    monkeypatch.setattr(
        service.cover_letter_generator,
        "generate",
        lambda *args, **kwargs: pytest.fail("scheduler generated a cover letter"),
    )

    summary = service.search_jobs()

    assert summary.created == 1
    with session_factory() as session:
        stored_job = session.scalar(select(Job).where(Job.url == "https://example.com/scheduler-job"))
        documents = session.scalars(select(GeneratedDocument)).all()
        assert stored_job is not None
        assert stored_job.tailored_cv_path is None
        assert stored_job.cover_letter_path is None
        assert documents == []


def test_cv_preview_endpoints_and_pdf_exports(isolated_env, monkeypatch):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\nDocker\n")
    job = _create_job(
        session_factory,
        slug="cv-preview",
        company="Preview Labs",
        title="Platform Engineer",
    )

    monkeypatch.setattr(service.cv_adapter, "generate", lambda job, base_cv: "# Tailored CV\n\nPython\nDocker\nKubernetes\n")
    client.post(f"/jobs/{job.id}/generate-cv")

    base_response = client.get("/cv/base")
    job_response = client.get(f"/jobs/{job.id}/cv")
    base_pdf_response = client.get(f"/cv/base/pdf?job_id={job.id}")
    tailored_pdf_response = client.get(f"/jobs/{job.id}/cv/pdf")

    assert base_response.status_code == 200
    assert "# Base CV" in base_response.json()["content"]
    assert job_response.status_code == 200
    assert "Tailored CV" in job_response.json()["tailored_cv_content"]
    assert base_pdf_response.status_code == 200
    assert base_pdf_response.headers["content-type"] == "application/pdf"
    assert base_pdf_response.content.startswith(b"%PDF")
    assert tailored_pdf_response.status_code == 200
    assert tailored_pdf_response.content.startswith(b"%PDF")


def test_job_cv_pdf_endpoint_requires_existing_tailored_cv(isolated_env):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")
    job = _create_job(session_factory, slug="no-tailored-yet")

    response = client.get(f"/jobs/{job.id}/cv/pdf")

    assert response.status_code == 400
    assert "No tailored CV exists" in response.json()["detail"]


def test_task_endpoints_and_completed_task_tracking(isolated_env, monkeypatch):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")
    job = _create_job(session_factory, slug="task-tracking", company="Task Co", title="Backend Engineer")
    monkeypatch.setattr(service.cv_adapter, "generate", lambda job, base_cv: "# Tailored CV\n\nPython\nDocker\n")

    response = client.post(f"/jobs/{job.id}/generate-cv")

    assert response.status_code == 200
    tasks_response = client.get("/tasks")
    running_response = client.get("/tasks/running")
    assert tasks_response.status_code == 200
    tasks = tasks_response.json()
    assert any(task["task_type"] == "tailored_cv_generation" and task["status"] == "completed" for task in tasks)
    assert running_response.status_code == 200
    assert all(task["status"] in {"pending", "running"} for task in running_response.json())

    tracked_task = next(task for task in tasks if task["task_type"] == "tailored_cv_generation")
    single_response = client.get(f"/tasks/{tracked_task['task_id']}")
    assert single_response.status_code == 200
    assert single_response.json()["progress_percentage"] == 100

    delete_response = client.delete(f"/tasks/{tracked_task['task_id']}")
    assert delete_response.status_code == 200
