"""Animation scheduling against the shared 6-a-day YouTube upload budget."""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services import schedule as shorts_schedule  # noqa: E402
from app.services import upload_budget, youtube_upload  # noqa: E402
from app.services.animation import jobs, pipeline, store  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.documentary import doc_schedule  # noqa: E402


class ScheduleTestCase(unittest.TestCase):
    """Every calendar and the animation store live in a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name
        for target, attr, value in (
            (store, "animation_dir", lambda: root),
            (shorts_schedule, "_schedule_file", lambda: os.path.join(root, "shorts.json")),
            (doc_schedule, "_schedule_file", lambda: os.path.join(root, "docs.json")),
        ):
            patcher = patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.day = (date.today() + timedelta(days=3)).isoformat()

    def finished(self, topic="A video", aspect="9:16") -> str:
        project = store.create_project(topic, seconds=30, aspect=aspect, voice="en-GB-RyanNeural")
        pid = project["project_id"]
        os.makedirs(store.project_dir(pid), exist_ok=True)
        with open(store.final_path(pid), "wb") as f:
            f.write(b"fake mp4")
        store.update_project(
            pid, status=store.STATUS_DONE, duration=30.0,
            youtube={"title": f"{topic}!", "description": "desc\n\n#Shorts", "hashtags": ["#Shorts"], "tags": ["t"], "generated": True},
        )
        return pid


class TestSharedBudget(ScheduleTestCase):
    def test_counts_shorts_documentaries_and_animations_together(self):
        shorts_schedule.create_entry(date=self.day, topic="shorts batch", video_count=2)
        doc_schedule.create_entry(date=self.day, mode="auto", topic="a documentary")
        anim_schedule.create_entry(date=self.day, post_time="18:00", project_id=self.finished())
        load = upload_budget.daily_load(self.day)
        self.assertEqual((load["shorts"], load["documentaries"], load["animations"]), (2, 1, 1))
        self.assertEqual((load["total"], load["left"], load["full"]), (4, 2, False))
        # the documentary page's indicator sees animations too
        self.assertEqual(doc_schedule.daily_upload_load(self.day)["total"], 4)

    def test_a_full_day_refuses_another_animation(self):
        shorts_schedule.create_entry(date=self.day, topic="five shorts", video_count=5)
        anim_schedule.create_entry(date=self.day, post_time="18:00", project_id=self.finished("first"))
        with self.assertRaises(anim_schedule.BudgetError):
            anim_schedule.create_entry(date=self.day, post_time="20:00", project_id=self.finished("second"))
        self.assertEqual(upload_budget.daily_load(self.day)["total"], 6)

    def test_a_batch_that_overflows_is_rejected_whole(self):
        shorts_schedule.create_entry(date=self.day, topic="four shorts", video_count=4)
        items = [{"date": self.day, "post_time": t, "project_id": self.finished(t)} for t in ("09:00", "12:00", "15:00")]
        with self.assertRaises(anim_schedule.BudgetError):
            anim_schedule.create_entries(items)
        self.assertEqual(anim_schedule.list_entries(), [])  # all or nothing

    def test_batch_plan_only_uses_free_capacity(self):
        shorts_schedule.create_entry(date=self.day, topic="five shorts", video_count=5)
        items = [{"project_id": self.finished(f"v{i}")} for i in range(3)]
        evening_before = datetime.combine(date.fromisoformat(self.day) - timedelta(days=1), datetime.min.time()).replace(hour=20)
        plan = anim_schedule.plan_batch(items, per_day=2, start_date=self.day, now=evening_before)
        by_day: dict[str, int] = {}
        for item in plan["items"]:
            by_day[item["date"]] = by_day.get(item["date"], 0) + 1
        next_day = (date.fromisoformat(self.day) + timedelta(days=1)).isoformat()
        self.assertEqual(by_day, {self.day: 1, next_day: 2})  # 5 shorts leave room for 1
        self.assertEqual({i["post_time"] for i in plan["items"] if i["date"] == next_day}, set(shorts_schedule.even_slot_times(2)))
        anim_schedule.create_entries(plan["items"])  # and the plan books cleanly
        self.assertEqual(upload_budget.daily_load(self.day)["total"], 6)

    def test_marking_as_posted_frees_the_slot_and_blocks_rebooking(self):
        pid = self.finished()
        entry = anim_schedule.create_entry(date=self.day, post_time="18:00", project_id=pid)
        anim_schedule.mark_posted(pid, url="https://youtu.be/abc", posted_on=self.day)
        self.assertEqual(anim_schedule.get_entry(entry["id"])["status"], anim_schedule.STATUS_POSTED)
        self.assertEqual(upload_budget.daily_load(self.day)["animations"], 0)
        self.assertTrue(store.load_project(pid)["posted"]["manual"])
        with self.assertRaises(ValueError):
            anim_schedule.create_entry(date=self.day, post_time="19:00", project_id=pid)


class TestRunningEntries(ScheduleTestCase):
    def setUp(self):
        super().setUp()
        uploader = patch.object(
            youtube_upload.youtube_upload_service, "upload_video", return_value={"success": True, "video_id": "VID123"}
        )
        self.upload = uploader.start()
        self.addCleanup(uploader.stop)

    def test_due_library_entry_uploads_with_its_publish_time(self):
        pid = self.finished("Tower", aspect="16:9")
        with open(store.thumb_path(pid), "wb") as f:
            f.write(b"jpg")
        entry = anim_schedule.create_entry(date=self.day, post_time="18:00", project_id=pid)
        with patch("app.services.discord_notify.discord_notify_service.notify_video_ready"):
            result = anim_schedule.run_due_entries(run_date=self.day)
        self.assertEqual(result, {"skipped": False, "ran": 1})
        done = anim_schedule.get_entry(entry["id"])
        self.assertEqual((done["status"], done["youtube_video_id"]), (anim_schedule.STATUS_SCHEDULED, "VID123"))
        kwargs = self.upload.call_args.kwargs
        self.assertEqual(kwargs["title"], "Tower!")
        self.assertTrue(kwargs["publish_at"].startswith(self.day[:4]))
        self.assertEqual(kwargs["thumbnail_path"], store.thumb_path(pid))  # 16:9 gets its thumbnail
        self.assertEqual(store.load_project(pid)["youtube_video_id"], "VID123")

    def test_auto_entry_generates_before_uploading(self):
        def fake_run(project_id, **_):
            with open(store.final_path(project_id), "wb") as f:
                f.write(b"mp4")
            return store.update_project(
                project_id, status=store.STATUS_DONE, youtube={"title": "Made on the day", "description": "", "tags": [], "generated": True}
            )

        anim_schedule.create_entry(date=self.day, post_time="18:00", topic="Why octopuses have three hearts", seconds=30, aspect="9:16")
        with patch.object(pipeline, "run_project", side_effect=fake_run), patch(
            "app.services.discord_notify.discord_notify_service.notify_video_ready"
        ):
            anim_schedule.run_due_entries(run_date=self.day)
        entry = anim_schedule.list_entries()[0]
        self.assertEqual(entry["status"], anim_schedule.STATUS_SCHEDULED)
        project = store.load_project(entry["project_id"])
        self.assertEqual((project["source"], project["topic"]), ("schedule", "Why octopuses have three hearts"))
        self.assertIsNone(self.upload.call_args.kwargs["thumbnail_path"])  # Shorts use a frame, not a custom thumbnail

    def test_failed_upload_marks_the_entry_failed_for_a_retry(self):
        self.upload.return_value = {"success": False, "error": "quota exceeded"}
        entry = anim_schedule.create_entry(date=self.day, post_time="18:00", project_id=self.finished())
        anim_schedule.run_due_entries(run_date=self.day)
        failed = anim_schedule.get_entry(entry["id"])
        self.assertEqual(failed["status"], anim_schedule.STATUS_FAILED)
        self.assertIn("quota", failed["error"])
        self.assertEqual(upload_budget.daily_load(self.day)["animations"], 0)  # failed entries free their slot
        anim_schedule.reset_entry(entry["id"])
        self.assertEqual(anim_schedule.get_entry(entry["id"])["status"], anim_schedule.STATUS_PENDING)


class TestJobRecovery(ScheduleTestCase):
    """After an app restart the queue is gone but project state is on disk."""

    def test_recovers_only_work_no_live_process_owns(self):
        owned = store.create_project("queued by another live app", voice="x")
        store.update_project(owned["project_id"], worker_pid=1)  # pid 1 is always alive
        orphan = store.create_project("queued by a process that died", voice="x")
        store.update_project(orphan["project_id"], worker_pid=999999)
        crashed = store.create_project("rendering when its process died", voice="x")
        store.update_project(crashed["project_id"], status=store.STATUS_RENDERING, worker_pid=999999)
        requeued = []
        with patch.object(jobs, "enqueue", requeued.extend):
            jobs.recover()
        self.assertEqual(requeued, [orphan["project_id"]])
        self.assertEqual(store.load_project(owned["project_id"])["status"], store.STATUS_QUEUED)
        self.assertEqual(store.load_project(crashed["project_id"])["status"], store.STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
