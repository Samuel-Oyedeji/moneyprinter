"""Trial-run additions: shadow mode (T1), owner verdicts (T2), the same-subject
check (T3) and the trial report (T4)."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import config  # noqa: E402
from app.services import schedule as shorts_schedule  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.animation import store as anim_store  # noqa: E402
from app.services.studios import evaluate, model, qa, runner, store, templates, trial  # noqa: E402
from app.utils import utils  # noqa: E402


class TrialTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name

        def storage_dir(sub_dir: str = "", create: bool = False):
            d = os.path.join(root, sub_dir)
            if create:
                os.makedirs(d, exist_ok=True)
            return d

        for p in (
            patch.object(utils, "storage_dir", storage_dir),
            patch.object(shorts_schedule, "_schedule_file", lambda: os.path.join(root, "shorts.json")),
            patch.dict(config.youtube, {"publish_timezone": "Africa/Lagos"}),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.studio = templates.ensure_studio("animation")

    def put(self, *slots):
        """Write queue slots straight to disk (any status, no lifecycle)."""
        clean = []
        for i, raw in enumerate(slots):
            slot = model.validate_slot(self.studio, {"brief": {"topic": f"Topic {i}"}, **raw})
            slot["id"] = raw.get("id") or f"s{i}"
            clean.append(slot)
        store._write_json(store._path("animation", "queue.json"), clean)
        return clean


# ------------------------------------------------------------------ T1
class TestShadow(TrialTestCase):
    def test_new_studios_start_in_shadow(self):
        self.assertTrue(self.studio["shadow"])

    def test_a_shadow_upload_stays_private_and_out_of_the_results(self):
        project = anim_store.create_project("Why do cats purr", seconds=35, source="studio")
        slot = self.put({"date": "2026-11-17", "time": "18:15", "status": model.SLOT_READY, "project_id": project["project_id"]})[0]
        with patch.object(anim_schedule, "upload_project", return_value="vidShadow01") as upload:
            runner.upload_slot(self.studio, slot, datetime(2026, 11, 17, 16, tzinfo=timezone.utc))
        self.assertIsNone(upload.call_args.args[1])  # no publish time: it never goes public
        done = store.get_slot("animation", slot["id"])
        self.assertEqual((done["shadow"], done["publish_at"], done["youtube_video_id"]), (True, "", "vidShadow01"))
        self.assertIn("privately (shadow mode", store.list_events("animation", limit=1)[0]["summary"])

        df = pd.DataFrame([{"video_id": "vidShadow01", "studio": "animation", "published_at": datetime(2026, 11, 17, tzinfo=timezone.utc), "views_3d": 0.0, "live": False}])
        self.assertEqual(evaluate.score_videos(store.load_queue("animation"), df, "animation"), [])
        self.assertEqual(runner.record_checkins(self.studio, datetime(2026, 12, 30, tzinfo=timezone.utc), df), [])

    def test_the_baseline_counts_public_videos_only(self):
        now = datetime(2026, 11, 20, tzinfo=timezone.utc)
        rows = [{"studio": "animation", "published_at": now - timedelta(days=30 - i), "views_3d": 100.0, "live": True} for i in range(5)]
        rows += [{"studio": "animation", "published_at": now - timedelta(days=20 - i), "views_3d": 0.0, "live": False} for i in range(5)]
        pool = evaluate.baseline_pool(pd.DataFrame(rows), "animation")
        self.assertEqual([views for _, views in pool], [100.0] * 5)


# ------------------------------------------------------------------ T2
class TestOwnerVerdicts(TrialTestCase):
    def test_a_thumbs_down_needs_a_reason_and_reaches_the_agent(self):
        slot = self.put({"date": "2026-11-17", "time": "18:15", "status": model.SLOT_READY})[0]
        with self.assertRaises(model.StudioError):
            store.review_slot("animation", slot["id"], "bad")
        store.review_slot("animation", slot["id"], "bad", "The narration says bats are blind")
        self.assertEqual(store.get_slot("animation", slot["id"])["owner_review"]["verdict"], "bad")
        note = store.list_notes("animation", unread_only=True)[0]
        self.assertIn('👎 "Topic 0" (2026-11-17 18:15): The narration says bats are blind', note["text"])

    def test_a_plain_thumbs_up_is_recorded_without_a_note(self):
        slot = self.put({"date": "2026-11-17", "time": "18:15", "status": model.SLOT_UPLOADED})[0]
        store.review_slot("animation", slot["id"], "good")
        self.assertEqual(store.list_notes("animation"), [])

    def test_only_finished_videos_can_be_rated(self):
        slot = self.put({"date": "2026-11-17", "time": "18:15", "status": model.SLOT_PLANNED})[0]
        with self.assertRaises(model.StudioError):
            store.review_slot("animation", slot["id"], "good")


# ------------------------------------------------------------------ T3
class TestSameSubject(TrialTestCase):
    def test_a_video_is_checked_against_what_comes_before_it_only(self):
        slots = self.put(
            {"id": "early", "date": "2026-11-17", "time": "10:45", "brief": {"topic": "What happens when a star dies"}},
            {"id": "late", "date": "2026-11-19", "time": "10:45", "brief": {"topic": "The lifecycle of a neutron star"}},
            {"id": "gone", "date": "2026-11-16", "time": "10:45", "status": model.SLOT_FAILED, "brief": {"topic": "Why Mars is red"}},
        )
        recent = [
            {"text": "What happens when a star dies", "source": "animation project", "date": ""},
            {"text": "The lifecycle of a neutron star", "source": "animation project", "date": ""},
            {"text": "Why Mars is red", "source": "animation project", "date": ""},
            {"text": "How volcanoes work", "source": "channel", "date": "2026-11-01"},
        ]
        early = [t["text"] for t in qa.earlier_topics(self.studio, slots[0], recent)]
        late = [t["text"] for t in qa.earlier_topics(self.studio, slots[1], recent)]
        self.assertEqual(sorted(early), ["How volcanoes work"])
        self.assertEqual(sorted(late), ["How volcanoes work", "What happens when a star dies"])

    def test_the_critic_sees_the_earlier_topics_and_a_repeat_means_a_reserve(self):
        seen = {}

        def ask(prompt):
            seen["prompt"] = prompt
            return json.dumps({"problems": [{"kind": "duplicate", "quote": "What happens when a star dies", "why": "same subject"}]}), 0.01

        check, _ = qa.critic_check(self.studio, "The lifecycle of a neutron star", "Script.", {"title": "t"}, ask, ["What happens when a star dies"])
        self.assertIn("- What happens when a star dies", seen["prompt"])
        self.assertEqual((check["ok"], check["fix"]), (False, "reserve"))


# ------------------------------------------------------------------ T4
NOW = datetime(2026, 11, 26, 12, tzinfo=timezone.utc)  # a Thursday


def live_slots(days: int, per_day: int = 2, **overrides) -> list[dict]:
    start = date(2026, 11, 9)
    slots = []
    for d in range(days):
        for k in range(per_day):
            slots.append(
                {
                    "id": f"d{d}k{k}", "date": (start + timedelta(days=d)).isoformat(), "time": "10:45" if k == 0 else "18:15",
                    "status": model.SLOT_UPLOADED, "youtube_video_id": f"v{d:02d}{k}", "publish_at": "x", "shadow": False,
                    "brief": {"topic": f"Topic {d}-{k}"}, **overrides,
                }
            )
    return slots


class TestTrialReport(TrialTestCase):
    def areas(self, result):
        return {a["area"]: a for a in result["areas"]}

    def test_before_going_live_only_the_shadow_numbers_show(self):
        self.put(
            {"date": "2026-11-05", "time": "10:45", "status": model.SLOT_UPLOADED, "shadow": True, "owner_review": {"verdict": "good"}},
            {"date": "2026-11-05", "time": "18:15", "status": model.SLOT_FAILED},
        )
        result = trial.report("animation", now=NOW)
        self.assertFalse(result["live"])
        self.assertEqual(
            {k: result["shadow"][k] for k in ("slots_due", "uploaded_unattended", "failed", "rated_good")},
            {"slots_due": 2, "uploaded_unattended": 1, "failed": 1, "rated_good": 1},
        )

    def test_a_clean_run_passes_and_says_not_yet_before_fourteen_days(self):
        self.put(*live_slots(10))
        self.assertEqual(self.areas(trial.report("animation", now=NOW, end=date(2026, 11, 18)))["Autonomy"]["status"], "not yet")
        self.put(*live_slots(16))
        areas = self.areas(trial.report("animation", now=NOW, end=date(2026, 11, 24)))
        self.assertEqual({k: v["status"] for k, v in areas.items()}, {
            "Autonomy": "pass", "Reliability": "pass", "Quality": "pass", "Learning hygiene": "pass", "Cost": "pass", "Performance": "info",
        })

    def test_cancellations_failures_and_bad_videos_fail_their_areas(self):
        slots = live_slots(16)
        slots[2].update(status=model.SLOT_FAILED, youtube_video_id="")  # with an incident
        slots[3].update(status=model.SLOT_FAILED, youtube_video_id="")  # silent
        slots[4]["owner_review"] = {"verdict": "bad", "note": "wrong date"}
        for slot in slots[5:7]:
            slot["veto_waived"] = True
        self.put(*slots)
        store.append_event("animation", "incident", "Dropped", {"slot_id": "d1k0"})
        areas = self.areas(trial.report("animation", now=NOW, end=date(2026, 11, 24)))
        self.assertEqual(areas["Reliability"]["status"], "fail")
        self.assertIn("1 silent of 2 failed", areas["Reliability"]["value"])
        self.assertEqual(areas["Quality"]["status"], "fail")
        self.assertIn("wrong date", areas["Quality"]["detail"])
        self.assertEqual(areas["Autonomy"]["status"], "fail")  # 4 of 28 needed you in the first 14 days

    def test_weeks_show_spend_and_three_day_views(self):
        slots = live_slots(7)
        for i, slot in enumerate(slots):
            slot["checkins"] = {"3d": {"views": 100.0 + i}}
        self.put(*slots)
        week = trial.report("animation", now=NOW, end=date(2026, 11, 15))["weeks"][0]
        self.assertEqual((week["week"], week["videos"], week["median_views_3d"]), ("2026-W46", 14, 106.5))


if __name__ == "__main__":
    unittest.main()
