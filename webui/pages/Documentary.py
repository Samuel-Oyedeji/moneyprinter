"""Documentary studio page: research → fact sheet review → script review.

Phase 1 of the long-form documentary pipeline. Each project pauses at human
checkpoints (fact sheet, script); approving moves it forward. Image sourcing
and rendering attach after script approval in phase 2.
"""
import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st

# Same as webui/Main.py: make sure the project root wins over any third-party
# package that happens to be named "app".
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config
from app.services.documentary import images as images_service
from app.services.documentary import pipeline, scriptwriter, store
from app.utils import utils

st.set_page_config(page_title="Documentary Studio", page_icon="🎬", layout="wide")

# Keep the film preview at a sane size: full column width makes a 16:9
# player enormous on wide screens. Same testid-based approach as Library.py.
st.markdown(
    """
<style>
video[data-testid="stVideo"] {
    max-height: 340px;
    width: auto !important;
    max-width: 100%;
    margin: 0 auto;
    display: block;
    border-radius: 10px;
    background: #000;
}
</style>
""",
    unsafe_allow_html=True,
)

st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("🎬 Documentary Studio")
st.caption(
    "Long-form still-image documentaries: web-grounded research, a sourced "
    "fact sheet you review, then a script in a restrained archival register."
)

STATUS_LABELS = {
    store.STATUS_CREATED: "🆕 Ready to research",
    store.STATUS_RESEARCHING: "🔎 Researching…",
    store.STATUS_FACTSHEET_REVIEW: "📋 Fact sheet awaiting review",
    store.STATUS_SCRIPTING: "✍️ Writing script…",
    store.STATUS_SCRIPT_REVIEW: "📜 Script awaiting review",
    store.STATUS_SCRIPT_APPROVED: "✅ Script approved",
    store.STATUS_SOURCING_IMAGES: "🖼 Sourcing images…",
    store.STATUS_IMAGE_REVIEW: "🖼 Images awaiting review",
    store.STATUS_RENDERING: "🎞 Rendering…",
    store.STATUS_DONE: "🏁 Done",
    store.STATUS_FAILED: "❌ Failed",
}

from app.services.documentary import research as research_service

serpapi_ready = bool(str(config.documentary.get("serpapi_api_key", "")).strip())


def _refresh_serpapi_quota():
    st.session_state["serpapi_quota"] = research_service.get_quota()


if serpapi_ready and "serpapi_quota" not in st.session_state:
    _refresh_serpapi_quota()
serpapi_quota = st.session_state.get("serpapi_quota")

if not serpapi_ready:
    st.warning(
        "SerpApi key is not set — research will fail. Add it under "
        "research settings below.",
        icon="🔑",
    )
elif serpapi_quota and serpapi_quota.get("error"):
    st.error(f"🔑 {serpapi_quota['error']} — fix it in research settings below.")
elif serpapi_quota and (serpapi_quota.get("left") or 0) <= 0 and serpapi_quota.get(
    "left"
) is not None:
    st.error(
        "🚫 The SerpApi key has no searches left — research is blocked. "
        "Change or top up the key in research settings, then refresh."
    )
elif serpapi_quota and (serpapi_quota.get("left") or 0) < research_service.QUOTA_WARN_THRESHOLD:
    st.warning(
        f"SerpApi quota is low: {serpapi_quota['left']} searches left "
        "(one research run uses ~14).",
        icon="⏳",
    )

