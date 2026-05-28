"""Streamlit dashboard entrypoint for the AI Job Hunter frontend."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.components import (
    build_jobs_dataframe,
    render_application_history,
    render_cv_diff,
    render_file_preview_if_exists,
    render_hero,
    render_jobs_table,
    render_logs,
    render_notifications,
    render_source_status,
    render_statistics_charts,
    render_task_monitor,
    render_terminal_card,
)
from dashboard.services import (
    JobFilters,
    approve_job,
    clear_dashboard_caches,
    export_base_cv_pdf,
    export_job_cv_pdf,
    get_application_history_data,
    get_cv_diff_data,
    get_cv_jobs_data,
    get_cv_preview_data,
    get_job_detail_data,
    get_jobs_data,
    get_logs_data,
    get_notifications_data,
    get_overview_data,
    get_settings_data,
    get_statistics_data,
    get_task_monitor_data,
    get_task_status_counts,
    is_task_running,
    launch_apply_to_job,
    launch_generate_cover_letter,
    launch_generate_tailored_cv,
    launch_recalculate_match,
    launch_search_now,
    mark_as_applied,
    reject_job,
    save_manual_cv_content,
    save_settings_data,
    skip_job,
)
from dashboard.styles import apply_global_styles


st.set_page_config(
    page_title="AI Job Hunter Terminal",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)
apply_global_styles()


def run_action(label: str, callback) -> object | None:
    """Run an action and surface errors."""
    try:
        with st.spinner(label):
            result = callback()
        st.success(label)
        return result
    except Exception as exc:  # pragma: no cover - UI feedback
        st.error(str(exc))
        return None


def _init_dashboard_state() -> None:
    """Initialize persisted dashboard state."""
    defaults = {
        "selected_job_id": None,
        "dashboard_page": "🧠 Overview",
        "task_monitor_auto_refresh": False,
        "jobs_keyword": "",
        "jobs_source": "All sources",
        "jobs_status": "All statuses",
        "jobs_location": "",
        "jobs_remote_status": "All",
        "jobs_easy_apply_filter": "All",
        "jobs_min_score": 60,
        "jobs_sponsorship_only": False,
        "jobs_required_skills_only": False,
        "jobs_date_range": (date.today() - timedelta(days=30), date.today()),
        "job_detail_tab": "Overview",
        "job_detail_cv_view": "Side-by-side Preview",
        "cv_page_selected_job": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _refresh_task_monitor() -> None:
    """Refresh only cached task-monitor reads."""
    get_task_monitor_data.clear()
    get_task_status_counts.clear()
    get_overview_data.clear()


def _render_task_monitor_block(prefix: str, *, show_controls: bool) -> None:
    """Render the compact task monitor with manual refresh controls."""
    task_monitor = get_task_monitor_data()
    task_counts = get_task_status_counts()
    st.markdown("### Task Monitor")
    st.caption(
        f"Pending {task_counts['pending']} · Running {task_counts['running']} · Completed {task_counts['completed']} · Failed {task_counts['failed']}"
    )
    if show_controls:
        controls = st.columns(2)
        if controls[0].button("Refresh task status", key=f"{prefix}_task_monitor_refresh", use_container_width=True):
            _refresh_task_monitor()
            st.rerun()
        controls[1].checkbox(
            "Enable task monitor auto-refresh",
            key="task_monitor_auto_refresh",
            help="Refresh only the task monitor every 15 seconds.",
        )
    render_task_monitor(task_monitor)


def _render_task_monitor_panel(prefix: str, *, show_controls: bool) -> None:
    """Render task monitor, auto-refreshing only this fragment when enabled."""
    if st.session_state.get("task_monitor_auto_refresh", False) and hasattr(st, "fragment"):
        @st.fragment(run_every="15s")
        def _auto_fragment() -> None:
            _refresh_task_monitor()
            _render_task_monitor_block(prefix, show_controls=show_controls)

        _auto_fragment()
    else:
        _render_task_monitor_block(prefix, show_controls=show_controls)


_init_dashboard_state()
overview = get_overview_data()
notifications = get_notifications_data()

with st.sidebar:
    st.markdown("## Navigation")
    page = st.radio(
        "Go to",
        ["🧠 Overview", "🔍 Jobs", "📄 CV", "📊 Statistics", "📁 Applications", "⚙️ Settings", "🧾 Logs"],
        label_visibility="collapsed",
        key="dashboard_page",
    )
    st.markdown("---")
    _render_task_monitor_panel("sidebar", show_controls=True)
    st.markdown("---")
    st.markdown("### Notifications")
    render_notifications(notifications[:5])


render_hero(overview)

if page == "🧠 Overview":
    metrics = overview["stats"]
    cols = st.columns(6)
    cols[0].metric("Total jobs found", metrics["total_jobs_found"])
    cols[1].metric("New jobs", metrics["new_jobs"])
    cols[2].metric("Pending approvals", metrics["pending_approvals"])
    cols[3].metric("Average match score", metrics["average_match_score"])
    cols[4].metric("Applications sent", metrics["applications_sent"])
    cols[5].metric("Rejected / skipped", metrics["rejected"] + metrics["applications_by_status"].get("skipped", 0))

    c1, c2 = st.columns([1.2, 1])
    with c1:
        render_terminal_card(
            "SYSTEM STATUS",
            (
                f"Jobs scanned: {metrics['total_jobs_found']}<br>"
                f"High match targets: {overview['high_match_targets']}<br>"
                f"Pending approval: {metrics['pending_approvals']}<br>"
                f"Applications sent: {metrics['applications_sent']}"
            ),
            eyebrow="Overview",
        )
        render_terminal_card(
            "SEARCH CONTROL PANEL",
            (
                f"Last search timestamp: {overview['last_search_at'] or 'N/A'}<br>"
                f"Next scheduled search: {overview['next_search_at'] or 'N/A'}<br>"
                f"Search interval: {overview['search_interval_hours']} hours<br>"
                f"Active sources: {', '.join(overview['active_sources']) or 'None'}"
            ),
            eyebrow="Control",
        )
        action_c1, action_c2 = st.columns(2)
        scheduler_running = bool(overview["scheduler_running_task"])
        if action_c1.button("Search Now", use_container_width=True, type="primary", disabled=scheduler_running):
            result = run_action("Search task queued", launch_search_now)
            if isinstance(result, dict):
                st.info(f"Task queued: {result['task_id']}")
                st.rerun()
        if action_c2.button("Refresh Dashboard Cache", use_container_width=True):
            clear_dashboard_caches()
            st.rerun()
        if overview["scheduler_running_task"]:
            st.warning(f"Scheduler running: {overview['scheduler_running_task']['current_step']}")
        else:
            st.info("Waiting for next scheduled run.")
    with c2:
        render_terminal_card("API / SOURCE STATUS", "Configured sources currently available below.", eyebrow="Status")
        render_source_status(overview["source_status"])
        st.markdown("### Notifications panel")
        render_notifications(notifications)
    st.markdown("## Task Monitor")
    _render_task_monitor_panel("overview", show_controls=False)

elif page == "🔍 Jobs":
    with st.expander("Filters Panel", expanded=True):
        fc1, fc2, fc3 = st.columns(3)
        keyword = fc1.text_input("Keyword", key="jobs_keyword")
        source = fc1.selectbox("Source", ["All sources"] + [item["source"] for item in overview["source_status"]], key="jobs_source")
        status = fc2.selectbox(
            "Status",
            ["All statuses", "found", "analyzed", "documents_generated", "pending_approval", "approved", "applied", "rejected", "skipped", "failed"],
            key="jobs_status",
        )
        location = fc2.text_input("Location", key="jobs_location")
        remote_status = fc3.selectbox("Remote", ["All", "Remote only", "Hybrid only", "On-site only", "Unknown"], key="jobs_remote_status")
        easy_apply_filter = fc3.selectbox("Easy Apply", ["All", "Easy Apply only", "Non-Easy Apply", "Unknown"], key="jobs_easy_apply_filter")
        min_score = fc3.slider("Minimum match score", min_value=0, max_value=100, step=5, key="jobs_min_score")
        sponsorship_only = fc3.toggle("Sponsorship only", key="jobs_sponsorship_only")
        required_skills_only = st.toggle("Show only jobs with required skills detected", key="jobs_required_skills_only")
        date_from, date_to = st.date_input("Date range", key="jobs_date_range")
        filters = JobFilters(
            keyword=keyword,
            source=source,
            status=status,
            location=location,
            remote_status=remote_status,
            easy_apply_filter=easy_apply_filter,
            minimum_match_score=min_score,
            sponsorship_only=sponsorship_only,
            required_skills_only=required_skills_only,
            date_from=date_from,
            date_to=date_to,
        )

    jobs = get_jobs_data(filters)
    jobs_df = build_jobs_dataframe(jobs)

    summary_cols = st.columns(4)
    summary_cols[0].metric("Matching jobs", len(jobs))
    summary_cols[1].metric("High priority", sum(1 for item in jobs if (item["base_match_score"] or 0) >= 85))
    summary_cols[2].metric("Pending approval", sum(1 for item in jobs if item["status"] == "pending_approval"))
    summary_cols[3].metric("Skills detected", sum(1 for item in jobs if item["required_skills_detected"]))

    render_terminal_card(
        "TARGET QUEUE",
        "Review the filtered job feed below, then select one target to inspect or act on. CV handling stays manual.",
        eyebrow="Jobs",
    )

    render_jobs_table(jobs_df)
    if jobs:
        options = {f"{item['company']} - {item['role']} ({item['id']})": item["id"] for item in jobs}
        st.markdown(
            """
            <div class="terminal-card compact-card">
                <div class="eyebrow">Selection</div>
                <div class="terminal-title">Active target control panel</div>
                <div class="muted-copy">Pick a job, then run the next action from one compact command strip.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        selected_job_index = 0
        if st.session_state.selected_job_id in options.values():
            selected_job_index = list(options.values()).index(st.session_state.selected_job_id)
        selected_label = st.selectbox("Selected job", list(options.keys()), index=selected_job_index, key="jobs_selected_job")
        st.session_state.selected_job_id = options[selected_label]
        selected_job = next(item for item in jobs if item["id"] == st.session_state.selected_job_id)

        st.caption(
            f"Selected: {selected_job['company']} · {selected_job['role']} · {selected_job['location'] or 'Unknown location'} · Remote: {selected_job['remote_status']} · Easy Apply: {selected_job['easy_apply']}"
        )

        quick_top = st.columns(4)
        quick_top[0].button("View Analysis Below", key="jobs_view_selected", use_container_width=True, disabled=True)
        cv_task_running = is_task_running("tailored_cv_generation", job_id=st.session_state.selected_job_id)
        cover_task_running = is_task_running("cover_letter_generation", job_id=st.session_state.selected_job_id)
        apply_task_running = is_task_running("playwright_automation", job_id=st.session_state.selected_job_id)
        if quick_top[1].button("Generate Tailored CV", key="jobs_generate_cv", use_container_width=True, disabled=cv_task_running):
            if run_action("Tailored CV task queued", lambda: launch_generate_tailored_cv(st.session_state.selected_job_id)) is not None:
                _refresh_task_monitor()
                st.rerun()
        if quick_top[2].button("Approve Apply", key="jobs_approve_selected", use_container_width=True):
            if run_action("Job approved", lambda: approve_job(st.session_state.selected_job_id)) is not None:
                st.rerun()
        quick_top[3].link_button("Open Job URL", selected_job["url"], use_container_width=True)

        quick_bottom = st.columns(3)
        if quick_bottom[0].button("Reject", key="jobs_reject_selected", use_container_width=True):
            if run_action("Job rejected", lambda: reject_job(st.session_state.selected_job_id)) is not None:
                st.rerun()
        if quick_bottom[1].button("Skip", key="jobs_skip_selected", use_container_width=True):
            if run_action("Job skipped", lambda: skip_job(st.session_state.selected_job_id)) is not None:
                st.rerun()
        if quick_bottom[2].button("Generate Cover Letter", key="jobs_generate_cover_letter", use_container_width=True, disabled=cover_task_running):
            if run_action("Cover letter task queued", lambda: launch_generate_cover_letter(st.session_state.selected_job_id)) is not None:
                _refresh_task_monitor()
                st.rerun()

    if st.session_state.selected_job_id:
        detail = get_job_detail_data(st.session_state.selected_job_id)
        st.markdown("## Job Detail View")
        detail_tab = st.radio(
            "Job detail section",
            ["Overview", "AI Analysis", "CV", "Cover Letter", "Application"],
            horizontal=True,
            key="job_detail_tab",
        )

        if detail_tab == "Overview":
            st.markdown(f"### {detail['company']} // {detail['role']}")
            st.write(f"**City:** {detail['city'] or 'Unknown'}")
            st.write(f"**State:** {detail['state'] or 'Unknown'}")
            st.write(f"**Country:** {detail['country'] or 'Unknown'}")
            st.write(f"**Full location:** {detail['full_location'] or 'Unknown'}")
            st.write(f"**Remote status:** {detail['remote_status'] or 'Unknown'}")
            st.write(f"**Easy Apply status:** {detail['easy_apply'] or 'Unknown'}")
            st.write(f"**Easy Apply detection source:** {detail['easy_apply_detection_source'] or 'Unknown'}")
            st.write(f"**Apply type:** {detail['easy_apply_type'] or 'Unknown'}")
            st.write(f"**Apply URL:** {detail['url']}")
            st.write(f"**Raw location:** {detail['raw_location'] or 'Unknown'}")
            st.write(f"**Salary:** {detail['salary'] or 'Not provided'}")
            st.write(f"**Source:** {detail['source']}")
            st.write(f"**Job URL:** {detail['url']}")
            st.write(f"**CV generation status:** {detail['cv_generation_status']}")
            st.write(f"**Base CV Match Score:** {detail['base_match_score'] if detail['base_match_score'] is not None else 'Not available'}")
            tailored_score_text = detail["tailored_cv_match_score"] if detail["tailored_cv_match_score"] is not None else "Not generated yet."
            st.write(f"**Tailored CV Match Score:** {tailored_score_text}")
            if detail["analysis_incomplete"]:
                st.warning("Analysis may be incomplete because the full job page could not be extracted cleanly.")
            if detail["analysis_warnings"]:
                for warning in detail["analysis_warnings"]:
                    st.caption(f"Warning: {warning}")
            with st.expander("Full job description", expanded=False):
                st.write(detail["description"])

        if detail_tab == "AI Analysis":
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Base CV Match Score", detail["base_match_score"] or 0)
            mc2.metric("Recommendation", detail["recommended_action"] or "N/A")
            mc3.metric("Visa / work rights", detail["visa_analysis"]["status"])
            tc1, tc2 = st.columns(2)
            tc1.metric(
                "Tailored CV Match Score",
                detail["tailored_cv_match_score"] if detail["tailored_cv_match_score"] is not None else "Not generated yet",
            )
            if tc2.button(
                "Recalculate Match Scores",
                key=f"detail_recalculate_match_{detail['id']}",
                use_container_width=True,
                disabled=is_task_running("match_score_calculation", job_id=detail["id"]),
            ):
                if run_action("Match recalculation queued", lambda: launch_recalculate_match(detail["id"])) is not None:
                    _refresh_task_monitor()
                    st.rerun()
            st.write("**Required skills**")
            if detail["required_skill_items"]:
                st.dataframe(detail["required_skill_items"], use_container_width=True, hide_index=True)
            else:
                st.info("No required skills were extracted from the full description.")
            st.write("**Preferred skills**")
            if detail["preferred_skill_items"]:
                st.dataframe(detail["preferred_skill_items"], use_container_width=True, hide_index=True)
            else:
                st.info("No preferred skills were extracted from the full description.")
            st.write("**Responsibilities**")
            if detail["responsibilities"]:
                st.dataframe(detail["responsibilities"], use_container_width=True, hide_index=True)
            else:
                st.info("No responsibilities were extracted from the full description.")
            st.write("**Missing skills**")
            if detail["missing_skill_items"]:
                st.dataframe(detail["missing_skill_items"], use_container_width=True, hide_index=True)
            elif detail["manual_cv_present"]:
                st.info("No missing skills were found against your manual CV.")
            else:
                st.info("Missing-skills analysis is waiting for a manual CV/profile.")
            st.write("**Visa/work rights analysis**")
            st.write(f"Result: {detail['visa_analysis']['status']}")
            st.write(f"Confidence: {detail['visa_analysis']['confidence_score']}")
            if detail["visa_analysis"]["evidence"]:
                for evidence in detail["visa_analysis"]["evidence"]:
                    st.code(evidence, language="text")
            else:
                st.info("No visa/work-rights sentence was found in the extracted job content.")
            st.write("**Analysis summary**")
            st.info(detail["ai_explanation"] or "No AI analysis available.")

        if detail_tab == "CV":
            c1, c2 = st.columns(2)
            c1.download_button(
                "Download Current CV",
                data=detail["manual_cv_content"].encode("utf-8"),
                file_name=f"{detail['company']}_{detail['role']}_cv.md".replace(" ", "_"),
                use_container_width=True,
            )
            if c2.button(
                "Generate Tailored CV",
                key=f"detail_generate_cv_{detail['id']}",
                use_container_width=True,
                disabled=is_task_running("tailored_cv_generation", job_id=detail["id"]),
            ):
                if run_action("Tailored CV task queued", lambda: launch_generate_tailored_cv(detail["id"])) is not None:
                    _refresh_task_monitor()
                    st.rerun()
            cv_view = st.radio(
                "CV View",
                ["Side-by-side Preview", "CV Diff"],
                horizontal=True,
                key="job_detail_cv_view",
            )
            base_pdf_state_key = f"job_detail_base_cv_pdf_payload_{detail['id']}"
            tailored_pdf_state_key = f"job_detail_tailored_cv_pdf_payload_{detail['id']}"
            pdf_c1, pdf_c2 = st.columns(2)
            if pdf_c1.button("Prepare Original CV PDF", key=f"detail_prepare_base_cv_pdf_{detail['id']}", use_container_width=True):
                exported = run_action("Original CV PDF exported", lambda: export_base_cv_pdf(detail["id"]))
                if isinstance(exported, dict):
                    st.session_state[base_pdf_state_key] = exported
            base_pdf_payload = st.session_state.get(base_pdf_state_key)
            if isinstance(base_pdf_payload, dict):
                pdf_c1.download_button(
                    "Download Original CV PDF",
                    data=base_pdf_payload["bytes"],
                    file_name=Path(base_pdf_payload["path"]).name,
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"detail_download_base_cv_pdf_{detail['id']}",
                )

            if detail["generated_cv"].strip():
                if pdf_c2.button("Prepare Tailored CV PDF", key=f"detail_prepare_tailored_cv_pdf_{detail['id']}", use_container_width=True):
                    exported = run_action("Tailored CV PDF exported", lambda: export_job_cv_pdf(detail["id"]))
                    if isinstance(exported, dict):
                        st.session_state[tailored_pdf_state_key] = exported
                tailored_pdf_payload = st.session_state.get(tailored_pdf_state_key)
                if isinstance(tailored_pdf_payload, dict):
                    pdf_c2.download_button(
                        "Download CV",
                        data=tailored_pdf_payload["bytes"],
                        file_name=Path(tailored_pdf_payload["path"]).name,
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"detail_download_tailored_cv_pdf_{detail['id']}",
                    )
                st.caption(f"Tailored CV file: `{detail['generated_cv_path']}`")
                markdown_c1, markdown_c2 = st.columns(2)
                markdown_c1.download_button(
                    "Download Original CV Markdown",
                    data=detail["manual_cv_content"].encode("utf-8"),
                    file_name=f"original_cv_{detail['id']}.md",
                    use_container_width=True,
                    key=f"detail_download_original_cv_md_{detail['id']}",
                )
                markdown_c2.download_button(
                    "Download Tailored CV Markdown",
                    data=detail["generated_cv"].encode("utf-8"),
                    file_name=f"tailored_cv_{detail['id']}_{detail['company']}_{detail['role']}.md".replace(" ", "_"),
                    use_container_width=True,
                    key=f"detail_download_tailored_cv_md_{detail['id']}",
                )
            else:
                pdf_c2.button("Download CV", key=f"detail_download_tailored_cv_pdf_disabled_{detail['id']}", use_container_width=True, disabled=True)

            if cv_view == "Side-by-side Preview":
                preview_c1, preview_c2 = st.columns(2)
                with preview_c1:
                    st.markdown("### Original CV")
                    st.code(detail["manual_cv_content"] or "Original CV is empty.", language="markdown")
                with preview_c2:
                    st.markdown("### Tailored CV")
                    if detail["generated_cv"].strip():
                        st.code(detail["generated_cv"], language="markdown")
                    else:
                        st.info("No tailored CV has been generated for this job yet.")
                        if st.button(
                            "Generate Tailored CV",
                            key=f"detail_generate_cv_inline_{detail['id']}",
                            use_container_width=True,
                            disabled=is_task_running("tailored_cv_generation", job_id=detail["id"]),
                        ):
                            if run_action("Tailored CV task queued", lambda: launch_generate_tailored_cv(detail["id"])) is not None:
                                _refresh_task_monitor()
                                st.rerun()
            else:
                st.markdown("### CV Diff")
                if detail["generated_cv"].strip():
                    diff_data = get_cv_diff_data(detail["id"])
                    render_cv_diff(diff_data["diff_lines"])
                else:
                    st.info("No tailored CV has been generated for this job yet.")
                    if st.button(
                        "Generate Tailored CV",
                        key=f"detail_generate_cv_diff_{detail['id']}",
                        use_container_width=True,
                        disabled=is_task_running("tailored_cv_generation", job_id=detail["id"]),
                    ):
                        if run_action("Tailored CV task queued", lambda: launch_generate_tailored_cv(detail["id"])) is not None:
                            _refresh_task_monitor()
                            st.rerun()

        if detail_tab == "Cover Letter":
            st.info("Cover letters are generated only when you press the button below.")
            cl1, cl2 = st.columns(2)
            if cl1.button(
                "Generate Cover Letter",
                key=f"detail_generate_cover_letter_{detail['id']}",
                use_container_width=True,
                disabled=is_task_running("cover_letter_generation", job_id=detail["id"]),
            ):
                if run_action("Cover letter task queued", lambda: launch_generate_cover_letter(detail["id"])) is not None:
                    _refresh_task_monitor()
                    st.rerun()
            if cl2.button(
                "Recalculate Match Scores",
                key=f"detail_recalculate_match_cover_{detail['id']}",
                use_container_width=True,
                disabled=is_task_running("match_score_calculation", job_id=detail["id"]),
            ):
                if run_action("Match recalculation queued", lambda: launch_recalculate_match(detail["id"])) is not None:
                    _refresh_task_monitor()
                    st.rerun()
            st.write(f"Recommended action: {detail['recommended_action'] or 'N/A'}")
            st.write(f"Top required skills: {', '.join(detail['required_skills']) or 'No skills extracted'}")
            st.write(f"Top responsibilities: {', '.join(item['skill'] for item in detail['responsibilities'][:5]) or 'No responsibilities extracted'}")
            if detail["generated_cover_letter_path"]:
                st.write(f"Stored file: `{detail['generated_cover_letter_path']}`")
                st.download_button(
                    "Download Cover Letter",
                    data=detail["generated_cover_letter"].encode("utf-8"),
                    file_name=Path(detail["generated_cover_letter_path"]).name,
                    use_container_width=False,
                    key=f"detail_download_cover_letter_{detail['id']}",
                )
                with st.expander("Preview cover letter", expanded=False):
                    st.code(detail["generated_cover_letter"], language="markdown")
            else:
                st.caption("Cover letter not generated yet.")

        if detail_tab == "Application":
            st.warning("Approval required before any assisted application flow runs.")
            a1, a2, a3 = st.columns(3)
            if a1.button("Approve Apply", key=f"detail_approve_{detail['id']}", use_container_width=True):
                if run_action("Job approved", lambda: approve_job(detail["id"])) is not None:
                    st.rerun()
            if a2.button("Reject", key=f"detail_reject_{detail['id']}", use_container_width=True):
                if run_action("Job rejected", lambda: reject_job(detail["id"])) is not None:
                    st.rerun()
            if a3.button("Mark as Applied", key=f"detail_mark_applied_{detail['id']}", use_container_width=True):
                if run_action("Job marked as applied", lambda: mark_as_applied(detail["id"])) is not None:
                    st.rerun()
            if st.button(
                "Run Assisted Application Flow",
                key=f"detail_assisted_apply_{detail['id']}",
                use_container_width=True,
                disabled=is_task_running("playwright_automation", job_id=detail["id"]),
            ):
                message = run_action("Application task queued", lambda: launch_apply_to_job(detail["id"]))
                if message:
                    st.info(f"Task queued: {message['task_id']}")
                    _refresh_task_monitor()
                    st.rerun()
            s1, s2 = st.columns(2)
            with s1:
                render_file_preview_if_exists(detail["before_screenshot"], "before_submit.png")
            with s2:
                render_file_preview_if_exists(detail["after_screenshot"], "after_submit.png")

