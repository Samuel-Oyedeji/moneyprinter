"""Animation studio: paper cut-out story videos, drawn entirely in code.

Create  - one topic or a batch, a length, an aspect ratio and an ElevenLabs
          voice; generation runs in the background (storyboard → voice-over
          → Remotion render → YouTube metadata).
Library - finished videos: preview, edit the YouTube copy, schedule, upload,
          or mark as already posted.
Schedule- single and batch YouTube scheduling on the animation calendar,
          booked against the 6-a-day upload budget shared with Shorts and
          documentaries.
"""
import os
import sys
import threading
from datetime import date as date_cls
from datetime import datetime
from datetime import time as time_cls
from datetime import timedelta

import pandas as pd
import streamlit as st

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config  # noqa: E402
from app.services import upload_budget  # noqa: E402
from app.services import schedule as shorts_schedule  # noqa: E402
from app.services import voice as voice_service  # noqa: E402
from app.services.animation import jobs, pipeline, render, store  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.animation import metadata as metadata_service  # noqa: E402
from app.services.animation import storyboard as storyboard_service  # noqa: E402

st.set_page_config(page_title="Animation Studio", page_icon="🎞", layout="wide")
st.markdown(
    """
<style>
video[data-testid="stVideo"] {
    max-height: 360px;
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
st.title("🎞 Animation Studio")
st.caption(
    "Paper cut-out story videos for moral stories, history and facts. Every "
    "character, prop and scene is drawn in code by Remotion. No generated images."
)

LENGTHS = [15, 20, 30, 45, 60, 90, 120]
ASPECT_LABELS = {"9:16": "Vertical 9:16 · Shorts", "16:9": "Landscape 16:9 · YouTube"}
STATUS_LABELS = {
    store.STATUS_QUEUED: "🕐 Queued",
    store.STATUS_WRITING: "✍️ Writing storyboard",
    store.STATUS_VOICING: "🎙 Recording narration",
    store.STATUS_RENDERING: "🎞 Rendering",
    store.STATUS_PACKAGING: "🏷 Writing YouTube copy",
    store.STATUS_DONE: "✅ Done",
    store.STATUS_FAILED: "❌ Failed",
}
ENTRY_CHIPS = {
    anim_schedule.STATUS_PENDING: "🕐 pending",
    anim_schedule.STATUS_GENERATING: "⚙️ generating",
    anim_schedule.STATUS_UPLOADING: "⬆️ uploading",
    anim_schedule.STATUS_SCHEDULED: "📅 scheduled on YouTube",
    anim_schedule.STATUS_UPLOADED: "📥 uploaded (private draft)",
    anim_schedule.STATUS_POSTED: "✅ posted by hand",
    anim_schedule.STATUS_FAILED: "❌ failed",
}
EDGE_VOICES = ["en-GB-RyanNeural", "en-GB-SoniaNeural", "en-US-AndrewNeural", "en-US-AvaNeural", "en-NG-AbeoNeural", "en-NG-EzinneNeural"]

# after a restart, pick up queued work and flag cut-off runs
if "anim_recovered" not in st.session_state:
    jobs.recover()
    st.session_state["anim_recovered"] = True

render_ok, render_msg = render.readiness()
if not render_ok:
    st.error(f"🎞 {render_msg}. Rendering is blocked until this is fixed.")


def _voice_label(v: str) -> str:
    return f"ElevenLabs · {v.split(':', 2)[2]}" if v.startswith("elevenlabs:") and v.count(":") >= 2 else f"Edge · {v}"


def _voice_options() -> list[str]:
    current = pipeline.default_voice()
    options = [current] + st.session_state.get("anim_el_voices", [])
    for doc_voice in [str(config.documentary.get("voice_name", "") or "")]:
        if doc_voice:
            options.append(doc_voice)
    options += EDGE_VOICES
    return list(dict.fromkeys(o for o in options if o))


# ------------------------------------------------------------ voice settings
with st.expander("🎙 Voice (ElevenLabs)", expanded=not voice_service.get_elevenlabs_api_key()):
    key_col, fetch_col = st.columns([3, 1], vertical_alignment="bottom")
    el_key = key_col.text_input(
        "ElevenLabs API key",
        value=str(config.elevenlabs.get("api_key", "") or ""),
        type="password",
        help="Shared with the rest of the app ([elevenlabs] in config.toml). "
        "Voices marked as favorites in your ElevenLabs library are listed.",
    )
    if el_key != str(config.elevenlabs.get("api_key", "") or ""):
        config.elevenlabs["api_key"] = el_key
        config.save_config()
    if fetch_col.button("Fetch my voices", disabled=not el_key.strip()):
        with st.spinner("Fetching your ElevenLabs voices…"):
            st.session_state["anim_el_voices"] = voice_service.get_elevenlabs_voices(el_key.strip())
        if not st.session_state["anim_el_voices"]:
            st.error("No voices returned. Check the key; only favorite voices are listed.")
    options = _voice_options()
    default = pipeline.default_voice()
    chosen = st.selectbox("Default narration voice", options, index=options.index(default), format_func=_voice_label)
    if chosen != default:
        config.animation["voice_name"] = chosen
        config.save_config()
        st.success("Default voice saved.")
    st.caption(
        "ElevenLabs returns word-level timings, which drive the captions and when "
        "each character moves. Edge voices are free, for drafts."
    )

section = st.segmented_control(
    "Section",
    ["🎬 Create", "📚 Library", "📅 Schedule"],
    default="🎬 Create",
    key="anim_section",
    label_visibility="collapsed",
)


# =================================================================== helpers
def _load_line(day_iso: str) -> tuple[str, dict]:
    load = upload_budget.daily_load(day_iso)
    line = (
        f"{load['total']}/{load['budget']} uploads booked on {day_iso}: Shorts {load['shorts']}, "
        f"documentaries {load['documentaries']}, animations {load['animations']}."
    )
    return line, load


def _date_time_inputs(prefix: str, default_day=None):
    d_col, t_col = st.columns(2)
    day = d_col.date_input("Publish date", value=default_day or date_cls.today() + timedelta(days=1), min_value=date_cls.today(), key=f"{prefix}_day")
    at = t_col.time_input("Publish time", value=time_cls(18, 0), key=f"{prefix}_time", step=300)
    line, load = _load_line(day.isoformat())
    (st.error if load["full"] else st.caption)(("🚫 Day is full. " if load["full"] else "") + line)
    return day, at, load["full"]


def _video_status(project: dict) -> str:
    if (project.get("posted") or {}).get("manual"):
        return "✅ posted by hand"
    entries = [e for e in anim_schedule.entries_for_project(project["project_id"]) if e["status"] != anim_schedule.STATUS_FAILED]
    if entries:
        e = entries[-1]
        return f"{ENTRY_CHIPS.get(e['status'], e['status'])} · {e['date']} {e.get('post_time', '')}".strip()
    return "not scheduled"


def _schedulable(project: dict) -> bool:
    if (project.get("posted") or {}).get("manual"):
        return False
    return not any(
        e["status"] in anim_schedule.ACTIVE_STATUSES + anim_schedule.DONE_STATUSES
        for e in anim_schedule.entries_for_project(project["project_id"])
    )


def _fmt_secs(s) -> str:
    s = float(s or 0)
    return f"{int(s // 60)}:{int(s % 60):02d}"


def _parse_batch(text: str) -> list[dict]:
    items = []
    for line in shorts_schedule.parse_topics(text):
        topic, _, context = line.partition("|")
        if topic.strip():
            items.append({"topic": topic.strip(), "context": context.strip()})
    return items


# =================================================================== create
def _render_create():
    if not voice_service.get_elevenlabs_api_key():
        st.info("Add your ElevenLabs key above for studio-quality narration; without it, pick a free Edge voice.", icon="🎙")

    mode = st.radio("What are you making?", ["Single video", "Batch"], horizontal=True, key="anim_mode")
    with st.form("anim_create"):
        if mode == "Single video":
            topic = st.text_input("Topic", placeholder="e.g. Why the Leaning Tower of Pisa leans")
            context = st.text_area(
                "Research / description (optional)",
                height=110,
                help="Facts, angle or the moral you want. The writer treats this as the most reliable source.",
            )
            items = [{"topic": topic.strip(), "context": context.strip()}] if topic.strip() else []
        else:
            batch = st.text_area(
                "Topics, one per line. Add context after a | (optional)",
                height=180,
                placeholder=(
                    "The boy who cried wolf | a moral about honesty\n"
                    "How the Great Fire of London started | 2 September 1666, Pudding Lane bakery\n"
                    "Why octopuses have three hearts"
                ),
            )
            items = _parse_batch(batch)
        c1, c2, c3 = st.columns([2, 2, 3])
        seconds = c1.select_slider(
            "Length", options=LENGTHS, value=int(config.animation.get("default_seconds", 30) or 30), format_func=lambda s: f"{s} s"
        )
        aspect_default = str(config.animation.get("default_aspect", "9:16") or "9:16")
        aspect = c2.radio(
            "Aspect ratio", list(ASPECT_LABELS), index=list(ASPECT_LABELS).index(aspect_default), format_func=lambda a: ASPECT_LABELS[a]
        )
        voices = _voice_options()
        voice = c3.selectbox("Voice", voices, index=0, format_func=_voice_label)
        go = st.form_submit_button("🎬 Generate", type="primary", disabled=not render_ok)
    if go:
        if not items:
            st.error("Add a topic first.")
        else:
            created = [store.create_project(i["topic"], i["context"], seconds, aspect, voice) for i in items]
            jobs.enqueue([p["project_id"] for p in created])
            st.success(f"Queued {len(created)} video(s). They render one at a time; progress below.")

    _render_progress()


@st.fragment(run_every="3s")
def _render_progress():
    projects = store.list_projects()
    active = [p for p in projects if p["status"] in (store.STATUS_QUEUED, *store.RUNNING_STATUSES)]
    failed = [p for p in projects if p["status"] == store.STATUS_FAILED][:10]
    done = [p for p in projects if p["status"] == store.STATUS_DONE][:3]
    if not (active or failed or done):
        st.caption("Nothing generated yet.")
        return
    st.subheader("In progress", anchor=False)
    if not active:
        st.caption("Nothing running.")
    for p in sorted(active, key=lambda p: p.get("created_at", 0)):
        with st.container(border=True):
            left, right = st.columns([5, 1], vertical_alignment="center")
            left.markdown(f"**{p['topic'][:80]}** · {p['seconds']} s · {p['aspect']}")
            left.progress(float(p.get("progress") or 0.0), text=f"{STATUS_LABELS.get(p['status'], p['status'])} · {p.get('stage', '')}")
            if p["status"] == store.STATUS_QUEUED and not jobs.is_active(p["project_id"]):
                if right.button("▶ Start", key=f"start_{p['project_id']}"):
                    jobs.enqueue([p["project_id"]])
                    st.rerun()
    if failed:
        st.subheader("Needs attention", anchor=False)
        for p in failed:
            with st.container(border=True):
                left, right = st.columns([5, 1], vertical_alignment="center")
                left.markdown(f"**{p['topic'][:80]}**  \n❌ {p.get('error', '')[:300]}")
                if right.button("🔁 Retry", key=f"retry_{p['project_id']}"):
                    jobs.enqueue([p["project_id"]])
                    st.rerun()
                if right.button("🗑", key=f"del_failed_{p['project_id']}"):
                    store.delete_project(p["project_id"])
                    st.rerun()
    if done:
        st.caption("Latest finished: " + " · ".join(p.get("youtube", {}).get("title") or p["topic"] for p in done) + ". See the Library.")


# =================================================================== library
def _metadata_editor(p: dict):
    pid = p["project_id"]
    meta = p.get("youtube") or {}
    with st.expander("🏷 YouTube title, description & hashtags", expanded=False):
        title = st.text_input("Title", value=meta.get("title", ""), key=f"meta_title_{pid}", max_chars=100)
        description = st.text_area("Description", value=meta.get("description", ""), key=f"meta_desc_{pid}", height=220)
        hashtags = st.text_input("Hashtags", value=" ".join(meta.get("hashtags", [])), key=f"meta_tags_{pid}")
        tags = st.text_input("Tags (comma separated)", value=", ".join(meta.get("tags", [])), key=f"meta_kw_{pid}")
        save_col, regen_col = st.columns(2)
        if save_col.button("💾 Save", key=f"meta_save_{pid}"):
            cleaned = metadata_service.sanitize(
                {"title": title, "description": description, "hashtags": hashtags.split(), "tags": [t for t in tags.split(",")]},
                p["topic"],
                p["aspect"],
            )
            cleaned["generated"] = True
            store.update_project(pid, youtube=cleaned)
            st.rerun()
        if regen_col.button("✍️ Rewrite with AI", key=f"meta_regen_{pid}"):
            board = store.read_json(store.path(pid, "storyboard.json")) or {}
            with st.spinner("Writing the YouTube copy…"):
                meta = metadata_service.generate(
                    p["topic"], storyboard_service.narration_text(board), p["aspect"], board.get("title", ""),
                    on_cost=lambda c: store.add_cost(pid, "llm", c),
                )
            store.update_project(pid, youtube=meta)
            st.rerun()


def _library_card(p: dict):
    pid = p["project_id"]
    meta = p.get("youtube") or {}
    with st.container(border=True):
        video_col, info_col = st.columns([2, 3])
        with video_col:
            st.video(store.final_path(pid))
        with info_col:
            st.markdown(f"**{meta.get('title') or p['topic']}**")
            created = datetime.fromtimestamp(p.get("created_at", 0)).strftime("%b %d, %Y")
            st.caption(
                f"{_fmt_secs(p.get('duration'))} · {p['aspect']} · ${store.total_cost(p):.2f} · {created}  \n"
                f"{_video_status(p)}"
            )
            if p.get("youtube_video_id"):
                st.markdown(f"▶ [youtu.be/{p['youtube_video_id']}](https://youtu.be/{p['youtube_video_id']})")
            posted = p.get("posted") or {}
            if posted.get("url"):
                st.markdown(f"🔗 [{posted['url']}]({posted['url']})")
            _metadata_editor(p)

            if _schedulable(p):
                with st.popover("📅 Schedule", use_container_width=True):
                    day, at, full = _date_time_inputs(f"lib_{pid}")
                    if st.button("Schedule upload", key=f"lib_sched_{pid}", type="primary", disabled=full):
                        try:
                            anim_schedule.create_entry(date=day.isoformat(), post_time=at.strftime("%H:%M"), project_id=pid)
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
            action_cols = st.columns(3)
            if _schedulable(p):
                today_load = upload_budget.daily_load(date_cls.today().isoformat())
                if action_cols[0].button(
                    "⬆️ Upload now",
                    key=f"lib_now_{pid}",
                    disabled=today_load["full"],
                    help="Uploads today as a private draft (uses one of today's 6 uploads).",
                ):
                    try:
                        anim_schedule.upload_now(pid)
                        st.success("Uploading in the background.")
                    except ValueError as exc:
                        st.error(str(exc))
                with action_cols[1].popover("✅ Already posted"):
                    st.caption("Uploaded it yourself? Mark it so it leaves the calendar and doesn't count toward the upload budget.")
                    url = st.text_input("Video URL (optional)", key=f"posted_url_{pid}")
                    posted_on = st.date_input("Posted on", value=date_cls.today(), key=f"posted_day_{pid}")
                    if st.button("Mark as posted", key=f"posted_btn_{pid}", type="primary"):
                        anim_schedule.mark_posted(pid, url=url, posted_on=posted_on.isoformat())
                        st.rerun()
            elif posted.get("manual"):
                if action_cols[0].button("↩️ Unmark posted", key=f"unpost_{pid}"):
                    store.unmark_posted(pid)
                    st.rerun()
            with action_cols[2].popover("⋯ More"):
                redo = st.selectbox(
                    "Redo from",
                    ["render", "voice", "storyboard", "package"],
                    format_func={
                        "render": "Render again",
                        "voice": "New voice-over + render",
                        "storyboard": "New storyboard (everything)",
                        "package": "Rewrite YouTube copy only",
                    }.get,
                    key=f"redo_{pid}",
                )
                if st.button("Run", key=f"redo_btn_{pid}"):
                    pipeline.reset_from(pid, redo)
                    jobs.enqueue([pid])
                    st.rerun()
                st.divider()
                if st.button("🗑 Delete video", key=f"lib_del_{pid}", type="primary"):
                    for e in anim_schedule.entries_for_project(pid):
                        if e["status"] in (anim_schedule.STATUS_PENDING, anim_schedule.STATUS_FAILED):
                            anim_schedule.delete_entry(e["id"])
                    store.delete_project(pid)
                    st.rerun()


def _render_library():
    projects = store.finished_projects()
    if not projects:
        st.info("No finished videos yet. Generate one in the Create tab.")
        return
    filt = st.segmented_control(
        "Show", ["All", "Not scheduled", "Scheduled / uploaded", "Posted by hand"], default="All", key="lib_filter"
    )

    def keep(p):
        status = _video_status(p)
        if filt == "Not scheduled":
            return status == "not scheduled"
        if filt == "Scheduled / uploaded":
            return status != "not scheduled" and not (p.get("posted") or {}).get("manual")
        if filt == "Posted by hand":
            return bool((p.get("posted") or {}).get("manual"))
        return True

    shown = [p for p in projects if keep(p)]
    st.caption(f"{len(shown)} of {len(projects)} video(s)")
    for p in shown:
        _library_card(p)


# =================================================================== schedule
_PLAN = "anim_batch_plan"


def _render_budget_strip():
    rows = upload_budget.upcoming(14)
    frame = pd.DataFrame(
        [
            {
                "Date": datetime.fromisoformat(r["date"]).strftime("%a %b %d"),
                "Shorts": r["shorts"],
                "Documentaries": r["documentaries"],
                "Animations": r["animations"],
                "Booked": f"{r['total']}/{r['budget']}",
                "Free": r["left"],
            }
            for r in rows
        ]
    )
    with st.expander("📊 Upload budget, next 14 days (shared by every calendar, 6 a day)"):
        st.dataframe(frame, hide_index=True, use_container_width=True)


def _render_schedule():
    from app.services import youtube_upload

    if not youtube_upload.youtube_upload_service.is_configured():
        st.warning(
            "YouTube uploads aren't set up on this machine (youtube.enabled + an OAuth token). "
            "Entries will fail at upload time until then.",
            icon="🔑",
        )
    _render_budget_strip()

    finished = [p for p in store.finished_projects() if _schedulable(p)]
    label_of = {p["project_id"]: f"{(p.get('youtube') or {}).get('title') or p['topic']} · {p['aspect']} · {_fmt_secs(p.get('duration'))}" for p in finished}

    single_tab, batch_tab = st.tabs(["Single", "Batch"])
    with single_tab:
        source = st.radio("Schedule", ["A finished video", "A topic (generated on the day)"], horizontal=True, key="single_src")
        if source == "A finished video":
            if not finished:
                st.caption("No unscheduled finished videos.")
            else:
                pid = st.selectbox("Video", list(label_of), format_func=label_of.get, key="single_pid")
                day, at, full = _date_time_inputs("single")
                if st.button("📅 Schedule", type="primary", disabled=full, key="single_go"):
                    try:
                        anim_schedule.create_entry(date=day.isoformat(), post_time=at.strftime("%H:%M"), project_id=pid)
                        st.success("Scheduled.")
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            topic = st.text_input("Topic", key="single_topic")
            context = st.text_area("Research / description (optional)", key="single_ctx", height=90)
            c1, c2 = st.columns(2)
            seconds = c1.select_slider("Length", options=LENGTHS, value=30, format_func=lambda s: f"{s} s", key="single_secs")
            aspect = c2.radio("Aspect ratio", list(ASPECT_LABELS), format_func=ASPECT_LABELS.get, key="single_aspect", horizontal=True)
            day, at, full = _date_time_inputs("single_auto")
            if st.button("🤖 Queue it", type="primary", disabled=full or not topic.strip(), key="single_auto_go"):
                try:
                    anim_schedule.create_entry(
                        date=day.isoformat(), post_time=at.strftime("%H:%M"), topic=topic, context=context,
                        seconds=seconds, aspect=aspect, voice=pipeline.default_voice(),
                    )
                    st.success("Queued. It will be generated and uploaded on the day.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

    with batch_tab:
        plan = st.session_state.get(_PLAN)
        if not plan:
            source = st.radio("Batch of", ["Finished videos", "Topics (generated on the day)"], horizontal=True, key="batch_src")
            with st.form("anim_batch"):
                if source == "Finished videos":
                    picked = st.multiselect("Videos", list(label_of), format_func=label_of.get, key="batch_pids")
                    items = [{"project_id": pid} for pid in picked]
                    topics_text, seconds, aspect = "", 30, "9:16"
                else:
                    topics_text = st.text_area("Topics, one per line (context after a | is optional)", height=150, key="batch_topics")
                    c1, c2 = st.columns(2)
                    seconds = c1.select_slider("Length", options=LENGTHS, value=30, format_func=lambda s: f"{s} s", key="batch_secs")
                    aspect = c2.radio("Aspect ratio", list(ASPECT_LABELS), format_func=ASPECT_LABELS.get, key="batch_aspect", horizontal=True)
                    items = []
                c1, c2 = st.columns(2)
                per_day = c1.number_input("Animations per day", min_value=1, max_value=upload_budget.DAILY_BUDGET, value=1, key="batch_per_day")
                start = c2.date_input("Start from (optional)", value=None, min_value=date_cls.today(), key="batch_start")
                st.caption(
                    "Each day only takes what the shared budget leaves free after Shorts and documentaries, "
                    f"with times spread through {shorts_schedule.PUBLISH_WINDOW_START}–{shorts_schedule.PUBLISH_WINDOW_END}."
                )
                preview = st.form_submit_button("Preview plan", type="primary")
            if preview:
                if source != "Finished videos":
                    items = [
                        {**i, "seconds": seconds, "aspect": aspect, "voice": pipeline.default_voice()} for i in _parse_batch(topics_text)
                    ]
                if not items:
                    st.error("Pick at least one video or topic.")
                else:
                    try:
                        st.session_state[_PLAN] = anim_schedule.plan_batch(
                            items, per_day=int(per_day), start_date=start.isoformat() if start else None
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
        else:
            items = plan["items"]
            st.markdown(f"**Review {len(items)} upload(s) across {len(plan['dates'])} day(s).** Nothing is booked yet.")
            if plan.get("skipped_full_days"):
                st.caption("Skipped full days: " + ", ".join(plan["skipped_full_days"]))
            frame = pd.DataFrame(
                [
                    {
                        "Date": date_cls.fromisoformat(i["date"]),
                        "Time": datetime.strptime(i["post_time"], "%H:%M").time(),
                        "What": label_of.get(i.get("project_id", ""), i.get("topic", "")),
                    }
                    for i in items
                ]
            )
            edited = st.data_editor(
                frame,
                hide_index=True,
                use_container_width=True,
                disabled=["What"],
                column_config={
                    "Date": st.column_config.DateColumn("Date", format="YYYY-MM-DD", required=True),
                    "Time": st.column_config.TimeColumn("Post time", format="HH:mm", step=300, required=True),
                },
                key="anim_batch_editor",
            )
            confirmed = [
                {**item, "date": pd.Timestamp(row["Date"]).date().isoformat(), "post_time": row["Time"].strftime("%H:%M")}
                for item, (_, row) in zip(items, edited.iterrows())
            ]
            ok_col, discard_col, _ = st.columns([2, 1, 3])
            if ok_col.button(f"✅ Confirm {len(confirmed)} upload(s)", type="primary", use_container_width=True):
                try:
                    anim_schedule.create_entries(confirmed)
                    st.session_state.pop(_PLAN, None)
                    st.success("Scheduled.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if discard_col.button("Discard", use_container_width=True):
                st.session_state.pop(_PLAN, None)
                st.rerun()

    st.divider()
    st.subheader("Calendar", anchor=False)
    entries = anim_schedule.list_entries()
    if not entries:
        st.info("Nothing scheduled yet.")
    for e in entries:
        project = store.load_project(e["project_id"]) if e.get("project_id") else None
        label = ((project or {}).get("youtube") or {}).get("title") or e.get("topic") or (project or {}).get("topic") or e["id"]
        with st.container(border=True):
            info, act = st.columns([4, 1], vertical_alignment="center")
            icon = "🤖" if e["mode"] == "auto" else "🎞"
            info.markdown(
                f"{icon} **{label[:80]}**  \n{e['date']} {e.get('post_time', '') or '(now)'} · {ENTRY_CHIPS.get(e['status'], e['status'])}"
            )
            if e.get("youtube_video_id"):
                info.markdown(f"▶ [youtu.be/{e['youtube_video_id']}](https://youtu.be/{e['youtube_video_id']})")
            if e.get("error"):
                info.caption(f"⚠️ {e['error'][:300]}")
            if e["status"] == anim_schedule.STATUS_FAILED and act.button("🔁 Retry", key=f"ent_retry_{e['id']}"):
                anim_schedule.reset_entry(e["id"])
                st.rerun()
            if e["status"] in (anim_schedule.STATUS_PENDING, anim_schedule.STATUS_FAILED):
                if e.get("project_id") and act.button("✅ Posted", key=f"ent_posted_{e['id']}", help="I uploaded this myself"):
                    anim_schedule.mark_posted(e["project_id"])
                    st.rerun()
                if act.button("🗑", key=f"ent_del_{e['id']}"):
                    anim_schedule.delete_entry(e["id"])
                    st.rerun()

    run_col, hint_col = st.columns([1, 3])
    if run_col.button("▶ Run due entries now"):
        threading.Thread(target=anim_schedule.run_due_entries, daemon=True, name="animation-schedule-run").start()
        st.success("Started in the background. Statuses above update as it goes.")
    hint_col.caption("Also runs automatically with the existing cron hook: `POST /api/v1/schedules/run`.")


if section == "📚 Library":
    _render_library()
elif section == "📅 Schedule":
    _render_schedule()
else:
    _render_create()
