"""Re-uploading a scheduled entry whose videos rendered but never reached YouTube.

The case this covers: the daily YouTube quota (6 uploads) runs out after the
video is already built. Finishing the entry must cost one ``videos.insert``,
not a whole regeneration - and must never send a video that already has an id.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services import discord_notify, llm, youtube_upload  # noqa: E402
from app.services import schedule as schedule_service  # noqa: E402


class FakeUploader:
    """Stands in for YoutubeUploadService, with a daily quota that runs out."""

    def __init__(self, quota: int = 99):
        self.quota = quota
        self.calls = []
        self._issued = 0

    def upload_video(self, video_path, title, description, tags,
                     thumbnail_path=None, publish_at=None):
        self.calls.append(os.path.basename(video_path))
        if len(self.calls) > self.quota:
            return {
                "success": False,
                "error": "YouTube API error: 403 quotaExceeded",
            }
        self._issued += 1
        return {"success": True, "video_id": f"vid{self._issued}"}


class FakeNotifier:
    def __init__(self):
        self.ready = 0
        self.failures = 0

    def notify_video_ready(self, **kwargs):
        self.ready += 1

    def notify_failure(self, *args, **kwargs):
        self.failures += 1


class ReuploadTestCase(unittest.TestCase):
    """Each test gets its own schedule.json and task directory."""

    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.store_path = os.path.join(self._temp_dir.name, "schedule.json")
        self.task_id = "task-under-test"
        self.task_dir = os.path.join(self._temp_dir.name, "tasks", self.task_id)
        os.makedirs(self.task_dir)

        self.uploader = FakeUploader()
        self.notifier = FakeNotifier()
        self.metadata_calls = 0

        def fake_metadata(**kwargs):
            self.metadata_calls += 1
            return {
                "title": f"Title {self.metadata_calls}",
                "caption": "a caption",
                "hashtags": ["#lagos"],
            }

        for target, replacement in (
            ("_schedule_file", lambda: self.store_path),
            ("_extract_thumbnail", lambda video_path, output_path: None),
        ):
            patcher = patch.object(schedule_service, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

        # 旧条目的成片要靠 task_dir 从磁盘找回，测试里指向临时目录。
        patcher = patch.object(
            schedule_service.utils,
            "task_dir",
            lambda sub_dir="": os.path.join(self._temp_dir.name, "tasks", sub_dir),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # 被测函数用 ``from app.services import llm`` 在调用点内部导入，
        # 那取的是包属性，替换 sys.modules 条目拦不住（真会打到网络上）。
        # 因此直接给真实模块打桩。
        for module, attribute, replacement in (
            (youtube_upload, "youtube_upload_service", self.uploader),
            (discord_notify, "discord_notify_service", self.notifier),
            (llm, "generate_social_metadata", fake_metadata),
        ):
            patcher = patch.object(module, attribute, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _render_videos(self, count: int) -> list[str]:
        """Put `count` finished videos and their script on disk."""
        paths = []
        for index in range(1, count + 1):
            path = os.path.join(self.task_dir, f"final-{index}.mp4")
            with open(path, "wb") as f:
                f.write(b"not really an mp4")
            paths.append(path)
        with open(os.path.join(self.task_dir, "script.json"), "w") as f:
            json.dump({"script": "the narration", "params": {}}, f)
        return paths

    def _entry_ready_to_upload(self, video_count: int = 3) -> dict:
        """An entry whose generation stage finished, sitting at the upload stage."""
        entry = schedule_service.create_entry(
            date="2026-09-11", topic="Lagos floods", video_count=video_count
        )
        schedule_service._patch_entry(
            entry["id"],
            task_ids=[self.task_id],
            status=schedule_service.STATUS_UPLOADING,
            uploads=schedule_service._build_upload_records(
                self._render_videos(video_count)
            ),
        )
        return schedule_service.get_entry(entry["id"])

    def _run_upload_stage(self, entry: dict) -> dict:
        result = schedule_service._upload_pending_videos(entry)
        schedule_service._finish_upload_stage(
            schedule_service.get_entry(entry["id"]), result
        )
        return schedule_service.get_entry(entry["id"])


class TestUploadStageFailure(ReuploadTestCase):
    def test_quota_failure_is_recorded_as_an_upload_stage_failure(self):
        self.uploader.quota = 0
        entry = self._run_upload_stage(self._entry_ready_to_upload())

        self.assertEqual(entry["status"], schedule_service.STATUS_FAILED)
        self.assertEqual(entry["failed_stage"], schedule_service.STAGE_UPLOAD)
        self.assertIn("quotaExceeded", entry["error"])
        self.assertEqual(self.notifier.failures, 1)

    def test_upload_stage_failure_can_be_finished_without_regenerating(self):
        self.uploader.quota = 0
        entry = self._run_upload_stage(self._entry_ready_to_upload())
        self.assertTrue(schedule_service.can_reupload(entry))
        self.assertEqual(len(schedule_service.pending_uploads(entry)), 3)

    def test_generation_stage_failure_is_not_offered_a_reupload(self):
        entry = schedule_service.create_entry(date="2026-09-11", topic="Broken")
        schedule_service._patch_entry(
            entry["id"],
            status=schedule_service.STATUS_FAILED,
            failed_stage=schedule_service.STAGE_GENERATE,
            error="script generation failed",
        )
        self.assertFalse(
            schedule_service.can_reupload(schedule_service.get_entry(entry["id"]))
        )

    def test_a_deleted_video_file_is_not_offered_a_reupload(self):
        self.uploader.quota = 0
        entry = self._run_upload_stage(self._entry_ready_to_upload(video_count=1))
        os.remove(entry["uploads"][0]["path"])
        self.assertFalse(
            schedule_service.can_reupload(schedule_service.get_entry(entry["id"]))
        )


class TestReupload(ReuploadTestCase):
    def test_reupload_finishes_the_entry_without_touching_generation(self):
        self.uploader.quota = 0
        entry = self._run_upload_stage(self._entry_ready_to_upload())
        self.uploader.quota = 99
        self.uploader.calls.clear()

        entry = schedule_service.reupload_entry(entry["id"])

        self.assertEqual(entry["status"], schedule_service.STATUS_DONE)
        self.assertEqual(entry["failed_stage"], "")
        self.assertEqual(len(entry["youtube_video_ids"]), 3)
        self.assertEqual(len(self.uploader.calls), 3)

    def test_a_partial_upload_never_sends_the_same_video_twice(self):
        """Quota dying halfway must not duplicate what is already on the channel."""
        self.uploader.quota = 2
        entry = self._run_upload_stage(self._entry_ready_to_upload())
        self.assertEqual(entry["status"], schedule_service.STATUS_FAILED)
        self.assertEqual(entry["youtube_video_ids"], ["vid1", "vid2"])

        self.uploader.quota = 99
        self.uploader.calls.clear()
        entry = schedule_service.reupload_entry(entry["id"])

        self.assertEqual(entry["status"], schedule_service.STATUS_DONE)
        self.assertEqual(self.uploader.calls, ["final-3.mp4"])
        self.assertEqual(entry["youtube_video_ids"], ["vid1", "vid2", "vid3"])

    def test_metadata_is_written_once_and_reused_on_every_retry(self):
        """A retry must not re-run the LLM or republish under a different title."""
        self.uploader.quota = 0
        entry = self._run_upload_stage(self._entry_ready_to_upload())
        self.assertEqual(self.metadata_calls, 3)

        self.uploader.quota = 99
        schedule_service.reupload_entry(entry["id"])
        self.assertEqual(self.metadata_calls, 3)

    def test_reupload_is_refused_when_everything_is_already_uploaded(self):
        entry = self._run_upload_stage(self._entry_ready_to_upload(video_count=1))
        self.assertEqual(entry["status"], schedule_service.STATUS_DONE)
        with self.assertRaises(ValueError):
            schedule_service.reupload_entry(entry["id"])

    def test_legacy_entry_without_upload_records_recovers_them_from_disk(self):
        """Entries that failed before `uploads` existed are still re-uploadable."""
        self._render_videos(2)
        entry = schedule_service.create_entry(date="2026-09-11", topic="Old one")
        schedule_service._patch_entry(
            entry["id"],
            status=schedule_service.STATUS_FAILED,
            task_ids=[self.task_id],
            error="quota exceeded",
        )
        entry = schedule_service.get_entry(entry["id"])
        entry.pop("uploads", None)

        self.assertEqual(len(schedule_service.upload_records(entry)), 2)
        self.assertTrue(schedule_service.can_reupload(entry))


class TestRebuild(ReuploadTestCase):
    def test_rebuilding_clears_the_upload_plan_but_keeps_uploaded_ids(self):
        """The orphan left on the channel by a rebuild must stay traceable."""
        self.uploader.quota = 1
        entry = self._run_upload_stage(self._entry_ready_to_upload(video_count=2))
        self.assertEqual(entry["youtube_video_ids"], ["vid1"])

        entry = schedule_service.update_entry(
            entry["id"], status=schedule_service.STATUS_PENDING
        )

        self.assertEqual(entry["uploads"], [])
        self.assertEqual(entry["failed_stage"], "")
        self.assertEqual(entry["youtube_video_ids"], ["vid1"])


class TestStaleRecovery(ReuploadTestCase):
    def test_an_entry_stuck_mid_upload_recovers_as_an_upload_failure(self):
        entry = self._entry_ready_to_upload(video_count=1)
        stale = "2020-01-01T00:00:00+00:00"
        schedule_service._patch_entry(entry["id"])
        # _patch_entry 会刷新 updated_at，因此直接改写存储里的时间戳。
        with open(self.store_path, encoding="utf-8") as f:
            data = json.load(f)
        data["entries"][0]["updated_at"] = stale
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        schedule_service.recover_stale_entries()
        entry = schedule_service.get_entry(entry["id"])

        self.assertEqual(entry["status"], schedule_service.STATUS_FAILED)
        self.assertEqual(entry["failed_stage"], schedule_service.STAGE_UPLOAD)
        self.assertTrue(schedule_service.can_reupload(entry))


if __name__ == "__main__":
    unittest.main()
