"""Video Library page: browse and play every generated final video.

Scans storage/tasks/*/final-*.mp4 directly from disk, so it shows videos
from any source - WebUI runs, API/cron runs, scheduled generations - and
survives container restarts (unlike the in-memory task list).
"""
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

from app.services import schedule as schedule_service
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
