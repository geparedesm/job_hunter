"""Streamlit dashboard for the personal AI job hunter."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from backend.services import JobHunterService

service = JobHunterService()

st.set_page_config(page_title="Personal AI Job Hunter", layout="wide")
st.title("Personal AI Job Hunter")


def refresh() -> None:
    """Rerun the app after an action."""
    st.rerun()


stats = service.get_statistics()
jobs = service.list_jobs()

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
col1.metric("Total Jobs", stats["total_jobs_found"])
col2.metric("New Jobs", stats["new_jobs"])
col3.metric("Avg Match", stats["average_match_score"])
col4.metric("Applied", stats["applications_sent"])
col5.metric("Pending", stats["pending_approvals"])
col6.metric("Interviews", stats["interviews"])
col7.metric("Rejected", stats["rejected"])

action_col1, action_col2 = st.columns([1, 1])
if action_col1.button("Search Now", use_container_width=True):
    try:
        service.search_now()
        refresh()
    except Exception as exc:
        st.error(str(exc))
if action_col2.button("Export CSV", use_container_width=True):
    try:
        export_path = service.export_applications_csv()
        st.success(f"Exported to {export_path}")
    except Exception as exc:
        st.error(str(exc))

chart_col1, chart_col2 = st.columns(2)
status_df = pd.DataFrame(
    [{"status": key, "count": value} for key, value in stats["applications_by_status"].items()]
)
source_df = pd.DataFrame(
    [{"source": key, "match_score": value} for key, value in stats["average_match_score_by_source"].items()]
)
skills_df = pd.DataFrame(
    [{"skill": key, "count": value} for key, value in stats["top_required_skills"].items()]
)
timeline_df = pd.DataFrame(
    [{"date": key, "count": value} for key, value in stats["applications_over_time"].items()]
)

with chart_col1:
    st.subheader("Applications by Status")
    if not status_df.empty:
        st.plotly_chart(px.bar(status_df, x="status", y="count"), use_container_width=True)
    st.subheader("Average Match Score by Source")
    if not source_df.empty:
        st.plotly_chart(px.bar(source_df, x="source", y="match_score"), use_container_width=True)

with chart_col2:
    st.subheader("Top Required Skills")
    if not skills_df.empty:
        st.plotly_chart(px.bar(skills_df, x="skill", y="count"), use_container_width=True)
    st.subheader("Applications Over Time")
    if not timeline_df.empty:
        st.plotly_chart(px.line(timeline_df, x="date", y="count"), use_container_width=True)

st.subheader("Job Table")
filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
keyword_filter = filter_col1.text_input("Keyword")
source_filter = filter_col2.selectbox("Source", [""] + sorted({job.source for job in jobs}))
status_filter = filter_col3.selectbox("Status", [""] + sorted({job.status for job in jobs}))
minimum_match_filter = filter_col4.number_input("Minimum Match Score", value=0, min_value=0, max_value=100)

filtered_jobs = service.list_jobs(
    keyword=keyword_filter or None,
    source=source_filter or None,
    status=status_filter or None,
    minimum_match_score=float(minimum_match_filter) if minimum_match_filter else None,
)

table_df = pd.DataFrame(
    [
        {
            "ID": job.id,
            "Company": job.company,
            "Role": job.title,
            "Source": job.source,
            "Match Score": job.match_score,
            "Salary": job.salary,
            "Location": job.location,
            "Status": job.status,
        }
        for job in filtered_jobs
    ]
)
st.dataframe(table_df, use_container_width=True, hide_index=True)

st.subheader("Job Details")
job_ids = [job.id for job in filtered_jobs]
selected_job_id = st.selectbox("Select Job", job_ids, format_func=lambda job_id: f"{job_id} - {next(job for job in filtered_jobs if job.id == job_id).title}") if job_ids else None

if selected_job_id is not None:
    details = service.get_job_details(selected_job_id)
    job = details["job"]
    detail_col1, detail_col2 = st.columns(2)
    with detail_col1:
        st.markdown(f"**Company:** {job.company}")
        st.markdown(f"**Title:** {job.title}")
        st.markdown(f"**Salary:** {job.salary or 'Not provided'}")
        st.markdown(f"**Location:** {job.location or 'Not provided'}")
        st.markdown(f"**Source:** {job.source}")
        st.markdown(f"**Status:** {job.status}")
        st.markdown(f"**Required skills:** {', '.join(job.required_skills) or 'None detected'}")
        st.markdown(f"**Missing skills:** {', '.join(job.missing_skills) or 'None detected'}")
        st.markdown(f"**Recommended action:** {job.recommended_action or 'N/A'}")
        st.markdown("**Description:**")
        st.write(job.description)
        st.markdown("**AI Analysis:**")
        st.write(job.ai_explanation or "No analysis yet")
    with detail_col2:
        st.markdown("**Generated CV Preview**")
        st.code(details["generated_cv"] or "No CV generated yet", language="markdown")
        st.markdown("**Generated Cover Letter Preview**")
        st.code(details["generated_cover_letter"] or "No cover letter generated yet", language="markdown")

    action_row1, action_row2, action_row3 = st.columns(3)
    if action_row1.button("Generate CV / Cover Letter", use_container_width=True):
        try:
            service.generate_documents(selected_job_id)
            refresh()
        except Exception as exc:
            st.error(str(exc))
    if action_row2.button("Approve Apply", use_container_width=True):
        try:
            service.approve_job(selected_job_id)
            refresh()
        except Exception as exc:
            st.error(str(exc))
    if action_row3.button("Reject", use_container_width=True):
        try:
            service.reject_job(selected_job_id)
            refresh()
        except Exception as exc:
            st.error(str(exc))

    action_row4, action_row5, action_row6 = st.columns(3)
    if action_row4.button("Skip", use_container_width=True):
        try:
            service.skip_job(selected_job_id)
            refresh()
        except Exception as exc:
            st.error(str(exc))
    if action_row5.button("Apply", use_container_width=True):
        try:
            result = service.apply_to_job(selected_job_id)
            st.info(result.message)
            refresh()
        except Exception as exc:
            st.error(str(exc))
    action_row6.link_button("Open Job URL", job.url, use_container_width=True)
