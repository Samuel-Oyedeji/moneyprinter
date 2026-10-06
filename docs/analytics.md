# Channel Analytics

The **Analytics** page (top bar → *Analytics*) pulls every video's numbers
back from YouTube and shows what works across the three studios: Shorts
(stock footage), Documentaries and Animations. It answers questions like:

- Which studio gets the most views, and which keeps people watching longest?
- Which **kinds of topics** do best (space vs. moral stories vs. history)?
- Which **animation styles** work: setting, characters, transitions, length,
  voice?
- Do **batches** do better than one-off videos? Which video in a batch won?
- Does the **publish day or hour** matter?

## Turning it on (one time)

1. Google Cloud Console → **APIs & Services → Library** → enable
   **YouTube Analytics API** (the Data API is already on for uploads).
2. Run `.venv/bin/python youtube_auth.py` again and tick every permission.
   On top of uploading, it now asks to *view* your channel and its analytics.
   Your old token keeps uploading until you do this.
3. VPS: copy the new `storage/youtube/token.json` to the server.
4. Open **Analytics** and press **🔄 Sync now**.

Syncing is cheap: listing the channel costs about 1 quota unit per 50
videos out of the 10,000 daily units, so it never eats into your 6 uploads
a day. Analytics API calls have their own quota.

## When it syncs

- **Sync now** on the page.
- **Every cron run**, before any upload (best-effort, at most two minutes;
  turn it off with `youtube.analytics_sync_before_uploads = false`).
- `POST /api/v1/analytics/sync` or `.venv/bin/python -m app.services.analytics.sync`,
  for example from a second cron line in the evening.

Each sync stores a daily view snapshot per video in
`storage/analytics/history.json`.

## Reconciling videos you post by hand

The calendar uploads up to 6 videos a day and records their YouTube IDs.
Everything else you upload yourself. Each sync matches the channel's videos
back to the app in this order:

| How | When |
|---|---|
| App upload | the app uploaded it and kept the video ID |
| Posted link | you clicked **✅ Already posted** and pasted the video's URL |
| Title | the YouTube title equals a title the app gave the video, ignoring case, emoji, punctuation, hashtags and a `(2/3)` part suffix |
| You | you confirmed a suggestion or linked it by hand on the Reconcile tab |

A video published more than a day *before* the app made the item is never
matched to it. When one title fits two app videos (same topic made twice),
the one made closest before the publish time wins.

Titles that are close but not equal (≥ 85% similar) are never linked
automatically. They wait on the **Reconcile** tab for one-click **Same** /
**No**.

Matching writes back to the studios. An animation or documentary found on
the channel is marked **posted by hand**, the same mark as the library
card's **✅ Already posted** button, so its pending calendar entries stop
and free their upload slot. Because this runs before every cron upload, a
video you already posted never gets uploaded a second time.

Where to mark things as posted yourself:

- **Animations**: library card or calendar entry → ✅ Already posted / ✅ Posted.
- **Documentaries**: Library tab → ✅ Already posted.
- **Shorts**: Video Library → ✅ Already posted.

The URL is optional; without it the next sync finds the video by title.

The Reconcile tab also lists:

- videos you marked posted that were not found (usually a changed title);
- possible double uploads (the same title twice on the channel);
- app uploads that are no longer on the channel;
- channel videos not from the app (older uploads), which you can link by
  hand to the app video they really are.

## What the tabs show

- **Overview**: totals, studio vs. studio (median views, average % viewed),
  views by publish week, and the clearest findings.
- **What works**: pick a studio and a ranking metric; every dimension is
  charted best-first. Bars fade when a group has fewer than 3 videos.
  "What stands out" lists groups that beat (▲) or trail (▼) the typical
  video by 25% or more.
  - All studios: topic category, batch or single, posted by app or by hand,
    length on YouTube, publish day and hour.
  - Animations: main setting, settings per video, characters, transitions,
    scene count, planned length, voice, research given, studio vs. calendar.
  - Documentaries: planned length, autopilot vs. reviewed, research notes,
    designed thumbnail.
  - Shorts: aspect, footage source, voice, music, subtitles, clip length,
    generator vs. calendar.
- **Batches**: batch vs. single per studio, every batch with its best and
  weakest video, and a per-batch chart. A batch is a pasted list on a
  calendar, the Animation studio's *Batch* mode, or several variants of one
  Shorts topic. Videos made before batch IDs were recorded are grouped by
  creation time and marked "guessed".
- **Videos**: every video with its numbers, CSV download, and the topic
  category editor.

**Topic categories** are assigned by the app's configured LLM on each sync.
It reuses existing categories so the set stays small. Correct any of them
under *Videos → ✏️ Topic categories*.

**Comparing fairly:** raw views favour older videos. Use *views per day* or
*average % viewed* to compare, and keep "Hide videos younger than" at 2+
days, because the Analytics API trails real time by about two days. View,
like and comment counts come from the Data API in real time.

## Files

`storage/analytics/`: `channel.json` (last channel listing),
`metrics.json` (Analytics API numbers), `history.json` (daily snapshots),
`links.json` (your confirmations, rejections, Shorts posted marks, topic
categories), `sync.json` (last sync status).

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/analytics/sync` | sync in the background |
| GET | `/api/v1/analytics/status` | connection + last sync |
| GET | `/api/v1/analytics/summary?by=category&studio=animation` | per-group results |
