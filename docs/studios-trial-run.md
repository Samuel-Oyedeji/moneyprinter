# Autonomous studios: the trial run (WP8)

Status: ready to run (2026-11-02). Builds on docs/studios-pilot-plan.md;
WP1–WP7 and T1–T4 are on `feature/autonomous-studios`.

The trial answers one question: **can the Paper Explainers studio run the
channel unattended for three weeks without publishing anything you'd have
stopped?** It is not long enough to prove the agent makes videos *better*;
that comes after.

```
 Day 0      setup (you, ~1–2 h)        checks, deploy, config, cron
 Days 1–4   shadow                     full loop, uploads stay private, you rate every video
 Day 5      go / no-go                 switch shadow off, or fix and repeat
 Weeks 1–3  live                       real publishing, cancel window on, Monday reviews
 +4 days    evaluation                 trial report against the pass criteria
```

With a start on **Tue 3 Nov**: shadow Wed 4 – Sat 7, go/no-go Sat 7, live
W46–W48 (Mon 9 – Sun 29 Nov), evaluation Thu 3 Dec once the last videos have
their 3-day numbers.

**Cost:** about $20 in all. That's roughly 50 videos at $0.30–0.40 each,
plus about $0.30 a week of planning and QA on a Sonnet-class model.

---

## 1. Built before Day 0 (four small gaps found while planning; done)

| | What | Why |
|---|---|---|
| T1 | **Shadow switch** per studio: the loop runs fully, but uploads go up private with no publish time, and the results scorer and baseline skip them. The baseline also counts public videos only. | The pilot plan's shadow phase needs it, and private videos with 0 views must never count as results. |
| T2 | **Your verdict on each video** (👍 / 👎 + a line) on the Queue cards. A 👎 also becomes a note the agent reads at its next plan. | It's how the quality criterion is measured: did QA pass anything you'd have rejected? |
| T3 | **Same-subject check** in the QA critic: it gets the last 60 days of topics and flags a repeat in different words. | The WP4 dry run planned "neutron star lifecycle" next to "what happens when a star dies"; the word-overlap check can't catch that. |
| T4 | **Trial report** on the Results tab: every pass criterion in §6, computed from the queue and the timeline. | The evaluation should be a number, not an impression. |

---

## 2. Day 0: setup

**On YouTube (5 min)**
1. YouTube Studio → Content: open a video the app uploaded with a publish
   time (e.g. the Eastland re-upload). If it says **"Locked (private)"**,
   stop here. The Google Cloud project needs the YouTube API compliance
   audit before anything autonomous can publish.
2. Optional, your channel decision: set old videos to private (don't
   delete them; their analytics stay). The baseline only counts public
   videos, so the studio then calibrates from its own first videos.
3. Pause the other calendars for the trial: no new Shorts, documentary or
   animation calendar entries. Other uploads on the channel would muddy
   the studio's results.

**Code (I can do this part on your go-ahead)**

4. Push `feature/autonomous-studios`, open a PR, and merge it into `main`.
   Merging is safe: every studio feature is off until `[studios] enabled`.
   The one change you'd notice is that the shared upload budget is 50 a day
   instead of 6. The Shorts calendar keeps its own 6-a-day spacing.

**On the server**

5. Deploy, rebuilding the image (animations need Node + Chrome in it):
   ```bash
   cd ~/moneyprinter && git pull && docker compose up -d --build
   ```
6. Time one animation render from the Animation page (30 s video). It
   should finish; note how long it takes. More than ~20 min means the
   server is too slow for 2 a day plus retries.
7. Add to `config.toml` on the server:
   ```toml
   [studios]
   enabled = true
   paused = false
   planner_model = "anthropic/claude-sonnet-5"
   app_url = "https://moneyprrr.samops.name.ng"
   notify_ready = true
   ```
   Then `docker compose restart`.
8. Add the hourly crontab line (pilot plan §10) and check it fires:
   ```
   5 * * * * curl -s -X POST http://127.0.0.1:9000/api/v1/studios/tick -H "x-api-key: YOUR-API-KEY-HERE" >> $HOME/mpt-studios.log 2>&1
   ```

**On the Studios page**

9. Create the studio. Read its rules on the Settings tab and edit the hard
   rules if any don't fit. It starts paused and in **Shadow**: leave
   Shadow on and unpause it.