# --------------------------------------------------------- research settings
with st.expander(
    "🔎 Research settings (SerpApi · Openverse)", expanded=not serpapi_ready
):
    key_col, save_col = st.columns([4, 1], vertical_alignment="bottom")
    serpapi_key = key_col.text_input(
        "SerpApi API key",
        value=str(config.documentary.get("serpapi_api_key", "") or ""),
        type="password",
        help="https://serpapi.com/manage-api-key — the free tier includes "
        "250 searches/month. Paste a key and hit Save; the quota refreshes "
        "against the new key immediately.",
    )
    if save_col.button("💾 Save key", type="primary" if not serpapi_ready else "secondary"):
        config.documentary["serpapi_api_key"] = serpapi_key.strip()
        config.save_config()
        _refresh_serpapi_quota()
        st.session_state["serpapi_key_saved"] = True
        st.rerun()

    if st.session_state.pop("serpapi_key_saved", False):
        saved_quota = st.session_state.get("serpapi_quota")
        if saved_quota and saved_quota.get("error"):
            st.error(f"Key saved, but: {saved_quota['error']}")
        elif saved_quota and saved_quota.get("left") is not None:
            st.success(f"Key saved — {saved_quota['left']} searches left.")
        else:
            st.success("Key saved.")

    quota_col, refresh_col = st.columns([3, 1], vertical_alignment="center")
    if serpapi_quota is None:
        quota_col.caption(
            "Quota unknown — no key set, or SerpApi was unreachable."
        )
    elif serpapi_quota.get("error"):
        quota_col.error(serpapi_quota["error"])
    else:
        left = serpapi_quota.get("left")
        per_month = serpapi_quota.get("per_month")
        quota_col.metric(
            "Searches left",
            f"{left if left is not None else '?'}"
            + (f" / {per_month}" if per_month else ""),
            help="One research run uses ~14 searches (7 queries × 2 engines).",
        )
    if refresh_col.button("🔄 Refresh quota"):
        _refresh_serpapi_quota()
        st.rerun()

    st.divider()
    st.caption(
        "**Openverse** (image sourcing) works without credentials, but "
        "anonymous requests are rate-limited hard enough that a long film "
        "gets throttled into timeouts — every one costs 15 seconds of a "
        "sourcing run. Register an application at "
        "https://api.openverse.org/v1/auth_tokens/register/ and paste the "
        "client id and secret it returns."
    )
    ov_id_col, ov_secret_col, ov_save_col = st.columns(
        [2, 2, 1], vertical_alignment="bottom"
    )
    openverse_id = ov_id_col.text_input(
        "Openverse client id",
        value=str(config.documentary.get("openverse_client_id", "") or ""),
    )
    openverse_secret = ov_secret_col.text_input(
        "Openverse client secret",
        value=str(config.documentary.get("openverse_client_secret", "") or ""),
        type="password",
    )
    if ov_save_col.button("💾 Save"):
        config.documentary["openverse_client_id"] = openverse_id.strip()
        config.documentary["openverse_client_secret"] = openverse_secret.strip()
        config.save_config()
        st.success("Openverse credentials saved.")

# ------------------------------------------------------------ voice settings
with st.expander("🎙 Narration voice settings"):
    from app.services import voice as voice_service

    current_voice = str(
        config.documentary.get("voice_name", "en-GB-RyanNeural-Male")
    )
    st.caption(f"Current narration voice: `{current_voice}`")

    key_col, fetch_col = st.columns([3, 1], vertical_alignment="bottom")
    elevenlabs_key = key_col.text_input(
        "ElevenLabs API key",
        value=str(config.elevenlabs.get("api_key", "") or ""),
        type="password",
        help="Stored in config.toml under [elevenlabs]. Favorite voices in "
        "your ElevenLabs voice library are the ones listed here.",
    )
    if elevenlabs_key != str(config.elevenlabs.get("api_key", "") or ""):
        config.elevenlabs["api_key"] = elevenlabs_key
        config.save_config()
    if fetch_col.button("Fetch voices", disabled=not elevenlabs_key.strip()):
        with st.spinner("Fetching your ElevenLabs voices…"):
            st.session_state["doc_el_voices"] = voice_service.get_elevenlabs_voices(
                elevenlabs_key.strip()
            )
        if not st.session_state["doc_el_voices"]:
            st.error(
                "No voices returned — check the API key, and note only "
                "voices marked as favorites in ElevenLabs are listed."
            )

    edge_voices = [
        "en-GB-RyanNeural-Male",
        "en-GB-ThomasNeural-Male",
        "en-GB-SoniaNeural-Female",
        "en-US-GuyNeural-Male",
        "en-US-ChristopherNeural-Male",
        "en-NG-AbeoNeural-Male",
        "en-NG-EzinneNeural-Female",
    ]
    voice_options = edge_voices + st.session_state.get("doc_el_voices", [])
    if current_voice not in voice_options:
        voice_options.insert(0, current_voice)
    chosen_voice = st.selectbox(
        "Narration voice (Edge TTS voices, plus ElevenLabs after fetching)",
        voice_options,
        index=voice_options.index(current_voice),
        format_func=lambda v: (
            f"ElevenLabs · {v.split(':', 2)[2]}"
            if v.startswith("elevenlabs:")
            else f"Edge · {v}"
        ),
    )
    if chosen_voice != current_voice:
        config.documentary["voice_name"] = chosen_voice
        config.save_config()
        st.success(f"Narration voice saved: {chosen_voice}")


# ============================================================ page sections
import threading
from datetime import date as date_cls
from datetime import time as time_cls
from datetime import timedelta

from app.services.documentary import costs as costs_service
from app.services.documentary import doc_schedule, thumbnail

DOC_STATUS_CHIPS = {
    doc_schedule.STATUS_PENDING: "🕐 pending",
    doc_schedule.STATUS_GENERATING: "⚙️ generating",
    doc_schedule.STATUS_UPLOADING: "⬆️ uploading",
    doc_schedule.STATUS_SCHEDULED: "📅 scheduled on YouTube",
    doc_schedule.STATUS_UPLOADED: "📥 uploaded (private draft)",
    doc_schedule.STATUS_FAILED: "❌ failed",
}


