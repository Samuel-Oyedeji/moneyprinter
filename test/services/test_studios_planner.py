"""The planning agent (WP4): plan rules, the tool loop and booking, with a fake model."""
import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services import schedule as shorts_schedule  # noqa: E402
from app.services import upload_budget  # noqa: E402
from app.services.analytics import report  # noqa: E402
from app.services.studios import model, planner, store, templates, topics  # noqa: E402
from app.utils import utils  # noqa: E402

SUNDAY = date(2026, 11, 15)
DAYS = [f"2026-11-{d}" for d in range(16, 23)]
TOPICS = [
    "Why do cats purr",
    "How volcanoes build islands",
    "What if the Moon vanished",
    "Why is the sky blue",
    "How bees make honey",
    "The five-second rule myth",
    "Why ice floats",
    "How the Great Wall was built",
    "What makes thunder loud",
    "Why octopuses have three hearts",
    "How a compass finds north",
    "The 1977 New York blackout",
    "Why bread rises",
    "How whales sleep",
    "Why onions make you cry",
    "How pyramids align with stars",
]


def good_plan() -> dict:
    """14 slots on Mon-Sun: a hook test (question vs cold-scene, 3 each), 2 reserves."""
    slots = []
    for i in range(14):
        day, time = DAYS[i // 2], ("10:45" if i % 2 == 0 else "18:15")
        slot = {"date": day, "time": time, "brief": {"topic": TOPICS[i], "category": "Science"}, "prediction": "at", "why": "variety"}
        if i < 6:
            slot["experiment"] = "w47-hook"
            slot["brief"]["hook"] = "question" if i % 2 == 0 else "cold-scene"
        slots.append(slot)
    return {
        "review": "First week: nothing published yet, so no results; the studio is calibrating.",
        "slots": slots,
        "reserves": [{"brief": {"topic": TOPICS[14]}}, {"brief": {"topic": TOPICS[15]}}],
        "experiments": [{"id": "w47-hook", "lever": "hook", "values": ["question", "cold-scene"], "hypothesis": "Cold opens hold viewers"}],
    }


def reply(text=None, calls=None, cost=0.002):
    message = SimpleNamespace(content=text, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(cost=cost, model_extra=None))


def call(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        return self.script.pop(0)


def empty_dataset():
    return pd.DataFrame(columns=list(report.BASE_COLUMNS))


class PlannerTestCase(unittest.TestCase):
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
        templates.ensure_studio("animation")

    def run_planner(self, *script):
        client = FakeClient(*script)
        result = planner.run("animation", today=SUNDAY, client=client, df=empty_dataset())
        return result, client

    def context(self):
        return planner.build_context("animation", SUNDAY, empty_dataset())


class TestTopics(unittest.TestCase):
    def test_rewordings_of_a_topic_match_and_different_topics_do_not(self):
        self.assertTrue(topics.is_same("Why do cats purr?", "The science of cat purring"))
        self.assertTrue(topics.is_same("Why do cats purr?", "why do cats purr"))
        self.assertFalse(topics.is_same("Why do cats purr?", "Why is the sky blue?"))
        for i, a in enumerate(TOPICS):
            for b in TOPICS[i + 1 :]:
                self.assertFalse(topics.is_same(a, b), (a, b))


class TestPlanningWindow(PlannerTestCase):
    def test_sunday_plans_the_whole_next_week(self):
        ctx = self.context()
        self.assertEqual([d["date"] for d in ctx.days], DAYS)
        self.assertEqual({d["needed"] for d in ctx.days}, {2})
        self.assertEqual(ctx.days[0]["suggested_times"], ["10:45", "18:15"])
        self.assertEqual(ctx.week, "2026-W47")
        self.assertTrue(ctx.packet["calibrating"])

    def test_a_first_run_midweek_plans_the_rest_of_the_week(self):
        ctx = planner.build_context("animation", date(2026, 11, 18), empty_dataset())
        self.assertEqual([d["date"] for d in ctx.days], ["2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"])

    def test_booked_slots_and_the_shared_budget_reduce_what_a_day_needs(self):
        store.add_slots("animation", [{"date": DAYS[0], "time": "09:00", "brief": {"topic": "Already booked"}}])
        shorts_schedule.create_entry(date=DAYS[1], topic="shorts", video_count=5)
        with patch.object(upload_budget, "daily_budget", return_value=6):
            ctx = self.context()
        self.assertEqual((ctx.days[0]["needed"], ctx.days[0]["booked_times"]), (1, ["09:00"]))
        self.assertEqual(ctx.days[1]["needed"], 1)


class TestPlanRules(PlannerTestCase):
    def problems(self, plan, ctx=None):
        return planner.check_plan(ctx or self.context(), plan)[1]

    def test_a_good_plan_passes_and_arms_are_computed(self):
        clean, problems = planner.check_plan(self.context(), good_plan())
        self.assertEqual(problems, [])
        arms = [s["arm"] for s in clean["slots"]]
        self.assertEqual(arms.count("explore"), 3)  # only the cold-scene videos differ from the defaults
        self.assertEqual(clean["slots"][0]["brief"]["length"], 35)  # missing levers take the default
        self.assertEqual(clean["new_experiments"][0]["week"], "2026-W47")

    def test_wrong_slot_counts_and_clashing_times(self):
        plan = good_plan()
        plan["slots"][1]["time"] = "11:15"  # 30 minutes after the 10:45 slot
        plan["slots"].pop()  # Sunday is one short
        problems = self.problems(plan)
        self.assertIn("2026-11-22 needs 2 slot(s); the plan has 1", problems)
        self.assertTrue(any("at least 60 minutes apart" in p for p in problems))

    def test_levers_differ_only_inside_an_experiment(self):
        plan = good_plan()
        plan["slots"][10]["brief"]["length"] = 55  # no experiment
        plan["slots"][1]["brief"]["angle"] = "danger"  # in the hook test
        problems = self.problems(plan)
        self.assertTrue(any("slot 11: length differ(s) from the default" in p for p in problems))
        self.assertTrue(any("slot 2: only hook may differ" in p for p in problems))

    def test_a_new_test_needs_three_videos_per_value(self):
        plan = good_plan()
        plan["slots"][5]["experiment"] = ""
        plan["slots"][5]["brief"]["hook"] = "question"
        self.assertTrue(any("'cold-scene' has 2 slot(s)" in p for p in self.problems(plan)))

    def test_too_much_exploring_is_refused_unless_calibrating(self):
        plan = good_plan()
        for i, slot in enumerate(plan["slots"][6:12]):
            slot["experiment"] = "w47-length"
            slot["brief"]["length"] = 45 if i % 2 == 0 else 35
        plan["experiments"].append({"id": "w47-length", "lever": "length", "values": [35, 45], "hypothesis": "longer holds"})
        ctx = self.context()  # calibrating: 6 of 14 exploring (43%) is allowed
        self.assertEqual(self.problems(plan, ctx), [])
        ctx.packet["calibrating"] = False
        self.assertIn(
            "6 of 14 slots differ from the defaults; at most 40% may (keep most videos on what works)", self.problems(plan, ctx)
        )

    def test_repeated_and_duplicate_topics_are_refused(self):
        store.add_slots("animation", [{"date": "2026-11-10", "time": "10:00", "brief": {"topic": "The science of cat purring"}}])
        plan = good_plan()
        plan["reserves"][0]["brief"]["topic"] = "Why do bees make honey?"
        problems = self.problems(plan)
        self.assertTrue(any("'Why do cats purr' repeats 'The science of cat purring'" in p for p in problems))
        self.assertTrue(any("are the same topic" in p for p in problems))

    def test_defaults_need_an_adopted_belief_and_a_baseline(self):
        plan = {**good_plan(), "defaults": {"length": 45}}
        problems = self.problems(plan)
        self.assertTrue(any("calibrating" in p for p in problems))
        self.assertTrue(any("needs an adopted belief about length" in p for p in problems))

    def test_adoption_is_counted_from_real_experiments_not_the_models_claim(self):
        ctx = self.context()
        ctx.packet["calibrating"] = False
        belief = {"id": "b1", "claim": "45s wins", "status": "adopted", "lever": "length", "evidence": ["w45-length"], "videos_per_arm": [99, 99]}
        self.assertTrue(any("unknown experiment 'w45-length'" in p for p in self.problems({**good_plan(), "beliefs": [belief]}, ctx)))

        winner = {"status": "winner"}
        ctx.judged = {
            "w45-length": {"lever": "length", "week": "2026-W45", "verdict": winner, "arms": [{"value": 35, "scored": 3}, {"value": 45, "scored": 3}]},
            "w46-length": {"lever": "length", "week": "2026-W46", "verdict": winner, "arms": [{"value": 35, "scored": 3}, {"value": 45, "scored": 4}]},
        }
        belief["evidence"] = ["w45-length", "w46-length"]
        plan = {**good_plan(), "beliefs": [belief], "defaults": {"length": 45}}
        for slot in plan["slots"] + plan["reserves"]:
            slot["brief"]["length"] = 45  # the new default
        clean, problems = planner.check_plan(ctx, plan)
        self.assertEqual(problems, [])
        self.assertEqual(clean["beliefs"][0]["videos_per_arm"], [6, 7])
        self.assertEqual(clean["beliefs"][0]["weeks"], ["2026-W45", "2026-W46"])

    def test_over_budget_is_refused(self):
        ctx = self.context()
        ctx.video_cost = 1.0
        self.assertTrue(any("over the $10.0 weekly budget" in p for p in self.problems(good_plan(), ctx)))


class TestAgentLoop(PlannerTestCase):
    def test_an_accepted_plan_is_booked_with_its_timeline(self):
        note = store.add_note("animation", "More animal topics please")
        plan = {**good_plan(), "note_replies": [{"note_id": note["id"], "reply": "Added cats, bees, octopuses and whales."}]}
        result, client = self.run_planner(
            reply(calls=[call("c1", "check_topics", {"topics": TOPICS})]),
            reply(calls=[call("c2", "submit_plan", plan)], cost=0.01),
        )
        self.assertTrue(result["ok"], result)
        queue = store.load_queue("animation")
        self.assertEqual((len(queue), sum(s["reserve"] for s in queue)), (16, 2))
        self.assertEqual(upload_budget.daily_load(DAYS[0])["studios"], 2)
        self.assertEqual(store.load_experiments("animation")[0]["id"], "w47-hook")
        self.assertEqual(store.list_notes("animation", unread_only=True), [])
        event = store.list_events("animation", types=("plan",))[0]
        self.assertIn("14 video(s) planned, 3 exploring", event["summary"])
        self.assertEqual(event["data"]["planner_cost"], 0.012)
        self.assertEqual(event["data"]["note_replies"][0]["reply"], "Added cats, bees, octopuses and whales.")
        self.assertIn("tools", client.calls[0])
        self.assertIn("Paper Explainers", client.calls[0]["messages"][0]["content"])
        checked = json.loads(client.calls[1]["messages"][-1]["content"])
        self.assertTrue(all(c["new"] for c in checked))

    def test_problems_go_back_to_the_model_and_a_fixed_plan_is_accepted(self):
        broken = good_plan()
        broken["slots"].pop()
        result, client = self.run_planner(
            reply(calls=[call("c1", "submit_plan", broken)]),
            reply(calls=[call("c2", "submit_plan", good_plan())]),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["submissions"], 2)
        feedback = json.loads(client.calls[1]["messages"][-1]["content"])
        self.assertFalse(feedback["accepted"])
        self.assertIn("2026-11-22 needs 2 slot(s); the plan has 1", feedback["problems"])

    def test_three_rejections_end_in_an_incident_and_book_nothing(self):
        broken = {"review": "too short"}
        result, _ = self.run_planner(*[reply(calls=[call(f"c{i}", "submit_plan", broken)]) for i in range(3)])
        self.assertFalse(result["ok"])
        self.assertEqual(store.load_queue("animation"), [])
        incident = store.list_events("animation", types=("incident",))[0]
        self.assertIn("3 submissions were rejected", incident["summary"])
        self.assertTrue(incident["data"]["problems"])

    def test_a_model_that_never_submits_is_nudged_once(self):
        result, client = self.run_planner(reply("Here is my plan in prose."), reply("Still prose."))
        self.assertFalse(result["ok"])
        self.assertEqual(client.calls[1]["messages"][-1]["content"], "Submit the plan now with submit_plan.")
        self.assertIn("submitted no plan", result["error"])

    def test_a_model_error_is_an_incident_not_a_crash(self):
        result, _ = self.run_planner(*[])
        self.assertFalse(result["ok"])
        self.assertEqual(store.list_events("animation", types=("incident",))[0]["data"]["stage"], "plan")

    def test_nothing_to_plan_when_the_week_is_booked(self):
        self.run_planner(reply(calls=[call("c1", "submit_plan", good_plan())]))
        result, client = self.run_planner()
        self.assertTrue(result["skipped"])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
