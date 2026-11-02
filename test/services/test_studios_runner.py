"""The studio tick (WP5): QA checks, production, the cancel window, uploads, check-ins."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import config  # noqa: E402
from app.services import discord_notify  # noqa: E402
from app.services import schedule as shorts_schedule  # noqa: E402
from app.services import youtube_upload  # noqa: E402
from app.services.analytics import report  # noqa: E402
from app.services.animation import pipeline  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.animation import store as anim_store  # noqa: E402
from app.services.studios import model, planner, qa, runner, store, templates  # noqa: E402
from app.utils import utils  # noqa: E402

SCRIPT = "Cats purr at twenty five to one hundred fifty hertz. Nobody fully knows why."
GOOD_LOG = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'final.mp4':
  Duration: 00:00:36.04, start: 0.000000, bitrate: 1200 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1080x1920, 24 fps
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 128 kb/s
[Parsed_volumedetect_1 @ 0x600] mean_volume: -18.4 dB
[Parsed_volumedetect_1 @ 0x600] max_volume: -1.2 dB
"""
SILENT_GAP = "[silencedetect @ 0x600] silence_end: 12.5 | silence_duration: 3.10\n"
BAD_PICTURE = (
    "[blackdetect @ 0x601] black_start:3 black_end:4.5 black_duration:1.5\n"
    "[freezedetect @ 0x602] lavfi.freezedetect.freeze_duration: 6.2\n"
)


# ---------------------------------------------------------------- fakes
def fake_run_project(pid, **_):
    """What a successful pipeline leaves behind."""
    anim_store.write_json(anim_store.path(pid, "script.json"), {"text": SCRIPT})
    anim_store.write_json(anim_store.path(pid, "words.json"), {"words": [{"text": w} for w in SCRIPT.split()]})
    with open(anim_store.final_path(pid), "wb") as f:
        f.write(b"mp4")
    anim_store.add_cost(pid, "llm", 0.2)
    return anim_store.update_project(
        pid, status=anim_store.STATUS_DONE, youtube={"title": "Why Do Cats Purr?", "description": "A short.", "generated": True}
    )


def critic_client(*replies):
    """A model client whose replies are the critic's JSON, in order."""
    script = list(replies)

    def create(**kwargs):
        message = SimpleNamespace(content=json.dumps(script.pop(0) if script else {"problems": []}), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(cost=0.003, model_extra=None))

    return SimpleNamespace(base_url="https://openrouter.ai/api/v1", chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def probes(*logs):
    remaining = list(logs)
    return lambda path: remaining.pop(0) if len(remaining) > 1 else remaining[0]


def lagos(day: str, hhmm: str) -> datetime:
    """A Lagos wall-clock time (UTC+1) as UTC."""
    return datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=1))).astimezone(timezone.utc)


DAY = "2026-11-17"  # a Tuesday


