from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ai.matcher import JobMatcher
from backend.models import GeneratedDocument, Job
from collectors.apply_utils import detect_easy_apply
from collectors.base import CollectedJob
from collectors.content_extractor import ExtractionResult
from collectors.location_utils import detect_work_mode, normalize_location


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
    diff_response = client.get(f"/jobs/{job.id}/cv/diff")
    base_pdf_response = client.get(f"/cv/base/pdf?job_id={job.id}")
    tailored_pdf_response = client.get(f"/jobs/{job.id}/cv/pdf")

    assert base_response.status_code == 200
    assert "# Base CV" in base_response.json()["content"]
    assert job_response.status_code == 200
    assert "Tailored CV" in job_response.json()["tailored_cv_content"]
    assert diff_response.status_code == 200
    assert any(line.startswith("+") or line.startswith("-") for line in diff_response.json()["diff_lines"])
    assert base_pdf_response.status_code == 200
    assert base_pdf_response.headers["content-type"] == "application/pdf"
    assert base_pdf_response.content.startswith(b"%PDF")
    assert tailored_pdf_response.status_code == 200
    assert tailored_pdf_response.content.startswith(b"%PDF")
    assert 'filename="tailored_cv_' in tailored_pdf_response.headers["content-disposition"]


def test_job_cv_pdf_endpoint_requires_existing_tailored_cv(isolated_env):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\n")
    job = _create_job(session_factory, slug="no-tailored-yet")

    response = client.get(f"/jobs/{job.id}/cv/pdf")

    assert response.status_code == 400
    assert "No tailored CV exists" in response.json()["detail"]


def test_interview_simulation_generation_and_export(isolated_env):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\nTypeScript\nNode.js\nDocker\n")
    job = _create_job(
        session_factory,
        slug="interview-sim",
        company="Luvo",
        title="Backend Developer (TypeScript/Node.js)",
        required_skills=["TypeScript", "Node.js", "Docker", "REST APIs"],
        preferred_skills=["AWS"],
        missing_skills=["AWS"],
        raw_payload={"content_extraction": {"is_complete": True}},
    )

    response = client.post(f"/jobs/{job.id}/interview-simulation")
    fetch_response = client.get(f"/jobs/{job.id}/interview-simulation")
    pdf_response = client.get(f"/jobs/{job.id}/interview-simulation/pdf")

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["markdown_path"].endswith(".md")
    assert payload["json_path"].endswith(".json")
    assert fetch_response.status_code == 200
    simulation = fetch_response.json()["simulation"]
    assert simulation["company"] == "Luvo"
    assert simulation["readiness_scores"]["overall_interview_readiness_score"] >= 35
    assert any(section["section_name"] == "Technical Questions" for section in simulation["sections"])
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF")

    with session_factory() as session:
        documents = session.scalars(select(GeneratedDocument).where(GeneratedDocument.job_id == job.id)).all()
        assert any(doc.doc_type == "interview_simulation_md" for doc in documents)
        assert any(doc.doc_type == "interview_simulation_json" for doc in documents)


def test_interactive_interview_question_and_answer_evaluation(isolated_env):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    _write_base_cv(service, "# Base CV\n\nPython\nTypeScript\nNode.js\nDocker\n")
    job = _create_job(
        session_factory,
        slug="interactive-interview",
        company="Signal Labs",
        title="Senior Backend Engineer",
        required_skills=["Python", "Docker", "REST APIs"],
        raw_payload={"content_extraction": {"is_complete": True}},
    )

    generate_response = client.post(f"/jobs/{job.id}/interview-simulation")
    question_response = client.post(f"/jobs/{job.id}/interview-simulation/interactive?question_index=0")
    evaluation_response = client.post(
        "/jobs/interview-answer-evaluation",
        json={
            "job_id": job.id,
            "question_id": question_response.json()["payload"]["question"]["id"],
            "answer": "I would align my experience in Python and APIs with the role, explain impact, and give concrete examples.",
        },
    )

    assert generate_response.status_code == 200
    assert question_response.status_code == 200
    assert question_response.json()["payload"]["total_questions"] >= 1
    assert evaluation_response.status_code == 200
    evaluation = evaluation_response.json()["payload"]
    assert evaluation["question_id"]
    assert evaluation["score"] >= 25
    assert evaluation["improved_answer"]


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


def test_location_normalization_prefers_city_and_detects_remote():
    location = normalize_location(full_location="Perth, Western Australia, Australia", raw_location="Perth WA", title="Senior Engineer", description="")
    is_remote, work_mode = detect_work_mode(title="Remote Backend Engineer", description="Work from home role", location_text="Anywhere in Australia")

    assert location["city"] == "Perth"
    assert location["state"] == "WA"
    assert location["country"] == "Australia"
    assert location["full_location"] == "Perth, Australia"
    assert is_remote == "Yes"
    assert work_mode == "remote"


