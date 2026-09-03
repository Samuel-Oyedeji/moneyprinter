"""Batch scheduling: pasted topics -> reviewed plan -> calendar entries."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services import schedule as schedule_service  # noqa: E402


class BatchScheduleTestCase(unittest.TestCase):
    """Each test gets its own schedule.json so nothing touches real storage."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.store_path = os.path.join(self._temp_dir.name, "schedule.json")
        patcher = patch.object(
            schedule_service, "_schedule_file", lambda: self.store_path
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._temp_dir.cleanup)

    def stored_entries(self) -> list[dict]:
        if not os.path.isfile(self.store_path):
            return []
        with open(self.store_path, encoding="utf-8") as f:
            return json.load(f)["entries"]


class TestParseTopics(BatchScheduleTestCase):
    def test_splits_lines_and_drops_blanks(self):
        self.assertEqual(
            schedule_service.parse_topics("first\n\n  second  \n\n\nthird"),
            ["first", "second", "third"],
        )

    def test_strips_list_markers(self):
        self.assertEqual(
            schedule_service.parse_topics("1. one\n2) two\n- three\n* four\n• five"),
            ["one", "two", "three", "four", "five"],
        )

    def test_keeps_a_leading_number_that_is_part_of_the_topic(self):
        self.assertEqual(
            schedule_service.parse_topics("5 AI tools that save you an hour"),
            ["5 AI tools that save you an hour"],
        )

    def test_empty_text(self):
        self.assertEqual(schedule_service.parse_topics(""), [])
        self.assertEqual(schedule_service.parse_topics(None), [])


class TestEvenSlotTimes(BatchScheduleTestCase):
    def test_six_slots_fill_the_waking_window(self):
        self.assertEqual(
            schedule_service.even_slot_times(6),
            ["08:20", "11:00", "13:40", "16:20", "19:00", "21:40"],
        )

    def test_other_counts_stay_inside_the_window(self):
        self.assertEqual(schedule_service.even_slot_times(1), ["15:00"])
        self.assertEqual(schedule_service.even_slot_times(2), ["11:00", "19:00"])
        self.assertEqual(
            schedule_service.even_slot_times(4),
            ["09:00", "13:00", "17:00", "21:00"],
        )

    def test_every_slot_sits_within_the_window_with_even_spacing(self):
        start = schedule_service._minutes_since_midnight(
            schedule_service.PUBLISH_WINDOW_START
        )
        end = schedule_service._minutes_since_midnight(
            schedule_service.PUBLISH_WINDOW_END
        )
        for per_day in range(1, schedule_service.DAILY_VIDEO_LIMIT + 1):
            with self.subTest(per_day=per_day):
                minutes = [
                    schedule_service._minutes_since_midnight(slot)
                    for slot in schedule_service.even_slot_times(per_day)
                ]
                self.assertTrue(all(start <= m < end for m in minutes))
                gaps = {b - a for a, b in zip(minutes, minutes[1:])}
                self.assertLessEqual(len(gaps), 1, "slots must be evenly spaced")
                # 首尾各留半格余量，两端对称。
                self.assertEqual(minutes[0] - start, end - minutes[-1])

    def test_window_is_configurable(self):
        self.assertEqual(
            schedule_service.even_slot_times(
                2, window_start="10:00", window_end="18:00"
            ),
            ["12:00", "16:00"],
        )

    def test_rejects_counts_over_the_daily_limit(self):
        with self.assertRaises(ValueError):
            schedule_service.even_slot_times(schedule_service.DAILY_VIDEO_LIMIT + 1)
        with self.assertRaises(ValueError):
            schedule_service.even_slot_times(0)

    def test_rejects_an_inverted_window(self):
        with self.assertRaises(ValueError):
            schedule_service.even_slot_times(
                3, window_start="22:00", window_end="08:00"
            )


class TestFindFreeDates(BatchScheduleTestCase):
    def setUp(self):
        super().setUp()
        # 固定"现在"，让测试与真实时钟无关。
        self.now = datetime(2026, 9, 3, 10, 30)
        self.slots = schedule_service.even_slot_times(6)

    def test_starts_tomorrow_because_today_has_slots_in_the_past(self):
        dates = schedule_service.find_free_dates(
            2, slot_times=self.slots, now=self.now
        )
        self.assertEqual(dates, ["2026-09-04", "2026-09-05"])

    def test_uses_today_when_the_whole_window_is_still_ahead(self):
        early = datetime(2026, 9, 3, 6, 0)
        dates = schedule_service.find_free_dates(
            1, slot_times=self.slots, now=early
        )
        self.assertEqual(dates, ["2026-09-03"])

    def test_skips_days_that_already_have_entries(self):
        for day in ("2026-09-04", "2026-09-05"):
            schedule_service.create_entry(date=day, topic="already booked")
        dates = schedule_service.find_free_dates(
            2, slot_times=self.slots, now=self.now
        )
        self.assertEqual(dates, ["2026-09-06", "2026-09-07"])

    def test_skip_busy_days_off_stacks_onto_booked_days(self):
        schedule_service.create_entry(date="2026-09-04", topic="already booked")
        dates = schedule_service.find_free_dates(
            1, slot_times=self.slots, skip_busy_days=False, now=self.now
        )
        self.assertEqual(dates, ["2026-09-04"])

    def test_explicit_start_date_is_honoured(self):
        dates = schedule_service.find_free_dates(
            1, start_date="2026-10-01", slot_times=self.slots, now=self.now
        )
        self.assertEqual(dates, ["2026-10-01"])

    def test_raises_when_the_horizon_is_exhausted(self):
        with self.assertRaises(ValueError):
            schedule_service.find_free_dates(
                5, slot_times=self.slots, now=self.now, horizon_days=2
            )

    def test_zero_count_returns_nothing(self):
        self.assertEqual(schedule_service.find_free_dates(0), [])