# ------------------------------------------------------------------ QA
class TestProbeParsing(unittest.TestCase):
    def test_numbers_come_out_of_the_log(self):
        info = qa.parse_probe(GOOD_LOG + SILENT_GAP + BAD_PICTURE)
        self.assertEqual((info["duration"], info["has_video"], info["has_audio"]), (36.04, True, True))
        self.assertEqual((info["mean_volume_db"], info["silences"], info["black"], info["frozen"]), (-18.4, [3.1], [1.5], [6.2]))

    def test_media_checks_name_their_fix(self):
        good = qa.media_checks(qa.parse_probe(GOOD_LOG), 35)
        self.assertTrue(all(c["ok"] for c in good))
        bad = {c["name"]: c for c in qa.media_checks(qa.parse_probe(GOOD_LOG + SILENT_GAP + BAD_PICTURE), 35)}
        self.assertEqual((bad["silence"]["fix"], bad["black frames"]["fix"], bad["frozen picture"]["fix"]), ("voice", "render", "render"))
        too_long = {c["name"]: c for c in qa.media_checks(qa.parse_probe(GOOD_LOG), 20)}
        self.assertEqual(too_long["length"]["fix"], "script")
        no_audio = qa.media_checks(qa.parse_probe(GOOD_LOG.replace("Audio:", "Data:")), 35)
        self.assertEqual((len(no_audio), no_audio[0]["fix"]), (1, "render"))

    def test_the_parser_reads_a_real_ffmpeg_log(self):
        ffmpeg = utils.get_ffmpeg_binary()
        with tempfile.TemporaryDirectory() as tmp:
            clip = os.path.join(tmp, "clip.mp4")
            made = subprocess.run(
                [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
                 "-shortest", "-pix_fmt", "yuv420p", clip],
                capture_output=True,
            )
            if made.returncode != 0:
                self.skipTest("ffmpeg could not make a test clip")
            info = qa.parse_probe(qa.probe(clip))
        self.assertAlmostEqual(info["duration"], 3.0, delta=0.2)
        self.assertTrue(info["has_video"] and info["has_audio"])
        self.assertGreater(info["mean_volume_db"], -40)
        self.assertTrue(info["black"])  # an all-black clip is caught


class TestContentChecks(unittest.TestCase):
    def test_narration_must_match_the_script(self):
        words = [{"text": w} for w in SCRIPT.split()]
        self.assertTrue(qa.narration_check(words, SCRIPT)["ok"])
        self.assertFalse(qa.narration_check(words[:5], SCRIPT)["ok"])

    def test_titles_that_shout_or_bait_are_refused(self):
        self.assertTrue(qa.title_check({"title": "How NASA Found Water on Mars", "description": "x"}, "9:16")["ok"])
        self.assertIn("shouting", qa.title_check({"title": "The SHOCKING Truth", "description": "x"}, "9:16")["detail"])
        self.assertIn("clickbait", qa.title_check({"title": "You won't believe this cat", "description": "x"}, "9:16")["detail"])

    def test_critic_problems_pick_the_fix_and_a_broken_reply_fails_safe(self):
        studio = templates.ANIMATION
        claim = {"problems": [{"kind": "claim", "quote": "Nobody fully knows why", "why": "it is well understood"}]}
        check, cost = qa.critic_check(studio, "Cats", SCRIPT, {"title": "t"}, lambda prompt: (json.dumps(claim), 0.01))
        self.assertEqual((check["ok"], check["fix"], cost), (False, "script", 0.01))
        check, _ = qa.critic_check(studio, "Cats", SCRIPT, {"title": "t"}, lambda prompt: ("not json at all", 0.0))
        self.assertFalse(check["ok"])
        title_only = {"problems": [{"kind": "title", "quote": "t", "why": "overpromises"}]}
        self.assertEqual(qa.critic_check(studio, "Cats", SCRIPT, {}, lambda p: (json.dumps(title_only), 0))[0]["fix"], "package")


