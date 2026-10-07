"""Analytics Assistant: metric tags, chat history and the agent loop."""
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services.analytics import assistant, report, tags  # noqa: E402
from app.services.animation import llm as anim_llm  # noqa: E402
from test.services.test_analytics import StorageTestCase, item, video  # noqa: E402

DAY = 86400


def dataset():
    """8 animations (space does best), 2 shorts and one old non-app upload."""
    now = time.time()
    items, videos, metrics = [], [], {}
    for n in range(8):
        setting = "space" if n < 4 else "forest"
        items.append(item(f"animation:p{n}", [f"Animation {n} {setting}"], created_at=now - 40 * DAY, studio="animation",
                          batch_id="b1" if n < 3 else "", batch_size=3 if n < 3 else 1,
                          features={"Main setting": setting, "Characters": "astronaut" if setting == "space" else "animal"}))
        videos.append(video(f"vid0000000{n}", f"Animation {n} {setting}", published=now - 20 * DAY, views=1000 if setting == "space" else 100))
        metrics[f"vid0000000{n}"] = {"averageViewPercentage": 80.0 if setting == "space" else 40.0}
    for n in range(2):
        items.append(item(f"shorts:t{n}/final-1.mp4", [f"Short {n}"], created_at=now - 400 * DAY, studio="shorts", features={"Footage source": "pexels"}))
        videos.append(video(f"vidshort000{n}", f"Short {n}", published=now - 300 * DAY, views=500))
    videos.append(video("vid0000other", "My first vlog", published=now - 30 * DAY, views=5))
    return report.build_dataset(items, videos, metrics, {"categories": {"Animation 0 space": "Space"}})


def reply(text=None, calls=None, cost=0.001):
    message = SimpleNamespace(content=text, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=SimpleNamespace(cost=cost, model_extra=None))


