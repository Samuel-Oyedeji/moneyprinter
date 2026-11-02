# Autonomous studios: the pilot plan

Status: proposal, not built yet (2026-11-02).

The goal: run the app's video formats as independent **studios**, each with
its own agent that decides what to make, reads its own results, keeps a
timeline of what it tried and learned, and schedules its own uploads, all
posting to **one channel**, with no human in the loop.

The pilot proves this with **one studio, the paper animations**, before
anything else is reorganised. Animations are the right first studio:

- the cheapest format (about $0.13–0.28 a video) and the fastest to make
  (5–9 minutes);
- Shorts give a usable signal within 2–3 days, so the agent gets feedback
  inside one weekly cycle;
- the lowest policy risk: original code-drawn animation and written scripts,
  not stock clips with a voice-over;
- the pipeline already runs topic → upload with no human
  (`app/services/animation/pipeline.py`, `schedule.py`).

---

## 1. What a studio is

```
storage/studios/<studio_id>/
  studio.json      the rules you set   (the agent reads, never writes)
  playbook.json    what it believes    (the agent writes, each belief with evidence)
  timeline.jsonl   what happened       (append-only journal, one event per line)
  queue.json       its upcoming slots  (planned → producing → ready → uploaded)
  notes.jsonl      your notes to it    (read at the next planning run)
```

**studio.json: the rules (you own these)**

| Field | Pilot value | Meaning |
|---|---|---|
| `pipeline` | `animation` | which pipeline makes the videos |
| `identity` | "Animated science and history explainers…" | the topic territory, one paragraph |
| `hard_rules` | list | e.g. no medical advice, no living people, no politics, no topic repeat within 60 days |
| `cadence` | 2 videos/day | how many slots it gets |
| `post_window` | 07:00–22:00 Africa/Lagos | when it may publish |
| `levers` | see §3 | the knobs it may turn, with allowed values |
| `weekly_budget_usd` | 10 | hard spend cap (production plus planner) |
| `veto_hours` | 12 | minimum time a finished video waits before upload |
| `planner_model` | the writer model by default | the model for planning runs |
| `paused` | false | kill switch |

**playbook.json: what it believes (the agent owns these)**

Each belief is a claim plus its status and evidence:

```json
{"id": "b7", "claim": "45s outperforms 30s on 72h views",
 "status": "testing",            // testing | adopted | rejected
 "lever": "length", "evidence": ["exp-2026w46-a"], "videos": 8,
 "effect": "+38% median vs baseline", "since": "2026-11-16"}
```

A belief can only become `adopted` once at least 6 videos on each side back
it and the direction has held in two separate weeks. The rule is enforced
in code, not left to the model.

**timeline.jsonl: the iteration timeline you asked for**

Event types: `plan` (the weekly plan, with its review of last week),
`result` (an experiment read out), `belief` (playbook change with
evidence), `produced`, `qa_failed`, `uploaded`, `vetoed`, `incident`,
`note` (yours). The Studios page renders it as a vertical timeline, which
reads like: *"Week 47 — last week 45-second videos beat 30-second ones by 38%
over 8 videos; keeping 45s as default. New test: question-style hooks vs
statement hooks."*

---

## 2. The loop

```
 hourly cron ──► studios tick (idempotent, one lock)
                   │
                   ├─ Sunday, no plan for the coming week? ──► PLAN
                   │     evaluator builds the results packet (code, no LLM)
                   │     planner agent reviews it + playbook + your notes
                   │     submit_plan → validated in code → queue + timeline
                   │
                   ├─ slots in the next 36h not produced? ──► PRODUCE
                   │     animation pipeline (existing) → QA checks
                   │     pass → "ready" (veto window starts, Discord ping)
                   │     fail → retry the failing stage once → else reserve topic
                   │
                   ├─ ready videos whose slot is ≤ 90 min away? ──► UPLOAD
                   │     existing upload path, private + publishAt = slot
                   │
                   └─ uploaded videos at 72h / 7d? ──► CHECK-IN
                         record result on the timeline
```

