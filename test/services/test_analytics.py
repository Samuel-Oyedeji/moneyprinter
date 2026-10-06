"""YouTube analytics: catalog, reconciliation, posted marks, sync and reports."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services import schedule as shorts_schedule  # noqa: E402
from app.services import upload_budget, youtube_upload  # noqa: E402
from app.services.analytics import catalog, reconcile, report, sync, topics, youtube_api  # noqa: E402
from app.services.analytics import store as analytics_store  # noqa: E402
from app.services.animation import schedule as anim_schedule  # noqa: E402
from app.services.animation import store as anim_store  # noqa: E402
from app.services.documentary import doc_schedule  # noqa: E402
from app.services.documentary import store as doc_store  # noqa: E402
from app.utils import utils  # noqa: E402


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def video(video_id, title, published=None, views=0, privacy="public", duration=40):
    return {
        "video_id": video_id,
        "title": title,
        "published_at": _iso(published or time.time()),
        "privacy_status": privacy,
        "publish_at": "",
        "duration_seconds": duration,
        "views": views,
        "likes": views // 20,
        "comments": views // 100,
        "thumbnail": "",
    }


def item(key, titles, created_at=None, studio="animation", **extra):
    return {
        "key": key,
        "studio": studio,
        "topic": titles[-1] if titles else "",
        "titles": titles,
        "created_at": created_at if created_at is not None else time.time() - 3600,
        "batch_id": "",
        "known_video_ids": [],
        "posted": {},
        "features": {},
        **extra,
    }


class StorageTestCase(unittest.TestCase):
    """Every store (calendars, studios, analytics, tasks) in a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

        def storage_dir(sub_dir="", create=False):
            d = os.path.join(self.root, sub_dir) if sub_dir else self.root
            if create:
                os.makedirs(d, exist_ok=True)
            return d

        patcher = patch.object(utils, "storage_dir", storage_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.day = (date.today() + timedelta(days=3)).isoformat()

    def finished_animation(self, topic="A video", title=None, board=None, **create):
        project = anim_store.create_project(topic, seconds=30, aspect="9:16", voice="en-GB-RyanNeural", **create)
        pid = project["project_id"]
        with open(anim_store.final_path(pid), "wb") as f:
            f.write(b"fake mp4")
        if board is not None:
            anim_store.write_json(anim_store.path(pid, "storyboard.json"), board)
        anim_store.update_project(pid, status=anim_store.STATUS_DONE, youtube={"title": title or f"{topic}!", "generated": True})
        return pid

    def finished_documentary(self, topic="A film", title="The Film"):
        project = doc_store.create_project(topic=topic, target_minutes=8)
        doc_store.save_script(project["project_id"], {"title": topic, "word_count": 1200, "youtube": {"title": title}})
        project["status"] = doc_store.STATUS_DONE
        doc_store.save_project(project)
        return project["project_id"]

    def generator_short(self, subject, finals=1, task_id=None):
        task_id = task_id or utils.get_uuid()
        task_dir = utils.task_dir(task_id)
        with open(os.path.join(task_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump({"script": f"All about {subject}.", "params": {"video_subject": subject, "video_aspect": "9:16", "video_source": "pexels", "voice_name": "en-US-AvaNeural"}}, f)
        paths = []
        for n in range(1, finals + 1):
            path = os.path.join(task_dir, f"final-{n}.mp4")
            with open(path, "wb") as f:
                f.write(b"fake")
            paths.append(path)
        return task_id, paths


# ------------------------------------------------------------------ reconcile
class TestTitleNormalization(unittest.TestCase):
    def test_ignores_case_punctuation_emoji_hashtags_and_part_suffix(self):
        self.assertEqual(
            reconcile.normalize_title("Why Octopuses Have 3 Hearts?! 🐙 #shorts #facts (2/3)"),
            reconcile.normalize_title("why octopuses have 3 hearts"),
        )

    def test_keeps_words_and_numbers(self):
        self.assertNotEqual(reconcile.normalize_title("Top 5 facts"), reconcile.normalize_title("Top 6 facts"))

    def test_video_id_from_any_url(self):
        for url in (
            "https://youtu.be/abcdefghijk",
            "https://www.youtube.com/watch?v=abcdefghijk&t=3",
            "https://youtube.com/shorts/abcdefghijk",
            "https://studio.youtube.com/video/abcdefghijk/edit",
            "abcdefghijk",
        ):
            self.assertEqual(reconcile.video_id_from_url(url), "abcdefghijk", url)
        self.assertEqual(reconcile.video_id_from_url("https://example.com"), "")


class TestReconcile(unittest.TestCase):
    def test_app_uploads_link_by_id(self):
        result = reconcile.reconcile(
            [item("animation:a", ["Something else"], known_video_ids=["vid00000001"])],
            [video("vid00000001", "Totally different title")],
        )
        self.assertEqual(result["links"]["animation:a"][0]["method"], "app upload")

    def test_hand_posted_video_links_by_title(self):
        result = reconcile.reconcile(
            [item("animation:a", ["The Boy Who Cried Wolf 🐺", "boy who cried wolf"])],
            [video("vid00000001", "The boy who cried wolf #shorts")],
        )
        self.assertEqual(result["video_to_item"], {"vid00000001": "animation:a"})
        self.assertEqual(result["links"]["animation:a"][0]["method"], "title")

    def test_same_title_twice_pairs_by_time(self):
        now = time.time()
        items = [
            item("animation:old", ["Moon facts"], created_at=now - 10 * 86400),
            item("animation:new", ["Moon facts"], created_at=now - 2 * 86400),
        ]
        videos = [video("vid0000new1", "Moon facts", published=now - 86400), video("vid0000old1", "Moon facts", published=now - 9 * 86400)]
        result = reconcile.reconcile(items, videos)
        self.assertEqual(result["video_to_item"], {"vid0000old1": "animation:old", "vid0000new1": "animation:new"})

    def test_video_published_before_the_item_existed_is_not_it(self):
        now = time.time()
        result = reconcile.reconcile(
            [item("animation:a", ["Moon facts"], created_at=now)], [video("vid00000001", "Moon facts", published=now - 30 * 86400)]
        )
        self.assertEqual(result["links"], {})
        self.assertEqual(result["unmatched_videos"], ["vid00000001"])

    def test_owner_decisions_win(self):
        items = [item("animation:a", ["Moon facts"]), item("animation:b", ["Sun facts"])]
        videos = [video("vid00000001", "Moon facts")]
        manual = reconcile.reconcile(items, videos, {"links": {"animation:b": "vid00000001"}})
        self.assertEqual(manual["video_to_item"], {"vid00000001": "animation:b"})
        self.assertEqual(manual["links"]["animation:b"][0]["method"], "manual")
        rejected = reconcile.reconcile(items, videos, {"rejected": {"animation:a": ["vid00000001"]}})
        self.assertEqual(rejected["links"], {})

    def test_near_miss_is_only_a_suggestion(self):
        result = reconcile.reconcile(
            [item("animation:a", ["Why the Leaning Tower of Pisa leans"])],
            [video("vid00000001", "Why the Leaning Tower of Pisa Really Leans")],
        )
        self.assertEqual(result["links"], {})
        self.assertEqual([(s["item_key"], s["video_id"]) for s in result["suggestions"]], [("animation:a", "vid00000001")])

    def test_posted_url_links_and_problems_are_reported(self):
        items = [
            item("animation:a", ["Anything"], posted={"manual": True, "url": "https://youtu.be/vid00000001"}),
            item("animation:b", ["Never found"], posted={"manual": True}),
            item("animation:c", ["Deleted"], known_video_ids=["vid0deleted"]),
            item("animation:d", ["Dupe me"], known_video_ids=["vid00000002"]),
        ]
        videos = [video("vid00000001", "Renamed"), video("vid00000002", "Dupe me"), video("vid00000003", "Dupe me")]
        result = reconcile.reconcile(items, videos)
        self.assertEqual(result["links"]["animation:a"][0]["method"], "posted link")
        self.assertEqual(result["missing_posted"], ["animation:b"])
        self.assertEqual(result["gone"], [{"item_key": "animation:c", "video_id": "vid0deleted"}])
        self.assertEqual(result["duplicates"], [{"item_key": "animation:d", "video_id": "vid00000003"}])


# -------------------------------------------------------------------- catalog
BOARD = {
    "title": "Working title",
    "cast": [{"id": "fox", "kind": "animal", "species": "fox"}, {"id": "kid", "kind": "person"}],
    "scenes": [
        {"narration": "a", "sky": "day", "ground": "forest"},
        {"narration": "b", "sky": "dusk", "ground": "forest", "transition": {"type": "fly", "from": "left"}},
        {"narration": "c", "sky": "room", "transition": "tear"},
    ],
}


class TestCatalog(StorageTestCase):
    def test_animation_style_from_storyboard(self):
        style = catalog.animation_style(BOARD)
        self.assertEqual(style["Main setting"], "forest")
        self.assertEqual(style["Characters"], "animal + person")
        self.assertTrue(style["Transitions"].startswith("In-picture"))
        self.assertEqual(style["Settings per video"], "2 settings")
        self.assertEqual(catalog.animation_style({}), {})

    def test_animation_items_carry_titles_ids_marks_and_batches(self):
        batch = self.finished_animation("Fox and grapes", title="The Fox & the Grapes 🦊", board=BOARD, batch_id="b1")
        self.finished_animation("Second in batch", batch_id="b1")
        uploaded = self.finished_animation("Uploaded one")
        anim_store.update_project(uploaded, youtube_video_id="vid00000001")
        posted = self.finished_animation("Posted one")
        anim_schedule.mark_posted(posted, url="https://youtu.be/vid00000002")
        anim_store.create_project("still rendering")  # not done: not an item

        items = {i["key"]: i for i in catalog.build_items()}
        self.assertEqual(len(items), 4)
        fox = items[f"animation:{batch}"]
        self.assertEqual(fox["titles"][:2], ["The Fox & the Grapes 🦊", "Working title"])
        self.assertEqual((fox["batch_id"], fox["batch_size"]), ("b1", 2))
        self.assertEqual(fox["features"]["Main setting"], "forest")
        self.assertEqual(items[f"animation:{uploaded}"]["known_video_ids"], ["vid00000001"])
        self.assertTrue(items[f"animation:{posted}"]["posted"]["manual"])

    def test_legacy_animation_batch_is_inferred(self):
        a = self.finished_animation("One")
        b = self.finished_animation("Two")
        old = self.finished_animation("Much older")
        anim_store.update_project(old, created_at=time.time() - 3600)
        items = {i["key"]: i for i in catalog.animation_items()}
        self.assertTrue(items[f"animation:{a}"]["batch_inferred"])
        self.assertEqual(items[f"animation:{a}"]["batch_id"], items[f"animation:{b}"]["batch_id"])
        self.assertEqual(items[f"animation:{old}"]["batch_id"], "")

    def test_documentary_items(self):
        pid = self.finished_documentary()
        doc_schedule.create_entry(date=self.day, mode="library", project_id=pid)
        entry = doc_schedule.list_entries()[0]
        doc_schedule._patch_entry(entry["id"], youtube_video_id="vid00000009")
        [doc] = catalog.documentary_items()
        self.assertEqual(doc["titles"][0], "The Film")
        self.assertEqual(doc["known_video_ids"], ["vid00000009"])
        self.assertEqual(doc["features"]["Planned length"], "8–15 min")

    def test_shorts_from_generator_and_calendar(self):
        _, [single] = self.generator_short("Honey never spoils")
        variants_task, _ = self.generator_short("Three variants", finals=3)
        created = shorts_schedule.create_entries(
            [{"date": self.day, "topic": "Calendar topic A"}, {"date": self.day, "topic": "Calendar topic B"}]
        )
        task_id, [path] = self.generator_short("Calendar topic A")
        shorts_schedule._patch_entry(
            created[0]["id"],
            uploads=[{"path": path, "video_id": "vid00000005", "title": "Topic A, the title", "description": "", "tags": [], "error": ""}],
            youtube_video_ids=["vid00000005", "vid0000legc"],
        )

        items = {i["key"]: i for i in catalog.shorts_items()}
        lone = items[f"shorts:{os.path.basename(os.path.dirname(single))}/final-1.mp4"]
        self.assertEqual((lone["topic"], lone["batch_id"], lone["features"]["Made from"]), ("Honey never spoils", "", "Generator"))
        self.assertEqual(items[f"shorts:{variants_task}/final-2.mp4"]["batch_id"], f"variants-{variants_task[:8]}")
        calendar = items[f"shorts:{task_id}/final-1.mp4"]
        self.assertEqual(calendar["titles"][0], "Topic A, the title")
        self.assertEqual(calendar["known_video_ids"], ["vid00000005"])
        self.assertEqual(calendar["batch_id"], created[0]["batch_id"])
        self.assertEqual(calendar["features"]["Made from"], "Calendar")
        self.assertEqual(calendar["features"]["Footage source"], "pexels")
        legacy = items[f"shorts:entry:{created[0]['id']}:vid0000legc"]
        self.assertEqual(legacy["known_video_ids"], ["vid0000legc"])

    def test_documentary_renders_are_not_counted_as_shorts(self):
        pid = self.finished_documentary()
        with open(os.path.join(utils.task_dir(pid), "final-1.mp4"), "wb") as f:
            f.write(b"x")
        with open(os.path.join(utils.task_dir(pid), "script.json"), "w") as f:
            json.dump({"params": {}}, f)
        self.assertEqual(catalog.shorts_items(), [])

    def test_length_buckets(self):
        self.assertEqual(catalog.length_bucket(0), "Unknown")
        self.assertEqual(catalog.length_bucket(15), "Under 20 s")
        self.assertEqual(catalog.length_bucket(59), "40–60 s")
        self.assertEqual(catalog.length_bucket(600), "8–15 min")
        self.assertEqual(catalog.length_bucket(3600), "15 min +")


class TestBatchIds(StorageTestCase):
    def test_shorts_calendar_batch_gets_one_id_and_single_entries_none(self):
        batch = shorts_schedule.create_entries([{"date": self.day, "topic": "a"}, {"date": self.day, "topic": "b"}])
        self.assertTrue(batch[0]["batch_id"])
        self.assertEqual(batch[0]["batch_id"], batch[1]["batch_id"])
        self.assertEqual(shorts_schedule.create_entries([{"date": self.day, "topic": "c"}])[0]["batch_id"], "")
        self.assertEqual(shorts_schedule.create_entry(date=self.day, topic="d")["batch_id"], "")

    def test_scheduled_animation_inherits_the_calendar_batch(self):
        anim_schedule.create_entries([{"date": self.day, "topic": "x"}, {"date": self.day, "topic": "y"}])
        entry = anim_schedule.list_entries()[0]
        with patch("app.services.animation.pipeline.run_project", side_effect=lambda pid: anim_store.update_project(pid, status=anim_store.STATUS_DONE)):
            project = anim_schedule._ensure_video(entry)
        self.assertEqual(project["batch_id"], entry["batch_id"])


# ---------------------------------------------------------------- posted marks
class TestPostedMarks(StorageTestCase):
    def test_documentary_posted_frees_the_budget(self):
        pid = self.finished_documentary()
        doc_schedule.create_entry(date=self.day, post_time="18:00", mode="library", project_id=pid)
        self.assertEqual(upload_budget.daily_load(self.day)["documentaries"], 1)
        doc_schedule.mark_posted(pid, url="https://youtu.be/vid00000001")
        self.assertEqual(doc_schedule.list_entries()[0]["status"], doc_schedule.STATUS_POSTED)
        self.assertEqual(upload_budget.daily_load(self.day)["documentaries"], 0)
        self.assertTrue(doc_store.load_project(pid)["posted"]["manual"])
        self.assertEqual(doc_store.unmark_posted(pid)["posted"], {})

    def test_reconciled_hand_posts_are_marked_in_their_studio(self):
        anim = self.finished_animation("Fox", title="The Fox")
        anim_schedule.create_entry(date=self.day, post_time="18:00", project_id=anim)
        doc = self.finished_documentary(title="The Film")
        _, [short_path] = self.generator_short("Honey never spoils")
        app_uploaded = self.finished_animation("Mine", title="Uploaded by the app")
        anim_store.update_project(app_uploaded, youtube_video_id="vid00000004")
        videos = [
            video("vid00000001", "The Fox"),
            video("vid00000002", "The Film"),
            video("vid00000003", "Honey never spoils"),
            video("vid00000004", "Uploaded by the app"),
        ]
        result = sync.reconcile_now(videos)
        self.assertEqual(len(result["marked_posted"]), 3)
        self.assertEqual(anim_store.load_project(anim)["posted"]["url"], "https://youtu.be/vid00000001")
        self.assertEqual(anim_schedule.list_entries()[0]["status"], anim_schedule.STATUS_POSTED)
        self.assertEqual(upload_budget.daily_load(self.day)["animations"], 0)
        self.assertTrue(doc_store.load_project(doc)["posted"]["manual"])
        short_key = f"shorts:{os.path.basename(os.path.dirname(short_path))}/final-1.mp4"
        self.assertIn(short_key, analytics_store.load_links()["posted"])
        self.assertEqual(anim_store.load_project(app_uploaded).get("posted"), {})
        # a second pass changes nothing
        self.assertEqual(sync.reconcile_now(videos)["marked_posted"], [])


# ---------------------------------------------------------------- store/topics
class TestAnalyticsStore(StorageTestCase):
    def test_link_reject_and_categories(self):
        analytics_store.link("animation:a", "vid00000001")
        analytics_store.link("animation:b", "vid00000001")  # a video belongs to one item
        self.assertEqual(analytics_store.load_links()["links"], {"animation:b": "vid00000001"})
        analytics_store.reject("animation:b", "vid00000001")
        links = analytics_store.load_links()
        self.assertEqual((links["links"], links["rejected"]), ({}, {"animation:b": ["vid00000001"]}))
        analytics_store.link("animation:b", "vid00000001")
        self.assertEqual(analytics_store.load_links()["rejected"]["animation:b"], [])
        analytics_store.set_categories({"Moon": "Space", "Sun": "Space"})
        analytics_store.set_categories({"Sun": ""})
        self.assertEqual(analytics_store.load_links()["categories"], {"Moon": "Space"})

    def test_short_posted_mark_round_trip(self):
        analytics_store.mark_short_posted("shorts:t/final-1.mp4", url="https://youtu.be/vid00000001")
        self.assertTrue(analytics_store.load_links()["posted"]["shorts:t/final-1.mp4"]["manual"])
        analytics_store.unmark_short_posted("shorts:t/final-1.mp4")
        self.assertEqual(analytics_store.load_links()["posted"], {})

    def test_one_snapshot_per_video_per_day(self):
        analytics_store.record_snapshots([video("vid00000001", "x", views=5)], "2026-10-01")
        analytics_store.record_snapshots([video("vid00000001", "x", views=9)], "2026-10-01")
        analytics_store.record_snapshots([video("vid00000001", "x", views=20)], "2026-10-02")
        self.assertEqual([r["views"] for r in analytics_store.load_history()["vid00000001"]], [9, 20])

    def test_categorize_only_new_topics_and_survive_bad_replies(self):
        analytics_store.set_categories({"Moon landing": "Space"})
        prompts = []

        def fake_llm(prompt):
            prompts.append(prompt)
            return '```json\n{"1": "Ancient History", "2": "Animals & Nature"}\n```'

        added = topics.categorize(["Moon landing", "The pyramids", "Octopus hearts"], generate=fake_llm)
        self.assertEqual(added, {"The pyramids": "Ancient History", "Octopus hearts": "Animals & Nature"})
        self.assertIn("- Space", prompts[0])
        self.assertNotIn("Moon landing", prompts[0].split("Topics:")[1])
        self.assertEqual(topics.categorize(["New one"], generate=lambda p: "Error: no key"), {})
        self.assertEqual(topics.parse_response("not json", ["a"]), {})


# ------------------------------------------------------------------ YouTube API
class TestYoutubeApi(StorageTestCase):
    def test_parse_duration(self):
        self.assertEqual(youtube_api.parse_duration("PT1M5S"), 65)
        self.assertEqual(youtube_api.parse_duration("PT2H"), 7200)
        self.assertEqual(youtube_api.parse_duration("P1DT1S"), 86401)
        self.assertEqual(youtube_api.parse_duration("garbage"), 0)

    def ready(self):
        return patch.object(youtube_api, "readiness", return_value=(True, ""))

    def test_list_channel_videos_pages_through_uploads(self):
        client = MagicMock()
        client.channels().list().execute.return_value = {
            "items": [{"id": "UC1", "snippet": {"title": "My channel"}, "contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]
        }
        client.playlistItems().list().execute.side_effect = [
            {"items": [{"contentDetails": {"videoId": "vid00000001"}}], "nextPageToken": "p2"},
            {"items": [{"contentDetails": {"videoId": "vid00000002"}}]},
        ]
        client.videos().list().execute.return_value = {
            "items": [
                {"id": "vid00000001", "snippet": {"title": "Old", "publishedAt": "2026-01-01T10:00:00Z"}, "status": {"privacyStatus": "public"}, "statistics": {"viewCount": "12"}, "contentDetails": {"duration": "PT45S"}},
                {"id": "vid00000002", "snippet": {"title": "New", "publishedAt": "2026-02-01T10:00:00Z"}, "status": {"privacyStatus": "private", "publishAt": "2026-02-03T10:00:00Z"}, "statistics": {}, "contentDetails": {"duration": "PT8M"}},
            ]
        }
        with self.ready():
            result = youtube_api.list_channel_videos(client=client)
        self.assertEqual(result["channel"], {"id": "UC1", "title": "My channel"})
        self.assertEqual([v["video_id"] for v in result["videos"]], ["vid00000002", "vid00000001"])
        self.assertEqual((result["videos"][1]["views"], result["videos"][1]["duration_seconds"]), (12, 45))
        self.assertEqual(result["videos"][0]["publish_at"], "2026-02-03T10:00:00Z")

    def test_fetch_video_metrics_maps_rows(self):
        client = MagicMock()
        client.reports().query().execute.return_value = {
            "columnHeaders": [{"name": "video"}] + [{"name": m} for m in youtube_api.ANALYTICS_METRICS],
            "rows": [["vid00000001", 100, 50.5, 30, 64.2, 5, 1, 2, 3]],
        }
        with self.ready():
            metrics = youtube_api.fetch_video_metrics(["vid00000001", "vid00000002"], client=client)
        self.assertEqual(metrics["vid00000001"]["averageViewPercentage"], 64.2)
        self.assertNotIn("vid00000002", metrics)

    def test_readiness_explains_what_is_missing(self):
        service = youtube_upload.youtube_upload_service
        token = os.path.join(self.root, "token.json")
        with patch.dict(youtube_upload.config.youtube, {"enabled": True, "token_file": token}):
            self.assertIn("not connected", youtube_api.readiness()[1])
            with open(token, "w") as f:
                json.dump({"scopes": [youtube_upload.UPLOAD_SCOPE]}, f)
            ready, reason = youtube_api.readiness()
            self.assertFalse(ready)
            self.assertIn("youtube_auth.py", reason)
            with open(token, "w") as f:
                json.dump({"scopes": youtube_upload.YOUTUBE_SCOPES}, f)
            self.assertEqual(youtube_api.readiness(), (True, ""))
            self.assertEqual(service.missing_scopes(youtube_upload.YOUTUBE_SCOPES), [])
        with patch.dict(youtube_upload.config.youtube, {"enabled": False}):
            self.assertIn("turned off", youtube_api.readiness()[1])
        with self.assertRaises(youtube_api.AnalyticsAuthError):
            youtube_api.list_channel_videos(client=MagicMock())


class TestUploadTokenScopes(StorageTestCase):
    def test_an_upload_only_token_refreshes_with_its_own_scopes(self):
        token = os.path.join(self.root, "token.json")
        with open(token, "w") as f:
            json.dump({"scopes": [youtube_upload.UPLOAD_SCOPE], "refresh_token": "r", "client_id": "c", "client_secret": "s"}, f)
        with patch.dict(youtube_upload.config.youtube, {"token_file": token}), patch(
            "google.oauth2.credentials.Credentials.from_authorized_user_file"
        ) as load:
            load.return_value = MagicMock(expired=False, valid=True)
            youtube_upload.youtube_upload_service._load_credentials()
        load.assert_called_once_with(token, [youtube_upload.UPLOAD_SCOPE])

    def test_saved_token_records_the_scopes_actually_granted(self):
        token = os.path.join(self.root, "token.json")
        credentials = MagicMock(granted_scopes=[youtube_upload.UPLOAD_SCOPE])
        credentials.to_json.return_value = json.dumps({"scopes": youtube_upload.YOUTUBE_SCOPES, "refresh_token": "r"})
        with patch.dict(youtube_upload.config.youtube, {"token_file": token}):
            youtube_upload.youtube_upload_service._save_credentials(credentials)
            self.assertEqual(youtube_upload.youtube_upload_service.granted_scopes(), [youtube_upload.UPLOAD_SCOPE])


# ------------------------------------------------------------------------ sync
class TestSync(StorageTestCase):
    def test_full_sync_stores_everything_and_reports(self):
        self.finished_animation("Fox", title="The Fox", board=BOARD)
        channel = {"channel": {"id": "UC1", "title": "Me"}, "videos": [video("vid00000001", "The Fox", views=500)]}
        with patch.object(youtube_api, "list_channel_videos", return_value=channel), patch.object(
            youtube_api, "fetch_video_metrics", return_value={"vid00000001": {"views": 480, "averageViewPercentage": 71.0}}
        ) as metrics, patch.object(topics, "categorize", return_value={"Fox": "Moral Stories"}):
            status = sync.run()
        self.assertTrue(status["ok"], status)
        self.assertEqual((status["videos"], status["linked"], status["marked_posted"], status["metrics"]), (1, 1, 1, 1))
        self.assertEqual(metrics.call_args.kwargs["start_date"], date.today().isoformat())
        self.assertEqual(analytics_store.load_sync_status()["linked"], 1)
        self.assertEqual(analytics_store.channel_videos()[0]["video_id"], "vid00000001")
        self.assertEqual(analytics_store.load_metrics()["vid00000001"]["averageViewPercentage"], 71.0)

    def test_auth_errors_are_reported_not_raised(self):
        with patch.object(youtube_api, "list_channel_videos", side_effect=youtube_api.AnalyticsAuthError("run youtube_auth.py")):
            status = sync.run()
        self.assertFalse(status["ok"])
        self.assertIn("youtube_auth.py", status["error"])

    def test_metrics_failure_keeps_the_channel_data(self):
        channel = {"channel": {}, "videos": [video("vid00000001", "x")]}
        with patch.object(youtube_api, "list_channel_videos", return_value=channel), patch.object(
            youtube_api, "fetch_video_metrics", side_effect=RuntimeError("boom")
        ):
            status = sync.run(categorize_topics=False)
        self.assertTrue(status["ok"])
        self.assertIn("boom", status["metrics_error"])

    def test_before_uploads_is_skipped_without_read_access(self):
        with patch.object(youtube_api, "readiness", return_value=(False, "no")), patch.object(sync, "run") as run:
            sync.run_before_uploads()
        run.assert_not_called()
        with patch.object(youtube_api, "readiness", return_value=(True, "")), patch.object(sync, "run") as run:
            sync.run_before_uploads(timeout=5)
        run.assert_called_once()

    def test_cron_hook_syncs_before_running_calendars(self):
        from app.controllers.v1 import schedule as schedule_controller

        calls = []
        with patch.object(sync, "run_before_uploads", side_effect=lambda: calls.append("sync")), patch.object(
            shorts_schedule, "run_due_entries", side_effect=lambda run_date=None: calls.append("shorts")
        ), patch.object(doc_schedule, "run_due_entries", side_effect=lambda run_date=None: calls.append("docs")), patch.object(
            anim_schedule, "run_due_entries", side_effect=lambda run_date=None: calls.append("anims")
        ):
            schedule_controller._run_all_calendars()
            deadline = time.time() + 5
            while len(calls) < 4 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(calls[0], "sync")
        self.assertEqual(sorted(calls[1:]), ["anims", "docs", "shorts"])


# ---------------------------------------------------------------------- report
class TestReport(unittest.TestCase):
    def setUp(self):
        now = time.time()
        self.now = datetime.fromtimestamp(now, timezone.utc)
        self.items = []
        self.videos = []
        self.metrics = {}
        for n in range(8):
            setting = "space" if n < 4 else "forest"
            key = f"animation:p{n}"
            self.items.append(
                item(key, [f"Video {n}"], created_at=now - 20 * 86400, studio="animation", batch_id="b1" if n < 3 else "", batch_size=3 if n < 3 else 1, features={"Main setting": setting})
            )
            views = 1000 if setting == "space" else 100
            self.videos.append(video(f"vid0000000{n}", f"Video {n}", published=now - 10 * 86400, views=views))
            self.metrics[f"vid0000000{n}"] = {"averageViewPercentage": 80.0 if setting == "space" else 40.0, "shares": 2, "subscribersGained": 1}
        self.videos.append(video("vid0000other", "Some old upload", published=now - 400 * 86400, views=50))
        self.decisions = {"categories": {"Video 0": "Space"}}

    def dataset(self):
        return report.build_dataset(self.items, self.videos, self.metrics, self.decisions, now=self.now)

    def test_dataset_rows(self):
        df = self.dataset()
        self.assertEqual(len(df), 9)
        row = df[df["video_id"] == "vid00000000"].iloc[0]
        self.assertEqual((row["studio"], row["category"], row["generation"], row["posted_via"]), ("animation", "Space", "Batch", "Posted by hand"))
        self.assertEqual(row["views_per_day"], 100.0)
        self.assertEqual(row["Main setting"], "space")
        self.assertAlmostEqual(row["engagement_per_1k"], (50 + 10 + 2) / 1000 * 1000)
        other = df[df["video_id"] == "vid0000other"].iloc[0]
        self.assertEqual((other["studio"], other["category"]), ("other", ""))
        self.assertIn("Main setting", report.feature_dimensions(df, "animation"))
        self.assertTrue(report.build_dataset([], [], {}, {}).empty)

    def test_summaries_and_insights(self):
        df = self.dataset()
        df = df[df["studio"] == "animation"]
        by_setting = report.summarize(df, "Main setting")
        self.assertEqual(list(by_setting["Main setting"]), ["space", "forest"])
        self.assertEqual(int(by_setting.iloc[0]["Median views"]), 1000)
        self.assertEqual(float(by_setting.iloc[0]["Avg % viewed"]), 80.0)

        batches = report.batch_summary(df)
        self.assertEqual(len(batches), 1)
        self.assertEqual((batches.iloc[0]["Posted"], batches.iloc[0]["Total views"]), (3, 3000))

        found = report.insights(df, ["Main setting", "generation"], metric="views", min_videos=3)
        self.assertEqual((found[0]["dimension"], found[0]["group"], found[0]["positive"]), ("Main setting", "space", True))
        self.assertTrue(any(not f["positive"] and f["group"] == "forest" for f in found))
        self.assertEqual(report.insights(df, ["Main setting"], min_videos=5), [])


if __name__ == "__main__":
    unittest.main()


class TestAnalyticsApi(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from app.asgi import app

        self.client = TestClient(app)

    def test_status_and_sync_without_access(self):
        with patch.object(youtube_api, "readiness", return_value=(False, "connect first")), patch.object(sync, "run") as run:
            status = self.client.get("/api/v1/analytics/status").json()["data"]
            triggered = self.client.post("/api/v1/analytics/sync").json()["data"]
        self.assertEqual((status["ready"], status["reason"]), (False, "connect first"))
        self.assertEqual(triggered, {"triggered": False, "reason": "connect first"})
        run.assert_not_called()

    def test_summary_groups_and_cleans_nan(self):
        frame = report.build_dataset(
            [item("animation:a", ["Moon"], features={"Main setting": "space"})],
            [video("vid00000001", "Moon", views=10)],
            {},
            {},
        )
        with patch.object(report, "build_dataset", return_value=frame):
            data = self.client.get("/api/v1/analytics/summary?by=Main setting&studio=animation").json()["data"]
        self.assertEqual(data["groups"][0]["Main setting"], "space")
        self.assertIsNone(data["groups"][0]["Avg % viewed"])