def _upload_load_line(day_iso: str) -> tuple[str, bool]:
    load = doc_schedule.daily_upload_load(day_iso)
    line = (
        f"{load['total']}/{load['budget']} uploads planned on {day_iso} "
        f"(Shorts {load['shorts']} + documentaries {load['documentaries']}). "
        "YouTube's API quota allows ~6 uploads/day."
    )
    return line, load["total"] >= load["budget"]


def _finished_projects() -> list[dict]:
    finished = []
    for project in store.list_projects():
        if project.get("status") != store.STATUS_DONE:
            continue
        final_path = os.path.join(
            utils.task_dir(project["project_id"]), "final-1.mp4"
        )
        if os.path.exists(final_path):
            project["_final_path"] = final_path
            finished.append(project)
    return finished


def _schedule_controls(prefix: str, day_default=None):
    """Shared date/time picker with the daily upload-budget indicator."""
    date_col, time_col = st.columns(2)
    day = date_col.date_input(
        "Publish date",
        value=day_default or (date_cls.today() + timedelta(days=1)),
        min_value=date_cls.today(),
        key=f"{prefix}_date",
    )
    at = time_col.time_input(
        "Publish time", value=time_cls(18, 0), key=f"{prefix}_time"
    )
    line, full = _upload_load_line(day.isoformat())
    (st.error if full else st.caption)(line)
    return day, at, full


def _render_library_tab():
    st.subheader("📚 Documentary library")
    projects = _finished_projects()
    if not projects:
        st.info("No finished films yet — complete a project in the Studio tab.")
        return

    for project in projects:
        pid = project["project_id"]
        script = store.load_script(pid) or {}
        youtube_meta = script.get("youtube", {})
        with st.container(border=True):
            thumb_col, info_col = st.columns([2, 3])
            with thumb_col:
                thumb_path = thumbnail.thumbnail_path(pid)
                if os.path.isfile(thumb_path):
                    st.image(thumb_path)
                else:
                    st.caption("No thumbnail yet.")
                gen_col, up_col = st.columns(2)
                if gen_col.button(
                    "🎨 " + ("Redesign" if os.path.isfile(thumb_path) else "Design"),
                    key=f"lib_thumb_{pid}",
                ):
                    costs_service.set_project(pid)
                    with st.spinner("Designing thumbnail with the image model…"):
                        result = thumbnail.ensure_thumbnail(
                            project, regenerate=True
                        )
                    if result:
                        st.rerun()
                    st.error("Thumbnail design failed — check the logs.")
                uploaded_thumb = up_col.file_uploader(
                    "Upload custom",
                    type=["jpg", "jpeg", "png"],
                    key=f"lib_thumb_up_{pid}",
                    label_visibility="collapsed",
                )
                if uploaded_thumb is not None:
                    custom_hash = hash(uploaded_thumb.getvalue())
                    if st.session_state.get(f"lib_thumb_done_{pid}") != custom_hash:
                        thumbnail._save_cover(
                            uploaded_thumb.getvalue(), thumb_path
                        )
                        st.session_state[f"lib_thumb_done_{pid}"] = custom_hash
                        st.rerun()
            with info_col:
                st.markdown(f"**{youtube_meta.get('title') or project['topic']}**")
                cost_summary = costs_service.summarize(pid)
                st.caption(
                    f"{script.get('word_count', 0)} words · "
                    f"~{max(script.get('word_count', 0), 1) // 150} min · "
                    f"cost ${cost_summary['total']:.2f}"
                    + ("*" if cost_summary["any_estimated"] else "")
                )
                with st.expander("Description & tags"):
                    if not youtube_meta.get("description_enhanced"):
                        st.caption(
                            "⚠️ Draft title/description from the scriptwriter "
                            "— use the button below to write proper publishing "
                            "copy (also happens automatically before upload)."
                        )
                    st.write(youtube_meta.get("description", "") or "_none yet_")
                    st.caption(", ".join(youtube_meta.get("tags", [])))
                    if st.button(
                        "✍️ Rewrite title & description", key=f"lib_desc_{pid}"
                    ):
                        costs_service.set_project(pid)
                        with st.spinner("Writing the YouTube packaging…"):
                            scriptwriter.ensure_youtube_packaging(
                                pid, script, regenerate=True
                            )
                        st.rerun()
                already = [
                    e
                    for e in doc_schedule.list_entries()
                    if e.get("project_id") == pid
                    and e.get("status") != doc_schedule.STATUS_FAILED
                ]
                if already:
                    entry = already[-1]
                    st.info(
                        f"{DOC_STATUS_CHIPS.get(entry['status'], entry['status'])}"
                        f" · {entry['date']} {entry.get('post_time', '')}"
                    )
                else:
                    day, at, full = _schedule_controls(f"lib_{pid}")
                    if st.button(
                        "📅 Schedule upload",
                        key=f"lib_sched_{pid}",
                        type="primary",
                        disabled=full,
                    ):
                        doc_schedule.create_entry(
                            date=day.isoformat(),
                            post_time=at.strftime("%H:%M"),
                            mode="library",
                            project_id=pid,
                            topic=project["topic"],
                        )
                        st.rerun()


