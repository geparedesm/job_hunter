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
    render_file_preview_if_exists,
    render_hero,
    render_jobs_table,
    render_logs,
    render_notifications,
    render_source_status,
    render_statistics_charts,
    render_terminal_card,
)
from dashboard.services import (
    JobFilters,
    approve_job,
    apply_to_job,
    clear_dashboard_caches,
    generate_cover_letter,
    generate_tailored_cv,
    get_application_history_data,
    get_job_detail_data,
    get_jobs_data,
    get_logs_data,
    get_notifications_data,
    get_overview_data,
    get_settings_data,
    get_statistics_data,
    mark_as_applied,
    recalculate_match,
    reject_job,
    save_manual_cv_content,
    save_settings_data,
    skip_job,
    trigger_search_now,
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
        result = callback()
        st.success(label)
        return result
    except Exception as exc:  # pragma: no cover - UI feedback
        st.error(str(exc))
        return None


overview = get_overview_data()
notifications = get_notifications_data()

if "selected_job_id" not in st.session_state:
    st.session_state.selected_job_id = None

with st.sidebar:
    st.markdown("## Navigation")
    page = st.radio(
        "Go to",
        ["🧠 Overview", "🔍 Jobs", "📊 Statistics", "📁 Applications", "⚙️ Settings", "🧾 Logs"],
        label_visibility="collapsed",
    )
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
        if action_c1.button("Search Now", use_container_width=True, type="primary"):
            result = run_action("Search completed", trigger_search_now)
            if isinstance(result, dict):
                st.info(
                    f"Discovered {result['discovered']} jobs, created {result['created']}, analyzed {result['analyzed']}, pending approval {result['pending_approval']}."
                )
                st.rerun()
        if action_c2.button("Refresh Dashboard Cache", use_container_width=True):
            clear_dashboard_caches()
            st.rerun()
    with c2:
        render_terminal_card("API / SOURCE STATUS", "Configured sources currently available below.", eyebrow="Status")
        render_source_status(overview["source_status"])
        st.markdown("### Notifications panel")
        render_notifications(notifications)

elif page == "🔍 Jobs":
    with st.expander("Filters Panel", expanded=True):
        fc1, fc2, fc3 = st.columns(3)
        keyword = fc1.text_input("Keyword")
        source = fc1.selectbox("Source", ["All sources"] + [item["source"] for item in overview["source_status"]])
        status = fc2.selectbox(
            "Status",
            ["All statuses", "found", "analyzed", "documents_generated", "pending_approval", "approved", "applied", "rejected", "skipped", "failed"],
        )
        location = fc2.text_input("Location")
        min_score = fc3.slider("Minimum match score", min_value=0, max_value=100, value=60, step=5)
        sponsorship_only = fc3.toggle("Sponsorship only", value=False)
        required_skills_only = st.toggle("Show only jobs with required skills detected", value=False)
        date_from, date_to = st.date_input("Date range", value=(date.today() - timedelta(days=30), date.today()))
        filters = JobFilters(
            keyword=keyword,
            source=source,
            status=status,
            location=location,
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
        selected_label = st.selectbox("Selected job", list(options.keys()))
        st.session_state.selected_job_id = options[selected_label]
        selected_job = next(item for item in jobs if item["id"] == st.session_state.selected_job_id)

        st.caption(
            f"Selected: {selected_job['company']} · {selected_job['role']} · {selected_job['location'] or 'Unknown location'}"
        )

        quick_top = st.columns(4)
        quick_top[0].button("View Analysis Below", key="jobs_view_selected", use_container_width=True, disabled=True)
        if quick_top[1].button("Generate Tailored CV", key="jobs_generate_cv", use_container_width=True):
            if run_action("Tailored CV generated", lambda: generate_tailored_cv(st.session_state.selected_job_id)) is not None:
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
        if quick_bottom[2].button("Generate Cover Letter", key="jobs_generate_cover_letter", use_container_width=True):
            if run_action("Cover letter generated", lambda: generate_cover_letter(st.session_state.selected_job_id)) is not None:
                st.rerun()

    if st.session_state.selected_job_id:
        detail = get_job_detail_data(st.session_state.selected_job_id)
        st.markdown("## Job Detail View")
        tabs = st.tabs(["Overview", "AI Analysis", "CV", "Cover Letter", "Application"])

        with tabs[0]:
            st.markdown(f"### {detail['company']} // {detail['role']}")
            st.write(f"**Location:** {detail['location'] or 'Unknown'}")
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

        with tabs[1]:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Base CV Match Score", detail["base_match_score"] or 0)
            mc2.metric("Recommendation", detail["recommended_action"] or "N/A")
            mc3.metric("Visa / work rights", detail["visa_analysis"]["status"])
            tc1, tc2 = st.columns(2)
            tc1.metric(
                "Tailored CV Match Score",
                detail["tailored_cv_match_score"] if detail["tailored_cv_match_score"] is not None else "Not generated yet",
            )
            if tc2.button("Recalculate Match Scores", key=f"detail_recalculate_match_{detail['id']}", use_container_width=True):
                if run_action("Match scores recalculated", lambda: recalculate_match(detail["id"])) is not None:
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

        with tabs[2]:
            st.info("Tailored CV generation is manual only. Nothing is generated during search or scheduling.")
            uploaded_cv = st.file_uploader("Upload manual CV (.md or .txt)", type=["md", "txt"], key=f"manual_cv_upload_{detail['id']}")
            current_cv_value = detail["manual_cv_content"]
            if uploaded_cv is not None:
                current_cv_value = uploaded_cv.getvalue().decode("utf-8", errors="ignore")
            manual_cv_editor = st.text_area(
                "Manual CV / profile content",
                value=current_cv_value,
                height=320,
                key=f"manual_cv_editor_{detail['id']}",
            )
            c1, c2, c3 = st.columns(3)
            if c1.button("Save Manual CV", key=f"detail_save_manual_cv_{detail['id']}", use_container_width=True):
                if run_action("Manual CV saved", lambda: save_manual_cv_content(manual_cv_editor)) is not None:
                    st.rerun()
            c2.download_button(
                "Download Current CV",
                data=manual_cv_editor.encode("utf-8"),
                file_name=f"{detail['company']}_{detail['role']}_cv.md".replace(" ", "_"),
                use_container_width=True,
            )
            if c3.button("Generate Tailored CV", key=f"detail_generate_cv_{detail['id']}", use_container_width=True):
                if run_action("Tailored CV generated", lambda: generate_tailored_cv(detail["id"])) is not None:
                    st.rerun()
            if detail["generated_cv_path"]:
                st.write(f"Stored file: `{detail['generated_cv_path']}`")
                st.download_button(
                    "Download Tailored CV",
                    data=detail["generated_cv"].encode("utf-8"),
                    file_name=Path(detail["generated_cv_path"]).name,
                    use_container_width=False,
                    key=f"detail_download_generated_cv_{detail['id']}",
                )
                with st.expander("Preview tailored CV", expanded=False):
                    st.code(detail["generated_cv"], language="markdown")

        with tabs[3]:
            st.info("Cover letters are generated only when you press the button below.")
            cl1, cl2 = st.columns(2)
            if cl1.button("Generate Cover Letter", key=f"detail_generate_cover_letter_{detail['id']}", use_container_width=True):
                if run_action("Cover letter generated", lambda: generate_cover_letter(detail["id"])) is not None:
                    st.rerun()
            if cl2.button("Recalculate Match Scores", key=f"detail_recalculate_match_cover_{detail['id']}", use_container_width=True):
                if run_action("Match scores recalculated", lambda: recalculate_match(detail["id"])) is not None:
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

        with tabs[4]:
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
            if st.button("Run Assisted Application Flow", key=f"detail_assisted_apply_{detail['id']}", use_container_width=True):
                message = run_action("Application flow completed", lambda: apply_to_job(detail["id"]))
                if message:
                    st.info(message)
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
