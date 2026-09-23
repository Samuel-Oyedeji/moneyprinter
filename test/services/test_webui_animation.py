"""The Animation page: create → queue, library, and scheduling through the UI."""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.services import schedule as shorts_schedule  # noqa: E402
from app.services.animation import jobs, render, store  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.documentary import doc_schedule  # noqa: E402

PAGE = str(ROOT_DIR / "webui" / "pages" / "Animation.py")


class TestAnimationPage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name
        self.enqueued: list[list[str]] = []
        for target, attr, value in (
            (store, "animation_dir", lambda: root),
            (shorts_schedule, "_schedule_file", lambda: os.path.join(root, "shorts.json")),
            (doc_schedule, "_schedule_file", lambda: os.path.join(root, "docs.json")),
            (render, "readiness", lambda: (True, "Renderer ready")),
            (jobs, "enqueue", lambda ids: self.enqueued.append(list(ids))),
            (st, "page_link", lambda *a, **k: None),  # needs a real multipage app
        ):
            patcher = patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def finished(self, topic: str) -> str:
        pid = store.create_project(topic, seconds=30, aspect="9:16", voice="en-GB-RyanNeural")["project_id"]
        with open(store.final_path(pid), "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42")
        store.update_project(pid, status=store.STATUS_DONE, duration=31.0, youtube={"title": f"{topic}!", "description": "d", "hashtags": [], "tags": [], "generated": True})
        return pid

    def test_single_topic_is_created_and_queued(self):
        at = AppTest.from_file(PAGE, default_timeout=30).run()
        self.assertFalse(at.exception, at.exception)
        at.text_input[1].input("Why octopuses have three hearts")  # [0] is the ElevenLabs key
        at.text_area[0].input("Two pump blood to the gills.")
        next(b for b in at.button if "Generate" in b.label).click().run()
        self.assertFalse(at.exception, at.exception)
        projects = store.list_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["topic"], "Why octopuses have three hearts")
        self.assertEqual(projects[0]["context"], "Two pump blood to the gills.")
        self.assertEqual(self.enqueued, [[projects[0]["project_id"]]])

    def test_batch_mode_queues_one_video_per_line(self):
        at = AppTest.from_file(PAGE, default_timeout=30).run()
        at.radio(key="anim_mode").set_value("Batch").run()
        at.text_area[0].input("1. The boy who cried wolf | honesty\n- Why the sky is blue\n\n").run()
        next(b for b in at.button if "Generate" in b.label).click().run()
        self.assertFalse(at.exception, at.exception)
        topics = sorted(p["topic"] for p in store.list_projects())
        self.assertEqual(topics, ["The boy who cried wolf", "Why the sky is blue"])
        wolf = next(p for p in store.list_projects() if p["topic"] == "The boy who cried wolf")
        self.assertEqual(wolf["context"], "honesty")
        self.assertEqual(len(self.enqueued[0]), 2)

    def test_library_and_schedule_sections(self):
        pid = self.finished("The Messy Lab")
        at = AppTest.from_file(PAGE, default_timeout=30)
        at.session_state["anim_section"] = "📚 Library"
        at.run()
        self.assertFalse(at.exception, at.exception)
        self.assertTrue(any("The Messy Lab!" in m.value for m in at.markdown))

        at.session_state["anim_section"] = "📅 Schedule"
        at.run()
        self.assertFalse(at.exception, at.exception)
        at.date_input(key="single_day").set_value(date.today() + timedelta(days=2))
        at.button(key="single_go").click().run()
        self.assertFalse(at.exception, at.exception)
        entries = anim_schedule.list_entries()
        self.assertEqual([(e["project_id"], e["post_time"]) for e in entries], [(pid, "18:00")])


if __name__ == "__main__":
    unittest.main()