# --------------------------------------------------------------- runner
class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name

        def storage_dir(sub_dir: str = "", create: bool = False):
            d = os.path.join(root, sub_dir)
            if create:
                os.makedirs(d, exist_ok=True)
            return d

        patchers = [
            patch.object(utils, "storage_dir", storage_dir),
            patch.object(shorts_schedule, "_schedule_file", lambda: os.path.join(root, "shorts.json")),
            patch.dict(config.studios, {"enabled": True, "paused": False}),
            patch.dict(config.youtube, {"publish_timezone": "Africa/Lagos"}),
            patch.object(pipeline, "run_project", side_effect=fake_run_project),
            patch.object(runner, "_sync_analytics"),
            patch.object(youtube_upload.youtube_upload_service, "is_configured", return_value=True),
            # never reach the real webhook in config.toml
            patch.object(discord_notify.DiscordNotifyService, "send", return_value=True),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.upload = patch.object(anim_schedule, "upload_project", return_value="vid00000001")
        self.uploaded = self.upload.start()
        self.addCleanup(self.upload.stop)
        templates.ensure_studio("animation")
        store.update_studio("animation", paused=False, veto_hours=2)

    def book(self, hhmm="18:15", day=DAY, topic="Why do cats purr", reserves=1):
        slots = [{"date": day, "time": hhmm, "brief": {"topic": topic}, "prediction": "above"}]
        slots += [{"reserve": True, "brief": {"topic": f"Spare topic number {i}"}} for i in range(reserves)]
        return store.add_slots("animation", slots)[0]

    def tick(self, when: datetime, *critic_replies, probe=None):
        return runner.tick(now=when, client=critic_client(*critic_replies), probe_fn=probe or probes(GOOD_LOG), reload=False)

    def slot(self, slot_id):
        return store.get_slot("animation", slot_id)

    def events(self, *types):
        return store.list_events("animation", types=types or None)


class TestGates(RunnerTestCase):
    def test_nothing_runs_while_disabled_or_paused(self):
        with patch.dict(config.studios, {"enabled": False}):
            self.assertFalse(self.tick(lagos(DAY, "08:00"))["ran"])
        with patch.dict(config.studios, {"paused": True}):
            self.assertIn("paused", self.tick(lagos(DAY, "08:00"))["reason"])
        store.set_paused("animation", True)
        self.assertEqual(self.tick(lagos(DAY, "08:00"))["studios"]["animation"], {"paused": True})


class TestProduceAndUpload(RunnerTestCase):
    def setUp(self):
        super().setUp()
        self.plan = patch.object(runner, "maybe_plan", return_value=None)
        self.plan.start()
        self.addCleanup(self.plan.stop)

    def test_a_video_is_made_waits_out_the_cancel_window_then_uploads_for_its_slot(self):
        slot = self.book()
        self.tick(lagos(DAY, "15:00"))
        ready = self.slot(slot["id"])
        self.assertEqual(ready["status"], model.SLOT_READY)
        self.assertTrue(ready["qa"]["ok"])
        project = anim_store.load_project(ready["project_id"])
        self.assertEqual((project["source"], project["brief"]["topic"], project["studio"]["slot_id"]), ("studio", "Why do cats purr", slot["id"]))
        self.assertEqual(project["seconds"], 35)  # the length lever's default
        self.assertEqual(project["costs"]["qa"], 0.003)  # the critic's cost lands on the video
        self.uploaded.assert_not_called()  # 16:45 is the upload time, and the window runs to 17:00

        self.tick(lagos(DAY, "16:50"))
        self.uploaded.assert_not_called()
        self.tick(lagos(DAY, "17:05"))
        self.assertEqual(self.uploaded.call_args.args[1], "2026-11-17T17:15:00Z")  # 18:15 Lagos
        done = self.slot(slot["id"])
        self.assertEqual((done["status"], done["youtube_video_id"]), (model.SLOT_UPLOADED, "vid00000001"))
        self.assertIn("goes public Tue 17 Nov 18:15", self.events("uploaded")[0]["summary"])

    def test_an_approved_video_skips_the_window_but_not_the_lead_time(self):
        slot = self.book()
        self.tick(lagos(DAY, "16:00"))
        store.update_slot("animation", slot["id"], veto_waived=True)
        self.tick(lagos(DAY, "16:30"))
        self.uploaded.assert_not_called()
        self.tick(lagos(DAY, "16:46"))
        self.uploaded.assert_called_once()

    def test_a_late_upload_publishes_soon_instead_of_in_the_past(self):
        slot = self.book()
        self.tick(lagos(DAY, "17:30"))  # made after its slot time
        self.tick(lagos(DAY, "19:31"))
        self.assertEqual(self.uploaded.call_args.args[1], "2026-11-17T18:46:00Z")
        self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_UPLOADED)

    def test_a_vetoed_video_never_uploads(self):
        slot = self.book()
        self.tick(lagos(DAY, "10:00"))
        store.update_slot("animation", slot["id"], status=model.SLOT_CANCELLED)
        self.tick(lagos(DAY, "18:00"))
        self.uploaded.assert_not_called()

    def test_qa_gets_one_fix(self):
        slot = self.book()
        with patch.object(pipeline, "reset_from", wraps=pipeline.reset_from) as reset:
            self.tick(lagos(DAY, "10:00"), probe=probes(GOOD_LOG + SILENT_GAP, GOOD_LOG))
        reset.assert_called_once()
        self.assertEqual(reset.call_args.args[1], "voice")
        self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_READY)
        self.assertTrue(self.events("qa_failed")[0]["data"]["retry"])

    def test_a_second_qa_failure_hands_the_slot_to_a_reserve(self):
        slot = self.book()
        claim = {"problems": [{"kind": "claim", "quote": "Nobody fully knows why", "why": "wrong"}]}
        self.tick(lagos(DAY, "10:00"), claim, claim)
        self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_FAILED)
        reserve = next(s for s in store.load_queue("animation") if s["id"] != slot["id"])
        self.assertEqual((reserve["reserve"], reserve["date"], reserve["time"], reserve["status"]), (False, DAY, "18:15", model.SLOT_PLANNED))
        self.assertIn("takes 2026-11-17 18:15", self.events("incident")[0]["summary"])
        self.tick(lagos(DAY, "11:00"))  # the reserve is made on the next tick
        self.assertEqual(self.slot(reserve["id"])["status"], model.SLOT_READY)

    def test_a_failed_render_is_retried_once_then_replaced(self):
        slot = self.book(reserves=0)

        def broken(pid, **_):
            return anim_store.update_project(pid, status=anim_store.STATUS_FAILED, error="Remotion crashed")

        with patch.object(pipeline, "run_project", side_effect=broken):
            self.tick(lagos(DAY, "08:00"))
            self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_PLANNED)
            self.tick(lagos(DAY, "09:00"))
        self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_FAILED)
        self.assertIn("No reserve left", self.events("incident")[0]["summary"])

    def test_a_slot_never_made_in_time_is_missed(self):
        slot = self.book("08:00")
        with patch.object(runner, "produce_due", return_value=[]):
            self.tick(lagos(DAY, "15:00"))
        self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_FAILED)
        self.assertIn("Missed", self.events("incident")[0]["summary"])

    def test_upload_errors_retry_then_give_up(self):
        slot = self.book()
        self.tick(lagos(DAY, "10:00"))
        self.uploaded.side_effect = RuntimeError("quotaExceeded")
        for hhmm in ("17:00", "17:10", "17:20"):
            self.tick(lagos(DAY, hhmm))
        self.assertEqual(self.slot(slot["id"])["status"], model.SLOT_FAILED)
        self.assertIn("Giving up", self.events("incident")[0]["summary"])

    def test_without_youtube_videos_wait_and_one_incident_a_day(self):
        self.book()
        self.tick(lagos(DAY, "10:00"))
        with patch.object(youtube_upload.youtube_upload_service, "is_configured", return_value=False):
            self.tick(lagos(DAY, "17:00"))
            self.tick(lagos(DAY, "18:00"))
        self.assertEqual(len([e for e in self.events("incident") if e["data"].get("key") == "youtube"]), 1)

    def test_the_weekly_budget_stops_production(self):
        store.update_studio("animation", weekly_budget_usd=0.5)
        first = self.book()
        self.tick(lagos(DAY, "10:00"))  # nothing spent yet: the first video fits
        anim_store.add_cost(self.slot(first["id"])["project_id"], "tts", 0.3)  # it cost $0.50 in all
        second = self.book("20:00", topic="How whales sleep")
        self.tick(lagos(DAY, "11:00"))
        self.assertEqual(self.slot(second["id"])["status"], model.SLOT_PLANNED)
        self.assertIn("budget", self.events("incident")[0]["summary"])

    def test_a_restart_mid_upload_never_uploads_twice(self):
        slot = self.book()
        self.tick(lagos(DAY, "10:00"))
        pid = self.slot(slot["id"])["project_id"]
        store.update_slot("animation", slot["id"], status=model.SLOT_UPLOADING)
        anim_store.update_project(pid, youtube_video_id="vidEarlier01", publish_at="2026-11-17T17:15:00Z")
        self.tick(lagos(DAY, "17:00"))
        self.uploaded.assert_not_called()
        self.assertEqual(self.slot(slot["id"])["youtube_video_id"], "vidEarlier01")

    def test_studio_videos_are_safe_from_the_storage_sweeper(self):
        slot = self.book()
        self.tick(lagos(DAY, "10:00"))
        self.assertIn(self.slot(slot["id"])["project_id"], store.active_project_ids())


