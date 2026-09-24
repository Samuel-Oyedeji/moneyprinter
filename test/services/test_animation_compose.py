"""Storyboard + word timings → Remotion story: timing, cues, layout, sanitizing."""
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.services.animation import compose  # noqa: E402

STORYBOARD = {
    "title": "The Messy Lab",
    "cast": [
        {
            "id": "Fleming",
            "age": "adult",
            "skin": "fair",
            "hair": {"style": "side-part", "color": "#8a7f76"},
            "top": {"style": "labcoat", "color": "not-a-colour"},
            "accessories": ["bowtie", "jetpack"],
        },
        {"id": "kid", "age": "child", "hair": {"style": "mohawk"}},
    ],
    "scenes": [
        {
            "narration": "In 1928, Alexander Fleming came home.",
            "sky": "day",
            "ground": "town",
            "people": [
                {"who": "fleming", "place": "left", "enter": "walk-in-left", "actions": [{"do": "point", "cue": "home"}]},
                {"who": "ghost", "place": "right"},
            ],
            "notes": [
                {"kind": "stamp", "text": "1928", "cue": "1928"},
                {"kind": "label", "text": "Alexander Fleming", "target": "fleming", "cue": "Alexander"},
            ],
        },
        {
            "narration": "His dishes of germs were piled high.",
            "sky": "volcano",
            "extras": ["window", "lava"],
            "props": [
                {"prop": "dish-stack", "place": "right", "size": "medium", "level": "table", "cue": "dishes",
                 "actions": [{"do": "shake", "cue": "piled"}, {"do": "tilt", "cue": "high", "deg": 90}]},
                {"prop": "spaceship", "place": "center"},
                {"prop": "custom", "name": "tower", "place": "left", "aspect": 0.4, "shapes": [
                    {"type": "rect", "x": 0.2, "y": 0.1, "w": 0.6, "h": 0.9, "color": "#efe6d2"},
                    {"type": "poly", "points": [[0.1, 0.1], [0.5, 0], [0.9, 0.1]], "color": "#b5542d"},
                    {"type": "rect", "x": "oops", "y": 0, "w": 1, "h": 1, "color": "#000000"},
                ]},
            ],
            "notes": [{"kind": "label", "text": "the tower", "target": "tower", "cue": "germs"}],
        },
    ],
}


def timed_words(narration: list[str], start: float = 0.1, gap: float = 0.35) -> list[dict]:
    words, t = [], start
    for sentence in narration:
        for token in sentence.split():
            words.append({"text": token, "at": round(t, 3), "end": round(t + 0.3, 3)})
            t += gap
        t += 0.6  # pause between scenes
    return words