**Why the veto happens before upload, not after.** The current token has
upload and read scopes only. Pulling back a video that is already uploaded
(`videos.update` / `delete`) needs a broader scope and a re-auth. Holding a
finished video until 90 minutes before its slot gives you a cancel window
without changing scopes: cancel in the app (or the Discord link to it) and
the slot gets the reserve video or stays empty.

**Why hourly instead of the daily 06:00 cron.** Uploads have to happen
shortly before each slot, and the veto window needs a clock. Every tick
does nothing unless something is due, so running it hourly is cheap. It is one
more line in the server crontab, hitting a new `POST /api/v1/studios/tick`.

**The agent is mostly code, with the model making the judgement calls.**
- Code does all the arithmetic: baselines, ratios, counts, significance
  rules. Models are unreliable at statistics, and the numbers must be
  reproducible.
- The model does what code can't: read the packet and decide what it means,
  write the review, choose the next experiment, pick topics in the studio's
  voice.
- Code validates everything the model submits (budget, slot count, lever
  values, topic novelty, hard rules) and returns the errors to it to fix.
  That correction loop is what makes it an agent rather than a single prompt.

---

## 3. Levers: what the agent can change

Today the pipeline takes `topic`, `context` (NOTES), `seconds`, `aspect`,
`voice`. The storyboard writer then picks the settings, characters and
transitions on its own, and analytics records them afterwards
(`catalog.animation_style`). The pilot adds a structured **brief** to each
project so the agent's choices are explicit and measurable:

| Lever | Allowed values (pilot) | Reaches the pipeline via |
|---|---|---|
| `topic` | free text in the studio's territory | `topic` |
| `topic_category` | the analytics categories | analytics |
| `angle` | what-if · how-it-works · myth-busting · danger · history-moment | script NOTES |
| `hook` | question · shocking-fact · direct-address · cold-scene | script NOTES |
| `length` | 25 · 35 · 45 · 55 s | `seconds` |
| `setting_hint` | any setting in `vocab`, or "writer's choice" | storyboard context |
| `title_style` | question · statement · number | metadata prompt |
| `publish_hour` | inside `post_window` | slot time |

Every lever lands in `project["brief"]`, and `catalog.animation_items()`
copies it into the features. The existing Analytics page and Assistant can
then slice by these levers too, with no extra work.

**Experiment rules (enforced by `submit_plan` validation):**
- At most **2 levers under test per week**. Everything else stays at the
  playbook default, so results can be attributed.
- About **70% exploit / 30% explore**: most slots use the current best
  settings, the rest test something new.
- Each test has at least 3 videos per arm in a week. With 14 slots that
  allows one 2-arm test plus one 3-arm test.
- The plan includes **2 reserve topics** for QA failures.

---

## 4. How results are judged

Weekly per-video signals come from what analytics already stores:

- **72h views** from `daily_stats.csv` snapshots (Data API, no lag): the primary score.
- **% viewed** from `analytics.csv` (Analytics API, ~3-day settle): the quality score.
- **7-day views**, read at the second check-in and used for confirmation.

Each video is scored against the **studio baseline**: the rolling median of
its last 20 videos, compared on a log scale. Shorts views are heavy-tailed,
and one viral video must not rewrite the playbook. An arm "wins" only if its
median log-ratio beats the other arm's and its video count meets the
threshold. Anything weaker is reported to the agent as *inconclusive*, and
the agent is told so in plain words.

**Weeks 1–2 are calibration.** There is no baseline yet, because the
channel is being repurposed, so the agent explores widely and adopts
nothing. The timeline says so.

**Prediction log.** For each planned video the agent records a predicted
outcome (above, at or below baseline). The check-ins score those
predictions, which shows whether the agent is actually learning or just
narrating.

---

## 5. QA without a human

Run on every finished video before it is marked ready:

