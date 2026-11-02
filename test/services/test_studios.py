"""Studio rules, playbook evidence rule, queue booking and the timeline."""
import os
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import config  # noqa: E402
from app.services import schedule as shorts_schedule  # noqa: E402
from app.services import upload_budget  # noqa: E402
from app.services.studios import model, store, templates  # noqa: E402
from app.utils import utils  # noqa: E402


class StudioTestCase(unittest.TestCase):
    """All storage (studios and every calendar) lives in a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name

        def storage_dir(sub_dir: str = "", create: bool = False):
            d = os.path.join(root, sub_dir)
            if create:
                os.makedirs(d, exist_ok=True)
            return d

        for target, attr, value in (
            (utils, "storage_dir", storage_dir),
            (shorts_schedule, "_schedule_file", lambda: os.path.join(root, "shorts.json")),
        ):
            patcher = patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.day = (date.today() + timedelta(days=3)).isoformat()
        self.studio = templates.ensure_studio("animation")

    def slot(self, hhmm="10:00", day=None, **brief):
        return {"date": day or self.day, "time": hhmm, "brief": {"topic": f"Topic at {hhmm}", **brief}}


class TestStudioRules(StudioTestCase):
    def test_template_creates_a_paused_valid_studio_once(self):
        self.assertTrue(self.studio["paused"])
        self.assertEqual(self.studio["pipeline"], "animation")
        again = templates.ensure_studio("animation")
        self.assertEqual(again["created_at"], self.studio["created_at"])
        self.assertEqual([s["id"] for s in store.list_studios()], ["animation"])
        events = store.list_events("animation")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "settings")

    def test_every_problem_is_reported_at_once(self):
        bad = {**templates.ANIMATION, "id": "Bad Id", "cadence": {"per_day": 0}, "post_window": {"start": "22:00", "end": "07:00"}}
        with self.assertRaises(model.StudioError) as caught:
            model.validate_studio(bad)
        self.assertEqual(len(caught.exception.problems), 3)

    def test_levers_need_a_default_among_their_values(self):
        levers = {**templates.ANIMATION["levers"], "hook": {"values": ["a", "b"], "default": "c"}}
        with self.assertRaises(model.StudioError):
            model.validate_studio({**templates.ANIMATION, "levers": levers})

    def test_update_logs_changed_fields_and_keeps_id_and_pipeline(self):
        store.update_studio("animation", veto_hours=4, paused=False)
        self.assertFalse(store.load_studio("animation")["paused"])
        self.assertIn("paused", store.list_events("animation", limit=1)[0]["data"]["fields"])
        with self.assertRaises(model.StudioError):
            store.update_studio("animation", pipeline="documentary")

    def test_slot_times_spread_through_the_window(self):
        self.assertEqual(model.slot_times(self.studio), ["10:45", "18:15"])


class TestBriefs(StudioTestCase):
    def test_missing_levers_take_playbook_then_studio_defaults(self):
        brief = model.validate_brief(self.studio, {"topic": "Why is the sky blue?"}, {"hook": "cold-scene"})
        self.assertEqual(brief["hook"], "cold-scene")
        self.assertEqual(brief["length"], 35)

    def test_values_outside_a_lever_and_unknown_fields_are_rejected(self):
        with self.assertRaises(model.StudioError) as caught:
            model.validate_brief(self.studio, {"topic": "x", "length": 90, "mood": "spooky"})
        self.assertEqual(len(caught.exception.problems), 2)


class TestPlaybook(StudioTestCase):
    def belief(self, **fields):
        return {"id": "b1", "claim": "45s beats 35s", "status": "adopted", "lever": "length", "evidence": ["exp-1"], **fields}

    def test_adoption_needs_enough_videos_on_every_arm_across_weeks(self):
        with self.assertRaises(model.StudioError):
            store.save_playbook("animation", {"beliefs": [self.belief(videos_per_arm=[6, 4], weeks=["w46", "w47"])]})
        with self.assertRaises(model.StudioError):
            store.save_playbook("animation", {"beliefs": [self.belief(videos_per_arm=[7, 6], weeks=["w46"])]})
        saved = store.save_playbook(
            "animation", {"defaults": {"length": 45}, "beliefs": [self.belief(videos_per_arm=[7, 6], weeks=["w46", "w47"])]}
        )
        self.assertEqual(saved["defaults"], {"length": 45})

    def test_testing_beliefs_need_no_evidence_yet(self):
        store.save_playbook("animation", {"beliefs": [self.belief(status="testing", evidence=[])]})
        self.assertEqual(store.load_playbook("animation")["beliefs"][0]["status"], "testing")

    def test_defaults_must_be_allowed_values(self):
        with self.assertRaises(model.StudioError):
            store.save_playbook("animation", {"defaults": {"length": 90}})


class TestQueue(StudioTestCase):
    def test_booking_counts_toward_the_shared_budget(self):
        store.add_slots("animation", [self.slot("10:00"), self.slot("18:00"), {"reserve": True, "brief": {"topic": "Spare"}}])
        load = upload_budget.daily_load(self.day)
        self.assertEqual((load["studios"], load["total"]), (2, 2))

    def test_a_booking_is_all_or_nothing(self):
        with self.assertRaises(model.StudioError) as caught:
            store.add_slots("animation", [self.slot("10:00"), self.slot("03:00"), self.slot("12:00", length=90)])
        self.assertEqual(len(caught.exception.problems), 2)
        self.assertEqual(store.load_queue("animation"), [])

    def test_double_booking_a_time_is_refused(self):
        store.add_slots("animation", [self.slot("10:00")])
        with self.assertRaises(model.StudioError):
            store.add_slots("animation", [self.slot("10:00")])

    def test_a_full_day_is_refused(self):
        shorts_schedule.create_entry(date=self.day, topic="lots of shorts", video_count=5)
        with patch.object(upload_budget, "daily_budget", return_value=6):
            store.add_slots("animation", [self.slot("10:00")])
            with self.assertRaises(model.StudioError):
                store.add_slots("animation", [self.slot("12:00")])

    def test_status_changes_follow_the_lifecycle(self):
        slot = store.add_slots("animation", [self.slot("10:00")])[0]
        with self.assertRaises(model.StudioError):
            store.update_slot("animation", slot["id"], status=model.SLOT_UPLOADED)
        for status in (model.SLOT_PRODUCING, model.SLOT_READY, model.SLOT_CANCELLED):
            store.update_slot("animation", slot["id"], status=status)
        self.assertEqual(upload_budget.daily_load(self.day)["studios"], 0)  # a vetoed slot frees its upload
        with self.assertRaises(model.StudioError):
            store.update_slot("animation", slot["id"], status=model.SLOT_READY)

    def test_a_reserve_given_a_time_becomes_a_regular_slot(self):
        reserve = store.add_slots("animation", [{"reserve": True, "brief": {"topic": "Spare"}}])[0]
        self.assertEqual(upload_budget.daily_load(self.day)["studios"], 0)
        promoted = store.update_slot("animation", reserve["id"], date=self.day, time="11:00")
        self.assertFalse(promoted["reserve"])
        self.assertEqual(upload_budget.daily_load(self.day)["studios"], 1)

    def test_parallel_bookings_never_lose_a_slot(self):
        def book(hhmm):
            store.add_slots("animation", [self.slot(hhmm)])

        threads = [threading.Thread(target=book, args=(f"{h:02d}:00",)) for h in range(8, 20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(store.load_queue("animation")), 12)


class TestTimelineAndNotes(StudioTestCase):
    def test_events_come_back_newest_first_and_filterable(self):
        store.append_event("animation", "plan", "Week 46 plan")
        store.append_event("animation", "uploaded", "Video up")
        self.assertEqual(store.list_events("animation", limit=1)[0]["summary"], "Video up")
        self.assertEqual([e["summary"] for e in store.list_events("animation", types=("plan",))], ["Week 46 plan"])
        with self.assertRaises(ValueError):
            store.append_event("animation", "gossip", "nope")

    def test_a_torn_last_line_is_skipped(self):
        store.append_event("animation", "plan", "Week 46 plan")
        with open(os.path.join(store.studio_dir("animation"), "timeline.jsonl"), "a", encoding="utf-8") as f:
            f.write('{"id": "half')
        self.assertEqual(store.list_events("animation", limit=1)[0]["summary"], "Week 46 plan")

    def test_notes_land_on_the_timeline_and_can_be_marked_read(self):
        note = store.add_note("animation", "Fewer space topics this week")
        self.assertEqual(store.list_events("animation", limit=1)[0]["type"], "note")
        store.mark_notes_read("animation", [note["id"]])
        self.assertEqual(store.list_notes("animation", unread_only=True), [])


class TestBudgetSetting(unittest.TestCase):
    def test_budget_comes_from_config_and_stays_under_the_api_allowance(self):
        with patch.dict(config.youtube, {"daily_upload_budget": 20}):
            self.assertEqual(upload_budget.daily_budget(), 20)
        with patch.dict(config.youtube, {"daily_upload_budget": 500}):
            self.assertEqual(upload_budget.daily_budget(), upload_budget.API_DAILY_UPLOADS)
        with patch.dict(config.youtube, {"daily_upload_budget": "lots"}):
            self.assertEqual(upload_budget.daily_budget(), upload_budget.DEFAULT_DAILY_BUDGET)


if __name__ == "__main__":
    unittest.main()
