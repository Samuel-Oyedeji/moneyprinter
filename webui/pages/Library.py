"""Video Library page: browse and play every generated final video.

Scans storage/tasks/*/final-*.mp4 directly from disk, so it shows videos
from any source - WebUI runs, API/cron runs, scheduled generations - and
survives container restarts (unlike the in-memory task list).
"""
import json
import os
import sys
from datetime import datetime
from glob import glob

import streamlit as st

# 与 webui/Main.py 相同：确保项目根目录优先于第三方依赖里的同名 app 包。
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir in sys.path:
    sys.path.remove(root_dir)
sys.path.insert(0, root_dir)

from app.utils import utils

st.set_page_config(page_title="Video Library", page_icon="🎞️", layout="wide")

st.page_link("Main.py", label="Back to generator", icon=":material/arrow_back:")
st.title("🎞️ Video Library")
st.caption(
    "Every generated final video, newest first - including videos created "
    "by the scheduler and API. Use the player's ⋮ menu to download."
)


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
            value=min(6, len(videos)),
            step=1,
            help="Each shown video is streamed by the server; keep this low "
            "on slow connections.",
        )
    else:
        show_count = len(videos)
with count_col:
    st.metric("In library", f"{len(videos)} videos · {total_size_mb:,.0f} MB")

columns_per_row = 3
shown = videos[:show_count]
for row_start in range(0, len(shown), columns_per_row):
    row_videos = shown[row_start : row_start + columns_per_row]
    cols = st.columns(columns_per_row)
    for col, video in zip(cols, row_videos):
        with col, st.container(border=True):
            title = video["subject"] or video["script"][:60] or video["task_id"]
            st.markdown(f"**{title[:80]}**")
            created = datetime.fromtimestamp(video["mtime"]).strftime(
                "%b %d, %Y %H:%M"
            )
            st.caption(
                f"{created} · {video['size_mb']:.0f} MB · "
                f"{video['filename']} · `{video['task_id'][:8]}…`"
            )
            st.video(video["path"])
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