class TestPlanBatch(BatchScheduleTestCase):
    def setUp(self):
        super().setUp()
        self.now = datetime(2026, 9, 3, 10, 30)

    def plan(self, topic_count, **kwargs):
        topics = [f"Topic {i}" for i in range(1, topic_count + 1)]
        kwargs.setdefault("now", self.now)
        return schedule_service.plan_batch(topics, **kwargs)

    def test_groups_into_days_of_six_and_spreads_the_slots(self):
        result = self.plan(14)
        items = result["items"]
        self.assertEqual(len(items), 14)
        self.assertEqual(result["dates"], ["2026-09-04", "2026-09-05", "2026-09-06"])

        first_day = [i for i in items if i["date"] == "2026-09-04"]
        self.assertEqual(len(first_day), 6)
        self.assertEqual(
            [i["post_time"] for i in first_day],
            schedule_service.even_slot_times(6),
        )
        # 最后一天只剩两条，用当天最前面的两个时段。
        last_day = [i for i in items if i["date"] == "2026-09-06"]
        self.assertEqual(
            [i["post_time"] for i in last_day],
            schedule_service.even_slot_times(6)[:2],
        )
        self.assertEqual([i["topic"] for i in last_day], ["Topic 13", "Topic 14"])

    def test_one_video_per_row_and_preset_language_applied(self):
        items = self.plan(3, preset="horizontal", language="en-US")["items"]
        self.assertTrue(all(i["video_count"] == 1 for i in items))
        self.assertTrue(all(i["preset"] == "horizontal" for i in items))
        self.assertTrue(all(i["language"] == "en-US" for i in items))

    def test_custom_per_day(self):
        result = self.plan(5, per_day=2)
        self.assertEqual(len(result["dates"]), 3)
        self.assertEqual(result["slot_times"], ["11:00", "19:00"])

    def test_starts_after_days_that_are_already_booked(self):
        for day in ("2026-09-04", "2026-09-05"):
            schedule_service.create_entry(date=day, topic="already booked")
        result = self.plan(2)
        self.assertEqual(result["dates"], ["2026-09-06"])

    def test_plans_nothing_to_disk(self):
        self.plan(8)
        self.assertEqual(self.stored_entries(), [])

    def test_rejects_empty_and_oversized_input(self):
        with self.assertRaises(ValueError):
            schedule_service.plan_batch(["  ", ""])
        with self.assertRaises(ValueError):
            self.plan(3, per_day=schedule_service.DAILY_VIDEO_LIMIT + 1)
        with self.assertRaises(ValueError):
            self.plan(3, preset="vertical-ish")


class TestCreateEntries(BatchScheduleTestCase):
    def test_writes_every_item_once(self):
        items = schedule_service.plan_batch(
            [f"Topic {i}" for i in range(1, 8)],
            now=datetime(2026, 9, 3, 10, 30),
        )["items"]
        created = schedule_service.create_entries(items)
        self.assertEqual(len(created), 7)
        stored = self.stored_entries()
        self.assertEqual(len(stored), 7)
        self.assertEqual(len({e["id"] for e in stored}), 7)
        self.assertTrue(
            all(e["status"] == schedule_service.STATUS_PENDING for e in stored)
        )
        self.assertEqual(stored[0]["post_time"], "08:20")

    def test_appends_to_existing_entries(self):
        schedule_service.create_entry(date="2026-09-04", topic="manual one")
        schedule_service.create_entries(
            [{"date": "2026-09-10", "topic": "batch one", "post_time": "08:00"}]
        )
        self.assertEqual(len(self.stored_entries()), 2)

    def test_a_bad_row_leaves_the_calendar_untouched(self):
        good = {"date": "2026-09-10", "topic": "fine", "post_time": "08:00"}
        bad = {"date": "2026-09-10", "topic": "   ", "post_time": "08:00"}
        with self.assertRaises(ValueError):
            schedule_service.create_entries([good, bad])
        self.assertEqual(self.stored_entries(), [])

    def test_rejects_a_bad_time(self):
        with self.assertRaises(ValueError):
            schedule_service.create_entries(
                [{"date": "2026-09-10", "topic": "fine", "post_time": "25:00"}]
            )

    def test_empty_list_is_a_no_op(self):
        self.assertEqual(schedule_service.create_entries([]), [])
        self.assertEqual(self.stored_entries(), [])


class TestPlanningNow(BatchScheduleTestCase):
    def test_uses_the_configured_publish_timezone(self):
        from app.config import config

        with patch.dict(config.youtube, {"publish_timezone": "Africa/Lagos"}):
            lagos = schedule_service._planning_now()
        self.assertIsNone(lagos.tzinfo)
        utc_now = datetime.utcnow()
        # Lagos 是 UTC+1，允许几秒误差。
        self.assertLess(abs((lagos - utc_now) - timedelta(hours=1)), timedelta(minutes=2))

    def test_falls_back_on_an_invalid_timezone(self):
        from app.config import config

        with patch.dict(config.youtube, {"publish_timezone": "Not/AZone"}):
            self.assertIsInstance(schedule_service._planning_now(), datetime)


if __name__ == "__main__":
    unittest.main()
