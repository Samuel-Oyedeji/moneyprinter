"""End to end: script → storyboard → voice-over → real Remotion render → YouTube copy.

The LLM and the voice are mocked (no network, no cost); the render is real,
at quarter scale, so this needs Node and remotion/node_modules and takes
about half a minute. It is skipped when the renderer isn't available.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services.animation import compose, llm, pipeline, render, store, tts  # noqa: E402
from app.utils import utils  # noqa: E402

STORYBOARD = {
    "title": "The Lighthouse Keeper",
    "cast": [{"id": "keeper", "age": "elder", "skin": "brown", "facialHair": "beard", "top": {"style": "coat", "color": "#4f7fbf"}}],
    "scenes": [
        {
            "narration": "Every night, the old keeper climbed his tower.",
            "sky": "night", "ground": "sea", "camera": "push",
            "people": [{"who": "keeper", "place": "left", "enter": "walk-in-left", "holding": {"prop": "candle", "pose": "up"}}],
            "props": [{"prop": "custom", "name": "lighthouse", "place": "right", "size": "large", "aspect": 0.4, "shapes": [
                {"type": "rect", "x": 0.25, "y": 0.15, "w": 0.5, "h": 0.85, "color": "#f6efdc"},
                {"type": "rect", "x": 0.25, "y": 0.45, "w": 0.5, "h": 0.1, "color": "#d1495b"},
                {"type": "poly", "points": [[0.15, 0.17], [0.5, 0.0], [0.85, 0.17]], "color": "#d1495b"},
            ], "actions": [{"do": "tilt", "cue": "tower", "deg": 4}]}],
            "notes": [{"kind": "label", "text": "the lighthouse", "target": "lighthouse", "cue": "climbed"}],
        },
        {
            "narration": "Ships came home safely.",
            "sky": "dusk", "ground": "hills",
            "props": [{"prop": "boat", "place": "center", "size": "medium", "enter": "slide-left", "cue": "Ships"}],
            "notes": [{"kind": "stamp", "text": "70%", "cue": "safely"}],
        },
    ],
}
SCRIPT = "Every night, the old keeper climbed his tower. Ships came home safely."
METADATA = {"title": "The Keeper Who Never Slept", "description": "Line one.\n\nMore.", "hashtags": ["#Lighthouse"], "tags": ["lighthouse"]}


LLM_PROMPTS: list[str] = []
SCRIPT_CALLS: list[list[dict]] = []


def fake_llm(prompt, on_cost=None, role="writer"):
    LLM_PROMPTS.append(prompt)
    if on_cost:
        on_cost(0.01)
    return METADATA if "SEO copywriter" in prompt else json.loads(json.dumps(STORYBOARD))


def fake_script_model(messages, role="writer", on_cost=None):
    SCRIPT_CALLS.append(messages)
    if on_cost:
        on_cost(0.01)
    return f"TITLE: The Keeper's Light\n\nSCRIPT:\n{SCRIPT}"


def fake_voice(text, voice, out_path):
    """Silent audio of the right length plus evenly spaced word timings."""
    tokens = text.split()
    duration = round(0.32 * len(tokens) + 0.4, 2)
    subprocess.run(
        [utils.get_ffmpeg_binary(), "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", str(duration), "-q:a", "9", out_path],
        check=True, capture_output=True,
    )
    words = [{"text": t, "at": round(0.2 + i * 0.32, 3), "end": round(0.45 + i * 0.32, 3)} for i, t in enumerate(tokens)]
    return {"words": words, "duration": duration, "cost": 0.004, "provider": "fake", "chars": len(text)}


def renderer_available() -> bool:
    ok, _ = render.readiness()
    return ok and os.path.isdir(os.path.join(render.remotion_dir(), "node_modules", "@remotion"))


@unittest.skipUnless(renderer_available(), "Node/Remotion not installed")
class TestAnimationPipeline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        LLM_PROMPTS.clear()
        SCRIPT_CALLS.clear()
        for target, attr, value in (
            (store, "animation_dir", lambda: self._tmp.name),
            (llm, "generate_json", fake_llm),
            (llm, "chat", fake_script_model),
            (tts, "synthesize", fake_voice),
        ):
            patcher = patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_topic_to_rendered_video_with_youtube_copy(self):
        project = store.create_project("The lighthouse keeper", "a moral about duty", seconds=15, aspect="9:16", voice="elevenlabs:x:y")
        stages = []
        done = pipeline.run_project(project["project_id"], on_stage=stages.append, render_scale=0.25)
        self.assertEqual(done["status"], store.STATUS_DONE, done.get("error"))
        pid = done["project_id"]

        story = store.read_json(store.path(pid, "story.json"))
        self.assertEqual((story["width"], story["height"]), (1080, 1920))
        self.assertEqual(story["scenes"][0]["actors"][0]["prop"], "shapes")  # the custom lighthouse
        self.assertTrue(os.path.isfile(store.thumb_path(pid)))

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height", "-of", "json", store.final_path(pid)],
            capture_output=True, text=True,
        )
        info = json.loads(probe.stdout)
        self.assertAlmostEqual(float(info["format"]["duration"]), compose.story_duration(story), delta=0.3)
        self.assertEqual((info["streams"][0]["width"], info["streams"][0]["height"]), (270, 480))  # quarter scale

        meta = done["youtube"]
        self.assertEqual(meta["title"], "The Keeper Who Never Slept")
        self.assertEqual(meta["hashtags"][:2], ["#Shorts", "#Lighthouse"])
        # The script model got its own system prompt and the topic, length and
        # notes; its 12 words are too few for 15 seconds, so it was asked twice
        # to rewrite, then kept (the rewrites were no closer).
        self.assertEqual(len(SCRIPT_CALLS), 3)
        system, request = SCRIPT_CALLS[0]
        self.assertEqual(system["role"], "system")
        self.assertIn("Shorts Scriptwriter", system["content"])
        self.assertEqual(request["content"], "TOPIC: The lighthouse keeper\nDURATION: 15 seconds (38 to 45 words)\nNOTES: a moral about duty")
        self.assertIn("must be", SCRIPT_CALLS[1][-1]["content"])
        written = store.read_json(store.path(pid, "script.json"))
        self.assertEqual((written["title"], written["text"]), ("The Keeper's Light", SCRIPT))
        self.assertEqual(story["title"], "The Keeper's Light")  # the script's title is the working title
        # The writer staged that exact script in one pass
        storyboard_prompts = [p for p in LLM_PROMPTS if "SEO copywriter" not in p]
        self.assertEqual(len(storyboard_prompts), 1)
        self.assertIn(SCRIPT, storyboard_prompts[0])
        self.assertEqual(store.read_json(store.path(pid, "words.json"))["chars"], len(SCRIPT))
        self.assertEqual(set(done["models"]), {"script", "writer"})
        self.assertAlmostEqual(store.total_cost(done), 0.054, places=3)  # 5 LLM calls + the voice
        self.assertIn("Rendering 100%", stages)
        self.assertEqual(stages[-1], "Done")

        # redoing only the metadata reuses the storyboard, voice and render
        pipeline.reset_from(pid, "package")
        with patch.object(tts, "synthesize", side_effect=AssertionError("voice redone")), patch.object(
            render, "render_story", side_effect=AssertionError("render redone")
        ):
            again = pipeline.run_project(pid)
        self.assertEqual(again["status"], store.STATUS_DONE, again.get("error"))


if __name__ == "__main__":
    unittest.main()
