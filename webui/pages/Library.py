"""Video Library page: browse and play every generated final video.

Scans storage/tasks/*/final-*.mp4 directly from disk, so it shows videos
from any source - WebUI runs, API/cron runs, scheduled generations - and
survives container restarts (unlike the in-memory task list).
"""
import csv
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from glob import glob

import streamlit as st

# 与 webui/Main.py 相同：确保项目根目录优先于第三方依赖里的同名 app 包。
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.config import config
from app.services import schedule as schedule_service
from app.services import sweeper
from app.services.analytics import store as analytics_store
from app.services.youtube_upload import youtube_upload_service
from app.utils import utils

st.set_page_config(page_title="Video Library", page_icon="🎞️", layout="wide")

# 竖屏 9:16 视频会按列宽等比放大，在宽屏下单个播放器可高达上千像素。
# 这里限制播放器高度并居中，让网格保持紧凑、可扫视的卡片式布局。
st.markdown(
    """
<style>
/* Streamlit 把 data-testid="stVideo" 直接放在 <video> 元素上，
   因此这里必须选中元素本身，而不是它的父容器。 */
video[data-testid="stVideo"] {
    max-height: 300px;
    width: auto !important;
    max-width: 100%;
    margin: 0 auto;
    display: block;
    border-radius: 8px;
    background: #000;
}
</style>
""",
    unsafe_allow_html=True,
)

st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("🎞️ Video Library")
st.caption(
    "Every generated final video, newest first - including videos created "
    "by the scheduler and API. Use the player's ⋮ menu to download, or "
    "upload any video here straight to YouTube."
)


def _upload_panel(video: dict) -> None:
    """Upload one already-rendered video to YouTube, no regeneration.

    The safety net for a video whose scheduled upload failed on something
    unrelated to the file itself - daily quota exhausted, expired token -
    and for videos orphaned by an older retry that rebuilt from scratch.
    """
    key = f"{video['task_id']}_{video['filename']}"
    with st.popover("⬆️ Upload to YouTube", use_container_width=True):
        if not youtube_upload_service.is_configured():
            st.warning(
                "YouTube is not connected. Run `python youtube_auth.py` once "
                "and set `youtube.enabled = true` in config.toml."
            )
            return

        st.caption(
            "Uploads this exact file as a private video. Nothing is "
            "regenerated."
        )
        title = st.text_input(
            "Title",
            value=(video["subject"] or video["script"][:80] or video["task_id"])[:100],
            key=f"yt_title_{key}",
        )
        description = st.text_area(
            "Description", value=video["script"][:500], height=100,
            key=f"yt_desc_{key}",
        )
        tags_text = st.text_input(
            "Tags (comma separated)", value="", key=f"yt_tags_{key}"
        )
        schedule_publish = st.checkbox(
            "Schedule the publish time", key=f"yt_sched_{key}",
            help="Leave off to keep it a private draft you publish by hand.",
        )
        publish_at = None
        if schedule_publish:
            date_col, time_col = st.columns(2)
            publish_date = date_col.date_input(
                "Publish date", value=date.today() + timedelta(days=1),
                key=f"yt_date_{key}",
            )
            publish_time = time_col.time_input(
                "Publish time", value=time(12, 0), key=f"yt_time_{key}",
            )
            # 复用排期页的时区换算，保证手动上传和自动排期的发布时间一致。
            publish_at = schedule_service._compute_publish_at(
                {
                    "date": publish_date.isoformat(),
                    "post_time": publish_time.strftime("%H:%M"),
                    "id": key,
                }
            )
            if publish_at is None:
                st.warning(
                    "That time is in the past - it will upload as a plain "
                    "private draft instead."
                )

        if st.button("Upload now", type="primary", key=f"yt_go_{key}"):
            tags = [t.strip() for t in tags_text.split(",") if t.strip()]
            thumbnail_path = schedule_service._extract_thumbnail(
                video["path"], os.path.splitext(video["path"])[0] + "-thumbnail.jpg"
            )
            with st.spinner("Uploading to YouTube…"):
                result = youtube_upload_service.upload_video(
                    video_path=video["path"],
                    title=title,
                    description=description,
                    tags=tags,
                    thumbnail_path=thumbnail_path,
                    publish_at=publish_at,
                )
            if result.get("success"):
                video_id = result["video_id"]
                st.success(
                    f"Uploaded: [studio.youtube.com]"
                    f"(https://studio.youtube.com/video/{video_id}/edit)"
                )
            else:
                st.error(result.get("error", "upload failed"))