def test_location_normalization_avoids_state_as_city():
    assert normalize_location(full_location="New South Wales, Australia")["full_location"] == "Unknown, Australia"
    assert normalize_location(full_location="Western Australia, Australia")["full_location"] == "Unknown, Australia"
    assert normalize_location(full_location="Victoria, Australia")["full_location"] == "Unknown, Australia"
    assert normalize_location(full_location="Sydney, New South Wales, Australia")["full_location"] == "Sydney, Australia"
    assert normalize_location(full_location="Perth, Western Australia, Australia")["full_location"] == "Perth, Australia"
    assert normalize_location(full_location="Melbourne, Victoria, Australia")["full_location"] == "Melbourne, Australia"
    assert normalize_location(full_location="Remote, Australia", title="Remote role")["full_location"] == "Remote, Australia"


def test_dashboard_remote_filter_and_precise_location(isolated_env):
    session_factory = isolated_env["SessionLocal"]
    dashboard_services = isolated_env["dashboard_services"]

    _create_job(
        session_factory,
        slug="remote-job",
        required_skills=["Python"],
        raw_payload={"content_extraction": {"is_complete": True}},
    )
    with session_factory() as session:
        remote_job = session.scalar(select(Job).where(Job.url == "https://example.com/jobs/remote-job"))
        remote_job.city = "Perth"
        remote_job.state = "WA"
        remote_job.country = "Australia"
        remote_job.full_location = "Perth, Australia"
        remote_job.raw_location = "Perth"
        remote_job.is_remote = "Yes"
        session.commit()

    _create_job(
        session_factory,
        slug="hybrid-job",
        required_skills=["Python"],
        raw_payload={"content_extraction": {"is_complete": True}},
    )
    with session_factory() as session:
        hybrid_job = session.scalar(select(Job).where(Job.url == "https://example.com/jobs/hybrid-job"))
        hybrid_job.city = "Sydney"
        hybrid_job.state = "NSW"
        hybrid_job.country = "Australia"
        hybrid_job.full_location = "Sydney, Australia"
        hybrid_job.raw_location = "Sydney"
        hybrid_job.is_remote = "Hybrid"
        session.commit()

    dashboard_services.get_jobs_data.clear()
    remote_jobs = dashboard_services.get_jobs_data(
        dashboard_services.JobFilters(minimum_match_score=0, remote_status="Remote only", location="Perth")
    )
    hybrid_jobs = dashboard_services.get_jobs_data(
        dashboard_services.JobFilters(minimum_match_score=0, remote_status="Hybrid only")
    )

    assert len(remote_jobs) == 1
    assert remote_jobs[0]["location"] == "Perth, Australia"
    assert remote_jobs[0]["remote_status"] == "Yes"
    assert len(hybrid_jobs) == 1
    assert hybrid_jobs[0]["remote_status"] == "Hybrid"


def test_easy_apply_detection_from_metadata_url_and_description():
    metadata_result = detect_easy_apply(source="adzuna", url="https://example.com/apply", description="Standard flow", metadata={"apply_options": "Easy Apply available"})
    url_result = detect_easy_apply(source="jsearch", url="https://jobs.example.com/easyapply/123", description="Standard flow", metadata={})
    text_result = detect_easy_apply(source="serpapi", url="https://jobs.example.com/apply", description="Apply in one click through our fast application process", metadata={})
    unknown_result = detect_easy_apply(source="serpapi", url="https://linkedin.com/jobs/view/123", description="Apply now", metadata={})

    assert metadata_result["easy_apply"] == "Yes"
    assert metadata_result["easy_apply_detection_source"] == "adzuna_metadata"
    assert url_result["easy_apply"] == "Yes"
    assert url_result["easy_apply_detection_source"] == "apply_url_pattern"
    assert text_result["easy_apply"] == "Yes"
    assert text_result["easy_apply_detection_source"] == "description_text"
    assert unknown_result["easy_apply"] == "Unknown"


