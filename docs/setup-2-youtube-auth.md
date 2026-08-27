# Step 2 — YouTube Authorization (one-time)

Goal: sign in once so the app gets a **refresh token**
(`storage/youtube/token.json`). After this, uploads work forever without a
browser — including on your VPS.

Prerequisite: you finished
[setup-1-google-cloud.md](setup-1-google-cloud.md) and
`storage/youtube/client_secret.json` exists.

Do this **on your Mac** (it needs to open a browser).

---

## 1. Run the auth script

From the MoneyPrinterTurbo folder:

```bash
.venv/bin/python youtube_auth.py
```

What happens:

1. Your default browser opens a Google sign-in page automatically.
   (If it doesn't, the terminal prints a URL — copy it into your browser.)
2. **Choose the Google account that owns your YouTube channel.**
3. You'll see a warning screen: *"Google hasn't verified this app"*.
   This is expected — it's your own app in testing mode.
   Click **Continue** (you may need to click "Advanced" →
   "Go to MoneyPrinterTurbo (unsafe)" first, depending on the screen shown).
4. On the permissions screen ("MoneyPrinterTurbo wants access to your
   Google Account — Upload videos to your YouTube channel"), click
   **Continue** / **Allow**.
5. The browser shows "The authentication flow has completed. You may close
   this window." — close it.
6. The terminal prints a success line with the token path.

Verify the token exists:

```bash
ls -la storage/youtube/token.json
```

## 2. Enable uploads in config.toml

Open `config.toml` and change the `[youtube]` section:

```toml
[youtube]
enabled = true            # <-- was false
client_secrets_file = ""  # leave empty (uses the default path)
token_file = ""           # leave empty (uses the default path)
default_privacy_status = "private"
category_id = "22"
```

## 3. Verify it works (optional but recommended)

This does a dry credential check without uploading anything:

```bash
.venv/bin/python -c "
from app.services.youtube_upload import youtube_upload_service
creds = youtube_upload_service._load_credentials()
print('OK - credentials valid:', creds.valid)
print('Configured:', youtube_upload_service.is_configured())
"
```

Expected output:

```
OK - credentials valid: True
Configured: True
```

The Schedule page in the WebUI will also stop showing the
"YouTube is not connected" warning once this is done.

---

**Done.** Continue with [setup-3-discord.md](setup-3-discord.md).

## What to know

- **Where videos land**: your channel → YouTube Studio → Content. Each
  scheduled video appears with **Visibility: Private**, title, description,
  hashtags and thumbnail already filled in. Click it → set Visibility to
  **Public** → done.
- **Daily quota**: ~6 uploads/day on Google's default free quota (each
  upload costs 1,600 of 10,000 units). If you schedule more than 6 videos
  on one date, the extra uploads will fail with a `quotaExceeded` error and
  you'll get a Discord failure alert. To raise it: Google Cloud Console →
  APIs & Services → YouTube Data API v3 → Quotas → request increase.
- **Thumbnails**: need a phone-verified channel
  (<https://www.youtube.com/verify>, takes 2 minutes). Without it uploads
  still succeed — only the custom thumbnail is skipped.
- **Re-authorizing**: if uploads ever fail with "credentials are invalid
  and cannot be refreshed", just run `.venv/bin/python youtube_auth.py`
  again and (for VPS) re-copy `token.json` to the server.

## Troubleshooting

- **"OAuth client secrets file not found"** → the JSON isn't at
  `storage/youtube/client_secret.json`. Re-check step 5 of the Google
  Cloud doc.
- **"Access blocked" / "app has not completed verification"** → your Google
  account isn't added as a **test user** on the OAuth consent screen, or
  you picked the wrong account at sign-in.
- **Browser opens but hangs on localhost** → a firewall/VPN is blocking the
  local callback. Disable it briefly and re-run.
