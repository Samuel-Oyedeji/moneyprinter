"""End-to-end check of the Schedule page's batch paste -> review -> confirm flow."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from app.services import schedule as schedule_service  # noqa: E402

SCHEDULE_PAGE = ROOT_DIR / "webui" / "pages" / "Schedule.py"


class TestScheduleBatchPage(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.store_path = os.path.join(self._temp_dir.name, "schedule.json")
        store_patcher = patch.object(
            schedule_service, "_schedule_file", lambda: self.store_path
        )
        store_patcher.start()
        self.addCleanup(store_patcher.stop)

        # st.page_link 需要真正的多页应用上下文，AppTest 里不可用。
        link_patcher = patch.object(st, "page_link", lambda *a, **k: None)
        link_patcher.start()
        self.addCleanup(link_patcher.stop)

    def stored_entries(self) -> list[dict]:
        if not os.path.isfile(self.store_path):
            return []
        with open(self.store_path, encoding="utf-8") as f:
            return json.load(f)["entries"]

    def run_page(self) -> AppTest:
        app = AppTest.from_file(str(SCHEDULE_PAGE), default_timeout=120)
        app.run()
        self.assertEqual([str(e.value) for e in app.exception], [])
        return app

    def test_page_renders_the_batch_form(self):
        app = self.run_page()
        labels = [area.label for area in app.text_area]
        self.assertIn("Topics (one per line)", labels)

    def test_paste_preview_and_confirm_schedules_every_topic(self):
        app = self.run_page()
        topics = [f"{i}. Batch topic {i}" for i in range(1, 15)]
        [a for a in app.text_area if a.label == "Topics (one per line)"][0].set_value(
            "\n".join(topics)
        )
        [b for b in app.button if "Preview" in str(b.label)][0].click()
        app.run()
        self.assertEqual([str(e.value) for e in app.exception], [])

        # 预览阶段不写盘。
        self.assertEqual(self.stored_entries(), [])
        review = [m.value for m in app.markdown if "Review 14 video(s)" in m.value]
        self.assertTrue(review, "expected a review header for the 14 planned videos")
        self.assertIn("across 3 day(s)", review[0])

        confirm = [b for b in app.button if "Confirm all" in str(b.label)]
        self.assertEqual(len(confirm), 1)
        self.assertIn("14 entries", str(confirm[0].label))
        confirm[0].click()
        app.run()
        self.assertEqual([str(e.value) for e in app.exception], [])

        stored = self.stored_entries()
        self.assertEqual(len(stored), 14)
        # 序号被剥掉，主题保持原顺序。
        self.assertEqual(
            [e["topic"] for e in stored],
            [f"Batch topic {i}" for i in range(1, 15)],
        )
        # 每天 6 条，按均分时段排列。
        by_date: dict[str, list[str]] = {}
        for entry in stored:
            by_date.setdefault(entry["date"], []).append(entry["post_time"])
        self.assertEqual(sorted(len(v) for v in by_date.values()), [2, 6, 6])
        self.assertEqual(
            sorted(max(by_date.values(), key=len)),
            ["08:20", "11:00", "13:40", "16:20", "19:00", "21:40"],
        )
        self.assertTrue(all(e["video_count"] == 1 for e in stored))

        # 确认后表单回到初始状态。AppTest 不会跟随 st.rerun，需再跑一次脚本。
        self.assertNotIn("batch_plan", app.session_state)
        app.run()
        self.assertFalse([b for b in app.button if "Confirm all" in str(b.label)])

    def test_discard_throws_the_plan_away(self):
        app = self.run_page()
        [a for a in app.text_area if a.label == "Topics (one per line)"][0].set_value(
            "one topic"
        )
        [b for b in app.button if "Preview" in str(b.label)][0].click()
        app.run()
        [b for b in app.button if str(b.label) == "Discard"][0].click()
        app.run()
        self.assertEqual([str(e.value) for e in app.exception], [])
        self.assertEqual(self.stored_entries(), [])
        self.assertNotIn("batch_plan", app.session_state)
        app.run()
        self.assertFalse([b for b in app.button if "Confirm all" in str(b.label)])

    def test_batch_starts_after_days_that_already_have_entries(self):
        from datetime import date, datetime, time, timedelta

        today = date.today()
        booked = [(today + timedelta(days=n)).isoformat() for n in (0, 1, 2)]
        for day in booked:
            schedule_service.create_entry(date=day, topic="already booked")

        # 固定"现在"为清晨，否则测试结果会随运行时刻变化：
        # 傍晚运行时当天时段已过期，本来就会被跳过。
        clock = patch.object(
            schedule_service,
            "_planning_now",
            lambda: datetime.combine(today, time(6, 0)),
        )
        clock.start()
        self.addCleanup(clock.stop)

        app = self.run_page()
        [a for a in app.text_area if a.label == "Topics (one per line)"][0].set_value(
            "fresh topic"
        )
        [b for b in app.button if "Preview" in str(b.label)][0].click()
        app.run()
        [b for b in app.button if "Confirm all" in str(b.label)][0].click()
        app.run()

        new_entries = [e for e in self.stored_entries() if e["topic"] == "fresh topic"]
        self.assertEqual(len(new_entries), 1)
        self.assertNotIn(new_entries[0]["date"], booked)
        self.assertEqual(
            new_entries[0]["date"], (today + timedelta(days=3)).isoformat()
        )

    def test_empty_paste_is_rejected(self):
        app = self.run_page()
        [b for b in app.button if "Preview" in str(b.label)][0].click()
        app.run()
        self.assertEqual([str(e.value) for e in app.exception], [])
        self.assertTrue([e for e in app.error if "at least one topic" in e.value])
        self.assertEqual(self.stored_entries(), [])


if __name__ == "__main__":
    unittest.main()