elif page == "📊 Statistics":
    stats = get_statistics_data()
    st.markdown("## Statistics")
    render_statistics_charts(stats)

elif page == "📄 CV":
    st.markdown("## CV")
    st.caption("Preview the base CV alongside a job-specific tailored CV. PDF exports happen only when you request them.")
    cv_jobs = get_cv_jobs_data()
    jobs_with_tailored_cv = [job for job in cv_jobs if job["has_tailored_cv"]]

    if not cv_jobs:
        st.info("No jobs are available yet. Run a search first.")
    else:
        if jobs_with_tailored_cv:
            preferred_jobs = jobs_with_tailored_cv
            st.caption(f"Jobs with generated tailored CVs: {len(jobs_with_tailored_cv)}")
        else:
            preferred_jobs = cv_jobs
            st.warning("No tailored CVs exist yet. Select a job below to generate one manually.")

        selected_cv_job_id = st.session_state.selected_job_id if any(job["id"] == st.session_state.selected_job_id for job in preferred_jobs) else preferred_jobs[0]["id"]
        cv_options = {f"{item['company']} - {item['role']} ({item['id']})": item["id"] for item in preferred_jobs}
        selected_cv_label = st.selectbox(
            "Select job for CV preview",
            list(cv_options.keys()),
            index=list(cv_options.values()).index(selected_cv_job_id),
            key="cv_page_selected_job",
        )
        selected_cv_job_id = cv_options[selected_cv_label]
        st.session_state.selected_job_id = selected_cv_job_id
        cv_detail = get_cv_preview_data(selected_cv_job_id)

        info_c1, info_c2, info_c3, info_c4 = st.columns(4)
        info_c1.metric("Job Title", cv_detail["title"])
        info_c2.metric("Company", cv_detail["company"])
        info_c3.metric("Base CV Match Score", cv_detail["base_match_score"] if cv_detail["base_match_score"] is not None else "N/A")
        info_c4.metric(
            "Tailored CV Match Score",
            cv_detail["tailored_cv_match_score"] if cv_detail["tailored_cv_match_score"] is not None else "Not generated yet",
        )

        if cv_detail["tailored_cv_path"]:
            st.write(f"Tailored CV file: `{cv_detail['tailored_cv_path']}`")
        elif cv_detail["documents_generated_at"]:
            st.write(f"Generated at: {cv_detail['documents_generated_at']}")
        else:
            st.write("Tailored CV status: Not generated yet.")

        base_pdf_state_key = f"base_cv_pdf_payload_{selected_cv_job_id}"
        tailored_pdf_state_key = f"tailored_cv_pdf_payload_{selected_cv_job_id}"
        action_c1, action_c2 = st.columns(2)
        if action_c1.button("Prepare Base CV PDF", use_container_width=True, key=f"cv_base_pdf_prepare_{selected_cv_job_id}"):
            exported = run_action("Base CV PDF exported", lambda: export_base_cv_pdf(selected_cv_job_id))
            if isinstance(exported, dict):
                st.session_state[base_pdf_state_key] = exported
        base_pdf_payload = st.session_state.get(base_pdf_state_key)
        if isinstance(base_pdf_payload, dict):
            action_c1.download_button(
                "Download Base CV as PDF",
                data=base_pdf_payload["bytes"],
                file_name=Path(base_pdf_payload["path"]).name,
                mime="application/pdf",
                use_container_width=True,
                key=f"cv_base_pdf_download_{selected_cv_job_id}",
            )

        if cv_detail["tailored_cv_content"].strip():
            if action_c2.button("Prepare Tailored CV PDF", use_container_width=True, key=f"cv_tailored_pdf_prepare_{selected_cv_job_id}"):
                exported = run_action("Tailored CV PDF exported", lambda: export_job_cv_pdf(selected_cv_job_id))
                if isinstance(exported, dict):
                    st.session_state[tailored_pdf_state_key] = exported
            tailored_pdf_payload = st.session_state.get(tailored_pdf_state_key)
            if isinstance(tailored_pdf_payload, dict):
                action_c2.download_button(
                    "Download Tailored CV as PDF",
                    data=tailored_pdf_payload["bytes"],
                    file_name=Path(tailored_pdf_payload["path"]).name,
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"cv_tailored_pdf_download_{selected_cv_job_id}",
                )
        else:
            action_c2.button("Download Tailored CV as PDF", use_container_width=True, disabled=True, key=f"cv_tailored_pdf_disabled_{selected_cv_job_id}")

        preview_c1, preview_c2 = st.columns(2)
        with preview_c1:
            st.markdown("### Base CV Preview")
            st.code(cv_detail["base_cv_content"] or "Base CV is empty.", language="markdown")
        with preview_c2:
            st.markdown("### Tailored CV Preview")
            if cv_detail["tailored_cv_content"].strip():
                st.code(cv_detail["tailored_cv_content"], language="markdown")
            else:
                st.info("No tailored CV exists for this job yet.")
                if st.button(
                    "Generate Tailored CV",
                    key=f"cv_page_generate_cv_{selected_cv_job_id}",
                    use_container_width=True,
                    disabled=is_task_running("tailored_cv_generation", job_id=selected_cv_job_id),
                ):
                    if run_action("Tailored CV task queued", lambda: launch_generate_tailored_cv(selected_cv_job_id)) is not None:
                        _refresh_task_monitor()
                        st.rerun()

