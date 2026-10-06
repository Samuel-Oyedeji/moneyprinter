"""Daily storage clean-up: what goes, what stays, and when."""
import os
import sys
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services import cache_manager, sweeper  # noqa: E402
from app.services import schedule as shorts_schedule  # noqa: E402
from app.services.analytics import catalog  # noqa: E402
from app.services.analytics import store as analytics_store  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.animation import store as anim_store  # noqa: E402
from app.services.documentary import doc_schedule  # noqa: E402
from app.services.documentary import store as doc_store  # noqa: E402
from app.utils import utils  # noqa: E402
from test.services.test_analytics import StorageTestCase, video  # noqa: E402

DAY = 86400


def age(path: str, days: float) -> None:
    """Backdate every file under ``path``."""
    stamp = time.time() - days * DAY
    targets = [path] if os.path.isfile(path) else [os.path.join(r, n) for r, _, files in os.walk(path) for n in files]
    for target in targets:
        os.utime(target, (stamp, stamp))


def ago(days: float) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


class SweeperTestCase(StorageTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch.dict(sweeper.config.sweeper, {"enabled": True, "posted_days": 7, "unposted_days": 30, "cache_days": 7}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def short(self, subject, days_old, finals=1, posted_days_ago=None):
        task_id, paths = self.generator_short(subject, finals=finals)
        age(os.path.dirname(paths[0]), days_old)
        if posted_days_ago is not None:
            for path in paths:
                analytics_store.mark_posted(f"shorts:{task_id}/{os.path.basename(path)}", posted_on=ago(posted_days_ago))
        return task_id

    def animation(self, topic, days_old, posted_days_ago=None):
        pid = self.finished_animation(topic)
        os.makedirs(anim_store.path(pid, "public"), exist_ok=True)
        with open(anim_store.path(pid, "public/narration.mp3"), "wb") as f:
            f.write(b"mp3")
        anim_store.update_project(pid, created_at=time.time() - days_old * DAY)
        if posted_days_ago is not None:
            anim_store.mark_posted(pid, posted_on=ago(posted_days_ago))
        age(anim_store.project_dir(pid), days_old)
        return pid

    def swept_keys(self):
        return {v["key"].split(":", 1)[0] + ":" + v["key"].split(":", 1)[1].split("/")[0] for v in sweeper.plan()["videos"]}


class TestShorts(SweeperTestCase):
    def test_posted_and_unposted_rules(self):
        posted_old = self.short("posted long ago", 12, posted_days_ago=10)
        posted_new = self.short("posted recently", 12, posted_days_ago=3)
        unposted_old = self.short("never posted, old", 40)
        unposted_new = self.short("never posted, new", 10)
        failed = utils.task_dir("failed-run")
        with open(os.path.join(failed, "audio.mp3"), "wb") as f:
            f.write(b"x")
        age(failed, 40)

        keys = self.swept_keys()
        self.assertIn(f"shorts:{posted_old}", keys)
        self.assertIn(f"shorts:{unposted_old}", keys)
        self.assertIn("shorts:failed-run", keys)
        self.assertNotIn(f"shorts:{posted_new}", keys)
        self.assertNotIn(f"shorts:{unposted_new}", keys)

    def test_app_upload_counts_as_posted_on_the_publish_day(self):
        task_id = self.short("calendar video", 20)
        [path] = [os.path.join(utils.task_dir(task_id), "final-1.mp4")]
        entry = shorts_schedule.create_entry(date=ago(20), topic="calendar video")
        shorts_schedule._patch_entry(entry["id"], status="done", uploads=[{"path": path, "video_id": "vid00000001", "title": "t"}])
        # without a channel listing: uploaded when made, 20 days ago
        self.assertIn(f"shorts:{task_id}", self.swept_keys())
        # with one: a video scheduled to go public 2 days ago is 2 days posted
        analytics_store.save_channel({}, [{**video("vid00000001", "t", published=time.time() - 20 * DAY), "publish_at": f"{ago(2)}T10:00:00Z"}])
        self.assertNotIn(f"shorts:{task_id}", self.swept_keys())

    def test_hand_post_matched_by_title_counts(self):
        task_id = self.short("Honey never spoils", 20)
        analytics_store.save_channel({}, [video("vid00000001", "Honey never spoils", published=time.time() - 9 * DAY)])
        self.assertIn(f"shorts:{task_id}", self.swept_keys())

    def test_failed_upload_and_busy_runs_are_protected(self):
        task_id = self.short("upload failed", 40)
        path = os.path.join(utils.task_dir(task_id), "final-1.mp4")
        entry = shorts_schedule.create_entry(date=ago(40), topic="upload failed")
        shorts_schedule._patch_entry(entry["id"], status="failed", uploads=[{"path": path, "video_id": "", "title": ""}])
        busy = self.short("generating", 40)
        other = shorts_schedule.create_entry(date=ago(40), topic="generating")
        shorts_schedule._patch_entry(other["id"], status="generating", task_ids=[busy])
        keys = self.swept_keys()
        self.assertNotIn(f"shorts:{task_id}", keys)
        self.assertNotIn(f"shorts:{busy}", keys)

    def test_recent_activity_and_partly_posted_variants_are_kept(self):
        touched = self.short("posted but touched today", 12, posted_days_ago=10)
        age(utils.task_dir(touched), 0)
        variants, _ = self.generator_short("three variants", finals=2)
        age(utils.task_dir(variants), 12)
        analytics_store.mark_posted(f"shorts:{variants}/final-1.mp4", posted_on=ago(10))
        keys = self.swept_keys()
        self.assertNotIn(f"shorts:{touched}", keys)
        self.assertNotIn(f"shorts:{variants}", keys)  # final-2 never posted, 12 < 30 days


class TestStudios(SweeperTestCase):
    def test_animation_heavy_files_go_details_stay(self):
        pid = self.animation("Fox", 15, posted_days_ago=9)
        sweeper.run()
        self.assertFalse(os.path.exists(anim_store.final_path(pid)))
        self.assertFalse(os.path.exists(anim_store.path(pid, "public")))
        project = anim_store.load_project(pid)
        self.assertEqual(project["status"], anim_store.STATUS_DONE)
        self.assertTrue(project["files_swept_at"])
        # gone from the library, still known to analytics
        self.assertNotIn(pid, [p["project_id"] for p in anim_store.finished_projects()])
        self.assertIn(f"animation:{pid}", {i["key"] for i in catalog.build_items()})

    def test_booked_and_unfinished_animations_are_kept(self):
        booked = self.animation("Booked", 40)
        anim_schedule.create_entry(date=(date.today() + timedelta(days=2)).isoformat(), post_time="18:00", project_id=booked)
        unfinished = anim_store.create_project("Still rendering")
        anim_store.update_project(unfinished["project_id"], status=anim_store.STATUS_RENDERING, created_at=time.time() - 60 * DAY)
        keys = self.swept_keys()
        self.assertNotIn(f"animation:{booked}", keys)
        self.assertNotIn(f"animation:{unfinished['project_id']}", keys)

    def test_documentary_render_and_images_go_thumbnail_and_script_stay(self):
        pid = self.finished_documentary()
        render = utils.task_dir(pid)
        for name in ("final-1.mp4", "thumbnail.jpg", "narration.mp3"):
            with open(os.path.join(render, name), "wb") as f:
                f.write(b"x")
        images = doc_store.images_dir(pid)
        with open(os.path.join(images, "1.jpg"), "wb") as f:
            f.write(b"x")
        project = doc_store.load_project(pid)
        project["created_at"] = time.time() - 40 * DAY
        doc_store.save_project(project)
        age(render, 40)
        age(images, 40)

        busy = self.finished_documentary(topic="Booked film")
        with open(os.path.join(utils.task_dir(busy), "final-1.mp4"), "wb") as f:
            f.write(b"x")
        age(utils.task_dir(busy), 40)
        doc_schedule.create_entry(date=(date.today() + timedelta(days=1)).isoformat(), mode="library", project_id=busy)

        sweeper.run()
        self.assertEqual(sorted(os.listdir(render)), ["thumbnail.jpg"])
        self.assertFalse(os.path.exists(images))
        self.assertIsNotNone(doc_store.load_script(pid))
        self.assertTrue(doc_store.load_project(pid)["files_swept_at"])
        self.assertTrue(os.path.isfile(os.path.join(utils.task_dir(busy), "final-1.mp4")))


class TestRunning(SweeperTestCase):
    def test_dry_run_deletes_nothing_and_run_logs_everything(self):
        task_id = self.short("old one", 40)
        folder = utils.task_dir(task_id)
        with patch.object(cache_manager, "clean_video_cache", wraps=cache_manager.clean_video_cache) as clean:
            preview = sweeper.run(dry_run=True)
            self.assertTrue(preview["dry_run"])
            self.assertEqual(len(preview["videos"]), 1)
            self.assertTrue(os.path.isdir(folder))
            clean.assert_not_called()

            result = sweeper.run()
            clean.assert_called_once_with(max_age_days=7)
        self.assertEqual(result["videos_swept"], 1)
        self.assertGreater(result["video_bytes_freed"], 0)
        self.assertFalse(os.path.exists(folder))
        with open(os.path.join(utils.storage_dir("sweeper"), "log.csv"), encoding="utf-8-sig") as f:
            log = f.read()
        self.assertIn("never posted", log)
        self.assertIn(f"tasks/{task_id}", log)
        # the registry kept it for analytics
        self.assertIn(f"shorts:{task_id}/final-1.mp4", analytics_store.load_registry())
        self.assertEqual(sweeper.run()["videos_swept"], 0)

    def test_cache_files_older_than_cache_days_go(self):
        cache = utils.storage_dir("cache_videos", create=True)
        old, new = (os.path.join(cache, f"vid-{c * 32}.mp4") for c in "ab")
        for path in (old, new):
            with open(path, "wb") as f:
                f.write(b"clip")
        age(old, 8)
        with patch.object(cache_manager, "video_cache_dir", return_value=os.path.realpath(cache)):
            self.assertEqual(sweeper.plan()["cache_files"], 1)
            self.assertEqual(sweeper.run()["cache_files_deleted"], 1)
        self.assertEqual(os.listdir(cache), [os.path.basename(new)])

    def test_settings_and_the_off_switch(self):
        with patch.dict(sweeper.config.sweeper, {"enabled": False, "posted_days": "0"}):
            self.assertEqual(sweeper.settings()["posted_days"], 1)  # never "delete the moment it's posted"
            self.assertIsNone(sweeper.run_scheduled())
        with patch.object(sweeper, "run", return_value={"ok": 1}) as run:
            self.assertEqual(sweeper.run_scheduled(), {"ok": 1})
        run.assert_called_once()

    def test_api_preview_shows_paths_relative_to_storage(self):
        from fastapi.testclient import TestClient

        from app.asgi import app

        task_id = self.short("old one", 40)
        data = TestClient(app).get("/api/v1/sweeper/preview").json()["data"]
        self.assertEqual(data["videos"][0]["paths"], [os.path.join("tasks", task_id)])
        self.assertTrue(os.path.isdir(utils.task_dir(task_id)))


if __name__ == "__main__":
    unittest.main()
