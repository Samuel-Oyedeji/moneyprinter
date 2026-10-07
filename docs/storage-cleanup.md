# Storage clean-up

Rendered videos are big, and once they're on YouTube you rarely need the
file again. The daily cron run (`POST /api/v1/schedules/run`) cleans up
right after the analytics sync and before it renders anything new.

| What | Deleted when |
|---|---|
| A **posted** video's files | 7 days after it went up on YouTube |
| A **never-posted** video's files | 30 days after it was made |
| Downloaded **stock clips** (`storage/cache_videos`) | 7 days old |

"Posted" means any of:
- the app uploaded it;
- you clicked **✅ Already posted**;
- the analytics sync found it on your channel under its title.

A video scheduled to go public later counts from its publish day, not its
upload day.

## What goes and what stays

| Studio | Deleted | Kept |
|---|---|---|
| Shorts | the task folder in `storage/tasks/` (video, voice-over, subtitles) | nothing; Analytics remembers it |
| Animations | `final.mp4` and the narration (`public/`) | project, script, storyboard, thumbnail |
| Documentaries | the render in `storage/tasks/<project>/` and the `images/`, `audio/`, `render/` folders | project, fact sheet, script, sources, thumbnail |

Every video is recorded in `storage/analytics/items.csv` before its files
go, so the Analytics page still matches it by title and keeps it in every
chart. A swept animation or documentary drops out of its studio's library,
because there's no file left to schedule or play.

## Never touched

- Anything on a calendar that is pending, running or failed and waiting
  for a retry, because those uploads read the file. A Shorts upload that
  failed keeps its files until it's retried.
- Animations and documentaries that aren't finished (still rendering,
  waiting at a review checkpoint).
- For Shorts that made several variants of one topic: the folder only
  counts as posted once every variant is posted.
- Anything modified in the last 24 hours.
- `storage/analytics/`. Keep that folder in your backups.

## Settings

In **Video Library → 🧹 Automatic clean-up**, or in `config.toml`:

```toml
[sweeper]
enabled = true
posted_days = 7
unposted_days = 30
cache_days = 7
```

## Checking and running it by hand

- **Video Library → 🧹 Automatic clean-up**: *Preview what would go* lists
  every video with the reason and size; *Clean up now* runs it.
- `GET /api/v1/sweeper/preview` (deletes nothing), `POST /api/v1/sweeper/run`
- `.venv/bin/python -m app.services.sweeper --dry-run` (or without the flag
  to delete)

Every deletion is logged to `storage/sweeper/log.csv`: when, which video,
why, how much space it freed, and which paths were removed. The last 20
show in the clean-up panel.
