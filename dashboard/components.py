"""Reusable UI components for the Streamlit dashboard."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st


def _fmt_dt(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "N/A"


def _status_color(status: str) -> str:
    mapping = {
        "pending_approval": "#facc15",
        "approved": "#67e8f9",
        "applied": "#7cffb2",
        "rejected": "#fb7185",
        "skipped": "#94a3b8",
        "failed": "#fb7185",
        "documents_generated": "#a78bfa",
    }
    return mapping.get(status, "#67e8f9")


def _score_label(score: float | None) -> str:
    if score is None:
        return "UNSCORED"
    if score >= 85:
        return f"{score:.0f} HIGH"
    if score >= 70:
        return f"{score:.0f} MED"
    return f"{score:.0f} LOW"


def render_hero(overview: dict[str, Any]) -> None:
    """Render the top hero section."""
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="eyebrow">Clawbot / Recon Console</div>
            <div class="hero-title">AI JOB HUNTER TERMINAL</div>
            <div class="muted-copy">
                Scan targets, rank signal quality, prepare custom payloads, and keep every application behind explicit human approval.
            </div>
            <div class="chip-row">
                <span class="chip">SCAN</span>
                <span class="chip">ANALYZE</span>
                <span class="chip">GENERATE</span>
                <span class="chip">APPROVE</span>
            </div>
            <div class="console-line">$ last_search={_fmt_dt(overview["last_search_at"])} // next_search={_fmt_dt(overview["next_search_at"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_terminal_card(title: str, body: str, eyebrow: str | None = None) -> None:
    """Render a generic terminal card."""
    eyebrow_html = f'<div class="eyebrow">{eyebrow}</div>' if eyebrow else ""
    st.markdown(
        f"""
        <div class="terminal-card">
            {eyebrow_html}
            <div class="terminal-title">{title}</div>
            <div class="muted-copy">{body}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_notifications(notifications: list[dict[str, Any]]) -> None:
    """Render notification lines."""
    if not notifications:
        st.info("No notifications yet.")
        return
    for item in notifications:
        color = {"ALERT": "#7cffb2", "WAITING": "#facc15", "FAILED": "#fb7185", "RESULT": "#67e8f9"}.get(item["level"], "#67e8f9")
        st.markdown(
            f"""
            <div class="alert-line" style="border-left-color:{color}">
                <strong>[{item["level"]}]</strong> {item["message"].replace(chr(10), " | ")}
                <div class="tiny">{_fmt_dt(item["created_at"])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_source_status(source_status: list[dict[str, Any]]) -> None:
    """Render source configuration/health pills."""
    pills = []
    for item in source_status:
        color = "#7cffb2" if item["configured"] else "#fb7185"
        label = "ONLINE" if item["configured"] else "MISSING KEY"
        pills.append(f'<span class="status-pill" style="background:rgba(0,0,0,0.18); color:{color}; border-color:{color}">{item["source"].upper()} // {label}</span>')
    st.markdown("".join(pills), unsafe_allow_html=True)


def build_jobs_dataframe(jobs: list[dict[str, Any]]) -> pd.DataFrame:
    """Create a readable jobs dataframe."""
    rows = []
    for job in jobs:
        rows.append(
            {
                "ID": job["id"],
                "Company": job["company"],
                "Role": job["role"],
                "Source": job["source"].title(),
                "Location": job["location"],
                "Remote": job["remote_status"],
                "Easy Apply": job["easy_apply"],
                "Salary": job["salary"],
                "Match Score": "" if job["match_score"] is None else round(job["match_score"], 1),
                "Sponsorship": "Yes" if job["sponsorship_detected"] else "No",
                "Status": job["status"].replace("_", " ").title(),
                "Created": job["created_date"].strftime("%Y-%m-%d"),
            }
        )
    return pd.DataFrame(rows)


def render_jobs_table(jobs_df: pd.DataFrame) -> None:
    """Render the jobs table with score coloring."""
    if jobs_df.empty:
        st.info("No jobs match the current filters.")
        return

    def score_color(value: object) -> str:
        if value in ("", None):
            return ""
        score = float(value)
        if score >= 85:
            return "color: #7cffb2; font-weight: 700;"
        if score >= 70:
            return "color: #67e8f9; font-weight: 700;"
        return "color: #fb7185; font-weight: 700;"

    st.dataframe(jobs_df.style.map(score_color, subset=["Match Score"]), use_container_width=True, hide_index=True)


def render_plotly_chart(fig) -> None:
    """Apply dark chart layout defaults and render the figure."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#d1fae5", family="Space Mono"),
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_statistics_charts(stats: dict[str, Any]) -> None:
    """Render the statistics page charts."""
    c1, c2 = st.columns(2)
    with c1:
        app_status_df = pd.DataFrame(
            [{"status": key.replace("_", " ").title(), "count": value} for key, value in stats["applications_by_status"].items()]
        )
        jobs_over_time_df = pd.DataFrame(
            [{"date": key, "count": value} for key, value in stats["jobs_found_over_time"].items()]
        )
        if not app_status_df.empty:
            render_plotly_chart(px.bar(app_status_df, x="status", y="count", color="status", color_discrete_sequence=["#7cffb2", "#67e8f9", "#a78bfa", "#facc15", "#fb7185"]))
        if not jobs_over_time_df.empty:
            render_plotly_chart(px.line(jobs_over_time_df, x="date", y="count", markers=True, color_discrete_sequence=["#67e8f9"]))
    with c2:
        by_source_df = pd.DataFrame(
            [{"source": key.title(), "score": value} for key, value in stats["average_match_score_by_source"].items()]
        )
        top_skills_df = pd.DataFrame(
            [{"skill": key, "count": value} for key, value in stats["top_required_skills"].items()]
        )
        if not by_source_df.empty:
            render_plotly_chart(px.bar(by_source_df, x="source", y="score", color="score", color_continuous_scale=["#062b22", "#10b981", "#7cffb2"]))
        if not top_skills_df.empty:
            render_plotly_chart(px.bar(top_skills_df, x="count", y="skill", orientation="h", color="count", color_continuous_scale=["#082f49", "#06b6d4", "#67e8f9"]))

    c3, c4 = st.columns(2)
    with c3:
        sponsorship_df = pd.DataFrame(
            [{"label": key, "count": value} for key, value in stats["sponsorship_counts"].items()]
        )
        if not sponsorship_df.empty:
            render_plotly_chart(px.pie(sponsorship_df, names="label", values="count", color="label", color_discrete_sequence=["#facc15", "#7cffb2"]))
    with c4:
        weekly_df = pd.DataFrame(
            [{"week": key, "count": value} for key, value in stats["applications_per_week"].items()]
        )
        if not weekly_df.empty:
            render_plotly_chart(px.line(weekly_df, x="week", y="count", markers=True, color_discrete_sequence=["#a78bfa"]))