class TestCheckins(RunnerTestCase):
    def test_three_and_seven_day_numbers_land_on_the_slot_and_timeline(self):
        slot = self.book()
        store.update_slot("animation", slot["id"], status=model.SLOT_PRODUCING)
        store.update_slot("animation", slot["id"], status=model.SLOT_READY)
        store.update_slot("animation", slot["id"], status=model.SLOT_UPLOADING)
        store.update_slot("animation", slot["id"], status=model.SLOT_UPLOADED, youtube_video_id="vidStudio01", publish_at="2026-11-17T17:15:00Z")
        published = datetime(2026, 11, 17, 17, 15, tzinfo=timezone.utc)
        rows = [{"video_id": f"h{i}", "studio": "animation", "published_at": published - timedelta(days=30 - i), "views_3d": 100.0} for i in range(10)]
        rows.append({"video_id": "vidStudio01", "studio": "animation", "published_at": published, "views_3d": 300.0, "views_7d": float("nan"), "title": "Why Do Cats Purr?"})
        df = pd.DataFrame(rows).assign(age_days=5.0, views=0, avg_view_pct=60.0)

        self.assertEqual(runner.record_checkins(store.load_studio("animation"), published + timedelta(days=2), df), [])
        runner.record_checkins(store.load_studio("animation"), published + timedelta(days=4), df)
        checkin = self.slot(slot["id"])["checkins"]["3d"]
        self.assertEqual((checkin["views"], checkin["outcome"], checkin["prediction_hit"]), (300.0, "above", True))
        self.assertIn("+198% vs baseline (above; predicted above)", self.events("result")[0]["summary"])

        runner.record_checkins(store.load_studio("animation"), published + timedelta(days=9), df)
        self.assertNotIn("7d", self.slot(slot["id"])["checkins"])  # no 7-day count yet: keep waiting
        runner.record_checkins(store.load_studio("animation"), published + timedelta(days=12), df)
        self.assertIsNone(self.slot(slot["id"])["checkins"]["7d"]["views"])  # gave up after the grace days


class TestPlanning(RunnerTestCase):
    def test_plans_on_the_first_tick_and_sundays_once_a_day(self):
        # timeline events carry the real clock, so these ticks are set relative to it
        now = datetime.now(timezone.utc)
        today = runner.local_date(now)
        weekday = next(now + timedelta(days=d) for d in range(1, 8) if (today + timedelta(days=d)).weekday() != 6)
        sunday = next(now + timedelta(days=d) for d in range(1, 8) if (today + timedelta(days=d)).weekday() == 6)
        with patch.object(planner, "run", return_value={"ok": False, "error": "x"}) as run:
            store.append_event("animation", "incident", "a failed plan", {"stage": "plan"})
            self.tick(now)  # the first tick, but planning already failed today
            run.assert_not_called()
            self.tick(now + timedelta(days=1))  # still never planned: try again the next day
            self.assertEqual(run.call_count, 1)
        store.append_event("animation", "plan", "a plan", {})
        with patch.object(planner, "run", return_value={"ok": True}) as run:
            self.tick(weekday)
            run.assert_not_called()
            self.tick(sunday)
            run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