elif page == "📁 Applications":
    history = get_application_history_data()
    st.markdown("## Application History")
    render_application_history(history)
    csv_payload = "Date,Company,Role,Status,Match Score,Notes,Documents,Source\n" + "\n".join(
        f"{item['date']},{item['company']},{item['role']},{item['status']},{item['match_score']},{item['notes']},{item['documents_generated']},{item['source']}"
        for item in history
    )
    st.download_button("Export CSV", data=csv_payload, file_name="application_history.csv", use_container_width=False)

elif page == "⚙️ Settings":
    settings = get_settings_data()
    st.markdown("## Settings")
    st.caption("These settings map to config/settings.yaml. API keys are intentionally not shown here.")
    with st.form("settings_form"):
        keywords = st.text_area("Keywords", value="\n".join(settings["keywords"]), height=140)
        locations = st.text_area("Locations", value="\n".join(settings["locations"]), height=100)
        c1, c2 = st.columns(2)
        minimum_match_score = c1.slider("Minimum match score", min_value=0, max_value=100, value=settings["minimum_match_score"])
        search_interval_hours = c2.number_input("Search interval hours", min_value=1, max_value=168, value=settings["search_interval_hours"])
        sponsorship_required = st.toggle("Sponsorship required", value=settings["sponsorship_required"], disabled=True)
        blacklist_keywords = st.text_area("Blacklist keywords", value="\n".join(settings["blacklist_keywords"]), height=120)
        blacklist_companies = st.text_area("Blacklist companies", value="\n".join(settings["blacklist_companies"]), height=100)
        sources = st.multiselect("Active sources", options=["adzuna", "jsearch", "serpapi"], default=settings["sources"])
        submitted = st.form_submit_button("Save settings", use_container_width=True)
        if submitted:
            payload = {
                "keywords": keywords.splitlines(),
                "locations": locations.splitlines(),
                "minimum_match_score": minimum_match_score,
                "search_interval_hours": search_interval_hours,
                "blacklist_keywords": blacklist_keywords.splitlines(),
                "blacklist_companies": blacklist_companies.splitlines(),
                "sources": sources,
            }
            if run_action("Settings saved", lambda: save_settings_data(payload)) is not None:
                st.rerun()

elif page == "🧾 Logs":
    st.markdown("## Logs")
    logs = get_logs_data()
    render_logs(logs)
