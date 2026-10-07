# Step 5 — YouTube Analytics Setup (for the Analytics page)

Goal: let MoneyPrinterTurbo **read** your channel's videos and their
performance, so the **Analytics** page can show what works, and the daily
cron can match videos you posted by hand. About 10 minutes, free, no
billing card.

This guide assumes the YouTube **posting** setup already works:

- [setup-1-google-cloud.md](setup-1-google-cloud.md): a Google Cloud
  project with an OAuth client, saved as `storage/youtube/client_secret.json`
- [setup-2-youtube-auth.md](setup-2-youtube-auth.md): a `token.json` that
  uploads videos

You'll reuse that **same project and the same OAuth client**. Nothing
there gets replaced. You'll turn on one more API and sign in once more so
your token also gets read permission.

Do this on your Mac in a normal browser, signed in to the **Google account
that owns your YouTube channel**.

---

## What changes, and why

The Analytics page uses two Google APIs:

| API | What the app reads with it | Already on? |
|---|---|---|
| **YouTube Data API v3** | your channel's video list: titles, publish times, privacy, live view / like / comment counts | ✅ yes, uploads use it |
| **YouTube Analytics API** | per-video watch time, average % viewed, shares, subscribers gained | ❌ enable it in step 2 |

Your token also needs two extra **read-only** permissions on top of
"upload videos":

| Permission (scope) | Shown on Google's consent screen as |
|---|---|
| `youtube.readonly` | View your YouTube account |
| `yt-analytics.readonly` | View YouTube Analytics reports for your YouTube content |

Neither of them can change, delete or publish anything.

Until you finish this guide, uploads keep working exactly as they do now.
The Analytics page just shows *"Your YouTube token only allows uploads"*.

---

## 1. Open the project you already use for posting

1. Go to <https://console.cloud.google.com>.
2. Click the **project selector** at the top-left (next to the "Google
   Cloud" logo) and pick the project you created for posting (e.g.
   `MoneyPrinterTurbo`).

**Make sure it's the right project.** The API must be enabled in the
*same* project as your OAuth client, or every analytics request fails
with "API has not been used in project …". To check:

1. ☰ menu → **APIs & Services** → **Credentials**.
2. Under **OAuth 2.0 Client IDs**, note the **Client ID**. It starts with
   a number, like `1234567890-abc….apps.googleusercontent.com`.
3. On your Mac, compare it with the one in your file:

   ```bash
   grep -o '"client_id": *"[^"]*"' storage/youtube/client_secret.json
   ```

   They must match. If they don't, switch projects in the selector until
   they do.

## 2. Enable the YouTube Analytics API