def _render_schedule_tab():
    st.subheader("📅 Documentary schedule")
    with st.container(border=True):
        st.markdown("**🤖 Generate & schedule automatically**")
        st.caption(
            "On the publish date the full autopilot pipeline runs — research, "
            "script, images, render — and the film is uploaded with the "
            "publish time set. No checkpoints."
        )
        auto_topic = st.text_input("Topic", key="auto_topic")
        auto_notes = st.text_area(
            "Background notes (optional)", key="auto_notes", height=80
        )
        auto_minutes = st.slider(
            "Target length (minutes)", 3.0, 15.0, 8.0, 0.5, key="auto_minutes"
        )
        day, at, full = _schedule_controls("auto")
        if st.button(
            "🤖 Queue it", type="primary", disabled=full or not auto_topic.strip()
        ):
            doc_schedule.create_entry(
                date=day.isoformat(),
                post_time=at.strftime("%H:%M"),
                mode="auto",
                topic=auto_topic,
                user_notes=auto_notes,
                target_minutes=auto_minutes,
            )
            st.success("Queued — it will generate and upload on the due date.")
            st.rerun()

    entries = doc_schedule.list_entries()
    if not entries:
        st.info("Nothing scheduled yet.")
    for entry in entries:
        with st.container(border=True):
            info_col, action_col = st.columns([4, 1])
            label = entry.get("topic") or entry.get("project_id", "")
            mode_icon = "🤖" if entry["mode"] == "auto" else "📚"
            info_col.markdown(
                f"{mode_icon} **{label[:70]}**  \n"
                f"{entry['date']} {entry.get('post_time', '')} · "
                f"{DOC_STATUS_CHIPS.get(entry['status'], entry['status'])}"
            )
            if entry.get("error"):
                info_col.caption(f"⚠️ {entry['error'][:200]}")
            if entry["status"] == doc_schedule.STATUS_FAILED:
                if action_col.button("🔁 Retry", key=f"sch_retry_{entry['id']}"):
                    doc_schedule.reset_entry(entry["id"])
                    st.rerun()
            if entry["status"] in (
                doc_schedule.STATUS_PENDING,
                doc_schedule.STATUS_FAILED,
            ):
                if action_col.button("🗑", key=f"sch_del_{entry['id']}"):
                    doc_schedule.delete_entry(entry["id"])
                    st.rerun()

    st.divider()
    run_col, hint_col = st.columns([1, 3])
    if run_col.button("▶ Run due entries now"):
        threading.Thread(
            target=doc_schedule.run_due_entries, daemon=True
        ).start()
        st.success("Run started in the background — watch statuses above.")
    hint_col.caption(
        "Runs automatically with the existing cron hook: "
        "`POST /api/v1/schedules/run` now also triggers documentary entries."
    )


def _render_uploads_tab():
    st.subheader("⬆️ Uploads")
    entries = [
        e
        for e in doc_schedule.list_entries()
        if e.get("youtube_video_id")
        or e.get("status")
        in (
            doc_schedule.STATUS_GENERATING,
            doc_schedule.STATUS_UPLOADING,
            doc_schedule.STATUS_FAILED,
        )
    ]
    if not entries:
        st.info("No uploads yet — schedule a film from the Library tab.")
        return
    for entry in entries:
        with st.container(border=True):
            label = entry.get("topic") or entry.get("project_id", "")
            st.markdown(
                f"**{label[:70]}**  \n"
                f"{entry['date']} {entry.get('post_time', '')} · "
                f"{DOC_STATUS_CHIPS.get(entry['status'], entry['status'])}"
            )
            if entry.get("youtube_video_id"):
                st.markdown(
                    f"▶ [youtu.be/{entry['youtube_video_id']}]"
                    f"(https://youtu.be/{entry['youtube_video_id']})"
                )
            if entry.get("error"):
                st.caption(f"⚠️ {entry['error'][:300]}")
                if st.button("🔁 Retry", key=f"upl_retry_{entry['id']}"):
                    doc_schedule.reset_entry(entry["id"])
                    st.rerun()


section = st.segmented_control(
    "Section",
    ["🎬 Studio", "📚 Library", "📅 Schedule", "⬆️ Uploads"],
    default="🎬 Studio",
    key="doc_section",
    label_visibility="collapsed",
)
if section == "📚 Library":
    _render_library_tab()
    st.stop()
elif section == "📅 Schedule":
    _render_schedule_tab()
    st.stop()
elif section == "⬆️ Uploads":
    _render_uploads_tab()
    st.stop()

