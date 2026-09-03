"""Content Calendar page: schedule video generations by date.

Appears as a separate "Schedule" page in the Streamlit sidebar next to the
main generator. Talks to app.services.schedule directly (same pattern as
Main.py importing app services), so it works without the API server running.
"""
import html
import os
import sys
import threading
from calendar import monthrange
from datetime import date, datetime, timedelta

import pandas as pd
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

# 日历网格用原生 HTML 渲染（Streamlit 列布局做不出紧凑的月历）。
# 颜色跟随 Streamlit 主题变量，浅色/深色主题都可读。
st.markdown(
    """
<style>
.cal-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 6px; }
.cal-dow  { text-align: center; font-size: 0.78rem; font-weight: 600;
            opacity: 0.55; padding: 2px 0 6px 0; letter-spacing: 0.04em; }
.cal-cell { border: 1px solid rgba(128,128,128,0.22); border-radius: 10px;
            min-height: 96px; padding: 6px 7px; min-width: 0;
            background: var(--secondary-background-color); }
.cal-cell.cal-empty { border: none; background: transparent; }
.cal-cell.cal-past  { opacity: 0.45; }
.cal-cell.cal-today { border: 2px solid var(--primary-color); }
.cal-day  { font-size: 0.82rem; font-weight: 700; opacity: 0.75;
            margin-bottom: 3px; }
.cal-cell.cal-today .cal-day { color: var(--primary-color); opacity: 1; }
.cal-pill { display: block; font-size: 0.72rem; line-height: 1.3;
            border-radius: 6px; padding: 3px 7px; margin-top: 3px;
            color: #fff; white-space: nowrap; overflow: hidden;
            text-overflow: ellipsis; cursor: default; }
.cal-pill .cal-meta { opacity: 0.8; font-size: 0.66rem; }
.pill-pending    { background: #b45309; }
.pill-generating { background: #2563eb; }
.pill-done       { background: #15803d; }
.pill-failed     { background: #b91c1c; }
.status-chip { display: inline-block; font-size: 0.72rem; font-weight: 600;
               border-radius: 999px; padding: 2px 10px; color: #fff;
               vertical-align: middle; }
/* Streamlit 的 popover 面板默认裁剪溢出内容，导致里面的多选日期下拉被
   挡住。允许面板溢出，并给它一个高于同级卡片的层级。 */
div[data-testid="stPopoverBody"] { overflow: visible !important; }
div[data-testid="stPopover"] { z-index: 1000; }
/* 折叠后的每日概览用小圆点表示各视频状态。 */
.day-dots { display: inline-flex; flex-wrap: wrap; gap: 5px;
            align-items: center; vertical-align: middle; }
.day-dot  { display: inline-block; font-size: 0.68rem; font-weight: 600;
            border-radius: 999px; padding: 1px 9px; color: #fff; }
</style>
""",
    unsafe_allow_html=True,
)

st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("📅 Content Calendar")
st.caption(
    "Schedule video generations by date. A daily cron run picks up every "
    "pending entry, generates the videos, uploads them to YouTube as private "
    "drafts, and pings you on Discord to review and publish."
)

_STATUS_LABELS = {
    schedule_service.STATUS_PENDING: "Pending",
    schedule_service.STATUS_GENERATING: "Generating…",
    schedule_service.STATUS_DONE: "Done",
    schedule_service.STATUS_FAILED: "Failed",
}
_PRESET_LABELS = {key: value["label"] for key, value in schedule_service.PRESETS.items()}
_PRESET_ICONS = {"shorts": "📱", "horizontal": "🖥️"}


def _status_chip(status: str) -> str:
    label = _STATUS_LABELS.get(status, status)
    return f'<span class="status-chip pill-{html.escape(status)}">{label}</span>'


