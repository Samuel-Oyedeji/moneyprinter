"""Studio briefs reaching the pipeline (WP2) and the results packet (WP3)."""
import json
import math
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

from app.services.analytics import catalog  # noqa: E402
from app.services.animation import brief, metadata, pipeline, script, storyboard, tts  # noqa: E402
from app.services.animation import store as anim_store  # noqa: E402
from app.services.studios import evaluate, model, store, templates  # noqa: E402
from app.utils import utils  # noqa: E402

BRIEF = {
    "topic": "Why do cats purr?",
    "category": "Animals",
    "notes": "Purring runs at 25-150 Hz.",
    "angle": "myth-busting",
    "hook": "cold-scene",
    "length": 35,
    "setting_hint": "room",
    "title_style": "question",
}
SLOT_INFO = {"studio_id": "animation", "slot_id": "s1", "week": "2026-W46", "experiment": "w46-hook", "arm": "explore"}


class TempStorage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = self._tmp.name

        def storage_dir(sub_dir: str = "", create: bool = False):
            d = os.path.join(root, sub_dir)
            if create:
                os.makedirs(d, exist_ok=True)
            return d

        patcher = patch.object(utils, "storage_dir", storage_dir)
        patcher.start()
        self.addCleanup(patcher.stop)


# ------------------------------------------------------------------ WP2
class TestBriefDirections(unittest.TestCase):
    def test_hand_made_projects_keep_their_prompts_unchanged(self):
        project = {"context": "Some research."}
        self.assertEqual(brief.script_notes(project), "Some research.")
        self.assertEqual(brief.storyboard_context(project), "Some research.")
        self.assertEqual(brief.title_direction(project), "")
        self.assertEqual(brief.features(project), {})

    def test_brief_becomes_directions_for_each_step(self):
        project = {"context": "Extra context.", "brief": BRIEF, "studio": SLOT_INFO}
        notes = brief.script_notes(project)
        self.assertIn("myth-busting", notes)
        self.assertIn("middle of a scene", notes)
        self.assertLess(notes.index("Angle"), notes.index("25-150 Hz"))
        self.assertIn("Extra context.", notes)
        self.assertIn('"room" setting', brief.storyboard_context(project))
        self.assertNotIn("Angle", brief.storyboard_context(project))
        self.assertIn("question", brief.title_direction(project))

    def test_writers_choice_adds_no_setting_direction(self):
        project = {"brief": {**BRIEF, "setting_hint": brief.WRITERS_CHOICE, "notes": ""}}
        self.assertEqual(brief.storyboard_context(project), "")

    def test_template_levers_all_have_directions(self):
        levers = templates.ANIMATION["levers"]
        self.assertEqual(set(levers["angle"]["values"]), set(brief.ANGLES))
        self.assertEqual(set(levers["hook"]["values"]), set(brief.HOOKS))
        self.assertEqual(set(levers["title_style"]["values"]), set(brief.TITLE_STYLES))

    def test_title_direction_lands_in_the_metadata_prompt(self):
        prompt = metadata.build_prompt("Cats", "Narration.", "9:16", direction=brief.TITLE_STYLES["number"])
        self.assertIn("Style: Lead the title with a specific number", prompt)
        self.assertNotIn("Style:", metadata.build_prompt("Cats", "Narration.", "9:16"))


class TestPipelineUsesTheBrief(TempStorage):
    def project(self):
        return anim_store.create_project(
            BRIEF["topic"], context="Extra context.", seconds=35, source="studio", brief=BRIEF, studio=SLOT_INFO
        )["project_id"]

    def test_script_and_storyboard_get_the_directions(self):
        pid = self.project()
        seen = {}

        def fake_script(topic, notes, seconds, on_cost=None):
            seen["script"] = notes
            return {"title": "T", "text": "One line.", "words": 2, "model": "m"}

        def fake_board(topic, context, text, aspect, on_cost=None):
            seen["storyboard"] = context
            return {"title": "T", "scenes": []}

        with patch.object(script, "write_script", fake_script), patch.object(storyboard, "write_storyboard", fake_board), patch.object(
            tts, "synthesize", side_effect=RuntimeError("stop after the storyboard")
        ):
            project = pipeline.run_project(pid)
        self.assertEqual(project["status"], anim_store.STATUS_FAILED)
        self.assertIn("Angle: myth-busting", seen["script"])
        self.assertIn('"room" setting', seen["storyboard"])

    def test_packaging_gets_the_title_style(self):
        pid = self.project()
        for name, data in (("script.json", {"title": "T", "text": "One line."}), ("storyboard.json", {"title": "T", "scenes": []})):
            anim_store.write_json(anim_store.path(pid, name), data)
        anim_store.write_json(anim_store.path(pid, "words.json"), {"words": [], "duration": 1.0})
        for target in (os.path.join(anim_store.public_dir(pid), "narration.mp3"), anim_store.final_path(pid)):
            with open(target, "wb") as f:
                f.write(b"x")
        with patch.object(metadata, "generate", return_value={"title": "Why?", "generated": True}) as generate:
            pipeline.run_project(pid)
        self.assertIn("question", generate.call_args.kwargs["direction"])

    def test_analytics_records_levers_and_experiment(self):
        pid = self.project()
        anim_store.update_project(pid, status=anim_store.STATUS_DONE)
        item = next(i for i in catalog.animation_items() if i["project_id"] == pid)
        features = item["features"]
        self.assertEqual(features["Made from"], "Autonomous studio")
        self.assertEqual((features["Angle"], features["Hook"], features["Title style"]), ("myth-busting", "cold-scene", "question"))
        self.assertEqual((features["Experiment"], features["Explore / exploit"]), ("w46-hook", "explore"))