# ---------------------------------------------------------------- new project
with st.expander("➕ New documentary project", expanded=not store.list_projects()):
    with st.form("new_project"):
        topic = st.text_input(
            "Topic",
            placeholder="e.g. The 2002 Lagos armoury explosion",
        )
        user_notes = st.text_area(
            "Background notes / research you already have (optional)",
            height=120,
            help="Treated as a privileged source during research.",
        )
        target_minutes = st.slider(
            "Target length (minutes of narration)",
            min_value=3.0,
            max_value=20.0,
            value=10.0,
            step=0.5,
        )
        col_a, col_b, col_c = st.columns(3)
        auto_factsheet = col_a.checkbox("Auto-approve fact sheet", value=False)
        auto_script = col_b.checkbox("Auto-approve script", value=False)
        auto_images = col_c.checkbox(
            "Auto-approve images",
            value=False,
            help="The vision model scores every candidate and the best one "
            "is used without review; rendering follows automatically.",
        )
        if st.form_submit_button("Create project", type="primary"):
            if not topic.strip():
                st.error("Topic is required.")
            else:
                project = store.create_project(
                    topic=topic,
                    user_notes=user_notes,
                    auto_approve_factsheet=auto_factsheet,
                    auto_approve_script=auto_script,
                    auto_approve_images=auto_images,
                    target_minutes=target_minutes,
                )
                st.session_state["doc_selected"] = project["project_id"]
                st.rerun()

projects = store.list_projects()
if not projects:
    st.info("No documentary projects yet — create one above.")
    st.stop()

# -------------------------------------------------------------- project grid
selected_id = st.session_state.get("doc_selected")
if selected_id and not store.load_project(selected_id):
    selected_id = None
    st.session_state.pop("doc_selected", None)

if not selected_id:
    grid_columns = 3
    for row_start in range(0, len(projects), grid_columns):
        cols = st.columns(grid_columns)
        for col, grid_project in zip(
            cols, projects[row_start : row_start + grid_columns]
        ):
            pid = grid_project["project_id"]
            with col, st.container(border=True):
                script = store.load_script(pid) or {}
                title = script.get("title") or grid_project["topic"]
                st.markdown(f"**{title[:60]}**")
                created = datetime.fromtimestamp(
                    grid_project["created_at"]
                ).strftime("%b %d, %Y")
                st.caption(
                    f"{STATUS_LABELS.get(grid_project['status'], grid_project['status'])}"
                    f"  \n{created}"
                )
                if grid_project["status"] == store.STATUS_DONE:
                    cost_total = costs_service.summarize(pid)["total"]
                    st.caption(
                        f"{script.get('word_count', 0)} words · "
                        f"~{max(script.get('word_count', 0), 1) // 150} min · "
                        f"${cost_total:.2f}"
                    )
                elif grid_project.get("error"):
                    st.caption(f"⚠️ {grid_project['error'][:60]}")
                if st.button(
                    "Open →", key=f"grid_open_{pid}", use_container_width=True
                ):
                    st.session_state["doc_selected"] = pid
                    st.rerun()
    st.stop()

project = store.load_project(selected_id)
status = project["status"]
created = datetime.fromtimestamp(project["created_at"]).strftime("%b %d, %Y %H:%M")
back_col, meta_col, del_col = st.columns([1, 4, 1], vertical_alignment="center")
if back_col.button("← All projects"):
    st.session_state.pop("doc_selected", None)
    st.rerun()
meta_col.markdown(
    f"**{project['topic']}**  \n"
    f"{STATUS_LABELS.get(status, status)} · created {created}"
)
with del_col.popover("🗑 Delete"):
    st.caption("Removes this project's research, fact sheet and script from disk.")
    if st.button("Delete permanently", type="primary", key="doc_delete"):
        store.delete_project(selected_id)
        st.session_state.pop("doc_selected", None)
        st.rerun()

if project.get("user_notes"):
    with st.expander("Producer notes"):
        st.text(project["user_notes"])


def _run_with_spinner(label: str, fn, *args):
    """Run a pipeline call, showing the stage it is actually in.

    Autopilot chains research → script → images → render inside this one
    call, so a fixed label would claim "researching" for the whole run. The
    pipeline reports each stage through on_stage and the status box updates
    live while the script is still blocked here.
    """
    status = st.status(label, expanded=True)

    def on_stage(message: str) -> None:
        status.update(label=message)

    try:
        fn(*args, on_stage=on_stage)
        status.update(state="complete")
    except Exception as exc:
        status.update(state="error")
        st.error(f"{exc}")
    st.rerun()


# ----------------------------------------------------------------- by status
if status == store.STATUS_CREATED:
    st.markdown(
        "Research will search the web (SerpApi), fetch the most relevant "
        "sources, and distill a fact sheet with per-claim sources for review."
    )
    if st.button("🔎 Start research", type="primary", disabled=not serpapi_ready):
        _run_with_spinner(
            "Researching — searching, fetching sources, distilling facts. "
            "This can take a few minutes…",
            pipeline.run_research_stage,
            project,
        )

