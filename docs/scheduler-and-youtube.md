# Content Calendar, YouTube Drafts & VPS Deployment

This guide covers the scheduling system: a calendar where you plan video
generations by date, a daily cron hook that generates due videos, automatic
upload to YouTube as **private drafts** (title, description, tags and
thumbnail pre-filled), and Discord alerts telling you a video is ready to
review and publish.

> **Detailed click-by-click setup guides:**
> 1. [Google Cloud setup](setup-1-google-cloud.md)
> 2. [YouTube authorization](setup-2-youtube-auth.md)
> 3. [Discord alerts](setup-3-discord.md)
> 4. [VPS deployment](setup-4-vps-deploy.md)

## How it works

```
Calendar entry (date, topic, count, preset)
        │  daily cron hits POST /api/v1/schedules/run
        ▼
Existing generation pipeline (script → TTS → subtitles → stock footage → render)
        ▼
LLM writes title/description/hashtags · thumbnail frame extracted
        ▼
Upload to YouTube as PRIVATE (a "draft")
        ▼
Discord alert with a YouTube Studio link → you review & publish
```

- Format presets: **Shorts (9:16)** and **Horizontal (16:9)**. All other
  generation settings (voice, subtitles, BGM, video source…) are inherited
  from the last settings you saved in the WebUI.
- Entries can be **duplicated across dates** with just the topic changed.
- A **batch** of pasted topics is spread over the next free days, six a day
  in evenly spaced 07:00–23:00 slots, with a review step before anything is
  saved.
- Missed days are caught up: any entry still `pending` from an earlier date
  runs on the next cron hit.

## 1. YouTube setup (one-time, ~10 minutes)

There is no true "draft" state in the YouTube API; uploading as `private`
is the standard equivalent — the video sits on your channel invisible to
everyone until you publish it from YouTube Studio.

