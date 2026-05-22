# Personal AI Job Hunter

Personal AI-powered job hunting assistant for Clawbot. This project searches software developer jobs on a schedule, analyzes them against a base CV, generates tailored application documents, and only applies after explicit user approval.

## MVP Features

- FastAPI backend for search, analysis, approvals, exports, and automation triggers
- SQLite persistence with SQLAlchemy and PostgreSQL-friendly models
- Streamlit dashboard for statistics, charts, filters, and job actions
- APScheduler background search every 12 hours
- API-first collectors for Adzuna, JSearch, and SerpApi Google Jobs
- OpenAI-assisted job analysis, CV tailoring, and cover letter generation
- Console notifications with extensible notifier interfaces
- Playwright automation gated behind explicit approval
- Clawbot integration surface in `skills/job_hunter/skill.py`

## Project Layout

```text
job_hunter/
├── backend/
├── scheduler/
├── collectors/
├── ai/
├── automation/
├── dashboard/
├── notifications/
├── skills/job_hunter/
├── config/
├── data/
├── generated/
├── applications/
└── logs/
```

## Setup

1. Create and activate a Python 3.11+ virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy the environment template and fill in API keys:

```bash
cp .env.example .env
```

4. Update `config/settings.yaml` and `data/base_cv.md`.

## Run

Start the API:

```bash
uvicorn backend.api:app --reload
```

Start the dashboard:

```bash
streamlit run dashboard/dashboard.py
```

Run the scheduler service:

```bash
python main.py
```

## Safety

- No job application is submitted automatically.
- Approval is a separate action from application automation.
- LinkedIn and SEEK automation are intentionally excluded from the collectors.
- API-first collection is preferred and scraping is minimized.

## Phases

- Phase 1: Search, analyze, generate documents, dashboard, notifications
- Phase 2: Approval workflow, Playwright automation, screenshots
- Phase 3: Telegram/email/push notifications, PDF generation, more sources