elif status in (
    store.STATUS_RESEARCHING,
    store.STATUS_SCRIPTING,
    store.STATUS_SOURCING_IMAGES,
    store.STATUS_RENDERING,
):
    st.info(
        "This project shows an in-progress stage. If the page was closed "
        "mid-run, the stage was interrupted — restart it below."
    )
    if st.button("↩️ Restart interrupted stage"):
        _run_with_spinner("Restarting stage…", pipeline.retry_failed, project)

elif status == store.STATUS_FAILED:
    st.error(f"Stage failed: {project.get('error', 'unknown error')}")
    if st.button("🔁 Retry", type="primary"):
        _run_with_spinner("Retrying failed stage…", pipeline.retry_failed, project)

elif status == store.STATUS_FACTSHEET_REVIEW:
    factsheet = store.load_factsheet(selected_id) or {}
    st.subheader("Fact sheet review")
    for warning in factsheet.get("research_warnings") or []:
        st.warning(warning)
    if factsheet.get("summary"):
        st.markdown(f"> {factsheet['summary']}")

    source_index = factsheet.get("source_index", [])
    with st.expander(f"Sources ({len(source_index)})"):
        for source in source_index:
            st.markdown(
                f"- **{source['label']}** · [{source['title'] or source['url']}]"
                f"({source['url']}) · `{source['domain']}`"
            )

    # Flatten facts for tabular editing; edits are written back on save.
    url_by_id = {}
    rows = []
    for section, facts in (factsheet.get("sections") or {}).items():
        for fact in facts:
            url_by_id[fact["id"]] = fact.get("source_urls", [])
            rows.append(
                {
                    "keep": True,
                    "id": fact["id"],
                    "section": section,
                    "claim": fact["claim"],
                    "quote": fact.get("quote", ""),
                    "confidence": fact.get("confidence", "medium"),
                    "sources": ", ".join(fact.get("sources", [])),
                }
            )
    edited = st.data_editor(
        pd.DataFrame(rows),
        num_rows="dynamic",
        use_container_width=True,
        height=440,
        column_config={
            "keep": st.column_config.CheckboxColumn("keep", width="small"),
            "id": st.column_config.TextColumn("id", disabled=True, width="small"),
            "section": st.column_config.SelectboxColumn(
                "section", options=list(factsheet.get("sections", {}).keys())
            ),
            "claim": st.column_config.TextColumn("claim", width="large"),
            "confidence": st.column_config.SelectboxColumn(
                "confidence", options=["high", "medium", "low"], width="small"
            ),
        },
        key="factsheet_editor",
    )

    if factsheet.get("conflicting_reports"):
        with st.expander("⚖️ Conflicting reports", expanded=True):
            for conflict in factsheet["conflicting_reports"]:
                st.markdown(f"**{conflict.get('issue', '')}**")
                for version in conflict.get("versions", []):
                    st.markdown(
                        f"- {version.get('claim', '')} "
                        f"({', '.join(version.get('sources', []))})"
                    )
    if factsheet.get("open_questions"):
        with st.expander("❓ Open questions"):
            for question in factsheet["open_questions"]:
                st.markdown(f"- {question}")

    def _save_factsheet_edits() -> dict:
        sections: dict[str, list] = {
            name: [] for name in factsheet.get("sections", {})
        }
        counter = 0
        for _, row in edited.iterrows():
            if not row.get("keep", True) or not str(row.get("claim", "")).strip():
                continue
            counter += 1
            section = str(row.get("section") or "background")
            fact_id = str(row.get("id") or f"F{counter}")
            sections.setdefault(section, []).append(
                {
                    "id": fact_id,
                    "claim": str(row["claim"]).strip(),
                    "quote": str(row.get("quote", "") or "").strip(),
                    "sources": [
                        s.strip()
                        for s in str(row.get("sources", "") or "").split(",")
                        if s.strip()
                    ]
                    or ["producer"],
                    "source_urls": url_by_id.get(fact_id, []),
                    "confidence": str(row.get("confidence", "medium")),
                }
            )
        factsheet["sections"] = sections
        store.save_factsheet(selected_id, factsheet)
        return factsheet

    save_col, approve_col, rerun_col = st.columns(3)
    if save_col.button("💾 Save edits"):
        _save_factsheet_edits()
        st.success("Fact sheet saved.")
    if approve_col.button("✅ Approve & write script", type="primary"):
        _save_factsheet_edits()
        _run_with_spinner(
            "Writing the script from the approved fact sheet…",
            pipeline.approve_factsheet,
            project,
        )
    if rerun_col.button("🔁 Re-run research"):
        _run_with_spinner(
            "Re-running research from scratch…",
            pipeline.run_research_stage,
            project,
        )

