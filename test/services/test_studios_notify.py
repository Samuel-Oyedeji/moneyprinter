"""Discord alerts, the daily digest and the tick heartbeat (WP6). Discord is mocked."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import config  # noqa: E402
from app.services import discord_notify  # noqa: E402
from app.services import schedule as shorts_schedule  # noqa: E402
from app.services.studios import model, notify, runner, store, templates  # noqa: E402
from app.utils import utils  # noqa: E402


class NotifyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name

        def storage_dir(sub_dir: str = "", create: bool = False):
            d = os.path.join(root, sub_dir)
            if create:
                os.makedirs(d, exist_ok=True)
            return d

        self.sent = []
        patchers = [
            patch.object(utils, "storage_dir", storage_dir),
            patch.object(shorts_schedule, "_schedule_file", lambda: os.path.join(root, "shorts.json")),
            patch.dict(config.studios, {"enabled": True, "paused": False, "app_url": "https://mpt.example.com/"}),
            patch.dict(config.youtube, {"publish_timezone": "Africa/Lagos"}),
            patch.object(discord_notify.DiscordNotifyService, "is_configured", return_value=True),
            patch.object(discord_notify.DiscordNotifyService, "send", side_effect=lambda content, embed=None: self.sent.append((content, embed)) or True),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.studio = templates.ensure_studio("animation")
        self.now = datetime.now(timezone.utc)  # timeline events carry the real clock

    def ready_slot(self, hours_ahead=20):
        when = (self.now + timedelta(hours=hours_ahead)).astimezone(runner.local_tz())
        slot = store.add_slots("animation", [{"date": when.strftime("%Y-%m-%d"), "time": "12:00", "brief": {"topic": "Why do cats purr"}}])[0]
        store.update_slot("animation", slot["id"], status=model.SLOT_PRODUCING)
        return store.update_slot("animation", slot["id"], status=model.SLOT_READY, ready_at=self.now.timestamp())


class TestAlerts(NotifyTestCase):
    def test_the_first_flush_only_sets_the_mark(self):
        store.append_event("animation", "incident", "An old problem")
        self.assertEqual(notify.flush(self.studio, self.now), 0)
        self.assertEqual(self.sent, [])

    def test_problems_and_ready_videos_are_sent_and_retries_are_not(self):
        notify.flush(self.studio, self.now)
        slot = self.ready_slot()
        store.append_event("animation", "qa_failed", "Silence: fixing (voice)", {"retry": True})
        store.append_event("animation", "produced", "Ready: \"Why Cats Purr\" for tomorrow. It uploads once the 12h cancel window is over.", {"slot_id": slot["id"]})
        store.append_event("animation", "incident", "Upload failed: quotaExceeded")
        self.assertEqual(notify.flush(self.studio, self.now), 2)
        content, embed = self.sent[0]
        self.assertIn("Paper Explainers", content)
        self.assertIn("🎬 Ready: \"Why Cats Purr\" for tomorrow. Cancel before", embed["description"])
        self.assertIn("⚠️ Upload failed: quotaExceeded", embed["description"])
        self.assertNotIn("fixing", embed["description"])
        self.assertIn("(https://mpt.example.com/Studios)", embed["description"])
        self.assertEqual(notify.flush(self.studio, self.now), 0)  # nothing twice

    def test_ready_pings_can_be_turned_off(self):
        notify.flush(self.studio, self.now)
        slot = self.ready_slot()
        store.append_event("animation", "produced", "Ready: x. It uploads once…", {"slot_id": slot["id"]})
        with patch.dict(config.studios, {"notify_ready": False}):
            self.assertEqual(notify.flush(self.studio, self.now), 0)


class TestDigest(NotifyTestCase):
    def at_local(self, hour):
        return datetime.now(runner.local_tz()).replace(hour=hour, minute=5).astimezone(timezone.utc)

    def test_once_a_day_from_seven(self):
        self.ready_slot()
        self.assertFalse(notify.send_digest(self.at_local(6)))
        self.assertTrue(notify.send_digest(self.at_local(7)))
        self.assertFalse(notify.send_digest(self.at_local(9)))
        content, embed = self.sent[0]
        self.assertIn("📋 Studios", content)
        self.assertIn("⏳ Waiting: 'Why do cats purr'", embed["description"])
        self.assertIn("💵 This week: $0.00 of $10", embed["description"])
        self.assertIn("No tick has run yet.", embed["description"])

    def test_the_digest_lists_problems_and_check_ins(self):
        store.append_event("animation", "incident", "Dropped \"Owls\" (failed QA)")
        store.append_event("animation", "result", "3d check-in: \"Cats\" has 1,240 views, +38% vs baseline", {"kind": "checkin"})
        lines = notify.digest_lines(self.studio, self.now)
        self.assertIn("📈 3d check-in: \"Cats\" has 1,240 views, +38% vs baseline", lines)
        self.assertTrue(any(line.startswith("⚠️ 1 problem(s)") for line in lines))


class TestHeartbeat(NotifyTestCase):
    def test_a_silent_tick_is_reported_once(self):
        notify.record_tick(self.now - timedelta(hours=5))
        self.assertTrue(notify.check_heartbeat(self.now))
        self.assertFalse(notify.check_heartbeat(self.now + timedelta(hours=1)))
        self.assertIn("stopped", self.sent[0][0])

    def test_no_alarm_when_studios_are_off_or_ticking(self):
        notify.record_tick(self.now - timedelta(hours=5))
        with patch.dict(config.studios, {"enabled": False}):
            self.assertFalse(notify.check_heartbeat(self.now))
        notify.record_tick(self.now - timedelta(hours=1))
        self.assertFalse(notify.check_heartbeat(self.now))

    def test_the_tick_coming_back_is_reported(self):
        notify.record_tick(self.now - timedelta(hours=6))
        notify.record_tick(self.now)
        self.assertIn("running again", self.sent[-1][0])

    def test_a_tick_flushes_records_and_digests(self):
        store.update_studio("animation", paused=False)
        with patch.object(runner, "_sync_analytics"), patch.object(runner, "maybe_plan", return_value=None):
            runner.tick(now=self.now, reload=False)
            store.append_event("animation", "incident", "Something broke")
            runner.tick(now=self.now, reload=False)
        self.assertTrue(any("Something broke" in (embed or {}).get("description", "") for _, embed in self.sent))
        self.assertAlmostEqual(notify.load_state()["last_tick"], self.now.timestamp())


if __name__ == "__main__":
    unittest.main()