class TestCompileStory(unittest.TestCase):
    def setUp(self):
        self.narration = [s["narration"] for s in STORYBOARD["scenes"]]
        self.words = timed_words(self.narration)
        self.audio = self.words[-1]["end"] + 0.2
        self.story = compose.compile_story(STORYBOARD, self.words, self.audio, "9:16")

    def test_scenes_cut_just_before_their_first_word_and_cover_the_audio(self):
        first, second = self.story["scenes"]
        second_first_word = self.words[len(self.narration[0].split())]
        self.assertAlmostEqual(first["duration"], second_first_word["at"] - compose.LEAD, places=2)
        total = compose.story_duration(self.story)
        self.assertAlmostEqual(total, self.audio + compose.TAIL, places=2)

    def test_a_loop_ending_cuts_straight_back_to_the_start(self):
        # "...the edge of..." replays into the first line, so no hold at the end
        words = [dict(w) for w in self.words]
        words[-1]["text"] = words[-1]["text"].rstrip(".!?") + "..."
        audio = words[-1]["end"] + 0.6  # trailing silence in the file is cut too
        story = compose.compile_story(STORYBOARD, words, audio, "9:16")
        self.assertAlmostEqual(compose.story_duration(story), words[-1]["end"] + compose.LOOP_TAIL, places=2)

    def test_actions_land_on_their_cue_word(self):
        fleming = next(a for a in self.story["scenes"][0]["actors"] if a.get("who") == "fleming")
        home = next(w for w in self.words if w["text"] == "home.")
        self.assertAlmostEqual(fleming["actions"][0]["at"], home["at"], places=2)
        self.assertEqual(fleming["enter"]["type"], "slide-left")
        # scene 2 cue times are relative to scene 2's start
        dishes = next(a for a in self.story["scenes"][1]["actors"] if a.get("prop") == "dish-stack")
        scene2_start = self.story["scenes"][0]["duration"]
        piled = next(w for w in self.words if w["text"] == "piled")
        self.assertAlmostEqual(dishes["actions"][0]["at"], round(piled["at"] - scene2_start, 2), places=2)

    def test_vocabulary_is_enforced(self):
        cast = {c["id"]: c for c in self.story["cast"]}
        self.assertEqual(set(cast), {"fleming", "kid"})
        self.assertNotIn("color", cast["fleming"]["top"])  # bad hex dropped
        self.assertEqual(cast["fleming"]["accessories"], ["bowtie"])  # unknown accessory dropped
        self.assertNotIn("hair", cast["kid"])  # unknown hair style dropped
        scene1, scene2 = self.story["scenes"]
        self.assertEqual([a.get("who") for a in scene1["actors"]], ["fleming"])  # "ghost" is not in the cast
        self.assertEqual(scene2["backdrop"]["sky"], "day")  # "volcano" → default
        self.assertEqual([e["type"] for e in scene2["backdrop"]["extras"]], ["window", "table"])
        self.assertNotIn("spaceship", [a.get("prop") for a in scene2["actors"]])
        tilt = next(a for a in next(x for x in scene2["actors"] if x.get("prop") == "dish-stack")["actions"] if a["do"] == "tilt")
        self.assertEqual(tilt["deg"], 45)  # clamped

    def test_custom_props_become_clean_shapes(self):
        custom = next(a for a in self.story["scenes"][1]["actors"] if a.get("prop") == "shapes")
        self.assertEqual(len(custom["shapes"]), 2)  # the malformed rect is dropped
        self.assertEqual(custom["aspect"], 0.4)
        label = self.story["scenes"][1]["notes"][0]
        self.assertAlmostEqual(label["toX"], custom["x"], places=3)

    def test_table_props_sit_on_the_table(self):
        scene2 = self.story["scenes"][1]
        table = next(e for e in scene2["backdrop"]["extras"] if e["type"] == "table")
        dishes = next(a for a in scene2["actors"] if a.get("prop") == "dish-stack")
        self.assertEqual(dishes["y"], table["y"])
        self.assertEqual(table["y"], compose.LAYOUTS["9:16"]["table"])

    def test_year_stamps_count_up_and_labels_point_at_their_target(self):
        stamp, label = self.story["scenes"][0]["notes"]
        self.assertEqual(stamp["count"], {"from": 1898, "to": 1928, "dur": 0.9, "separator": False})
        fleming = next(a for a in self.story["scenes"][0]["actors"] if a.get("who") == "fleming")
        self.assertAlmostEqual(label["toX"], fleming["x"], places=3)
        self.assertLess(label["y"], label["toY"])  # the tag hangs above what it names

    def test_landscape_uses_its_own_layout(self):
        wide = compose.compile_story(STORYBOARD, self.words, self.audio, "16:9")
        self.assertEqual((wide["width"], wide["height"]), (1920, 1080))
        fleming = next(a for a in wide["scenes"][0]["actors"] if a.get("who") == "fleming")
        self.assertEqual(fleming["height"], compose.LAYOUTS["16:9"]["person"])
        self.assertEqual(fleming["y"], compose.LAYOUTS["16:9"]["feet"])
        self.assertAlmostEqual(compose.story_duration(wide), compose.story_duration(self.story), places=3)

    def test_word_count_mismatch_falls_back_to_proportional_spans(self):
        merged = self.words[:1] + self.words[2:]  # a provider merged "In 1928,"
        spans = compose.scene_word_spans(STORYBOARD["scenes"], merged)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(merged))

    def test_rejects_unknown_aspect_and_empty_input(self):
        with self.assertRaises(ValueError):
            compose.compile_story(STORYBOARD, self.words, self.audio, "4:3")
        with self.assertRaises(ValueError):
            compose.compile_story({"scenes": []}, self.words, self.audio, "9:16")


if __name__ == "__main__":
    unittest.main()