elif status in (store.STATUS_SCRIPT_REVIEW, store.STATUS_SCRIPT_APPROVED):
    script = store.load_script(selected_id) or {}
    approved = status == store.STATUS_SCRIPT_APPROVED
    st.subheader("Script" + (" (approved)" if approved else " review"))
    st.markdown(
        f"**{script.get('title', project['topic'])}** · "
        f"{script.get('word_count', 0)} words · "
        f"~{script.get('word_count', 0) // 150} min narration"
    )

    for section_idx, section in enumerate(script.get("sections", [])):
        with st.expander(
            f"{section.get('name', f'section {section_idx + 1}').replace('_', ' ').title()}",
            expanded=section_idx == 0,
        ):
            for para_idx, paragraph in enumerate(section.get("paragraphs", [])):
                key = f"doc_para_{section_idx}_{para_idx}"
                if approved:
                    st.markdown(paragraph.get("text", ""))
                    st.caption(f"🖼 {paragraph.get('image_cue', '')}")
                else:
                    st.text_area(
                        "Narration",
                        value=paragraph.get("text", ""),
                        key=f"{key}_text",
                        height=110,
                        label_visibility="collapsed",
                    )
                    cue_col, facts_col = st.columns([3, 1])
                    cue_col.text_input(
                        "Image cue",
                        value=paragraph.get("image_cue", ""),
                        key=f"{key}_cue",
                    )
                    facts_col.caption(
                        "Facts: " + (", ".join(paragraph.get("fact_ids", [])) or "—")
                    )

    youtube_meta = script.get("youtube", {})
    with st.expander("YouTube metadata"):
        st.markdown(
            f"**Title:** {youtube_meta.get('title', '')}  \n"
            f"**Description:** {youtube_meta.get('description', '')}  \n"
            f"**Tags:** {', '.join(youtube_meta.get('tags', []))}"
        )

    if approved:
        st.success(
            "Script approved. Next: source candidate images for every "
            "paragraph (Wikimedia Commons, Openverse, Pexels, Pixabay)."
        )
        source_col, download_col = st.columns(2)
        if source_col.button("🖼 Source images", type="primary"):
            _run_with_spinner(
                "Sourcing candidate images for every paragraph — searching "
                "four providers and downloading candidates. This can take a "
                "few minutes…",
                pipeline.run_image_sourcing_stage,
                project,
            )
        download_col.download_button(
            "⬇️ Download narration text",
            scriptwriter.full_narration_text(script),
            file_name=f"{selected_id}-narration.txt",
        )
    else:

        def _save_script_edits():
            for section_idx, section in enumerate(script.get("sections", [])):
                for para_idx, paragraph in enumerate(section.get("paragraphs", [])):
                    key = f"doc_para_{section_idx}_{para_idx}"
                    text_value = st.session_state.get(f"{key}_text")
                    cue_value = st.session_state.get(f"{key}_cue")
                    if text_value is not None:
                        paragraph["text"] = text_value.strip()
                    if cue_value is not None:
                        paragraph["image_cue"] = cue_value.strip()
            script["word_count"] = len(
                scriptwriter.full_narration_text(script).split()
            )
            store.save_script(selected_id, script)

        save_col, approve_col, regen_col = st.columns(3)
        if save_col.button("💾 Save edits"):
            _save_script_edits()
            st.success("Script saved.")
        if approve_col.button("✅ Approve script", type="primary"):
            _save_script_edits()
            pipeline.approve_script(project)
            st.rerun()
        if regen_col.button("🔁 Regenerate from fact sheet"):
            _run_with_spinner(
                "Regenerating the script…", pipeline.approve_factsheet, project
            )