# ------------------------------------------------------------------ WP3
NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
STUDIO = {**templates.ANIMATION, "created_at": 1}


def frame(rows: list[dict]) -> pd.DataFrame:
    """A build_dataset()-like frame with just the columns the packet reads."""
    full = []
    for i, row in enumerate(rows):
        published = row.get("published_at", NOW - timedelta(days=30 - i * 0.5))
        full.append(
            {
                "video_id": row.get("video_id", f"hist{i:04d}"),
                "title": row.get("title", f"Video {i}"),
                "studio": row.get("studio", "animation"),
                "published_at": published,
                "age_days": (NOW - published).total_seconds() / 86400,
                "views": row.get("views_3d", 0),
                "views_3d": row.get("views_3d", float("nan")),
                "views_7d": row.get("views_7d", float("nan")),
                "avg_view_pct": row.get("avg_view_pct", 60.0),
            }
        )
    return pd.DataFrame(full)


def history(count: int, views: float = 100.0) -> list[dict]:
    return [{"views_3d": views, "published_at": NOW - timedelta(days=40 - i)} for i in range(count)]


def slot(slot_id: str, video_id: str = "", status: str = model.SLOT_UPLOADED, **fields) -> dict:
    brief_fields = fields.pop("brief", {})
    return {
        "id": slot_id,
        "status": status,
        "date": fields.pop("date", "2026-11-14"),
        "week": "2026-W46",
        "youtube_video_id": video_id,
        "project_id": fields.pop("project_id", ""),
        "brief": {"topic": f"Topic {slot_id}", **brief_fields},
        "experiment": fields.pop("experiment", ""),
        "arm": fields.pop("arm", "exploit"),
        "prediction": fields.pop("prediction", ""),
        **fields,
    }


EXPERIMENT = {"id": "w46-length", "week": "2026-W46", "lever": "length", "values": [35, 45], "status": "running"}


def experiment_data(views_35: list[float], views_45: list[float], extra_slots: list[dict] = ()):
    rows = history(10)
    queue = []
    for value, views in ((35, views_35), (45, views_45)):
        for j, v in enumerate(views):
            vid = f"v{value}_{j}"
            rows.append({"video_id": vid, "views_3d": v, "published_at": NOW - timedelta(days=6, hours=j)})
            queue.append(slot(f"s{value}_{j}", vid, experiment=EXPERIMENT["id"], brief={"length": value}))
    return frame(rows), queue + list(extra_slots)


class TestScoring(unittest.TestCase):
    def test_a_new_channel_is_calibrating_and_scores_nothing(self):
        df = frame(history(3) + [{"video_id": "new1", "views_3d": 500}])
        packet = evaluate.build_packet(STUDIO, [slot("s1", "new1", prediction="above")], [], df, today=NOW.date())
        self.assertTrue(packet["calibrating"])
        self.assertEqual(packet["videos"][0]["state"], "no baseline yet (calibrating)")
        self.assertIsNone(packet["videos"][0]["score"])
        self.assertEqual(packet["predictions"]["scored"], 0)

    def test_score_is_views_vs_baseline_on_a_log_scale(self):
        df = frame(history(10) + [{"video_id": "new1", "views_3d": 300}])
        packet = evaluate.build_packet(STUDIO, [slot("s1", "new1", prediction="above")], [], df, today=NOW.date())
        video = packet["videos"][0]
        self.assertEqual(video["baseline"], 100)
        self.assertAlmostEqual(video["score"], round(math.log(301 / 101), 3))
        self.assertEqual((video["outcome"], video["vs_baseline_pct"], video["prediction_hit"]), ("above", 198, True))
        self.assertEqual(packet["predictions"], {"scored": 1, "hits": 1, "hit_rate": 1.0})

    def test_baseline_only_uses_earlier_videos(self):
        later = [{"views_3d": 10_000, "published_at": NOW - timedelta(days=1, hours=i)} for i in range(10)]
        df = frame(history(10) + [{"video_id": "new1", "views_3d": 100, "published_at": NOW - timedelta(days=5)}] + later)
        video = evaluate.build_packet(STUDIO, [slot("s1", "new1")], [], df, today=NOW.date())["videos"][0]
        self.assertEqual((video["baseline"], video["outcome"]), (100, "at"))

    def test_young_and_missing_videos_say_why_they_are_unscored(self):
        df = frame(history(10) + [{"video_id": "young", "published_at": NOW - timedelta(days=1)}])
        queue = [slot("s1", "young"), slot("s2", "notsynced"), slot("s3", status=model.SLOT_READY)]
        videos = evaluate.build_packet(STUDIO, queue, [], df, today=NOW.date())["videos"]
        self.assertEqual({v["slot_id"]: v["state"] for v in videos}, {"s1": "too young to score", "s2": "not on the channel yet"})

    def test_the_packet_is_plain_json(self):
        df, queue = experiment_data([100, 100, 100], [200, 210, 190])
        packet = evaluate.build_packet(STUDIO, queue, [EXPERIMENT], df, today=NOW.date())
        json.dumps(packet, allow_nan=False)


