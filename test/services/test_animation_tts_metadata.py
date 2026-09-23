"""ElevenLabs word timings and YouTube metadata rules for animations."""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services.animation import metadata, tts  # noqa: E402


def alignment_for(text: str, per_char: float = 0.05) -> dict:
    chars, starts, ends = [], [], []
    t = 0.0
    for ch in text:
        chars.append(ch)
        starts.append(round(t, 3))
        t += per_char
        ends.append(round(t, 3))
    return {"characters": chars, "character_start_times_seconds": starts, "character_end_times_seconds": ends}


class TestWordTimings(unittest.TestCase):
    def test_alignment_becomes_words_with_punctuation(self):
        words = tts.words_from_alignment(alignment_for("In 1928, a  scientist came home."))
        self.assertEqual([w["text"] for w in words], ["In", "1928,", "a", "scientist", "came", "home."])
        self.assertEqual(words[0]["at"], 0.0)
        self.assertEqual(words[1]["at"], 0.15)  # after "In" and the space
        self.assertAlmostEqual(words[1]["end"], 0.4, places=3)
        self.assertTrue(all(w["end"] > w["at"] for w in words))

    def test_edge_boundaries_get_the_scripts_punctuation_back(self):
        raw = [{"text": "In 1928", "at": 0.1, "end": 1.4}, {"text": "a", "at": 1.5, "end": 1.6}, {"text": "scientist", "at": 1.6, "end": 2.2}]
        words = tts.reattach_punctuation("In 1928, a scientist.", raw)
        self.assertEqual([w["text"] for w in words], ["In 1928,", "a", "scientist."])

    def test_elevenlabs_synthesis_writes_audio_and_prices_by_character(self):
        text = "Every night, a little sun watched over the town."
        response = MagicMock(status_code=200)
        response.json.return_value = {"audio_base64": base64.b64encode(b"ID3fake").decode(), "alignment": alignment_for(text)}
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts.requests, "post", return_value=response) as post, patch.object(
            tts.voice_service, "get_elevenlabs_api_key", return_value="key"
        ), patch.object(tts, "_audio_duration", return_value=2.6), patch.object(tts, "price_per_1k_chars", return_value=0.1):
            out = os.path.join(tmp, "public", "narration.mp3")
            result = tts.synthesize(text, "elevenlabs:VOICE123:Alyx", out)
            self.assertTrue(os.path.isfile(out))
            self.assertIn("VOICE123/with-timestamps", post.call_args.args[0])
        self.assertEqual(result["provider"], "elevenlabs")
        self.assertEqual(len(result["words"]), len(text.split()))
        self.assertAlmostEqual(result["cost"], len(text) / 1000 * 0.1, places=5)
        self.assertEqual(result["duration"], 2.6)

    def test_missing_key_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(tts.voice_service, "get_elevenlabs_api_key", return_value=""):
            with self.assertRaisesRegex(tts.TTSError, "API key"):
                tts.synthesize("hello there", "elevenlabs:V:Name", os.path.join(tmp, "n.mp3"))


class TestMetadata(unittest.TestCase):
    RAW = {
        "title": '"The Tower That Refused to Fall | Pisa Explained With a Very Long Tail That Goes On"',
        "description": "Why does it lean?\n\nBuilt on soft clay in 1173, it sank.\n#pisa #history\n\nWhat would you have done?",
        "hashtags": ["#Leaning Tower", "history", "#history", "pisa facts!!", "#Shorts", "#Italy", "#Engineering"],
        "tags": ["leaning tower of pisa", "#pisa", "Leaning Tower of Pisa"] + [f"tag number {i}" for i in range(60)],
    }

    def test_shorts_rules(self):
        meta = metadata.sanitize(self.RAW, "Pisa", "9:16")
        self.assertLessEqual(len(meta["title"]), 60)
        self.assertEqual(meta["title"], "The Tower That Refused to Fall")  # quotes and the "| ..." tail removed
        self.assertEqual(meta["hashtags"][0], "#Shorts")
        self.assertIn("#LeaningTower", meta["hashtags"])
        self.assertIn("#PisaFacts", meta["hashtags"])
        self.assertEqual(len([h for h in meta["hashtags"] if h.lower() == "#history"]), 1)
        self.assertLessEqual(len(meta["hashtags"]), metadata.MAX_HASHTAGS + 1)
        lines = meta["description"].splitlines()
        self.assertEqual(lines[-1], " ".join(meta["hashtags"]))  # hashtags on their own last line
        self.assertNotIn("#pisa #history", meta["description"])  # the model's inline hashtag line is gone
        self.assertLessEqual(sum(len(t) + 2 for t in meta["tags"]), metadata.TAGS_TOTAL_MAX)
        self.assertEqual(len([t for t in meta["tags"] if t.lower() == "leaning tower of pisa"]), 1)

    def test_landscape_gets_no_shorts_tag_and_a_longer_title(self):
        meta = metadata.sanitize(self.RAW, "Pisa", "16:9")
        self.assertNotIn("#Shorts", meta["hashtags"])
        self.assertLessEqual(len(meta["title"]), metadata.TITLE_MAX)

    def test_generate_falls_back_when_the_llm_fails(self):
        with patch.object(metadata.llm, "generate_json", side_effect=RuntimeError("down")):
            meta = metadata.generate("Why octopuses have three hearts", "narration", "9:16")
        self.assertTrue(meta["title"])
        self.assertTrue(meta["description"].endswith("#Shorts"))
        self.assertTrue(meta["generated"])


if __name__ == "__main__":
    unittest.main()
