"""The render's frame timeout: passed to Remotion, and a timed-out frame is
retried once with half the browser tabs. Node is faked; nothing renders."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import config  # noqa: E402
from app.services.animation import render  # noqa: E402

FRAME_TIMEOUT = (
    "Error: Timeout (120000ms) exceeded rendering the component at frame 16. "
    'You can increase the timeout using the "timeoutInMilliseconds" / "--timeout" option'
)


class FakeNode:
    """Stands in for `node scripts/render.mjs`: fails or writes the output file."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        error = self.outcomes.pop(0)
        out = cmd[cmd.index("--out") + 1]
        if error:
            lines = [json.dumps({"stage": "error", "error": error})]
        else:
            Path(out).write_bytes(b"mp4")
            lines = [json.dumps({"stage": "rendering", "progress": 1.0})]
        return _Proc(lines, 1 if error else 0)

    def flag(self, call, name):
        cmd = self.commands[call]
        return cmd[cmd.index(name) + 1] if name in cmd else None


class _Proc:
    def __init__(self, lines, code):
        self.stdout = iter(line + "\n" for line in lines)
        self.code = code

    def wait(self):
        return self.code

    def kill(self):
        pass


class TestFrameTimeout(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = os.path.join(self._tmp.name, "final.mp4")
        for p in (
            patch.object(render, "ensure_installed", lambda: None),
            patch.object(render, "node_binary", lambda: "/usr/bin/node"),
            patch.dict(config.animation, {"render_concurrency": "", "render_frame_timeout": ""}),
        ):
            p.start()
            self.addCleanup(p.stop)

    def run_render(self, node, **kwargs):
        with patch.object(render.subprocess, "Popen", node):
            return render.render_story("story.json", "public", self.out, **kwargs)

    def test_the_frame_timeout_reaches_remotion(self):
        node = FakeNode([None, None])
        self.run_render(node)
        self.assertEqual(node.flag(0, "--timeout"), "120000")
        with patch.dict(config.animation, {"render_frame_timeout": 2}):
            self.run_render(node)
        self.assertEqual(node.flag(1, "--timeout"), "7000")  # Remotion refuses less

    def test_a_timed_out_frame_renders_again_with_half_the_tabs(self):
        node = FakeNode([FRAME_TIMEOUT, None])
        self.assertEqual(self.run_render(node, concurrency=4), self.out)
        self.assertEqual([node.flag(0, "--concurrency"), node.flag(1, "--concurrency")], ["4", "2"])

    def test_without_a_setting_the_retry_halves_remotions_default(self):
        node = FakeNode([FRAME_TIMEOUT, None])
        with patch.object(render, "default_concurrency", lambda: 3):
            self.run_render(node)
        self.assertEqual([node.flag(0, "--concurrency"), node.flag(1, "--concurrency")], [None, "1"])

    def test_it_gives_up_after_the_second_timeout(self):
        node = FakeNode([FRAME_TIMEOUT, FRAME_TIMEOUT])
        with self.assertRaises(render.FrameTimeoutError):
            self.run_render(node, concurrency=4)
        self.assertEqual(len(node.commands), 2)

    def test_one_tab_and_other_errors_are_not_retried(self):
        node = FakeNode([FRAME_TIMEOUT])
        with self.assertRaises(render.FrameTimeoutError):
            self.run_render(node, concurrency=1)
        node = FakeNode(["TypeError: something else broke"])
        with self.assertRaises(render.RenderError) as caught:
            self.run_render(node, concurrency=4)
        self.assertNotIsInstance(caught.exception, render.FrameTimeoutError)
        self.assertEqual(len(node.commands), 1)


if __name__ == "__main__":
    unittest.main()