1. ☰ menu → **APIs & Services** → **Library**
   (or <https://console.cloud.google.com/apis/library>).
2. In the search box type: `YouTube Analytics API`
3. Click the result named exactly **YouTube Analytics API**.
   - Not "YouTube Reporting API": that one is for bulk report downloads
     and isn't used.
   - Not "YouTube Data API v3": that's already on.
4. Click the blue **ENABLE** button.
5. You land on the API's overview page; that means it's enabled.

Check both are on: ☰ menu → **APIs & Services** → **Enabled APIs &
services**. The list should include **YouTube Data API v3** and
**YouTube Analytics API**.

> Just enabled? Give it 2–5 minutes before the first sync. Google takes a
> moment to switch a new API on for a project.

## 3. Check the consent screen settings

These were set during the posting setup. Confirm them, because they
decide whether analytics keeps working after a week.

1. ☰ menu → **APIs & Services** → **OAuth consent screen**. In the newer
   console this opens **Google Auth Platform**, with **Branding**,
   **Audience**, **Clients** and **Data Access** in the left sidebar.
2. **Audience** (left sidebar; older UI: on the main page):
   - **Publishing status** should be **In production**. If it says
     **Testing**, click **Publish app** → **Confirm**. In Testing, your
     token expires after 7 days and both uploads *and* analytics stop.
   - If you leave it in Testing, your Gmail address must be listed under
     **Test users**.
3. **Data Access** (left sidebar) is **optional**. The app asks for its
   permissions when you sign in, so you don't have to list them here. If
   you'd like the screen to be accurate, click **Add or remove scopes**,
   tick these three, then **Update** → **Save**:
   - `.../auth/youtube.upload`
   - `.../auth/youtube.readonly`
   - `.../auth/yt-analytics.readonly`

   If Google then offers to start a verification review, you can ignore
   it. A personal, unverified app only shows the "Google hasn't verified
   this app" warning at sign-in, which you've already clicked through for
   posting.

You do **not** need a new OAuth client or a new `client_secret.json`.

## 4. Get the new code (if you haven't yet)

The Analytics page and the extra permissions come with the
`feature/youtube-analytics` branch. On your Mac:

```bash
cd ~/Documents/explore/MoneyPrinterTurbo
git fetch origin
git checkout feature/youtube-analytics   # or: git pull, once it's merged into main
```

## 5. Sign in once more to add the read permissions

Your current `token.json` was issued for uploads only, so Google has to
ask you once more, now including the read permissions.

1. On your Mac, from the MoneyPrinterTurbo folder:

   ```bash
   .venv/bin/python youtube_auth.py
   ```

2. A browser opens. **Choose the Google account that owns your channel.**
   If your channel is a **Brand Account**, Google then asks you to choose
   between your personal account and the channel. Pick the **channel**.
3. On *"Google hasn't verified this app"*, click **Advanced** → **Go to
   MoneyPrinterTurbo (unsafe)**. It's your own app, so this is expected.
4. On the permissions screen, **tick every box**. There are three:
   - ☑ Manage your YouTube videos (upload)
   - ☑ View your YouTube account
   - ☑ View YouTube Analytics reports for your YouTube content

   Then click **Continue**. Untick the two "View" boxes and uploads still
   work, but analytics stays off; just run the script again to fix it.
5. The browser says *"The authentication flow has completed."* Close it.
6. The terminal prints the token path. If a permission was left unticked,
   it also prints a warning naming it.

This replaces `storage/youtube/token.json`. The new token uploads just
like the old one did.

## 6. Check the token can read your channel

Still on your Mac:

```bash
.venv/bin/python -c "
from app.services.analytics import youtube_api
print(youtube_api.readiness())
"
```

Expected:

```
(True, '')
```

If you see `(False, '...')`, the message says what's missing. See
Troubleshooting below.

Then do a real read (it lists your channel; nothing is changed):

```bash
.venv/bin/python -c "
from app.services.analytics import youtube_api
result = youtube_api.list_channel_videos()
print(result['channel']['title'], '-', len(result['videos']), 'videos')
"
```

Expected: your channel name and the number of videos on it, private and
scheduled ones included.

## 7. Copy the new token to your VPS

The server still has the old upload-only token. **From your Mac**:

```bash
cd ~/Documents/explore/MoneyPrinterTurbo
scp storage/youtube/token.json youruser@YOUR_SERVER_IP:~/MoneyPrinterTurbo/storage/youtube/
```

Then update the code on the server and restart it, so it runs the
Analytics page and the new daily steps:

```bash
ssh youruser@YOUR_SERVER_IP
cd ~/MoneyPrinterTurbo
git fetch origin && git checkout feature/youtube-analytics   # or: git pull
docker compose up -d --build
```

Check the token from inside the server's API container:

```bash
docker compose exec api python3 -c "
from app.services.analytics import youtube_api
print(youtube_api.readiness())
"
```

Expected: `(True, '')`.

`config.toml` needs no change, as long as `[youtube] enabled = true` is
already set from the posting setup. The analytics-related settings all
have sensible defaults (see step 9).

## 8. Run the first sync

1. Open the WebUI → top bar → **Analytics**. (On the VPS, through your SSH
   tunnel: `ssh -L 8501:127.0.0.1:8501 youruser@YOUR_SERVER_IP`, then
   <http://localhost:8501>.)
2. The yellow *"token only allows uploads"* banner should be gone.
3. Click **🔄 Sync now**. The first sync:
   - lists every video on your channel;
   - matches them to the app's videos (by upload ID or by title) and marks
     hand-posted ones as posted;
   - backfills each video's lifetime metrics, one request per 200 videos;
   - sorts your topics into categories with your configured LLM.

   It takes a few seconds to a minute. A toast shows how many videos were
   found, matched, and newly marked as posted.
4. Check the **Reconcile** tab for any near-miss titles to confirm.

From now on, the daily cron (`POST /api/v1/schedules/run`) syncs
automatically before it uploads. You don't need to add anything to your
crontab.

**What to expect from the numbers:**

- Views, likes and comments are live (from the Data API).
- Watch time, % viewed, shares and subscribers come from the Analytics
  API, which settles each day's numbers after about 3 days. Very new
  videos show blanks there at first; that's normal.
- "Views after 7 days" fills in for videos published from now on, because
  the app snapshots their views daily.

## 9. Optional settings

In `config.toml`:

```toml
[youtube]
# Sync the channel at the start of every cron run (matches hand-posted
# videos before uploads, refreshes the stats). Default: true
analytics_sync_before_uploads = true
```

To refresh more than once a day, add a second crontab line on the server,
for example at 18:00:

```
0 18 * * * curl -s -X POST http://127.0.0.1:9000/api/v1/analytics/sync -H "x-api-key: YOUR-API-KEY-HERE" >> $HOME/mpt-analytics.log 2>&1
```

## Quota: will this eat into my 6 uploads a day?

No.

- **YouTube Data API** (shared with uploads, 10,000 units/day): listing
  the channel costs about **1 unit per 50 videos**. A 500-video channel
  costs ~12 units per sync; one upload costs 1,600.
- **YouTube Analytics API** has its **own** quota, separate from uploads.
  After the first backfill, each sync only asks for the few days not
  stored yet: one request per 200 videos.

To see usage: ☰ menu → **APIs & Services** → **Enabled APIs & services** →
click an API → **Quotas & System Limits** (or the **Metrics** tab).

---

**Done.** What each tab shows is in [analytics.md](analytics.md).

## Troubleshooting

- **Analytics page says "Your YouTube token only allows uploads"** →
  step 5 wasn't done, a "View" box was left unticked, or the VPS still has
  the old `token.json` (step 7). Run `youtube_auth.py` again, tick every
  box, and re-copy the token.
- **"YouTube refused the request (403 …)" / "YouTube Analytics API has
  not been used in project … or it is disabled"** → the API isn't enabled
  in the project your OAuth client belongs to. Redo step 1's Client ID
  check, then step 2. If you just enabled it, wait 5 minutes.
- **"insufficientPermissions" / "Request had insufficient authentication
  scopes"** → same as the first item: the token lacks a read permission.
- **"YouTube authorization expired" / `invalid_grant`** → the consent
  screen is still in **Testing** (tokens die after 7 days). Do step 3.2
  (**Publish app**), then step 5 and step 7 again.
- **"The authorized Google account has no YouTube channel"** → you signed
  in with the personal account instead of the Brand Account that owns the
  channel. Run `youtube_auth.py` again and pick the **channel** at the
  account chooser.
- **"Access blocked: … has not completed the Google verification
  process"** → the app is in Testing and the account you picked isn't a
  **Test user** (step 3.2), or you picked a different Google account.
- **Watch time / % viewed are empty but views show** → the videos are
  newer than about 3 days, or the API was enabled minutes ago. Sync again
  tomorrow.
- **Uploads stopped working after this** → shouldn't happen: the new
  token still has the upload permission. Check the upload box was ticked
  in step 5; if not, run `youtube_auth.py` again and tick all three.