def tool_call(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class TestTags(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.df = dataset()

    def test_builtin_tags_cover_every_current_metric(self):
        ids = {t["id"] for t in tags.builtin_tags(self.df)}
        for expected in (
            "builtin:overview", "builtin:top", "builtin:batches", "builtin:category",
            "builtin:animation:Main setting", "builtin:animation:Characters", "builtin:animation:videos",
            "builtin:animation:insights", "builtin:shorts:Footage source", "builtin:animation:generation",
        ):
            self.assertIn(expected, ids)
        self.assertFalse(any(i.startswith("builtin:documentary") for i in ids))  # no documentaries in the data

    def test_breakdown_render_shows_groups_with_counts(self):
        text = tags.render(tags.get_tag("builtin:animation:Main setting", self.df), self.df)["text"]
        self.assertIn("8 published videos", text)
        header, space, forest = text.splitlines()[-3:]
        self.assertTrue(header.startswith("Main setting,Videos"))
        self.assertTrue(space.startswith("space,4,4000,1000"))
        self.assertTrue(forest.startswith("forest,4,400,100"))

    def test_videos_top_batches_and_insights_render(self):
        videos = tags.render(tags.get_tag("builtin:animation:videos", self.df), self.df)
        self.assertEqual(videos["videos"], 8)
        self.assertIn("Animation 0 space", videos["text"])
        self.assertIn("Main setting", videos["text"])  # the studio's style columns
        self.assertNotIn("My first vlog", videos["text"])  # not from the app
        self.assertIn("Best 15", tags.render(tags.get_tag("builtin:top", self.df), self.df)["text"])
        self.assertIn("3 videos", tags.render(tags.get_tag("builtin:batches", self.df), self.df)["text"])
        insights = tags.render(tags.get_tag("builtin:animation:insights", self.df), self.df)["text"]
        self.assertIn("Main setting = space", insights)

    def test_custom_tags_filter_save_and_delete(self):
        tag = tags.save_tag("Space animations", "animation", {"Main setting": ["space"]}, group_by="Characters", description="my best style")
        self.assertEqual(tag["kind"], "breakdown")
        self.assertIn(tag["id"], {t["id"] for t in tags.all_tags(self.df)})
        rendered = tags.render(tag, self.df)
        self.assertEqual(rendered["videos"], 4)
        self.assertIn("Only videos where Main setting = space", rendered["text"])
        self.assertIn("my best style", rendered["text"])
        with self.assertRaises(ValueError):
            tags.save_tag("space ANIMATIONS")  # names are unique
        with self.assertRaises(ValueError):
            tags.save_tag("")
        with self.assertRaises(ValueError):
            tags.save_tag("x", studio="podcasts")
        listing = tags.save_tag("Fables", "animation", {"Characters": ["animal"]})
        self.assertEqual(listing["kind"], "videos")
        tags.delete_tag(tag["id"])
        self.assertEqual([t["name"] for t in tags.custom_tags()], ["Fables"])

    def test_a_filter_on_an_unknown_setting_matches_nothing(self):
        tag = {"id": "x", "name": "x", "kind": "videos", "studio": "animation", "group_by": "", "filters": {"Not a setting": ["a"]}}
        self.assertIn("No published videos match", tags.render(tag, self.df)["text"])


class TestHistory(StorageTestCase):
    def test_chats_save_list_rename_and_delete(self):
        first, second = assistant.new_chat(model="m1"), assistant.new_chat(model="m2")
        self.assertEqual(assistant.list_chats(), [])  # unsaved until used
        first["messages"].append({"role": "user", "content": "hi"})
        assistant.save_chat(first)
        time.sleep(0.01)
        assistant.save_chat(second)
        self.assertEqual([c["id"] for c in assistant.list_chats()], [second["id"], first["id"]])
        self.assertEqual(assistant.list_chats()[1]["messages"], 1)
        self.assertEqual(assistant.rename_chat(first["id"], "Styles")["title"], "Styles")
        assistant.delete_chat(first["id"])
        self.assertIsNone(assistant.load_chat(first["id"]))
        self.assertEqual(assistant.delete_all_chats(), 1)
        self.assertEqual(assistant.list_chats(), [])
        self.assertIsNone(assistant.load_chat("../../etc/passwd"))  # ids can't be paths
        with self.assertRaises(ValueError):
            assistant._chat_path("../x")

    def test_titles_and_default_model(self):
        self.assertEqual(assistant.title_from("  Which   styles work? "), "Which styles work?")
        self.assertTrue(assistant.title_from("x" * 200).endswith("…"))
        with patch.dict(assistant.config.assistant, {"model": ""}), patch.object(anim_llm, "model_for", return_value="writer/model"):
            self.assertEqual(assistant.default_model(), "writer/model")
            with patch.object(assistant.config, "save_config") as save:
                assistant.set_default_model("openai/gpt-x")
                save.assert_called_once()
            self.assertEqual(assistant.default_model(), "openai/gpt-x")


class TestAgent(StorageTestCase):
    def setUp(self):
        super().setUp()
        self.df = dataset()
        self.chat = assistant.new_chat(model="test/model", refs=["builtin:animation:Main setting"])

    def test_tool_loop_answers_from_looked_up_data_and_saves_the_turn(self):
        client = FakeClient(
            reply(calls=[tool_call("c1", "get_data", {"tag_id": "builtin:animation:Characters"})], cost=0.002),
            reply("Space with astronauts wins: 1,000 median views vs 100.", cost=0.003),
        )
        steps = []
        answer = assistant.ask(self.chat, "Which animation styles work?", self.df, client=client, on_step=steps.append)
        self.assertIn("Space", answer["content"])
        self.assertEqual(steps, ["get_data builtin:animation:Characters"])
        system = client.calls[0]["messages"][0]["content"]
        self.assertIn("Main setting", system)  # the attached tag's data
        self.assertIn("space,4", system)
        self.assertEqual(client.calls[0]["tools"][1]["function"]["name"], "get_data")
        tool_reply = client.calls[1]["messages"][-1]
        self.assertEqual(tool_reply["role"], "tool")
        self.assertIn("astronaut", tool_reply["content"])
        saved = assistant.load_chat(self.chat["id"])
        self.assertEqual([m["role"] for m in saved["messages"]], ["user", "assistant"])
        self.assertEqual(saved["title"], "Which animation styles work?")
        self.assertEqual(saved["messages"][1]["tools"], [{"name": "get_data", "args": {"tag_id": "builtin:animation:Characters"}}])
        self.assertAlmostEqual(saved["cost"], 0.005)
        # the next question carries the conversation
        client = FakeClient(reply("Because of retention."))
        assistant.ask(saved, "Why?", self.df, client=client)
        self.assertEqual([m["role"] for m in client.calls[0]["messages"]], ["system", "user", "assistant", "user"])

    def test_models_without_tool_support_answer_from_attached_data(self):
        client = FakeClient(Exception("Error code: 404 - No endpoints found that support tool use"), reply("From the attached data: space."))
        answer = assistant.ask(self.chat, "Which styles?", self.df, client=client)
        self.assertEqual(answer["content"], "From the attached data: space.")
        self.assertIn("tools", client.calls[0])
        self.assertNotIn("tools", client.calls[1])

    def test_failures_are_saved_as_errors_and_kept_out_of_later_prompts(self):
        with self.assertRaises(assistant.AssistantError):
            assistant.ask(self.chat, "First?", self.df, client=FakeClient(RuntimeError("rate limited")))
        saved = assistant.load_chat(self.chat["id"])
        self.assertTrue(saved["messages"][-1]["error"])
        self.assertIn("rate limited", saved["messages"][-1]["content"])
        client = FakeClient(reply("ok"))
        assistant.ask(saved, "Second?", self.df, client=client)
        self.assertEqual([m["content"] for m in client.calls[0]["messages"][1:]], ["First?", "Second?"])

    def test_no_key_gives_a_clear_error(self):
        with patch.object(anim_llm, "_client", return_value=None):
            with self.assertRaises(assistant.AssistantError) as raised:
                assistant.ask(self.chat, "Hi", self.df)
        self.assertIn("OpenRouter key", str(raised.exception))

    def test_tool_rounds_are_capped(self):
        loop = [reply(calls=[tool_call(f"c{n}", "list_data", {})]) for n in range(2)]
        client = FakeClient(*loop, reply("Final."))
        answer = assistant.ask(self.chat, "Loop?", self.df, client=client, max_rounds=2)
        self.assertEqual(answer["content"], "Final.")
        self.assertNotIn("tools", client.calls[-1])
        self.assertIn("no more tool calls", client.calls[-1]["messages"][-1]["content"])

    def test_tools(self):
        listing = assistant.run_tool("list_data", {}, self.df)
        self.assertIn("builtin:animation:Main setting | Animation", listing.replace("Animations", "Animation"))
        found = assistant.run_tool("find_videos", {"studio": "animation", "title_contains": "SPACE", "sort_by": "views", "limit": 2}, self.df)
        self.assertTrue(found.startswith("4 match; showing 2"))
        self.assertNotIn("forest", found)
        self.assertIn("No tag", assistant.run_tool("get_data", {"tag_id": "nope"}, self.df))
        self.assertIn("Unknown tool", assistant.run_tool("rm_rf", {}, self.df))
        self.assertIn("No published videos match", assistant.run_tool("find_videos", {"title_contains": "zzz"}, self.df))

    def test_data_range_and_context_cap(self):
        self.assertEqual(len(assistant.scope(self.df, "90 days")), 9)  # the two 300-day-old shorts drop out
        self.assertEqual(len(assistant.scope(self.df, "All time")), 11)
        with patch.object(assistant, "MAX_CONTEXT_CHARS", 200):
            text = assistant.context_text(["builtin:animation:videos", "gone:tag"], self.df)
        self.assertTrue(text.endswith("use get_data for the rest)"))
        self.assertIn("no longer exists", assistant.context_text(["gone:tag"], self.df))


if __name__ == "__main__":
    unittest.main()