| Check | How | On failure |
|---|---|---|
| file is sound, duration within ±40% of brief | ffprobe | re-render |
| audio present, not clipped, no silence > 1.5s | ffmpeg `volumedetect` / `silencedetect` | re-voice |
| no black or frozen stretches | ffmpeg `blackdetect` / `freezedetect` | re-render |
| narration matches script | `words.json` vs `script.json` word overlap ≥ 95% | re-voice |
| claims are sound | one LLM critic pass over the script: flags false, misleading or dangerous claims | rewrite script once, else reserve |
| title/description sane | length, no ALL CAPS, no banned words, title is truthful to the script (critic pass) | regenerate metadata |
| topic is new | fuzzy match against the last 60 days of topics + titles on the channel | reserve topic |
| spend | project cost under the per-video cap | stop and flag |

Every failure lands on the timeline and in the inbox, and posts to Discord.
Nothing fails silently.

---

## 6. Your touchpoints

- **Discord, daily at 07:00:** yesterday's uploads, what's ready today
  (with a link to cancel), failures, spend this week.
- **Discord, immediately:** QA failure without a reserve, upload failure,
  budget hit, no successful tick in 3 hours (heartbeat).
- **Studios page:** the timeline, the playbook, the queue
  (cancel / approve now / swap with reserve), and a notes box. A note like
  "fewer space topics this week" is read at the next planning run and
  answered on the timeline.

---

## 7. Work packages

Rough sizes are in build sessions. Each package ends with tests and a commit.

**WP0 · Unblock (you, before any build)**
1. Check whether API uploads go public. Open an API-scheduled video (e.g. the
   Eastland re-upload) in YouTube Studio. If it shows "Locked (private)",
   apply for the YouTube API compliance audit first; nothing autonomous
   works until it passes.
2. Confirm the VPS can render animations. The Docker image needs the Node +
   Chrome rebuild from the animation work; time one 30s render there.
3. Make the old videos private (don't delete them; their data stays in
   analytics). Then run one analytics sync.
4. Decide the open questions in §9.

**WP1 · Studio core (1 session)**
- `app/services/studios/`: `store.py` (the files above, locking), `model.py`
  (studio.json schema + validation), `[studios]` config section
  (`enabled`, `tick_minutes`, global `paused`).
- `upload_budget.py`: `DAILY_BUDGET` becomes a config value (default 50,
  under the 100/day API allowance) and counts studio slots.
- Seed the animation studio from a template.

**WP2 · Briefs and levers (1 session)**
- `project["brief"]` in `animation/store.create_project`.
- The brief flows into script NOTES, storyboard context and the metadata prompt.
- `catalog.animation_items()` records brief levers, `studio`, `experiment`, `arm`.
- Tests: a brief reaches each prompt; features appear in the dataset.

**WP3 · Evaluator (1 session)**
- `studios/evaluate.py`: the results packet (per-video scores vs baseline,
  per-experiment arm comparisons with counts and verdicts, prediction hits,
  spend), built from `report.build_dataset()`.
- Pure functions, unit-tested on synthetic data, including the heavy-tail
  and small-sample cases.

**WP4 · Planner agent (1–2 sessions)**
- `studios/planner.py`: an OpenRouter tool-calling loop using the existing
  OpenAI-compatible client pattern in `animation/llm.py`.
- Read tools: `get_results_packet`, `get_playbook`, `get_recent_videos`,
  `check_topic(topic)`, `get_notes`.
- One write tool, `submit_plan`. It validates and returns errors; the agent
  retries up to 3 times.
- Output: review text, belief changes, experiments, 14 slots + 2 reserves
  with briefs and predictions.
- Cost recorded per run. The prompt states the studio identity, the hard
  rules and the experiment rules.
- Tests with a fake model: invalid plans rejected, valid plan books the queue.