def _day_summary_html(day_entries: list[dict]) -> str:
    """One coloured dot per scheduled video, in entry order.

    Gives the collapsed day row an at-a-glance read of what happened
    ("done done done generating") without expanding it.
    """
    dots = []
    for entry in day_entries:
        status = entry.get("status", "")
        label = _STATUS_LABELS.get(status, status)
        for _ in range(max(int(entry.get("video_count", 1) or 1), 1)):
            dots.append(
                f'<span class="day-dot pill-{html.escape(status)}">'
                f"{html.escape(label)}</span>"
            )
    return f'<div class="day-dots">{"".join(dots)}</div>'


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
with st.expander("➕ Schedule videos", expanded=False):
    with st.form("add_entry", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 3, 2])
        with col1:
            entry_date = st.date_input(
                "Date", min_value=date.today(), value=date.today()
            )
            post_time_value = st.time_input(
                "Post time (optional)",
                value=None,
                step=timedelta(minutes=15),
                help="With a time set, the video is scheduled on YouTube and "
                "goes public automatically at this time (timezone: "
                "youtube.publish_timezone in config.toml). Without one it "
                "stays a private draft for manual publishing.",
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
                    post_time=(
                        post_time_value.strftime("%H:%M") if post_time_value else ""
                    ),
                    language=language.strip(),
                )
                st.success(f"Scheduled {int(video_count)} video(s) on {entry_date}.")
            except ValueError as exc:
                st.error(str(exc))

# ------------------------------------------------------------ batch scheduling
# 批量排期分两步：先生成方案（不落盘），确认后一次性写入。
_BATCH_PLAN = "batch_plan"
_BATCH_EDITOR = "batch_plan_editor"
_PRESET_BY_LABEL = {label: key for key, label in _PRESET_LABELS.items()}


