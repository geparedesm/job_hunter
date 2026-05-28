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
    analyze_resume_profile,
    apply_suggested_keywords_to_settings,
    approve_job,
    clear_dashboard_caches,
    export_base_cv_pdf,
    export_interview_simulation_pdf,
    export_job_cv_pdf,
    evaluate_interview_answer,
    get_application_history_data,
    get_cv_diff_data,
    get_cv_jobs_data,
    get_cv_preview_data,
    get_interactive_interview_question,
    get_interview_jobs_data,
    get_interview_simulation_data,
    get_job_detail_data,
    get_jobs_data,
    get_logs_data,
    get_notifications_data,
    get_overview_data,
    get_resume_keyword_suggestions,
    get_resume_profile_data,
    get_settings_data,
    get_statistics_data,
    get_task_monitor_data,
    get_task_status_counts,
    is_task_running,
    launch_apply_to_job,
    launch_generate_cover_letter,
    launch_generate_interview_simulation,
    launch_generate_tailored_cv,
    launch_recalculate_match,
    launch_search_now,
    mark_as_applied,
    reject_job,
    save_manual_cv_content,
    save_settings_data,
    skip_job,
    suggest_resume_keywords,
    upload_resume_file,
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
        "interview_page_selected_job": None,
        "interview_question_index": 0,
        "interview_last_evaluation": None,
        "interview_current_question": None,
        "settings_keywords_text": None,
        "settings_locations_text": None,
        "settings_blacklist_keywords_text": None,
        "settings_blacklist_companies_text": None,
        "settings_sources_selected": None,
        "resume_keyword_suggestions_text": "",
        "resume_selected_professions": [],
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
        ["🧠 Overview", "🔍 Jobs", "📄 CV", "🎤 Interview Simulator", "📊 Statistics", "📁 Applications", "⚙️ Settings", "🧾 Logs"],
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