10. Press **Run a tick now** (or wait for the cron). The first tick plans
    tomorrow through Sunday. Read the plan on the Timeline and check the
    Queue looks sensible.

---

## 3. Days 1–4: shadow

The full loop runs: plan → make → QA → ready ping → cancel window →
upload (private, never published) → timeline + Discord.

**Your 10 minutes a day**
- Read the 07:00 digest and the ready pings.
- On the Queue, watch every finished video and give it 👍 or 👎 with a line
  on what's wrong. Be the strict reviewer you'd want before publishing.
- Skim the Timeline for incidents and QA failures. Did QA catch the things
  you'd have caught?

**Deliberate tests, once each, during shadow**

| Test | Expect |
|---|---|
| Cancel a ready video | it never uploads; "You cancelled…" on the timeline |
| Approve a ready video early | it uploads at its slot − 90 min, ignoring the window |
| Pause the studio for one tick | that tick does nothing for it |
| `[studios] paused = true` for one tick | no studio does anything |
| Leave a note ("more animal topics") | answered in the next plan's replies (use **Plan now** after the slots free up, or wait for Sunday) |
| Stop the cron for 4 hours | the heartbeat alert arrives with the next daily cron, and a "running again" message when it's back |

---

## 4. Day 5: go / no-go

Go live (turn **Shadow** off) only if all of these hold over the shadow days:

| Check | Bar |
|---|---|
| Made and uploaded without you stepping in | 7 of 8 slots or better |
| Every failure visible | each failed slot has a timeline entry and a Discord alert |
| Your 👎 videos | QA had already caught them, or there were none |
| Uploads | none "Locked (private)"; all private, none published |
| Cost per video | ≤ $0.50 |
| The deliberate tests | all behaved as expected |

**No-go:** fix what failed, and run another 2–3 shadow days. The usual
suspects: a QA check too loose or too strict, render time, the planner's
topic quality.

**When you switch Shadow off:** slots already uploaded stay private;
delete them in YouTube Studio when convenient. From the next slot on,
videos publish at their time.

---

## 5. Weeks 1–3: live

- **Daily (2 min):** the digest. Rate anything that looks off. Cancel
  anything you wouldn't publish (that's still a QA miss to note).
- **Mondays (15 min):** read the Sunday plan on the Timeline: its review,
  experiments, replies to your notes. Check the Results tab. Leave notes.
- **Week 1 is calibration:** there's no baseline yet, so nothing is
  "learned". The plan should say so.
- **Weeks 2–3:** the first experiments get verdicts. Expect mostly "no
  difference" or "too few" at this volume. That's the evaluator being
  honest, not a failure.

**Stop rules: pause the studio at once if**
- a published video has a factual error or breaks a rule (a QA miss:
  inspect its QA checks, fix, then resume);
- two days in a row lose slots to failures;
- YouTube shows any policy warning, limited-ads notice or spam or
  inauthentic-content flag. Stop everything and read it before resuming;
- spend goes over the weekly budget (the code stops production, but find out why).

---

## 6. Evaluation (Thu 3 Dec)

From the trial report (T4), over the 21 live days:

| Area | Pass |
|---|---|
| Autonomy | ≥ 95% of slots published with no action from you over 14 consecutive days |
| Reliability | every failed or missed slot has a timeline incident and a Discord alert; zero silent misses |
| Quality | no published video you rated 👎 (if any, the trial fails on quality) |
| Learning hygiene | every adopted belief meets the evidence rule (code-enforced, so this is a check); prediction hit rate reported |
| Cost | within the weekly budget every week |
| Performance | reported, not pass/fail: median 3-day views, week 1 vs week 3 |

**Pass:** phase 2. That means the documentary and Shorts studios, slot
sharing between studios, and the full UI redesign.
**Fail:** the report says which area, and that's the next piece of work.

---

## 7. Known risks going in

- **The planner on a cheap model** planned thinly in the dry run (every
  prediction "at", near-duplicate topics). Day 0 sets a Sonnet-class
  `planner_model`, which also runs the QA critic.
- **Server stability:** the September host segfaults. The heartbeat alert
  covers a dead tick; a dead nginx only blocks the page, not the tick.
- **Render time on the server** is unmeasured (Day 0, step 6).
- **ElevenLabs credits:** about 14 narrations a week. Check the plan's
  monthly character allowance covers about 60 videos plus retries.
- **Analytics read access** must work on the server for check-ins and
  results (the Analytics page syncing is the test).