def _posted_panel(video: dict, posted_marks: dict) -> None:
    """Mark a video as posted by hand, for the Analytics page.

    Without a URL, the next analytics sync finds it on the channel by its
    title (the subject, unless you renamed it when posting).
    """
    key = f"shorts:{video['task_id']}/{video['filename']}"
    mark = posted_marks.get(key) or {}
    if mark.get("manual"):
        link = f" · [link]({mark['url']})" if mark.get("url") else ""
        st.caption(f"✅ Posted by hand on {mark.get('date', '?')}{link}")
        if st.button("↩️ Unmark posted", key=f"lib_unpost_{key}", use_container_width=True):
            analytics_store.unmark_posted(key)
            st.rerun()
        return
    with st.popover("✅ Already posted", use_container_width=True):
        st.caption(
            "Uploaded it yourself? Mark it so Analytics counts it. Without a "
            "link it is matched by its title on the next sync."
        )
        url = st.text_input("Video URL (optional)", key=f"lib_posted_url_{key}")
        posted_on = st.date_input("Posted on", value=date.today(), key=f"lib_posted_day_{key}")
        if st.button("Mark as posted", key=f"lib_posted_btn_{key}", type="primary"):
            analytics_store.mark_posted(key, url=url, posted_on=posted_on.isoformat())
            st.rerun()


def _load_task_meta(task_dir: str) -> dict:
    script_file = os.path.join(task_dir, "script.json")
    try:
        with open(script_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        params = data.get("params") or {}
        return {
            "subject": (params.get("video_subject") or "").strip(),
            "script": (data.get("script") or "").strip(),
        }
    except (OSError, json.JSONDecodeError):
        return {"subject": "", "script": ""}


@st.cache_data(ttl=30, show_spinner=False)
def _scan_library() -> list[dict]:
    tasks_dir = utils.task_dir()
    videos = []
    for video_path in glob(os.path.join(tasks_dir, "*", "final-*.mp4")):
        try:
            stat = os.stat(video_path)
        except OSError:
            continue
        task_dir = os.path.dirname(video_path)
        meta = _load_task_meta(task_dir)
        videos.append(
            {
                "path": video_path,
                "task_id": os.path.basename(task_dir),
                "filename": os.path.basename(video_path),
                "mtime": stat.st_mtime,
                "size_mb": stat.st_size / (1024 * 1024),
                "subject": meta["subject"],
                "script": meta["script"],
            }
        )
    videos.sort(key=lambda v: v["mtime"], reverse=True)
    return videos


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):,.0f} MB"