**WP5 · Tick, production, QA, upload (1–2 sessions)**
- `studios/runner.py`: tick (plan, produce, upload, check-in), one lock, idempotent.
- `studios/qa.py`: the checks in §5.
- Production reuses `animation.pipeline.run_project`; upload reuses
  `animation.schedule._upload` (factored out so it takes a slot instead
  of a calendar entry).
- `POST /api/v1/studios/tick` + a crontab line.
- Studio slots count toward the shared upload budget.

**WP6 · Notifications (½ session)**
- Discord daily digest, immediate alerts, heartbeat.

**WP7 · Studios page (1 session)**
- `webui/pages/Studios.py`: studio card → Timeline · Playbook · Queue ·
  Settings, plus the notes box.
- Built in the new design direction, so it doubles as the prototype for the
  later redesign.

**WP8 · Shadow run, then live**
- **Shadow (3–4 days):** the full loop runs, but uploads go up private with
  no `publishAt`. You watch the outputs and the timeline and fix what's wrong.
- **Live (3 weeks):** uploads scheduled for real, veto window on.

WP2 and WP3 are independent of each other once WP1 exists, so they can be
built in parallel.

---

## 8. Pilot success criteria (judged at the end of the 3 live weeks)

| Area | Pass |
|---|---|
| Autonomy | ≥ 95% of slots published with no action from you over 14 consecutive days |
| Reliability | every failure visible (inbox + Discord), zero silent misses |
| Quality | no video you'd have vetoed got published; QA caught what you'd have caught |
| Learning hygiene | every adopted belief meets the evidence rule; prediction hit-rate tracked |
| Cost | within `weekly_budget_usd` every week |
| Performance | reported, not pass/fail: median 72h views in weeks 3–5 vs calibration |

Three weeks is too short to prove the agent makes videos *better*. It is
enough to prove the loop runs unattended, stays honest about what it knows,
and doesn't publish junk. If it passes, phase 2 adds the documentary and
Shorts studios, the network layer (slot arbitration, rankings, global kill
switch) and the full UI redesign.

---

## 9. Decisions (defaults shown; change any)

1. **Volume:** 2 animations a day (14 a week). Fewer gives the evaluator too
   little to work with; more raises the inauthentic-content risk.
2. **Veto window:** on, at least 12 hours. Can be set to 0 once you trust it.
3. **Studio identity:** "animated science and history explainers". This
   matches the current script prompt; the moral-story side of the paper
   style would be a later, separate studio.
4. **Planner model:** the existing writer model (Claude Sonnet via
   OpenRouter). It runs about once a week, so a stronger model is cheap if
   you want one.
5. **Weekly budget:** $10 (expected spend is about $4–6).

---

## 10. Running it (built in WP5)

The tick (`app/services/studios/runner.py`) does what is due and nothing
else, so it runs hourly. **On the server**, add this crontab line next to the
daily calendar one (same API key):

```
5 * * * * curl -s -X POST http://127.0.0.1:9000/api/v1/studios/tick -H "x-api-key: YOUR-API-KEY-HERE" >> $HOME/mpt-studios.log 2>&1
```

It returns at once; the work runs in the API container. Nothing happens until:

1. `[studios] enabled = true` in config.toml, and `[studios] paused` is false;
2. the studio exists and is unpaused (WP7's Studios page; until then, set
   `"paused": false` in `storage/studios/animation/studio.json`);
3. YouTube uploads are set up (`[youtube] enabled` + token). Without them
   videos are still made and wait as "ready", with a daily incident.

`GET /api/v1/studios` shows each studio's queue counts and latest event.

What one tick does, in order: refresh analytics (if 20h+ old) → plan
(Sundays, or a studio's first tick) → pick up anything a restart cut off →
drop planned videos 6h past their slot → upload ready videos (slot ≤ 90
min away and the cancel window over) → produce videos due within 36h (QA,
one fix, else a reserve) → upload again → 3- and 7-day check-ins.

QA lives in `app/services/studios/qa.py`. The critic uses the studio's
planner model.
