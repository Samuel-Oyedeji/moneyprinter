"""Script writer (own model + system prompt) → animation writer (same words, staged)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.config import config  # noqa: E402
from app.services.animation import llm, pipeline, script, store, storyboard  # noqa: E402

SCRIPT = (
    "In 1173, builders in Pisa began a bell tower. Five years later, it started to lean. "
    "The ground beneath it was soft clay. Today it still stands, tilted and famous."
)


class FakeClient:
    """Stands in for the OpenRouter client: records calls, replies from a list."""

    base_url = "https://openrouter.ai/api/v1"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, extra_body=None):
        self.calls.append({"model": model, "messages": messages})
        content = self.replies.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(cost=0.01, model_extra={}),
        )


class ModelSettingsCase(unittest.TestCase):
    def setUp(self):
        for section in (config.animation, config.documentary):
            patcher = patch.dict(section, {})
            patcher.start()
            self.addCleanup(patcher.stop)
        for key in ("script_model", "writer_model", "llm_model_name", "llm_provider"):
            config.animation.pop(key, None)
            config.documentary.pop(key, None)


class TestModels(ModelSettingsCase):
    def test_each_role_resolves_its_own_model(self):
        self.assertEqual((llm.model_for("script"), llm.model_for("writer")), (llm.DEFAULT_MODEL, llm.DEFAULT_MODEL))
        config.documentary["llm_model_name"] = "doc/model"
        self.assertEqual(llm.model_for("writer"), "doc/model")
        config.animation["writer_model"] = "openai/gpt-5.6-terra"
        self.assertEqual(llm.model_for("script"), "openai/gpt-5.6-terra")  # empty script model follows the writer
        config.animation["script_model"] = "anthropic/claude-opus-5.5"
        self.assertEqual((llm.model_for("script"), llm.model_for("writer")), ("anthropic/claude-opus-5.5", "openai/gpt-5.6-terra"))

    def test_openrouter_catalogue_keeps_text_models_with_prices(self):
        data = {
            "data": [
                {"id": "b/text", "name": "B", "context_length": 1000, "pricing": {"prompt": "0.000003", "completion": "0.000015"},
                 "architecture": {"output_modalities": ["text"]}},
                {"id": "b/text:batch", "name": "B batch", "pricing": {}},
                {"id": "a/image", "name": "Img", "pricing": {}, "architecture": {"output_modalities": ["image"]}},
                {"id": "a/free", "name": "Free", "pricing": {"prompt": "0", "completion": "0"}},
            ]
        }
        response = SimpleNamespace(json=lambda: data, raise_for_status=lambda: None)
        with patch.object(llm.requests, "get", return_value=response):
            models = llm.openrouter_models()
        self.assertEqual([m["id"] for m in models], ["a/free", "b/text"])
        self.assertEqual((models[1]["prompt"], models[1]["completion"]), (3.0, 15.0))
        self.assertEqual(models[0]["prompt"], 0.0)


class TestScriptWriter(ModelSettingsCase):
    def template(self, text: str):
        path = os.path.join(self._tmp.name, "prompt.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        patcher = patch.object(script, "PROMPT_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_the_real_prompt_gets_topic_duration_and_notes_in_the_request(self):
        system, request = script.build_messages("What if Earth were a cube?", "Keep it playful.", 30)
        self.assertTrue(system["content"].startswith("# System Prompt: Animated Explainer Shorts Scriptwriter"))
        self.assertNotIn("<!--", system["content"])  # the header note is stripped
        self.assertEqual(request, {"role": "user", "content": "TOPIC: What if Earth were a cube?\nDURATION: 30 seconds (75 to 90 words)\nNOTES: Keep it playful."})
        # no notes: the optional NOTES line is left out
        _, bare = script.build_messages("How do lasers work?", "", 55)
        self.assertEqual(bare["content"], "TOPIC: How do lasers work?\nDURATION: 55 seconds (138 to 165 words)")

    def test_placeholders_put_the_values_inside_the_prompt_instead(self):
        self.template("<!-- notes for me -->\nStyle rules.\nTopic: {topic}\nAbout: {description}\nLength: {duration}, {words}.")
        system, request = script.build_messages("The Leaning Tower", "", 30)
        self.assertEqual(system["content"], "Style rules.\nTopic: The Leaning Tower\nAbout: (none)\nLength: 30 seconds, 75 to 90 words.")
        self.assertEqual(request["content"], "Write the script.")  # never an empty turn

    def test_word_range_matches_the_prompts_length_table(self):
        for seconds, low, high in ((20, 50, 60), (30, 75, 90), (55, 138, 165), (60, 150, 180), (90, 225, 270)):
            self.assertEqual(script.word_range(seconds)[1:], (low, high))

    def test_title_and_beats_are_read_from_the_reply(self):
        reply = (
            "TITLE: What If Earth Were a Cube?\n\nSCRIPT:\n"
            "Earth, but as a cube.   Let's do it.\n\n"
            "Gravity pulls toward the centre,\nso every face becomes a slope.\n\n"
            "Which would make for a very long walk to the edge of..."
        )
        title, text = script.parse_reply(f"```\n{reply}\n```")
        self.assertEqual(title, "What If Earth Were a Cube?")
        self.assertEqual(
            text.split("\n\n"),
            [
                "Earth, but as a cube. Let's do it.",
                "Gravity pulls toward the centre, so every face becomes a slope.",
                "Which would make for a very long walk to the edge of...",
            ],
        )
        self.assertEqual(script.parse_reply("**TITLE:** Lasers\n**SCRIPT:**\nLight, in step.")[0], "Lasers")
        self.assertEqual(script.parse_reply("Just a bare script."), ("", "Just a bare script."))

    def test_script_call_uses_the_script_model_and_fixes_the_length(self):
        self.template("House style.")
        config.animation["script_model"] = "anthropic/claude-opus-5.5"
        config.animation["writer_model"] = "openai/gpt-5.6-terra"
        too_short = "TITLE: Pisa\n\nSCRIPT:\nThe tower leaned."
        closer = f"TITLE: Why Pisa Leans\n\nSCRIPT:\n{SCRIPT}"  # 30 words: closer, still short
        client = FakeClient([too_short, closer, closer])
        costs = []
        with patch.object(llm, "_client", return_value=client):
            result = script.write_script("The Leaning Tower", "Soft clay.", 15, on_cost=costs.append)
        self.assertEqual(result, {"title": "Why Pisa Leans", "text": SCRIPT, "words": 30, "model": "anthropic/claude-opus-5.5"})
        self.assertEqual([c["model"] for c in client.calls], ["anthropic/claude-opus-5.5"] * 3)
        first, retry = client.calls[0]["messages"], client.calls[1]["messages"]
        self.assertEqual(first, [
            {"role": "system", "content": "House style."},
            {"role": "user", "content": "TOPIC: The Leaning Tower\nDURATION: 15 seconds (38 to 45 words)\nNOTES: Soft clay."},
        ])
        # the rewrite is a follow-up turn in the same conversation
        self.assertEqual(retry[:2], first)
        self.assertEqual(retry[2], {"role": "assistant", "content": too_short})
        self.assertIn("must be 38 to 45 words", retry[3]["content"])
        self.assertEqual(costs, [0.01] * 3)

    def test_a_long_script_gets_a_second_rewrite_and_the_closest_is_kept(self):
        self.template("House style.")
        long, longer, right = (" ".join(["word"] * n) + "." for n in (130, 140, 84))
        client = FakeClient([f"SCRIPT:\n{long}", f"SCRIPT:\n{longer}", f"SCRIPT:\n{right}"])
        with patch.object(llm, "_client", return_value=client):
            result = script.write_script("Anything", "", 30)
        self.assertEqual(result["words"], 84)
        third = client.calls[2]["messages"]
        # each rewrite continues the conversation from the latest reply
        self.assertEqual([m["role"] for m in third], ["system", "user", "assistant", "user", "assistant", "user"])
        self.assertIn("That script is 140 words", third[-1]["content"])

    def test_a_script_inside_the_range_is_not_rewritten(self):
        self.template("House style.")
        in_range = " ".join(["word"] * 80) + "."
        client = FakeClient([f"TITLE: Fine\n\nSCRIPT:\n{in_range}"])
        with patch.object(llm, "_client", return_value=client):
            self.assertEqual(script.write_script("Anything", "", 30)["words"], 80)
        self.assertEqual(len(client.calls), 1)


class TestAnimationWriter(ModelSettingsCase):
    def board(self, *narrations):
        return {"title": "Pisa", "cast": [], "scenes": [{"narration": n, "sky": "day"} for n in narrations]}

    def test_writer_is_given_the_script_and_retried_when_it_edits_it(self):
        edited = self.board("In 1173 builders in Pisa started a bell tower.", "Five years later, it started to lean. The ground was soft clay.",
                            "Today it still stands, tilted and famous.")
        exact = self.board("In 1173, builders in Pisa began a bell tower.", "Five years later, it started to lean. The ground beneath it was soft clay.",
                           "Today it still stands, tilted and famous.")
        calls = []

        def fake(prompt, on_cost=None, role="writer"):
            calls.append((prompt, role))
            return [edited, exact][len(calls) - 1]

        with patch.object(llm, "generate_json", side_effect=fake):
            board = storyboard.write_storyboard("The Leaning Tower", "Soft clay.", SCRIPT, "9:16")
        self.assertIn(SCRIPT, calls[0][0])
        self.assertEqual([r for _, r in calls], ["writer", "writer"])
        self.assertIn("word for word", calls[1][0])
        self.assertEqual(storyboard.narration_text(board), SCRIPT)

    def test_leftover_edits_are_corrected_from_the_script(self):
        # changed ("started"), dropped ("beneath it") and added ("very") words
        edited = self.board(
            "In 1173, builders in Pisa started a bell tower.",
            "Five years later, it started to lean. The ground was very soft clay.",
            "Today it still stands, tilted and famous.",
        )
        fixed = storyboard.align_to_script(edited, SCRIPT)
        self.assertEqual(
            [s["narration"] for s in fixed["scenes"]],
            [
                "In 1173, builders in Pisa began a bell tower.",
                "Five years later, it started to lean. The ground beneath it was soft clay.",
                "Today it still stands, tilted and famous.",
            ],
        )
        self.assertEqual(fixed["scenes"][0]["sky"], "day")  # staging kept

    def test_missing_ending_is_restored_to_the_last_scene(self):
        fixed = storyboard.align_to_script(self.board("In 1173, builders in Pisa began a bell tower.", "Five years later, it started to lean."), SCRIPT)
        self.assertEqual(storyboard.narration_text(fixed), SCRIPT)
        self.assertEqual(len(fixed["scenes"]), 2)


class TestRedo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(store, "animation_dir", lambda: self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_new_scenes_keep_the_script_and_a_new_script_redoes_everything(self):
        pid = store.create_project("Pisa", voice="x")["project_id"]
        for name in ("script.json", "storyboard.json"):
            store.write_json(store.path(pid, name), {"text": SCRIPT})
        pipeline.reset_from(pid, "storyboard")
        self.assertTrue(os.path.isfile(store.path(pid, "script.json")))
        self.assertFalse(os.path.isfile(store.path(pid, "storyboard.json")))
        pipeline.reset_from(pid, "script")
        self.assertFalse(os.path.isfile(store.path(pid, "script.json")))


if __name__ == "__main__":
    unittest.main()