def _cleanup_panel() -> None:
    """Settings, preview and manual run for the daily storage clean-up."""
    opts = sweeper.settings()
    status = "on" if opts["enabled"] else "off"
    with st.expander(f"🧹 Automatic clean-up ({status})"):
        st.caption(
            "Runs with the daily cron, right after the analytics sync. It deletes the heavy files of "
            "finished videos and keeps their details, so Analytics still knows every video. Anything "
            "booked or retrying on a calendar, unfinished projects and anything changed in the last "
            "day are never touched."
        )
        with st.form("sweeper_settings"):
            enabled = st.toggle("Clean up automatically every day", value=opts["enabled"])
            c1, c2, c3 = st.columns(3)
            posted_days = c1.number_input("Posted videos: delete after (days)", 1, 365, opts["posted_days"], help="Counted from the day it went up on YouTube.")
            unposted_days = c2.number_input("Never-posted videos: delete after (days)", 1, 365, opts["unposted_days"], help="Counted from the day it was made.")
            cache_days = c3.number_input("Stock clip cache: delete after (days)", 1, 365, opts["cache_days"])
            if st.form_submit_button("💾 Save"):
                config.sweeper.update(enabled=enabled, posted_days=int(posted_days), unposted_days=int(unposted_days), cache_days=int(cache_days))
                config.save_config()
                st.rerun()

        preview_col, run_col = st.columns(2)
        if preview_col.button("🔍 Preview what would go", use_container_width=True):
            with st.spinner("Checking every studio…"):
                st.session_state["sweeper_preview"] = sweeper.plan()
        with run_col.popover("🧹 Clean up now", use_container_width=True):
            st.caption("Deletes everything the preview lists, now. This can't be undone.")
            if st.button("Delete these files", type="primary", key="sweeper_run_now"):
                with st.spinner("Cleaning up…"):
                    result = sweeper.run()
                st.session_state.pop("sweeper_preview", None)
                st.session_state["sweeper_result"] = result
                _scan_library.clear()
                st.rerun()

        result = st.session_state.pop("sweeper_result", None)
        if result and result.get("skipped"):
            st.warning(result["reason"])
        elif result:
            st.success(
                f"Deleted {result['videos_swept']} video(s) ({_mb(result['video_bytes_freed'])}) and "
                f"{result['cache_files_deleted']} cached clip(s) ({_mb(result['cache_bytes_freed'])})."
                + (f" Couldn't delete: {', '.join(result['failed'])}." if result.get("failed") else "")
            )

        preview = st.session_state.get("sweeper_preview")
        if preview:
            st.markdown(
                f"**{len(preview['videos'])} video(s), {_mb(preview['video_bytes'])}** would be deleted, plus "
                f"**{preview['cache_files']} cached clip(s), {_mb(preview['cache_bytes'])}**."
            )
            if preview["videos"]:
                st.dataframe(
                    [{"Studio": v["studio"], "Video": v["label"], "Why": v["reason"], "Size": _mb(v["bytes"])} for v in preview["videos"]],
                    hide_index=True,
                    use_container_width=True,
                )

        log_path = os.path.join(utils.storage_dir("sweeper"), "log.csv")
        if os.path.isfile(log_path):
            with open(log_path, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            if rows:
                st.caption(f"Recently deleted (full log: `{log_path}`)")
                st.dataframe(
                    [{"When": r["swept_at"], "Studio": r["studio"], "Video": r["label"], "Why": r["reason"], "Size": _mb(int(r["bytes"] or 0))} for r in reversed(rows[-20:])],
                    hide_index=True,
                    use_container_width=True,
                )


_cleanup_panel()
videos = _scan_library()

if not videos:
    st.info("No generated videos found yet. They will appear here once a task finishes.")
    st.stop()

total_size_mb = sum(v["size_mb"] for v in videos)
header_col, count_col = st.columns([3, 2], vertical_alignment="center")
with header_col:
    # 视频少于滑块下限时 st.slider 会因 min==max 抛异常，直接全量展示。
    if len(videos) > 3:
        show_count = st.slider(
            "Videos shown (newest first)",
            min_value=3,
            max_value=len(videos),
            value=min(8, len(videos)),
            step=1,
            help="Each shown video is streamed by the server; keep this low "
            "on slow connections.",
        )
    else:
        show_count = len(videos)
with count_col:
    st.metric("In library", f"{len(videos)} videos · {total_size_mb:,.0f} MB")

columns_per_row = 4
shown = videos[:show_count]
posted_marks = analytics_store.load_links()["posted"]
for row_start in range(0, len(shown), columns_per_row):
    row_videos = shown[row_start : row_start + columns_per_row]
    cols = st.columns(columns_per_row)
    for col, video in zip(cols, row_videos):
        with col, st.container(border=True):
            title = video["subject"] or video["script"][:60] or video["task_id"]
            st.markdown(f"**{title[:60]}**")
            created = datetime.fromtimestamp(video["mtime"]).strftime(
                "%b %d, %Y %H:%M"
            )
            st.caption(f"{created} · {video['size_mb']:.0f} MB")
            st.video(video["path"])
            _upload_panel(video)
            _posted_panel(video, posted_marks)
            with st.popover("🗑 Delete files", use_container_width=True):
                st.caption(
                    "Permanently deletes this task's folder from the server "
                    "(video, audio, subtitles). Videos already uploaded to "
                    "YouTube are not affected."
                )
                if st.button(
                    "Delete permanently",
                    key=f"lib_del_{video['task_id']}_{video['filename']}",
                    type="primary",
                ):
                    import shutil

                    shutil.rmtree(os.path.dirname(video["path"]), ignore_errors=True)
                    _scan_library.clear()
                    st.rerun()
