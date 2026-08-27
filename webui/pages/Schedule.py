"""Content Calendar page: schedule video generations by date.

Appears as a separate "Schedule" page in the Streamlit sidebar next to the
main generator. Talks to app.services.schedule directly (same pattern as
Main.py importing app services), so it works without the API server running.
"""
import os
import sys
from calendar import monthrange
from datetime import date, timedelta

import streamlit as st

# 与 webui/Main.py 相同：确保项目根目录优先于第三方依赖里的同名 app 包。
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config
from app.services import schedule as schedule_service
from app.services.discord_notify import discord_notify_service
from app.services.youtube_upload import youtube_upload_service

st.set_page_config(page_title="Content Calendar", page_icon="📅", layout="wide")

st.title("📅 Content Calendar")
st.caption(
    "Schedule video generations by date. A daily cron run picks up every "
    "pending entry, generates the videos, uploads them to YouTube as private "
    "drafts, and pings you on Discord to review and publish."
)

_STATUS_BADGES = {
    schedule_service.STATUS_PENDING: "🕒 pending",
    schedule_service.STATUS_GENERATING: "⚙️ generating",
    schedule_service.STATUS_DONE: "✅ done",
    schedule_service.STATUS_FAILED: "❌ failed",
}
_PRESET_LABELS = {key: value["label"] for key, value in schedule_service.PRESETS.items()}


def _readiness_banner():
    problems = []
    if not youtube_upload_service.is_configured():
        problems.append(
            "**YouTube is not connected** — videos will generate but uploads will "
            "fail. Run `python youtube_auth.py` once, then set "
            "`youtube.enabled = true` in config.toml."
        )
    if not discord_notify_service.is_configured():
        problems.append(
            "**Discord webhook is not set** — you will not get alerts. Add "
            "`webhook_url` under `[discord]` in config.toml."
        )
    if problems:
        st.warning("\n\n".join(problems))


_readiness_banner()

# ---------------------------------------------------------------- add entries
with st.expander("➕ Schedule videos", expanded=True):
    with st.form("add_entry", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 3, 2])
        with col1:
            entry_date = st.date_input(
                "Date", min_value=date.today(), value=date.today()
            )
            post_time = st.text_input(
                "Planned post time (HH:MM, optional)",
                value="",
                help="Informational: included in the Discord alert so you know "
                "when you meant to publish.",
            )
        with col2:
            topic = st.text_area(
                "Topic",
                placeholder="Example: 5 AI tools that save you an hour a day",
                height=68,
            )
            language = st.text_input(
                "Script language (optional, e.g. en-US)",
                value=config.ui.get("video_language", ""),
            )
        with col3:
            preset = st.selectbox(
                "Format preset",
                options=list(_PRESET_LABELS),
                format_func=lambda key: _PRESET_LABELS[key],
            )
            video_count = st.number_input(
                "Videos", min_value=1, max_value=20, value=1,
                help="Variations generated for this topic on this date.",
            )
        submitted = st.form_submit_button("Add to calendar", type="primary")
        if submitted:
            try:
                schedule_service.create_entry(
                    date=entry_date.isoformat(),
                    topic=topic,
                    video_count=int(video_count),
                    preset=preset,
                    post_time=post_time.strip(),
                    language=language.strip(),
                )
                st.success(f"Scheduled {int(video_count)} video(s) on {entry_date}.")
            except ValueError as exc:
                st.error(str(exc))

# ------------------------------------------------------------- month calendar
if "calendar_month" not in st.session_state:
    today = date.today()
    st.session_state.calendar_month = (today.year, today.month)

year, month = st.session_state.calendar_month
nav_prev, nav_label, nav_next = st.columns([1, 4, 1])
with nav_prev:
    if st.button("◀", use_container_width=True):
        first = date(year, month, 1) - timedelta(days=1)
        st.session_state.calendar_month = (first.year, first.month)
        st.rerun()
with nav_next:
    if st.button("▶", use_container_width=True):
        last = date(year, month, monthrange(year, month)[1]) + timedelta(days=1)
        st.session_state.calendar_month = (last.year, last.month)
        st.rerun()
with nav_label:
    st.subheader(date(year, month, 1).strftime("%B %Y"), anchor=False)

month_start = date(year, month, 1)
month_end = date(year, month, monthrange(year, month)[1])
entries = schedule_service.list_entries(
    month_start.isoformat(), month_end.isoformat()
)
entries_by_date: dict[str, list[dict]] = {}
for entry in entries:
    entries_by_date.setdefault(entry["date"], []).append(entry)