1. Go to [Google Cloud Console](https://console.cloud.google.com) and create
   a project (any name).
2. **APIs & Services → Library** → enable **YouTube Data API v3**.
3. **APIs & Services → OAuth consent screen** → External → fill in the app
   name/email → add your own Google account under **Test users**.
   (Staying in "Testing" mode is fine for personal use; tokens work
   indefinitely once issued to a test user via the flow below.)
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   → type **Desktop app** → download the JSON.
5. Save it as `storage/youtube/client_secret.json`.
6. On your Mac (needs a browser):

   ```bash
   .venv/bin/python youtube_auth.py
   ```

   Sign in, grant access. The refresh token lands in
   `storage/youtube/token.json`.
7. In `config.toml`, set:

   ```toml
   [youtube]
   enabled = true
   ```

Deploying on a VPS? Run step 6 locally, then copy both files to the server
(same paths). Uploads refresh the token automatically from then on.

### YouTube caveats

- **Quota**: each upload costs 1,600 of the default 10,000 daily units —
  about **6 uploads/day**. Need more? Request a quota increase in Google
  Cloud Console (YouTube Data API v3 → Quotas).
- **Custom thumbnails** require a phone-verified channel
  ([youtube.com/verify](https://www.youtube.com/verify)). If not verified,
  the upload still succeeds — only the thumbnail step is skipped.
- Uploads are declared as synthetic media (`containsSyntheticMedia: true`)
  per YouTube's AI-content policy.

## 2. Discord alerts

1. In your Discord server: **Channel settings → Integrations → Webhooks →
   New Webhook → Copy Webhook URL**.
2. In `config.toml`:

   ```toml
   [discord]
   webhook_url = "https://discord.com/api/webhooks/…"
   ```

You'll get a rich embed per uploaded video with a direct **YouTube Studio
edit link**, plus a red alert if a scheduled generation fails.

## 3. Using the calendar

Open the WebUI — there is now a **Schedule** page in the sidebar:

- **Add entries**: date, topic, number of videos, Shorts/Horizontal preset,
  optional planned post time.
- **Post time controls YouTube scheduling.** An entry WITH a post time is
  uploaded private and scheduled via the API's `publishAt` — YouTube flips
  it public automatically at that date+time, interpreted in
  `youtube.publish_timezone` from config.toml (IANA name like
  "Africa/Lagos"; empty = server local, which inside Docker is usually
  UTC). An entry WITHOUT a post time stays a private draft for you to
  publish manually. If generation finishes after the planned time has
  already passed, the video falls back to a private draft instead of
  going public instantly.
- **Month view** shows what's planned where; the list below has
  delete/retry and per-entry **Duplicate** (pick target dates, optionally a
  new topic — your "same preset, different day" workflow).
- **Run due entries now** triggers a run manually without waiting for cron.

### Scheduling a batch of topics

**🗂 Schedule a batch** takes a whole list at once — paste one topic per
line (numbering and bullets are stripped, so a list copied straight out of
a chat works) and it lays them out for you:

- **6 videos per day** by default. That is the YouTube quota ceiling, not a
  style choice: the default 10,000 daily API units divided by 1,600 per
  upload is about six. Lower it in the form if you want a slower cadence.
- **Starts on the first completely free day.** Days that already hold any
  entry are skipped, so a batch never stacks on top of what you planned
  earlier — paste on the 3rd with the 4th and 5th already booked and it
  starts on the 6th. Turn the toggle off to stack anyway, or set an
  explicit start date.
- **Times are spread evenly through waking hours, 07:00–23:00.** The
  window is cut into equal blocks and each video lands in the middle of
  one, so six a day means 08:20, 11:00, 13:40, 16:20, 19:00, 21:40 — even
  spacing, no overnight uploads burning a Short's critical first hours
  while the audience is asleep, and nothing pinned to the very edge of the
  window at lower counts (one a day lands at 15:00). The window lives in
  `PUBLISH_WINDOW_START` / `PUBLISH_WINDOW_END` in
  `app/services/schedule.py`. A day is only used if *all* of its slots are
  still in the future, so a batch never lands on a time that has already
  passed (which would upload a plain draft instead of publishing at the
  planned moment).
- **Nothing is scheduled until you confirm.** The preview is an editable
  table: change a date, nudge a time, retitle a topic, bump a row's video
  count, add or delete rows. It warns about days that go over the upload
  quota and about times in the past. **Confirm all** writes every row in one
  atomic operation — if any row is invalid, nothing is written at all.

Each row becomes an ordinary calendar entry afterwards, so it can be
edited, duplicated, retried or deleted individually like any other.

Everything is also available as REST endpoints (all under the same
`x-api-key` auth as the rest of the API):

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/schedules?start_date=&end_date=` | list entries |
| POST | `/api/v1/schedules` | create entry |
| PUT | `/api/v1/schedules/{id}` | update entry (set `status: pending` to retry) |
| DELETE | `/api/v1/schedules/{id}` | delete entry |
| POST | `/api/v1/schedules/{id}/duplicate` | copy onto other dates |
| POST | `/api/v1/schedules/batch/plan` | lay topics out over free days (saves nothing) |
| POST | `/api/v1/schedules/batch` | create a reviewed batch in one write |
| POST | `/api/v1/schedules/run` | run everything due (the cron hook) |

Schedule data lives in `storage/schedule/schedule.json`.

## 4. The daily cron job

Set a non-empty `api_key` under `[app]` in `config.toml` first — it protects
every API route including the cron hook.

On the VPS host (runs every day at 06:00):

```
0 6 * * * curl -s -X POST http://127.0.0.1:9000/api/v1/schedules/run -H "x-api-key: YOUR_API_KEY" -H "Content-Type: application/json" -d '{}' >> /var/log/mpt-schedule.log 2>&1
```

The endpoint returns immediately and processes entries in the background
(a batch can take an hour of rendering). Overlapping triggers are ignored.

Alternative without HTTP (e.g. from inside the container or on your Mac):

```bash
.venv/bin/python -m app.services.schedule
```

## 5. Deploying on a VPS

> Why not Vercel? The pipeline runs FFmpeg and Whisper for minutes per video
> and writes gigabytes of temp files — serverless platforms can't host it.
> Any Docker-capable VPS with **4–8 GB RAM** works: Hetzner CX32 (~€8/mo),
> DigitalOcean, Railway, Fly.io…

```bash
# on the server
git clone https://github.com/YOUR_FORK/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo

# bring your local config + YouTube credentials
scp config.toml           you@server:MoneyPrinterTurbo/
scp -r storage/youtube    you@server:MoneyPrinterTurbo/storage/

docker compose up -d      # webui :8501, api :9000 on the host (both bound to 127.0.0.1)
```

Then add the crontab line from section 4 on the host.

Security notes:

- Both ports bind to `127.0.0.1` in `docker-compose.yml`. To reach the WebUI
  remotely, use an SSH tunnel
  (`ssh -L 8501:127.0.0.1:8501 you@server`) or put a reverse proxy with
  auth (Caddy/nginx + basic auth) in front. Don't expose the ports raw.
- Set `[app] api_key` before exposing anything.
- `config.toml`, `storage/youtube/` and `storage/schedule/` contain secrets
  and state — keep them out of git and inside your backups.