def test_adzuna_easy_apply_detection_from_metadata_html_and_external_url():
    metadata_result = detect_easy_apply(
        source="adzuna",
        url="https://www.adzuna.com.au/details/5713940148?utm_medium=api",
        description="Standard flow",
        metadata={"directApply": "True", "reply_to_ad": 1},
    )
    html_result = detect_easy_apply(
        source="adzuna",
        url="https://www.adzuna.com.au/details/5713940148?utm_medium=api",
        description="Standard flow",
        metadata={"redirect_url": "https://www.adzuna.com.au/details/5713940148?utm_medium=api"},
        page_text="Backend Developer EASY APPLY Apply for this job",
    )
    external_result = detect_easy_apply(
        source="adzuna",
        url="https://careers.example.com/apply/backend-developer",
        description="Standard flow",
        metadata={"redirect_url": "https://careers.example.com/apply/backend-developer"},
    )
    unknown_result = detect_easy_apply(
        source="adzuna",
        url="https://www.adzuna.com.au/details/9999?utm_medium=api",
        description="Standard flow",
        metadata={"redirect_url": "https://www.adzuna.com.au/details/9999?utm_medium=api"},
    )

    assert metadata_result["easy_apply"] == "Yes"
    assert metadata_result["easy_apply_type"] == "Easy Apply"
    assert metadata_result["easy_apply_detection_source"] == "adzuna_metadata"
    assert html_result["easy_apply"] == "Yes"
    assert html_result["easy_apply_detection_source"] == "adzuna_html_badge"
    assert external_result["easy_apply"] == "No"
    assert external_result["easy_apply_type"] == "External Apply"
    assert external_result["easy_apply_detection_source"] == "external_apply_url"
    assert unknown_result["easy_apply"] == "Unknown"


def test_adzuna_easy_apply_backfill_updates_existing_jobs(isolated_env, monkeypatch):
    service = isolated_env["service"]
    client = isolated_env["client"]
    session_factory = isolated_env["SessionLocal"]

    job = _create_job(
        session_factory,
        slug="adzuna-backfill",
        source="adzuna",
        company="luvo",
        title="Backend Developer (TypeScript/Node.js)",
        url="https://www.adzuna.com.au/details/5713940148?utm_medium=api",
        raw_payload={"redirect_url": "https://www.adzuna.com.au/details/5713940148?utm_medium=api"},
    )

    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        stored_job.easy_apply = "Unknown"
        stored_job.easy_apply_type = "Unknown"
        stored_job.easy_apply_detection_source = "platform_apply_flow"
        session.commit()

    monkeypatch.setattr(
        service.content_extractor,
        "extract",
        lambda url, preview_text: ExtractionResult(
            full_text="Backend Developer EASY APPLY Apply for this job directApply True",
            sections={"general": ["Backend Developer EASY APPLY Apply for this job directApply True"]},
            warnings=[],
            source_method="test",
            is_complete=True,
        ),
    )

    response = client.post("/jobs/backfill-easy-apply?source=adzuna")

    assert response.status_code == 200
    assert response.json()["payload"]["updated"] >= 1

    with session_factory() as session:
        stored_job = session.get(Job, job.id)
        assert stored_job.easy_apply == "Yes"
        assert stored_job.easy_apply_type == "Easy Apply"
        assert stored_job.easy_apply_detection_source in {"adzuna_metadata", "adzuna_html_badge"}


def test_dashboard_easy_apply_filter_behavior(isolated_env):
    session_factory = isolated_env["SessionLocal"]
    dashboard_services = isolated_env["dashboard_services"]

    _create_job(session_factory, slug="easy-apply-yes", required_skills=["Python"], raw_payload={"content_extraction": {"is_complete": True}})
    _create_job(session_factory, slug="easy-apply-no", required_skills=["Python"], raw_payload={"content_extraction": {"is_complete": True}})
    _create_job(session_factory, slug="easy-apply-unknown", required_skills=["Python"], raw_payload={"content_extraction": {"is_complete": True}})

    with session_factory() as session:
        yes_job = session.scalar(select(Job).where(Job.url == "https://example.com/jobs/easy-apply-yes"))
        no_job = session.scalar(select(Job).where(Job.url == "https://example.com/jobs/easy-apply-no"))
        unknown_job = session.scalar(select(Job).where(Job.url == "https://example.com/jobs/easy-apply-unknown"))
        yes_job.easy_apply = "Yes"
        yes_job.easy_apply_type = "Easy Apply"
        no_job.easy_apply = "No"
        no_job.easy_apply_type = "External Apply"
        unknown_job.easy_apply = "Unknown"
        unknown_job.easy_apply_type = "Unknown"
        session.commit()

    dashboard_services.get_jobs_data.clear()
    easy_only = dashboard_services.get_jobs_data(dashboard_services.JobFilters(minimum_match_score=0, easy_apply_filter="Easy Apply only"))
    non_easy = dashboard_services.get_jobs_data(dashboard_services.JobFilters(minimum_match_score=0, easy_apply_filter="Non-Easy Apply"))
    unknown = dashboard_services.get_jobs_data(dashboard_services.JobFilters(minimum_match_score=0, easy_apply_filter="Unknown"))

    assert len(easy_only) == 1
    assert easy_only[0]["easy_apply"] == "Yes"
    assert len(non_easy) == 1
    assert non_easy[0]["easy_apply"] == "No"
    assert len(unknown) == 1
    assert unknown[0]["easy_apply"] == "Unknown"