def render_application_history(history: list[dict[str, Any]]) -> None:
    """Render application history table."""
    if not history:
        st.info("No application history yet.")
        return
    df = pd.DataFrame(
        [
            {
                "Date": _fmt_dt(item["date"]),
                "Company": item["company"],
                "Role": item["role"],
                "Status": item["status"],
                "Match Score": item["match_score"],
                "Notes": item["notes"],
                "Documents": item["documents_generated"],
                "Source": item["source"],
            }
            for item in history
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_logs(logs: list[dict[str, Any]]) -> None:
    """Render log lines."""
    if not logs:
        st.info("No logs available.")
        return
    for item in logs:
        st.markdown(
            f"""
            <div class="alert-line">
                <strong>[{item["level"]}]</strong> {item["event_type"]} // {item["message"]} {f"(task: {item['task_id']})" if item["task_id"] else ""}
                <div class="tiny">{_fmt_dt(item["timestamp"])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_task_monitor(task_data: dict[str, Any]) -> None:
    """Render running, completed, and failed tasks."""
    running = task_data.get("running", [])
    failed = task_data.get("failed", [])
    completed = task_data.get("completed", [])

    if not running and not failed and not completed:
        st.info("No tracked tasks yet.")
        return

    if running:
        st.markdown("### Running Tasks")
        for task in running:
            st.markdown(
                f"""
                <div class="alert-line" style="border-left-color:#facc15">
                    <strong>[{task["status"].upper()}]</strong> {task["task_name"]}
                    <div class="tiny">{task["current_step"]} · {task["execution_duration_seconds"] or 0}s · {task["task_id"]}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.progress(max(0, min(100, task["progress_percentage"])) / 100)

    if failed:
        st.markdown("### Failed Tasks")
        for task in failed[:5]:
            st.error(f"{task['task_name']} · {task['current_step']} · {task['error_message']}")
            if task["traceback_summary"]:
                with st.expander(f"Traceback {task['task_id']}", expanded=False):
                    st.code(task["traceback_summary"], language="text")

    if completed:
        st.markdown("### Recent Completed Tasks")
        for task in completed[:5]:
            st.success(
                f"{task['task_name']} · {task['current_step']} · {task['execution_duration_seconds'] or 0}s"
            )


def render_cv_diff(diff_lines: list[str]) -> None:
    """Render a Git-style CV diff."""
    if not diff_lines:
        st.info("No CV differences are available yet.")
        return
    for line in diff_lines:
        if line.startswith("---") or line.startswith("+++"):
            st.caption(line)
            continue
        if line.startswith("@@"):
            st.code(line, language="diff")
            continue
        if line.startswith("+"):
            st.markdown(
                f"<div style='padding:4px 8px; background:#052e16; color:#bbf7d0; border-left:4px solid #22c55e; font-family:monospace'>{line}</div>",
                unsafe_allow_html=True,
            )
            continue
        if line.startswith("-"):
            st.markdown(
                f"<div style='padding:4px 8px; background:#3f0d12; color:#fecaca; border-left:4px solid #ef4444; font-family:monospace'>{line}</div>",
                unsafe_allow_html=True,
            )
            continue
        st.markdown(
            f"<div style='padding:4px 8px; background:#111827; color:#d1d5db; border-left:4px solid #6b7280; font-family:monospace'>{line or '&nbsp;'}</div>",
            unsafe_allow_html=True,
        )


def render_file_preview_if_exists(path_str: str, label: str) -> None:
    """Show an image preview if a screenshot exists."""
    if not path_str:
        st.caption(f"No {label.lower()} available.")
        return
    path = Path(path_str)
    if not path.exists():
        st.caption(f"{label} file missing on disk.")
        return
    st.image(str(path), caption=label, use_container_width=True)