weekday_cols = st.columns(7)
for i, day_name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
    weekday_cols[i].markdown(f"**{day_name}**")

first_weekday = month_start.weekday()
day = 1
days_in_month = monthrange(year, month)[1]
while day <= days_in_month:
    row = st.columns(7)
    for col_index in range(7):
        if (day == 1 and col_index < first_weekday) or day > days_in_month:
            row[col_index].markdown(" ")
            continue
        cell_date = date(year, month, day)
        cell_entries = entries_by_date.get(cell_date.isoformat(), [])
        with row[col_index].container(border=True):
            is_today = cell_date == date.today()
            st.markdown(f"{'🔵 ' if is_today else ''}**{day}**")
            for entry in cell_entries:
                badge = _STATUS_BADGES.get(entry["status"], entry["status"])
                aspect = "📱" if entry["preset"] == "shorts" else "🖥️"
                st.caption(
                    f"{aspect} ×{entry['video_count']} {badge}\n\n"
                    f"{entry['topic'][:60]}"
                )
        day += 1

# ------------------------------------------------------------- entries table
st.divider()
st.subheader("Scheduled entries", anchor=False)
show_all = st.toggle("Show all dates (not just this month)", value=False)
table_entries = schedule_service.list_entries() if show_all else entries

if not table_entries:
    st.info("Nothing scheduled yet. Add your first entry above.")
else:
    for entry in table_entries:
        status = entry["status"]
        badge = _STATUS_BADGES.get(status, status)
        cols = st.columns([2, 4, 2, 2, 2, 3])
        cols[0].markdown(f"**{entry['date']}**  \n{entry.get('post_time') or ''}")
        cols[1].markdown(
            f"{entry['topic']}  \n"
            f"`{_PRESET_LABELS.get(entry['preset'], entry['preset'])}` × "
            f"{entry['video_count']}"
        )
        cols[2].markdown(badge)

        with cols[3]:
            if status in (
                schedule_service.STATUS_PENDING,
                schedule_service.STATUS_FAILED,
            ):
                if st.button("Delete", key=f"del_{entry['id']}"):
                    try:
                        schedule_service.delete_entry(entry["id"])
                        st.rerun()
                    except (KeyError, ValueError) as exc:
                        st.error(str(exc))
        with cols[4]:
            if status == schedule_service.STATUS_FAILED:
                if st.button("Retry", key=f"retry_{entry['id']}"):
                    schedule_service.update_entry(
                        entry["id"], status=schedule_service.STATUS_PENDING
                    )
                    st.rerun()
        with cols[5]:
            if status == schedule_service.STATUS_FAILED and entry.get("error"):
                st.caption(f"⚠️ {entry['error'][:200]}")
            if entry.get("youtube_video_ids"):
                links = " · ".join(
                    f"[video {i + 1}](https://studio.youtube.com/video/{vid}/edit)"
                    for i, vid in enumerate(entry["youtube_video_ids"])
                )
                st.caption(f"YouTube: {links}")

        # 复制排期到其它日期,只改主题。
        with st.expander(f"Duplicate · {entry['date']} · {entry['topic'][:40]}"):
            with st.form(f"dup_{entry['id']}"):
                dup_dates_text = st.text_input(
                    "Target dates (comma-separated YYYY-MM-DD)",
                    key=f"dup_dates_{entry['id']}",
                    placeholder="2026-09-01, 2026-09-03",
                )
                dup_topic = st.text_input(
                    "New topic (leave empty to keep the same)",
                    key=f"dup_topic_{entry['id']}",
                )
                if st.form_submit_button("Duplicate"):
                    dates = [d.strip() for d in dup_dates_text.split(",") if d.strip()]
                    if not dates:
                        st.error("Enter at least one target date.")
                    else:
                        try:
                            schedule_service.duplicate_entry(
                                entry["id"], dates, dup_topic.strip()
                            )
                            st.success(f"Duplicated onto {len(dates)} date(s).")
                            st.rerun()
                        except (KeyError, ValueError) as exc:
                            st.error(str(exc))

# ------------------------------------------------------------------ manual run
st.divider()
run_col, hint_col = st.columns([1, 3])
with run_col:
    if st.button("▶ Run due entries now", type="primary"):
        import threading

        threading.Thread(
            target=schedule_service.run_due_entries, daemon=True
        ).start()
        st.success("Run started in the background. Watch statuses above.")
with hint_col:
    st.caption(
        "In production this runs automatically: point a daily cron job at "
        "`POST /api/v1/schedules/run` (see docs/scheduler-and-youtube.md)."
    )
