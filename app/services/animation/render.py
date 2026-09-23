"""Render a compiled story with the Remotion project in remotion/.

Runs `node scripts/render.mjs`, which bundles the kit, renders the
PaperStory composition and reports progress as JSON lines. Needs Node 18+;
the kit's npm packages are installed on first use (and Remotion fetches its
own headless Chrome the first time it renders).
"""

import json
import os
import shutil
import subprocess
import threading

from loguru import logger

from app.config import config
from app.utils import utils

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_NODE_CANDIDATES = (
    "/opt/homebrew/opt/node@22/bin/node",
    "/opt/homebrew/bin/node",
    "/usr/local/bin/node",
    "/usr/bin/node",
)
_install_lock = threading.Lock()


class RenderError(RuntimeError):
    pass


def remotion_dir() -> str:
    return str(config.animation.get("remotion_dir", "") or os.path.join(ROOT, "remotion"))


def node_binary() -> str | None:
    configured = str(config.animation.get("node_path", "") or "").strip()
    if configured and os.path.isfile(configured):
        return configured
    found = shutil.which("node")
    if found:
        return found
    return next((p for p in _NODE_CANDIDATES if os.path.isfile(p)), None)


def readiness() -> tuple[bool, str]:
    """(ready, message) for the page banner."""
    if not os.path.isfile(os.path.join(remotion_dir(), "package.json")):
        return False, f"Remotion project not found at {remotion_dir()}"
    node = node_binary()
    if not node:
        return False, "Node.js 18+ is not installed (needed to render animations)"
    if not os.path.isdir(os.path.join(remotion_dir(), "node_modules", "@remotion")):
        return True, "Remotion packages will be installed on the first render (~1 min)"
    return True, "Renderer ready"


def ensure_installed() -> None:
    with _install_lock:
        if os.path.isdir(os.path.join(remotion_dir(), "node_modules", "@remotion")):
            return
        node = node_binary()
        if not node:
            raise RenderError("Node.js 18+ is not installed")
        npm = shutil.which("npm") or os.path.join(os.path.dirname(node), "npm")
        logger.info("installing the Remotion kit's npm packages…")
        lock = os.path.join(remotion_dir(), "package-lock.json")
        cmd = [npm, "ci" if os.path.isfile(lock) else "install", "--no-audit", "--no-fund"]
        env = {**os.environ, "PATH": f"{os.path.dirname(node)}{os.pathsep}{os.environ.get('PATH', '')}"}
        result = subprocess.run(cmd, cwd=remotion_dir(), env=env, capture_output=True, text=True, timeout=1200)
        if result.returncode != 0:
            raise RenderError(f"npm install failed: {(result.stderr or result.stdout)[-800:]}")


def render_story(
    story_path: str,
    public_dir: str,
    out_path: str,
    on_progress=None,
    scale: float | None = None,
    concurrency: int | None = None,
    timeout: float = 3600,
) -> str:
    """Render story_path to out_path; on_progress(fraction) as frames finish."""
    ensure_installed()
    node = node_binary()
    cmd = [node, "scripts/render.mjs", "--props", story_path, "--public-dir", public_dir, "--out", out_path]
    if scale:
        cmd += ["--scale", str(scale)]
    concurrency = concurrency or config.animation.get("render_concurrency")
    if concurrency:
        cmd += ["--concurrency", str(int(concurrency))]
    env = {**os.environ, "PATH": f"{os.path.dirname(node)}{os.pathsep}{os.environ.get('PATH', '')}"}

    tmp_out = f"{out_path}.part.mp4"
    cmd[cmd.index(out_path)] = tmp_out
    proc = subprocess.Popen(cmd, cwd=remotion_dir(), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        proc.kill()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    error, tail = "", []
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                tail = (tail + [line])[-20:]
                continue
            if event.get("stage") == "error":
                error = event.get("error", "")
            elif on_progress and event.get("stage") == "rendering":
                on_progress(float(event.get("progress", 0.0)))
        code = proc.wait()
    finally:
        timer.cancel()
    if code != 0 or not os.path.isfile(tmp_out):
        detail = error or "\n".join(tail) or f"exit code {code}"
        if timed_out.is_set():
            detail = f"render timed out after {int(timeout)}s"
        raise RenderError(f"Remotion render failed: {detail[-1500:]}")
    os.replace(tmp_out, out_path)
    return out_path


def extract_frame(video_path: str, out_path: str, at_seconds: float) -> str | None:
    try:
        subprocess.run(
            [utils.get_ffmpeg_binary(), "-y", "-ss", f"{max(0.0, at_seconds):.2f}", "-i", video_path, "-frames:v", "1", "-q:v", "3", out_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=True,
        )
        return out_path if os.path.isfile(out_path) else None
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning(f"thumbnail frame failed: {exc}")
        return None
