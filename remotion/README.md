# Paper Story (Remotion)

Paper cut-out story videos for MoneyPrinterTurbo. The same look covers moral
stories, history and facts. **Everything on screen is drawn in code:** people,
props, skies, grounds, weather, titles, captions and transitions. No images,
no AI art.

## Try it

```
cd remotion
npm install
npm run studio        # preview in the browser: PaperStory (demo), CastSheet, PropSheet
npm run render:demo   # out/demo.mp4
```

The **Animation** page in the web UI drives this kit end to end
(`app/services/animation/`): a script model writes the narration in the house
style (its system prompt is `app/services/animation/prompts/script_system.md`),
a writer model splits that script into scenes and stages them in the
vocabulary below, ElevenLabs records the narration with word timings, the
compiler turns both into a story file, and `scripts/render.mjs` renders it:

```
node scripts/render.mjs --props story.json --public-dir <job>/public --out final.mp4 [--scale 0.5]
```

(The public dir only holds the narration audio. The script prints one JSON
line per progress step and cleans up its bundle.)

## The look

- **Paper.** Every shape is torn paper: a cream torn edge, brush texture and a
  soft shadow. Small things (faces, cups) get finer edges than big things (hills).
- **Boil.** Every edge re-tears every 3 frames. Pieces are nudged by hand every
  3 frames.
- **On twos.** People and props move at 12 poses a second. The camera glides smoothly.
- **Paper puppets.** People are jointed at the shoulders, elbows, hips, knees and
  neck, and each part is its own piece of paper.
- **Parallax.** Sky, sun and clouds, far hills, near ground, the action and the
  foreground each sit at their own depth.
- **Tear transition.** The old scene is ripped away upward to reveal the next.
- **Finish.** A fibre grain and a light vignette over the whole frame.

## Story format (`src/types.ts`)

A story has a **cast** (people defined once, reused in every scene so they
always match), a list of **scenes**, and the narration audio with word timings
from TTS. Positions are fractions of the frame (x 0–1 left→right, y 0–1
top→bottom). Times are seconds from the scene's start.

### Cast (`Character`)

| Field | Options |
| --- | --- |
| `age` | `child` `adult` `elder` |
| `build` | `slim` `average` `broad` |
| `skin` | `light` `fair` `tan` `brown` `dark` `deep` or a hex colour |
| `hair.style` | `short` `side-part` `spiky` `curly` `afro` `long` `bob` `bun` `ponytail` `braids` `balding` `bald` `headscarf` |
| `facialHair` | `none` `mustache` `beard` `goatee` |
| `top.style` | `shirt` `tshirt` `sweater` `suit` `labcoat` `coat` `dress` `robe` (`inner` = shirt/vest colour under a suit or coat) |
| `bottom.style` | `trousers` `shorts` `skirt` |
| `hat.style` | `fedora` `bowler` `tophat` `cap` `crown` `beanie` `straw` `helmet` |
| `accessories` | `tie` `bowtie` `glasses` `scarf` `necklace` `belt` `apron` `cape` (coloured by `accent`) |

An outfit change is a second cast entry with the same face, hair and skin (see
`fleming` and `fleming-lab` in the demo).

### In a scene

| Scene field | Options |
| --- | --- |
| `backdrop.sky` | `day` `dusk` `night` `storm` `parchment` (a plain board for facts) `room` (an interior) |
| `backdrop.ground` | `hills` `town` `field` `sea` `none` |
| `backdrop.extras` | `sun` `moon` `stars` `clouds` `rain` `snow` `window` `table` `tree` |
| `camera.move` | `drift` (default) `push` `pull` `pan-left` `pan-right` `rise` `still` |
| `actors[]` (person) | `who`, `x`, `y` (feet), `height`, `facing` (`left` `right` `front`), `face`, `holding` (a prop, carried `down` or held `up`) |
| person `face` | `smile` `grin` `neutral` `frown` `surprised` `worried` `angry` `sleepy` |
| person `actions` | `walk` (to a new x) `talk` `point` `wave` `shrug` `think` `cheer` `nod` `shake-head` `hop` `turn` `look` `feel` (change face) |
| `actors[]` (prop) | `prop`, `x`, `y` (bottom), `height`, `color`, `color2`, `text`; `idle` `breathe` `sway` `float` `still`; actions `hop` `walk` `turn` `shake` `nod` `grow` `tilt` |
| `enter` / `exit` | `pop` `slide-left` `slide-right` (people walk in) `drop` `flip` / `fold` `slide-left` `slide-right` `fly-up` |
| `notes[]` | `title` (banner + sub-line), `stamp` (badge; `count` rolls a number up), `label` (tag on a string pinned to a point) |
| `transition` | `tear` (default) or `cut` |

**Props:** book, scroll, letter, coin, moneybag, crown, sword, flag, candle,
bottle, pills, cup, flask, petri-dish, dish-stack, microscope, apple, basket,
bucket, chest, key, clock, hourglass, globe, lightbulb, heart, star, trophy,
gift, suitcase, umbrella, house, boat, rock, well, sign, chair, plant, phone,
laptop and arrow. Anything else is a `shapes` prop built from rects, circles,
ellipses and polygons in its own box.

## Layout rules for 9:16

- **0.08–0.22:** titles and stamps.
- **0.25–0.70:** the action. Feet and object bottoms sit at about **y 0.69–0.71**
  outdoors, and table tops at 0.63 in a `room`.
- **0.72–0.81:** captions (one phrase at a time).
- **Below 0.82:** decoration only. Shorts, TikTok and Reels cover it with their
  own buttons and text.
- An adult is 0.30–0.34 of the frame tall, a child about 0.24, and a prop on a
  table about 0.08–0.13.

## Files

- `src/kit/paper.ts`: the torn-paper drawing kit (from the original sample).
- `src/kit/pen.ts`: draws paper shapes in an object's own box.
- `src/puppet/`: people (`character.ts` options and proportions, `pose.ts`
  acting, `draw.ts` the paper cut).
- `src/props/library.ts`: every prop.
- `src/components/`: backdrop, actors, notes, captions, grain, scene and tear.
- `src/demo/`: the demo story ("The Messy Lab") and the cast and prop sheets.