elif status == store.STATUS_IMAGE_REVIEW:
    images = store.load_images(selected_id) or {"items": []}
    items = images.get("items", [])
    st.subheader("Image review")
    unresolved = sum(
        1 for item in items if not images_service.selected_image_path(item)
    )
    if unresolved:
        st.warning(
            f"{unresolved} paragraph(s) still need an image — pick a candidate, "
            "re-search with a better query, or upload your own."
        )
    else:
        st.success("Every paragraph has an image selected.")

    for item_idx, item in enumerate(items):
        item_key = item["key"]
        has_image = bool(images_service.selected_image_path(item))
        with st.expander(
            f"{'🟢' if has_image else '🔴'} {item['section']} · {item['cue'][:70]}",
            expanded=not has_image,
        ):
            st.caption(item["text_preview"])
            candidates = item.get("candidates", [])
            if candidates:
                cols = st.columns(min(len(candidates), 3))
                for cand_idx, candidate in enumerate(candidates):
                    with cols[cand_idx % len(cols)]:
                        if os.path.exists(candidate.get("local_path", "")):
                            st.image(candidate["local_path"])
                        score = candidate.get("score")
                        score_text = (
                            f" · ⭐ {score:g}" if isinstance(score, (int, float))
                            else ""
                        )
                        st.caption(
                            f"{candidate['provider']} · "
                            f"{candidate.get('license', '?')}{score_text}"
                            + (
                                f" · [source]({candidate['page_url']})"
                                if candidate.get("page_url")
                                else ""
                            )
                        )
                        if candidate.get("score_reason"):
                            st.caption(f"_{candidate['score_reason'][:90]}_")
                current = item.get("selected")
                options = list(range(len(candidates)))
                selection = st.radio(
                    "Use candidate",
                    options,
                    index=current if isinstance(current, int) else 0,
                    format_func=lambda i, c=candidates: (
                        f"#{i + 1} ({c[i]['provider']})"
                    ),
                    horizontal=True,
                    key=f"img_sel_{item_key}",
                )
                if selection != current and isinstance(selection, int):
                    item["selected"] = selection
                    store.save_images(selected_id, images)
            else:
                st.info("No candidates found for this cue.")

            search_col, upload_col = st.columns(2)
            with search_col:
                new_query = st.text_input(
                    "Re-search query",
                    value=item.get("queries", {}).get("archival", ""),
                    key=f"img_q_{item_key}",
                )
                if st.button("🔎 Re-search", key=f"img_rs_{item_key}"):
                    with st.spinner("Searching providers…"):
                        images_service.research_cue(
                            selected_id, item_key, new_query
                        )
                    st.rerun()
            with upload_col:
                uploaded = st.file_uploader(
                    "Or upload your own image",
                    type=["jpg", "jpeg", "png"],
                    key=f"img_up_{item_key}",
                )
                if uploaded is not None:
                    custom_path = os.path.join(
                        store.images_dir(selected_id),
                        f"{item_key}-custom-{uploaded.name}",
                    )
                    with open(custom_path, "wb") as f:
                        f.write(uploaded.getbuffer())
                    if item.get("selected") != {"custom": custom_path}:
                        item["selected"] = {"custom": custom_path}
                        store.save_images(selected_id, images)
                        st.rerun()
                if isinstance(item.get("selected"), dict):
                    st.caption("✅ Using uploaded image")

    approve_col, resource_col = st.columns(2)
    if approve_col.button(
        "✅ Approve images & render", type="primary", disabled=unresolved > 0
    ):
        _run_with_spinner(
            "Rendering — narration TTS, Ken Burns segments, final mux. "
            "A 10-minute film can take a while; leave this page open…",
            pipeline.approve_images,
            project,
        )
    if resource_col.button("🔁 Re-source all images"):
        _run_with_spinner(
            "Re-sourcing images for all paragraphs…",
            pipeline.run_image_sourcing_stage,
            project,
        )

elif status == store.STATUS_DONE:
    from app.services.documentary import costs as costs_service

    st.subheader("🏁 Finished film")
    final_path = os.path.join(utils.task_dir(selected_id), "final-1.mp4")
    if os.path.exists(final_path):
        script = store.load_script(selected_id) or {}
        cost_summary = costs_service.summarize(selected_id)
        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        word_count = script.get("word_count", 0)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Narration", f"{word_count} words")
        m2.metric("Approx. runtime", f"~{max(word_count, 1) // 150} min")
        m3.metric("File size", f"{size_mb:,.0f} MB")
        m4.metric(
            "Generation cost",
            f"${cost_summary['total']:.2f}"
            + ("*" if cost_summary["any_estimated"] else ""),
            help="Sum of tracked LLM, vision, search and TTS costs for this "
            "project. * means at least part of it is estimated from "
            "configured prices rather than reported by the provider.",
        )

        st.video(final_path)
        st.caption(
            "The film is also in the Video Library, so the existing YouTube "
            "upload and scheduling flows can use it."
        )

        button_col, cost_col = st.columns([1, 2])
        srt_path = os.path.join(utils.task_dir(selected_id), "final-1.srt")
        if os.path.exists(srt_path):
            with open(srt_path, "r", encoding="utf-8") as f:
                button_col.download_button(
                    "⬇️ Subtitles (.srt)",
                    f.read(),
                    file_name=f"{selected_id}.srt",
                )
        if cost_summary["entries"]:
            with st.expander("💰 Cost breakdown"):
                for kind, bucket in sorted(cost_summary["by_kind"].items()):
                    detail = f"{bucket['count']} calls"
                    if bucket["tokens"]:
                        detail += f" · {bucket['tokens']:,} tokens"
                    if bucket["characters"]:
                        detail += f" · {bucket['characters']:,} chars"
                    st.markdown(
                        f"- **{kind}**: ${bucket['cost']:.4f} ({detail})"
                    )
                st.caption(
                    "Prices for estimated entries come from [documentary] "
                    "config: llm_price_per_mtok, vision_price_per_mtok, "
                    "serpapi_price_per_search, elevenlabs_price_per_1k_chars."
                )
    else:
        st.error("Final video not found on disk.")
        if st.button("🔁 Re-render"):
            _run_with_spinner(
                "Re-rendering…", pipeline.approve_images, project
            )