def _coerce_date(value):
    """Read a date back out of the editor, whatever pandas turned it into."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _coerce_time(value) -> str:
    """Read a post time back out of the editor as "HH:MM" ("" = unset)."""
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return ""
        try:
            return datetime.strptime(value, "%H:%M").strftime("%H:%M")
        except ValueError:
            return "invalid"
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return "invalid"


def _plan_frame(items: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": date.fromisoformat(item["date"]),
                "Time": (
                    datetime.strptime(item["post_time"], "%H:%M").time()
                    if item.get("post_time")
                    else None
                ),
                "Topic": item["topic"],
                "Format": _PRESET_LABELS.get(item["preset"], item["preset"]),
                "Videos": int(item.get("video_count", 1) or 1),
            }
            for item in items
        ]
    )


def _frame_to_items(frame: pd.DataFrame, language: str) -> tuple[list[dict], list[str]]:
    """Turn the reviewed table back into entry payloads, collecting problems."""
    items: list[dict] = []
    problems: list[str] = []
    for position, row in enumerate(frame.to_dict("records"), start=1):
        topic = str(row.get("Topic") or "").strip()
        row_date = _coerce_date(row.get("Date"))
        if not topic and row_date is None:
            continue  # 用户在动态表格里新增但没填的空行
        if not topic:
            problems.append(f"Row {position}: topic is empty.")
            continue
        if row_date is None:
            problems.append(f"Row {position}: date is missing or invalid.")
            continue
        post_time = _coerce_time(row.get("Time"))
        if post_time == "invalid":
            problems.append(f"Row {position}: time must look like 14:30.")
            continue
        try:
            video_count = int(row.get("Videos") or 1)
        except (TypeError, ValueError):
            problems.append(f"Row {position}: videos must be a whole number.")
            continue
        if video_count < 1 or video_count > 20:
            problems.append(f"Row {position}: videos must be between 1 and 20.")
            continue
        preset_label = str(row.get("Format") or "")
        preset_key = _PRESET_BY_LABEL.get(preset_label)
        if preset_key is None:
            problems.append(f"Row {position}: unknown format {preset_label!r}.")
            continue
        items.append(
            {
                "date": row_date.isoformat(),
                "post_time": post_time,
                "topic": topic,
                "preset": preset_key,
                "video_count": video_count,
                "language": language,
            }
        )
    return items, problems


with st.expander(
    "🗂 Schedule a batch — paste one topic per line",
    expanded=bool(st.session_state.get(_BATCH_PLAN)),
):
    plan = st.session_state.get(_BATCH_PLAN)

    if not plan:
        st.caption(
            f"Paste a list of topics and they are spread over the next free days "
            f"— up to {schedule_service.DAILY_VIDEO_LIMIT} videos a day (the "
            "YouTube upload quota), evenly spaced through waking hours "
            f"({schedule_service.PUBLISH_WINDOW_START}–"
            f"{schedule_service.PUBLISH_WINDOW_END}). Days that already have "
            "entries are skipped, and you get to review everything before "
            "anything is scheduled."
        )
        with st.form("batch_plan_form"):
            batch_topics_text = st.text_area(
                "Topics (one per line)",
                height=180,
                placeholder=(
                    "Why bananas are curved\n"
                    "The real reason planes leave trails\n"
                    "5 AI tools that save you an hour a day"
                ),
                help="Numbering and bullets ('1.', '-', '*') are stripped "
                "automatically, so you can paste a list straight from a chat.",
            )
            opt1, opt2, opt3 = st.columns([2, 2, 3])
            with opt1:
                batch_per_day = st.number_input(
                    "Videos per day",
                    min_value=1,
                    max_value=schedule_service.DAILY_VIDEO_LIMIT,
                    value=schedule_service.DAILY_VIDEO_LIMIT,
                    help=f"The {schedule_service.PUBLISH_WINDOW_START}–"
                    f"{schedule_service.PUBLISH_WINDOW_END} window is split "
                    "into this many equal blocks, one video in the middle of "
                    "each. YouTube's default API quota allows about "
                    f"{schedule_service.DAILY_VIDEO_LIMIT} uploads a day.",
                )
                batch_skip_busy = st.toggle(
                    "Skip days that already have entries",
                    value=True,
                    help="On: the batch starts on the first completely free "
                    "day. Off: it starts on the first day regardless, stacking "
                    "on top of what is already scheduled.",
                )
            with opt2:
                batch_preset = st.selectbox(
                    "Format preset",
                    options=list(_PRESET_LABELS),
                    format_func=lambda key: _PRESET_LABELS[key],
                    key="batch_preset",
                )
                batch_start = st.date_input(
                    "Start from (optional)",
                    value=None,
                    min_value=date.today(),
                    help="Leave empty to start from the first free day.",
                )
            with opt3:
                batch_language = st.text_input(
                    "Script language (optional, e.g. en-US)",
                    value=config.ui.get("video_language", ""),
                    key="batch_language",
                )
                st.caption(
                    "Every row is created as a separate calendar entry, so you "
                    "can still edit or delete them individually afterwards."
                )
            planned = st.form_submit_button("Preview schedule", type="primary")

        if planned:
            topics = schedule_service.parse_topics(batch_topics_text)
            if not topics:
                st.error("Paste at least one topic.")
            else:
                try:
                    result = schedule_service.plan_batch(
                        topics=topics,
                        per_day=int(batch_per_day),
                        preset=batch_preset,
                        language=batch_language.strip(),
                        start_date=(
                            batch_start.isoformat() if batch_start else None
                        ),
                        skip_busy_days=batch_skip_busy,
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state[_BATCH_PLAN] = result
                    st.session_state.pop(_BATCH_EDITOR, None)
                    st.rerun()
    else:
        items = plan["items"]
        language = items[0].get("language", "") if items else ""
        first_day = date.fromisoformat(plan["dates"][0])
        last_day = date.fromisoformat(plan["dates"][-1])
        st.markdown(
            f"**Review {len(items)} video(s) across {len(plan['dates'])} day(s)** — "
            f"{first_day.strftime('%a, %b %-d')} to {last_day.strftime('%a, %b %-d, %Y')}. "
            "Adjust any row below, then confirm. Nothing is scheduled yet."
        )
        edited = st.data_editor(
            _plan_frame(items),
            key=_BATCH_EDITOR,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config={
                "Date": st.column_config.DateColumn(
                    "Date", format="YYYY-MM-DD", required=True
                ),
                "Time": st.column_config.TimeColumn(
                    "Post time", format="HH:mm", step=300
                ),
                "Topic": st.column_config.TextColumn(
                    "Topic", width="large", required=True, max_chars=500
                ),
                "Format": st.column_config.SelectboxColumn(
                    "Format", options=list(_PRESET_LABELS.values()), required=True
                ),
                "Videos": st.column_config.NumberColumn(
                    "Videos", min_value=1, max_value=20, step=1, format="%d"
                ),
            },
        )

        confirm_items, problems = _frame_to_items(edited, language)

        # 生成后再校验一次：用户可能把两行改到同一天，或把时间调到过去。
        per_day_totals: dict[str, int] = {}
        for item in confirm_items:
            per_day_totals[item["date"]] = (
                per_day_totals.get(item["date"], 0) + item["video_count"]
            )
        overloaded = {
            day: total
            for day, total in per_day_totals.items()
            if total > schedule_service.DAILY_VIDEO_LIMIT
        }
        now_local = schedule_service._planning_now()
        past_rows = sum(
            1
            for item in confirm_items
            if item["post_time"]
            and datetime.strptime(
                f"{item['date']} {item['post_time']}", "%Y-%m-%d %H:%M"
            )
            <= now_local
        )

        for problem in problems:
            st.error(problem)
        if overloaded:
            st.warning(
                "Over the YouTube upload quota on: "
                + ", ".join(f"{day} ({total} videos)" for day, total in
                            sorted(overloaded.items()))
                + f". Uploads past ~{schedule_service.DAILY_VIDEO_LIMIT} a day "
                "will fail until the quota resets."
            )
        if past_rows:
            st.warning(
                f"{past_rows} row(s) have a post time in the past — those videos "
                "will be uploaded as private drafts instead of auto-publishing."
            )
        if not problems and confirm_items:
            total_videos = sum(item["video_count"] for item in confirm_items)
            st.caption(
                f"Ready to schedule {total_videos} video(s) over "
                f"{len(per_day_totals)} day(s)."
            )

        confirm_col, discard_col, _ = st.columns([2, 1, 3])
        with confirm_col:
            if st.button(
                f"✅ Confirm all — schedule {len(confirm_items)} entr"
                f"{'y' if len(confirm_items) == 1 else 'ies'}",
                type="primary",
                use_container_width=True,
                disabled=bool(problems) or not confirm_items,
            ):
                try:
                    created = schedule_service.create_entries(confirm_items)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.pop(_BATCH_PLAN, None)
                    st.session_state.pop(_BATCH_EDITOR, None)
                    st.success(f"Scheduled {len(created)} entries.")
                    st.rerun()
        with discard_col:
            if st.button("Discard", use_container_width=True):
                st.session_state.pop(_BATCH_PLAN, None)
                st.session_state.pop(_BATCH_EDITOR, None)
                st.rerun()

# ------------------------------------------------------------- month calendar
if "calendar_month" not in st.session_state:
    today = date.today()
    st.session_state.calendar_month = (today.year, today.month)

year, month = st.session_state.calendar_month
nav_prev, nav_today, nav_label, nav_next = st.columns([1, 1, 5, 1])
with nav_prev:
    if st.button("◀ Prev", use_container_width=True):
        first = date(year, month, 1) - timedelta(days=1)
        st.session_state.calendar_month = (first.year, first.month)
        st.rerun()
with nav_today:
    if st.button("Today", use_container_width=True):
        st.session_state.calendar_month = (date.today().year, date.today().month)
        st.rerun()
with nav_next:
    if st.button("Next ▶", use_container_width=True):
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


def _pill_html(entry: dict) -> str:
    icon = _PRESET_ICONS.get(entry["preset"], "🎬")
    status = entry["status"]
    topic_text = html.escape(entry["topic"])
    time_text = f" · {entry['post_time']}" if entry.get("post_time") else ""
    tooltip = html.escape(
        f"{entry['topic']} — {_PRESET_LABELS.get(entry['preset'], entry['preset'])}, "
        f"{entry['video_count']} video(s), {_STATUS_LABELS.get(status, status)}"
        + (f", post at {entry['post_time']}" if entry.get("post_time") else "")
    )
    return (
        f'<span class="cal-pill pill-{html.escape(status)}" title="{tooltip}">'
        f'{icon} ×{entry["video_count"]}'
        f'<span class="cal-meta">{time_text}</span> {topic_text}</span>'
    )


cells: list[str] = []
for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
    cells.append(f'<div class="cal-dow">{day_name}</div>')

first_weekday = month_start.weekday()
for _ in range(first_weekday):
    cells.append('<div class="cal-cell cal-empty"></div>')

today = date.today()
for day in range(1, monthrange(year, month)[1] + 1):
    cell_date = date(year, month, day)
    classes = ["cal-cell"]
    if cell_date == today:
        classes.append("cal-today")
    elif cell_date < today:
        classes.append("cal-past")
    pills = "".join(
        _pill_html(e) for e in entries_by_date.get(cell_date.isoformat(), [])
    )
    cells.append(
        f'<div class="{" ".join(classes)}"><div class="cal-day">{day}</div>'
        f"{pills}</div>"
    )

st.markdown(f'<div class="cal-grid">{"".join(cells)}</div>', unsafe_allow_html=True)

# ------------------------------------------------------------- entries list
st.divider()
list_header, list_toggle = st.columns([3, 2])
with list_header:
    st.subheader("Scheduled entries", anchor=False)
with list_toggle:
    show_all = st.toggle("Show all dates (not just this month)", value=False)

table_entries = schedule_service.list_entries() if show_all else entries

if not table_entries:
    st.info("Nothing scheduled yet. Add your first entry above.")

dates_in_order: list[str] = []
entries_by_list_date: dict[str, list[dict]] = {}
for entry in table_entries:
    if entry["date"] not in entries_by_list_date:
        dates_in_order.append(entry["date"])
    entries_by_list_date.setdefault(entry["date"], []).append(entry)

for entry_date_str in dates_in_order:
    day_entries = entries_by_list_date[entry_date_str]
    entry_date_obj = date.fromisoformat(entry_date_str)
    day_label = entry_date_obj.strftime("%A, %B %-d, %Y")
    total_videos = sum(
        max(int(e.get("video_count", 1) or 1), 1) for e in day_entries
    )
    header = (
        f"Show {len(day_entries)} entr"
        f"{'y' if len(day_entries) == 1 else 'ies'} · {total_videos} video"
        f"{'' if total_videos == 1 else 's'}"
    )
    # 折叠状态下用状态圆点概览当天进度，展开后才渲染完整卡片，
    # 避免排期变多时列表把页面撑得过长。
    if entry_date_obj == date.today():
        st.markdown(f"**{day_label}** &nbsp;·&nbsp; today", unsafe_allow_html=True)
    else:
        st.markdown(f"**{day_label}**", unsafe_allow_html=True)
    st.markdown(_day_summary_html(day_entries), unsafe_allow_html=True)
    with st.expander(header, expanded=False):
        for entry in day_entries:
            status = entry["status"]
            with st.container(border=True):
                info_col, action_col = st.columns([5, 2])
                with info_col:
                    st.markdown(
                        f"{_status_chip(status)} &nbsp; **{html.escape(entry['topic'])}**",
                        unsafe_allow_html=True,
                    )
                    meta_bits = [
                        f"{_PRESET_ICONS.get(entry['preset'], '')} "
                        f"{_PRESET_LABELS.get(entry['preset'], entry['preset'])}",
                        f"{entry['video_count']} video(s)",
                    ]
                    if entry.get("post_time"):
                        meta_bits.append(f"post at {entry['post_time']}")
                    if entry.get("language"):
                        meta_bits.append(entry["language"])
                    st.caption(" · ".join(meta_bits))
                    if status == schedule_service.STATUS_FAILED and entry.get("error"):
                        st.error(entry["error"][:300], icon="⚠️")
                    if entry.get("youtube_video_ids"):
                        links = " · ".join(
                            f"[video {i + 1}](https://studio.youtube.com/video/{vid}/edit)"
                            for i, vid in enumerate(entry["youtube_video_ids"])
                        )
                        st.caption(f"▶️ On YouTube (private): {links}")
                with action_col:
                    actions = ["copy"]
                    if status == schedule_service.STATUS_FAILED:
                        actions.insert(0, "retry")
                    if status != schedule_service.STATUS_GENERATING:
                        actions.append("delete")
                    # 每个卡片最多三个操作，两列自适应；奇数个时最后一个占整行。
                    button_row = st.columns(2) if len(actions) > 1 else [st.container()]

                    def _slot(index: int):
                        if len(actions) == 3 and index == 2:
                            return st.container()
                        return button_row[index % len(button_row)]

                    if "retry" in actions:
                        with _slot(actions.index("retry")):
                            if st.button(
                                "🔄 Retry", key=f"retry_{entry['id']}",
                                use_container_width=True,
                            ):
                                schedule_service.update_entry(
                                    entry["id"], status=schedule_service.STATUS_PENDING
                                )
                                st.rerun()
                    with _slot(actions.index("copy")):
                        with st.popover("📑 Duplicate", use_container_width=True):
                            st.caption(
                                "Duplicate this entry onto other dates - same "
                                "preset and count, optionally a new topic."
                            )
                            upcoming_dates = [
                                date.today() + timedelta(days=offset)
                                for offset in range(0, 91)
                            ]
                            # 表单把控件改动攒到提交时才触发 rerun；
                            # 否则每选一个日期 popover 都会被 rerun 关掉。
                            with st.form(f"dup_form_{entry['id']}", border=False):
                                dup_dates = st.multiselect(
                                    "Target dates (pick one or more)",
                                    options=upcoming_dates,
                                    format_func=lambda d: d.strftime("%a, %b %d %Y"),
                                    key=f"dup_dates_{entry['id']}",
                                    placeholder="Choose dates…",
                                )
                                dup_topic = st.text_input(
                                    "New topic (empty = keep the same)",
                                    key=f"dup_topic_{entry['id']}",
                                )
                                submitted_dup = st.form_submit_button(
                                    "Duplicate", type="primary"
                                )
                            if submitted_dup:
                                dates = [d.isoformat() for d in dup_dates]
                                if not dates:
                                    st.error("Pick at least one target date.")
                                else:
                                    try:
                                        schedule_service.duplicate_entry(
                                            entry["id"], dates, dup_topic.strip()
                                        )
                                        st.rerun()
                                    except (KeyError, ValueError) as exc:
                                        st.error(str(exc))
                    if "delete" in actions:
                        with _slot(actions.index("delete")):
                            if st.button(
                                "🗑 Delete", key=f"del_{entry['id']}",
                                use_container_width=True,
                            ):
                                try:
                                    schedule_service.delete_entry(entry["id"])
                                    st.rerun()
                                except (KeyError, ValueError) as exc:
                                    st.error(str(exc))

# ------------------------------------------------------------------ manual run
st.divider()
run_col, hint_col = st.columns([1, 3])
with run_col:
    if st.button("▶ Run due entries now", type="primary"):
        threading.Thread(
            target=schedule_service.run_due_entries, daemon=True
        ).start()
        st.success("Run started in the background. Watch statuses above.")
with hint_col:
    st.caption(
        "In production this runs automatically: point a daily cron job at "
        "`POST /api/v1/schedules/run` (see docs/scheduler-and-youtube.md)."
    )