class TestExperiments(unittest.TestCase):
    def judge(self, views_35, views_45, extra_slots=()):
        df, queue = experiment_data(views_35, views_45, extra_slots)
        return evaluate.build_packet(STUDIO, queue, [EXPERIMENT], df, today=NOW.date())["experiments"][0]

    def test_a_clear_gap_names_a_winner(self):
        result = self.judge([100, 90, 110], [200, 210, 190])
        self.assertEqual((result["verdict"]["status"], result["verdict"]["winner"]), ("winner", 45))
        self.assertEqual(result["videos_per_arm"], [3, 3])
        self.assertGreater(result["verdict"]["effect_pct"], 90)

    def test_a_small_gap_is_no_difference(self):
        result = self.judge([100, 100, 100], [110, 115, 108])
        self.assertEqual(result["verdict"]["status"], "no_difference")
        self.assertIsNone(result["verdict"]["winner"])

    def test_one_viral_video_does_not_win(self):
        result = self.judge([100, 100, 100], [100, 95, 50_000])
        self.assertEqual(result["verdict"]["status"], "no_difference")

    def test_videos_still_to_come_keep_it_pending(self):
        planned = slot("s45_9", status=model.SLOT_PLANNED, experiment=EXPERIMENT["id"], brief={"length": 45})
        result = self.judge([100, 100, 100], [200, 200], [planned])
        self.assertEqual(result["verdict"]["status"], "pending")

    def test_too_few_when_nothing_more_is_coming(self):
        cancelled = slot("s45_9", status=model.SLOT_CANCELLED, experiment=EXPERIMENT["id"], brief={"length": 45})
        result = self.judge([100, 100, 100], [200, 200], [cancelled])
        self.assertEqual(result["verdict"]["status"], "too_few")
        self.assertIn("45 has 2", result["verdict"]["summary"])

    def test_old_concluded_experiments_drop_out(self):
        old = {**EXPERIMENT, "id": "old", "week": "2026-W30", "status": "concluded"}
        df, queue = experiment_data([100] * 3, [100] * 3)
        packet = evaluate.build_packet(STUDIO, queue, [EXPERIMENT, old], df, today=NOW.date())
        self.assertEqual([e["id"] for e in packet["experiments"]], ["w46-length"])


class TestSpendAndStore(TempStorage):
    def test_spend_splits_this_week_and_last(self):
        queue = [
            slot("a", date="2026-11-18", project_id="p1"),
            slot("b", date="2026-11-11", project_id="p2"),
            slot("c", date="2026-10-01", project_id="p3"),
        ]
        packet = evaluate.build_packet(STUDIO, queue, [], frame([]), costs={"p1": 0.3, "p2": 0.25, "p3": 9}, today=date(2026, 11, 20))
        self.assertEqual(packet["spend"], {"this_week": 0.3, "last_week": 0.25, "weekly_budget": 10, "left_this_week": 9.7})

    def test_experiments_are_validated_and_upserted(self):
        templates.ensure_studio("animation")
        store.save_experiment("animation", EXPERIMENT)
        store.save_experiment("animation", {**EXPERIMENT, "hypothesis": "45s keeps people longer"})
        self.assertEqual([e["hypothesis"] for e in store.load_experiments("animation")], ["45s keeps people longer"])
        with self.assertRaises(model.StudioError) as caught:
            store.save_experiment("animation", {"id": "x", "week": "W46", "lever": "length", "values": [35, 90]})
        self.assertEqual(len(caught.exception.problems), 2)

    def test_load_packet_reads_everything_from_disk(self):
        templates.ensure_studio("animation")
        with patch("app.services.analytics.report.build_dataset", return_value=frame(history(10))):
            packet = evaluate.load_packet("animation", today=NOW.date())
        self.assertFalse(packet["calibrating"])
        self.assertEqual(packet["baseline"]["videos"], 10)


if __name__ == "__main__":
    unittest.main()
