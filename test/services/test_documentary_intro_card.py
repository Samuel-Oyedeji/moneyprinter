import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# add project root to python path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.documentary import render

FILTERS_WITH_DRAWTEXT = """Filters:
 ... drawbox           V->V       Draw a colored box on the input video.
 ... drawtext          V->V       Draw text on top of video frames using libfreetype.
 ... overlay           VV->V      Overlay a video source on top of the input.
"""

FILTERS_WITHOUT_DRAWTEXT = """Filters:
 ... drawbox           V->V       Draw a colored box on the input video.
 ... overlay           VV->V      Overlay a video source on top of the input.
"""

PROJECT = {"topic": "The Great Smog of London"}
SCRIPT = {
    "intro": {
        "title": "The Great Smog of London",
        "date_line": "London, December 1952",
    }
}


def _filters_output(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class TestSupportsDrawtext(unittest.TestCase):
    def setUp(self):
        render._supports_drawtext.cache_clear()

    def test_detects_drawtext_in_filter_list(self):
        with patch.object(
            render.subprocess, "run", return_value=_filters_output(FILTERS_WITH_DRAWTEXT)
        ):
            self.assertTrue(render._supports_drawtext("/usr/bin/ffmpeg"))

    def test_reports_missing_drawtext(self):
        with patch.object(
            render.subprocess,
            "run",
            return_value=_filters_output(FILTERS_WITHOUT_DRAWTEXT),
        ):
            self.assertFalse(render._supports_drawtext("/usr/bin/ffmpeg"))

    def test_probe_failure_falls_back_to_unsupported(self):
        with (
            patch.object(render.subprocess, "run", side_effect=OSError("boom")),
            patch.object(render.logger, "warning"),
        ):
            self.assertFalse(render._supports_drawtext("/usr/bin/ffmpeg"))


class TestRenderIntroSegment(unittest.TestCase):
    """The intro card must survive ffmpeg builds compiled without libfreetype."""

    def _render(self, supports_drawtext: bool) -> list[str]:
        recorded: list[str] = []
        with tempfile.TemporaryDirectory() as output_dir:
            background = str(Path(output_dir) / "bg.png")
            from PIL import Image

            Image.new("RGB", (640, 360), (40, 40, 40)).save(background)
            with (
                patch.object(render, "_supports_drawtext", return_value=supports_drawtext),
                patch.object(render, "_ffmpeg_exe", return_value="/usr/bin/ffmpeg"),
                patch.object(
                    render, "_run_ffmpeg", side_effect=lambda args, context: recorded.extend(args)
                ),
            ):
                render._render_intro_segment(PROJECT, SCRIPT, background, output_dir)
        return recorded

    def test_uses_drawtext_when_available(self):
        args = self._render(True)
        self.assertIn("-vf", args)
        self.assertTrue(any("drawtext=" in arg for arg in args))

    def test_overlays_a_pil_title_card_without_drawtext(self):
        args = self._render(False)
        self.assertFalse(any("drawtext=" in arg for arg in args))
        self.assertIn("-filter_complex", args)
        self.assertTrue(any("overlay=0:0" in arg for arg in args))
        self.assertTrue(any(arg.endswith("intro-text.png") for arg in args))


if __name__ == "__main__":
    unittest.main()