elif page == "🎤 Interview Simulator":
    st.markdown("## Interview Simulator")
    st.caption("Generate a recruiter-style interview pack manually, then practise one question at a time with feedback.")
    interview_jobs = get_interview_jobs_data()
    if not interview_jobs:
        st.info("No jobs are available yet. Run a search first.")
    else:
        preferred_job_id = st.session_state.interview_page_selected_job if any(job["id"] == st.session_state.interview_page_selected_job for job in interview_jobs) else interview_jobs[0]["id"]
        interview_options = {f"{item['company']} - {item['role']} ({item['id']})": item["id"] for item in interview_jobs}
        selected_interview_label = st.selectbox(
            "Select job for interview simulation",
            list(interview_options.keys()),
            index=list(interview_options.values()).index(preferred_job_id),
            key="interview_page_selector",
        )
        selected_interview_job_id = interview_options[selected_interview_label]
        st.session_state.interview_page_selected_job = selected_interview_job_id

        interview_data = get_interview_simulation_data(selected_interview_job_id)
        interview_task_running = is_task_running("interview_simulation_generation", job_id=selected_interview_job_id)

        ic1, ic2, ic3, ic4 = st.columns(4)
        ic1.metric("Company", interview_data["company"])
        ic2.metric("Role", interview_data["title"])
        ic3.metric("Base Match", interview_data["base_match_score"] if interview_data["base_match_score"] is not None else "N/A")
        ic4.metric("Tailored Match", interview_data["tailored_cv_match_score"] if interview_data["tailored_cv_match_score"] is not None else "Not generated")

        action_c1, action_c2 = st.columns(2)
        if action_c1.button(
            "Generate Interview Simulation",
            key=f"interview_generate_{selected_interview_job_id}",
            use_container_width=True,
            disabled=interview_task_running,
        ):
            if run_action("Interview simulation task queued", lambda: launch_generate_interview_simulation(selected_interview_job_id)) is not None:
                _refresh_task_monitor()
                st.rerun()

        interview_pdf_state_key = f"interview_pdf_payload_{selected_interview_job_id}"
        if interview_data["markdown_content"].strip():
            if action_c2.button(
                "Prepare Interview PDF",
                key=f"interview_prepare_pdf_{selected_interview_job_id}",
                use_container_width=True,
            ):
                exported = run_action("Interview PDF exported", lambda: export_interview_simulation_pdf(selected_interview_job_id))
                if isinstance(exported, dict):
                    st.session_state[interview_pdf_state_key] = exported
            interview_pdf_payload = st.session_state.get(interview_pdf_state_key)
            if isinstance(interview_pdf_payload, dict):
                action_c2.download_button(
                    "Download Interview PDF",
                    data=interview_pdf_payload["bytes"],
                    file_name=Path(interview_pdf_payload["path"]).name,
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"interview_download_pdf_{selected_interview_job_id}",
                )
        else:
            action_c2.button("Download Interview PDF", disabled=True, use_container_width=True, key=f"interview_pdf_disabled_{selected_interview_job_id}")

        simulation = interview_data["simulation"]
        if not simulation:
            st.info("No interview simulation has been generated for this job yet.")
        else:
            readiness = simulation["readiness_scores"]
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Interview Readiness", readiness["overall_interview_readiness_score"])
            rc2.metric("Technical Fit", readiness["technical_fit_score"])
            rc3.metric("Soft Skills Fit", readiness["soft_skills_fit_score"])
            rc4.metric("Hiring Confidence", readiness["hiring_confidence_score"])

            analysis = simulation["resume_analysis"]
            context = simulation["company_context"]
            st.markdown("### Resume Analysis")
            st.write(f"**Industry:** {context['industry']}")
            st.write(f"**Interview style:** {context['interview_style']}")
            st.write(f"**Work mode:** {context['work_mode']}")
            st.write(f"**Tech stack:** {', '.join(context['tech_stack']) or 'General software engineering'}")
            st.write(f"**Strong matches:** {', '.join(analysis['strong_matches']) or 'None detected'}")
            st.write(f"**Weak areas:** {', '.join(analysis['weak_areas']) or 'None detected'}")
            st.write(f"**Missing skills:** {', '.join(analysis['missing_skills']) or 'None detected'}")
            st.write(f"**Seniority fit:** {analysis['seniority_fit']}")
            st.write(f"**ATS compatibility:** {analysis['ats_compatibility']}")

            insights = simulation["recruiter_insights"]
            st.markdown("### Recruiter Insights")
            st.write(f"**What concerns me as a recruiter:** {', '.join(insights['what_concerns_me_as_a_recruiter']) or 'No major concerns'}")
            st.write(f"**What makes you stand out:** {', '.join(insights['what_makes_you_stand_out']) or 'No standout items yet'}")
            st.write(f"**What you should improve before the interview:** {', '.join(insights['what_you_should_improve_before_the_interview']) or 'No urgent improvements'}")
            st.write(f"**Most likely rejection reasons:** {', '.join(insights['most_likely_rejection_reasons']) or 'No likely rejection reasons identified'}")
            st.write(f"**Most likely hiring reasons:** {', '.join(insights['most_likely_hiring_reasons']) or 'No likely hiring reasons identified'}")

            st.markdown("### Interview Pack")
            for section in simulation["sections"]:
                with st.expander(section["section_name"], expanded=False):
                    for question in section["questions"]:
                        st.write(f"**Question:** {question['question']}")
                        st.write(f"**Strong example answer:** {question['strong_example_answer']}")
                        st.write(f"**Why this is good:** {question['why_the_answer_is_good']}")
                        st.write(f"**Common bad answer:** {question['common_bad_answer']}")
                        st.write(f"**What recruiters evaluate:** {question['what_recruiters_are_evaluating']}")
                        st.write(f"**Difficulty:** {question['difficulty_level']} · **Candidate confidence:** {question['candidate_confidence_score']}")
                        st.markdown("---")

            st.markdown("### Interactive Simulation")
            start_c1, start_c2 = st.columns(2)
            if start_c1.button("Load Current Question", key=f"interview_load_question_{selected_interview_job_id}", use_container_width=True):
                question_payload = run_action(
                    "Interactive question loaded",
                    lambda: get_interactive_interview_question(selected_interview_job_id, st.session_state.interview_question_index),
                )
                if isinstance(question_payload, dict):
                    st.session_state.interview_current_question = question_payload
                    st.session_state.interview_last_evaluation = None
            if start_c2.button("Next Question", key=f"interview_next_question_{selected_interview_job_id}", use_container_width=True):
                total_questions = sum(len(section["questions"]) for section in simulation["sections"])
                st.session_state.interview_question_index = min(st.session_state.interview_question_index + 1, max(0, total_questions - 1))
                question_payload = run_action(
                    "Next question loaded",
                    lambda: get_interactive_interview_question(selected_interview_job_id, st.session_state.interview_question_index),
                )
                if isinstance(question_payload, dict):
                    st.session_state.interview_current_question = question_payload
                    st.session_state.interview_last_evaluation = None

            current_question = st.session_state.get("interview_current_question")
            if isinstance(current_question, dict) and current_question.get("job_id") == selected_interview_job_id:
                question = current_question["question"]
                st.write(f"**Question {current_question['question_index'] + 1} of {current_question['total_questions']}:** {question['question']}")
                answer_key = f"interview_answer_{selected_interview_job_id}_{question['id']}"
                answer_text = st.text_area("Your answer", key=answer_key, height=180)
                if st.button("Evaluate Answer", key=f"interview_evaluate_{selected_interview_job_id}", use_container_width=True):
                    evaluation = run_action(
                        "Interview answer evaluated",
                        lambda: evaluate_interview_answer(selected_interview_job_id, question["id"], answer_text),
                    )
                    if isinstance(evaluation, dict):
                        st.session_state.interview_last_evaluation = evaluation
                evaluation = st.session_state.get("interview_last_evaluation")
                if isinstance(evaluation, dict) and evaluation.get("question_id") == question["id"]:
                    st.write(f"**Score:** {evaluation['score']}")
                    st.write(f"**Feedback:** {evaluation['feedback']}")
                    st.write(f"**Improved answer:** {evaluation['improved_answer']}")
                    st.write(f"**Confidence analysis:** {evaluation['confidence_analysis']}")
                    st.write(f"**Communication analysis:** {evaluation['communication_analysis']}")
            else:
                st.info("Load a question to start the interactive simulation.")

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
    profile = get_resume_profile_data()
    suggestions = get_resume_keyword_suggestions()
    if st.session_state.settings_keywords_text is None:
        st.session_state.settings_keywords_text = "\n".join(settings["keywords"])
    if st.session_state.settings_locations_text is None:
        st.session_state.settings_locations_text = "\n".join(settings["locations"])
    if st.session_state.settings_blacklist_keywords_text is None:
        st.session_state.settings_blacklist_keywords_text = "\n".join(settings["blacklist_keywords"])
    if st.session_state.settings_blacklist_companies_text is None:
        st.session_state.settings_blacklist_companies_text = "\n".join(settings["blacklist_companies"])
    if st.session_state.settings_sources_selected is None:
        st.session_state.settings_sources_selected = settings["sources"]
    if not st.session_state.resume_keyword_suggestions_text and suggestions.get("recommended_keywords"):
        st.session_state.resume_keyword_suggestions_text = "\n".join(suggestions["recommended_keywords"])
    if not st.session_state.resume_selected_professions and profile.get("profession_matches"):
        st.session_state.resume_selected_professions = [item["role_title"] for item in profile.get("profession_matches", [])[:5]]

    st.markdown("## Settings")
    st.caption("These settings map to config/settings.yaml. API keys are intentionally not shown here.")
    st.markdown("### Resume / CV Management")
    st.caption("Upload a local resume to extract skills, infer target roles, and generate smarter keyword suggestions.")
    uploaded_resume = st.file_uploader(
        "Upload resume",
        type=["pdf", "docx", "txt", "md", "markdown"],
        accept_multiple_files=False,
        help="Supported formats: PDF, DOCX, TXT, Markdown.",
    )
    resume_actions = st.columns(3)
    if resume_actions[0].button("Upload and Analyze Resume", use_container_width=True, disabled=uploaded_resume is None):
        if uploaded_resume is None:
            st.warning("Choose a resume file first.")
        else:
            uploaded_payload = run_action(
                "Resume uploaded and analyzed",
                lambda: upload_resume_file(uploaded_resume.name, uploaded_resume.getvalue()),
            )
            if isinstance(uploaded_payload, dict):
                st.session_state.resume_keyword_suggestions_text = "\n".join(uploaded_payload.get("recommended_keywords", []))
                clear_dashboard_caches()
                st.rerun()
    if resume_actions[1].button("Re-run Resume Analysis", use_container_width=True, disabled=not profile):
        refreshed_payload = run_action("Resume analysis refreshed", analyze_resume_profile)
        if isinstance(refreshed_payload, dict):
            st.session_state.resume_keyword_suggestions_text = "\n".join(refreshed_payload.get("recommended_keywords", []))
            clear_dashboard_caches()
            st.rerun()
    if resume_actions[2].button("Refresh Suggestions", use_container_width=True, disabled=not profile):
        refreshed_suggestions = run_action("Resume keyword suggestions refreshed", suggest_resume_keywords)
        if isinstance(refreshed_suggestions, dict):
            st.session_state.resume_keyword_suggestions_text = "\n".join(refreshed_suggestions.get("recommended_keywords", []))
            clear_dashboard_caches()
            st.rerun()

    if profile:
        info_c1, info_c2, info_c3, info_c4 = st.columns(4)
        info_c1.metric("Detected skills", len(profile.get("technical_skills", [])))
        info_c2.metric("Suggested professions", len(profile.get("suggested_professions", [])))
        info_c3.metric("ATS score", profile.get("resume_insights", {}).get("ats_optimization_score", "N/A"))
        info_c4.metric("Seniority", profile.get("seniority_level", "Unknown"))
        st.write(f"**Stored file:** `{profile.get('stored_file_path', 'Unknown')}`")
        st.write(f"**Uploaded at:** {profile.get('uploaded_at', 'Unknown')}")
        st.write(f"**Analysis source:** {profile.get('analysis_source', 'fallback')}")
        st.markdown("#### Professional Summary")
        st.info(profile.get("professional_summary", "No summary available."))

        st.markdown("#### Detected Skills")
        skill_groups = profile.get("skill_groups", {})
        skill_categories = [item for item in skill_groups.items() if item[1]]
        if skill_categories:
            skill_columns = st.columns(3)
            for index, (category, items) in enumerate(skill_categories):
                with skill_columns[index % 3]:
                    st.markdown(f"**{category}**")
                    st.write(", ".join(items))
        else:
            st.info("No grouped skills were detected yet.")

        detail_c1, detail_c2 = st.columns(2)
        with detail_c1:
            st.markdown("#### Experience Snapshot")
            st.write(f"**Job titles:** {', '.join(profile.get('job_titles', [])) or 'None detected'}")
            st.write(f"**Industries:** {', '.join(profile.get('industries', [])) or 'None inferred'}")
            st.write(f"**Suggested seniority levels:** {', '.join(profile.get('suggested_seniority_levels', [])) or 'None inferred'}")
            with st.expander("Work experience lines", expanded=False):
                for line in profile.get("work_experience", []):
                    st.write(f"- {line}")
        with detail_c2:
            st.markdown("#### Education and Certifications")
            st.write(f"**Education:** {', '.join(profile.get('education', [])) or 'None detected'}")
            st.write(f"**Certifications:** {', '.join(profile.get('certifications', [])) or 'None detected'}")
            st.write(f"**Suggested technologies:** {', '.join(profile.get('suggested_technologies', [])) or 'None suggested'}")

        st.markdown("#### Suggested Professions")
        profession_matches = profile.get("profession_matches", [])
        if profession_matches:
            profession_rows = [
                {
                    "Role": item["role_title"],
                    "Confidence": item["confidence_score"],
                    "Matched skills": ", ".join(item.get("matched_skills", [])),
                    "Missing skills": ", ".join(item.get("missing_skills", [])) or "None",
                    "Search keyword": item["suggested_search_keyword"],
                    "Why it fits": item["reason"],
                }
                for item in profession_matches
            ]
            st.dataframe(profession_rows, use_container_width=True, hide_index=True)
            profession_options = [item["role_title"] for item in profession_matches]
            selected_professions = st.multiselect(
                "Select professions to insert into Keywords",
                options=profession_options,
                key="resume_selected_professions",
                help="Only selected professions will be appended into your current keyword list.",
            )
            st.caption("Apply selected professions to keywords?")
            if st.button("Apply Selected Professions to Keywords", use_container_width=True):
                selected_keywords = [
                    next(
                        (
                            item["suggested_search_keyword"]
                            for item in profession_matches
                            if item["role_title"] == selected_role
                        ),
                        selected_role,
                    )
                    for selected_role in selected_professions
                ]
                if not selected_keywords:
                    st.warning("Choose at least one profession first.")
                else:
                    preview_keywords = [*selected_keywords, *[item for item in profile.get("recommended_keywords", []) if item not in selected_keywords][:6]]
                    st.session_state.settings_keywords_text = "\n".join(
                        [item for item in st.session_state.settings_keywords_text.splitlines() if item.strip()] + preview_keywords
                    )
                    if run_action("Selected professions applied to settings", lambda: apply_suggested_keywords_to_settings(preview_keywords)) is not None:
                        clear_dashboard_caches()
                        st.success("Selected professions were appended to your keyword list.")
                        st.rerun()
        else:
            st.info("No profession matches were generated yet.")

        st.markdown("#### Resume Insights")
        insights = profile.get("resume_insights", {})
        st.write(f"**Top strengths:** {', '.join(insights.get('top_strengths', [])) or 'None detected'}")
        st.write(f"**Most marketable skills:** {', '.join(insights.get('most_marketable_skills', [])) or 'None detected'}")
        st.write(f"**Missing high-demand skills:** {', '.join(insights.get('missing_high_demand_skills', [])) or 'None highlighted'}")

        st.markdown("#### Recommended Keywords")
        st.text_area(
            "AI-suggested keywords",
            key="resume_keyword_suggestions_text",
            height=160,
            help="Review these suggestions before copying them into your search keywords.",
        )
        st.caption("Apply AI suggested keywords?")
        if st.button("Apply AI Suggested Keywords", use_container_width=True):
            suggested_keywords = [item.strip() for item in st.session_state.resume_keyword_suggestions_text.splitlines() if item.strip()]
            if not suggested_keywords:
                st.warning("There are no suggested keywords to apply yet.")
            else:
                existing_lines = [item.strip() for item in st.session_state.settings_keywords_text.splitlines() if item.strip()]
                merged_preview = []
                seen = set()
                for item in [*existing_lines, *suggested_keywords]:
                    if item.lower() in seen:
                        continue
                    seen.add(item.lower())
                    merged_preview.append(item)
                st.session_state.settings_keywords_text = "\n".join(merged_preview)
                if run_action("Suggested keywords applied to settings", lambda: apply_suggested_keywords_to_settings(suggested_keywords)) is not None:
                    clear_dashboard_caches()
                    st.success("Suggested keywords were appended to Settings. Review them below if you want to keep editing.")
                    st.rerun()

        st.markdown("#### Debug / Preview")
        debug = profile.get("debug", {})
        debug_c1, debug_c2, debug_c3 = st.columns(3)
        debug_c1.metric("Raw text length", debug.get("extracted_raw_text_length", 0))
        debug_c2.metric("Parsed skill count", debug.get("parsed_skill_count", 0))
        debug_c3.metric("Final normalized skills", debug.get("final_normalized_skill_count", 0))
        st.write(f"**Detected sections:** {', '.join(debug.get('detected_sections', [])) or 'None'}")
        st.write(f"**Extraction method:** {debug.get('extraction_method', 'Unknown')}")
        st.write(f"**AI skill count:** {debug.get('ai_skill_count', 0)}")

    with st.form("settings_form"):
        keywords = st.text_area("Keywords", key="settings_keywords_text", height=140)
        locations = st.text_area("Locations", key="settings_locations_text", height=100)
        c1, c2 = st.columns(2)
        minimum_match_score = c1.slider("Minimum match score", min_value=0, max_value=100, value=settings["minimum_match_score"])
        search_interval_hours = c2.number_input("Search interval hours", min_value=1, max_value=168, value=settings["search_interval_hours"])
        sponsorship_required = st.toggle("Sponsorship required", value=settings["sponsorship_required"], disabled=True)
        blacklist_keywords = st.text_area("Blacklist keywords", key="settings_blacklist_keywords_text", height=120)
        blacklist_companies = st.text_area("Blacklist companies", key="settings_blacklist_companies_text", height=100)
        sources = st.multiselect("Active sources", options=["adzuna", "jsearch", "serpapi"], key="settings_sources_selected")
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
