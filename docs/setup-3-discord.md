# Step 3 — Discord Alerts Setup

Goal: get a webhook URL so the app can post "🎬 video ready to publish"
messages (with a direct YouTube Studio link) into a Discord channel you
control. Takes 3 minutes.

---

## 1. Create a server (skip if you already have one)

1. Open Discord (app or <https://discord.com/app>).
2. In the left server column, click the **+** button ("Add a Server").
3. Choose **Create My Own** → **For me and my friends**.
4. Name it (e.g. `Content Ops`) → **Create**.

## 2. Create a channel for alerts (optional but tidy)

1. In your server, hover over a channel category and click the **+**
   (Create Channel), or right-click the channel list → **Create Channel**.
2. Type: **Text**. Name: `video-alerts`. Click **Create Channel**.

## 3. Create the webhook

1. Hover over the `#video-alerts` channel → click the **gear icon**
   (Edit Channel).
2. In the left menu, click **Integrations**.
3. Click **Webhooks** → **New Webhook**.
4. A webhook appears (random name like "Spidey Bot"). Click it to expand:
   - **Name**: `MoneyPrinterTurbo` (this is the sender name shown on alerts)
   - **Channel**: make sure it's `#video-alerts`
5. Click **Copy Webhook URL**.
6. Click **Save Changes** (green button at the bottom).

The URL looks like:
`https://discord.com/api/webhooks/1234567890/AbCdEfGh...`

> Treat it like a password — anyone with this URL can post into your
> channel. Don't commit it anywhere public (`config.toml` is already
> gitignored in this repo).

## 4. Put it in config.toml

Open `config.toml`, find the `[discord]` section, paste the URL:

```toml
[discord]
webhook_url = "https://discord.com/api/webhooks/1234567890/AbCdEfGh..."
```

## 5. Send a test message

```bash
.venv/bin/python -c "
from app.services.discord_notify import discord_notify_service
ok = discord_notify_service.send('✅ MoneyPrinterTurbo webhook test - it works!')
print('sent:', ok)
"
```

Check the `#video-alerts` channel — the test message should be there, and
the terminal should print `sent: True`.

---

**Done.** If you're deploying to a server, continue with
[setup-4-vps-deploy.md](setup-4-vps-deploy.md).

## What alerts you'll get

- **Green embed** per uploaded video: title, scheduled date, topic, your
  planned post time, a **YouTube Studio edit link** (one click → flip to
  Public) and a preview link.
- **Red embed** if a scheduled generation or upload fails, with the date,
  topic and error so you know what to fix.

## Troubleshooting

- **`sent: False` and a 404 in the logs** → the URL is wrong or the webhook
  was deleted. Copy it again from Channel settings → Integrations.
- **`sent: False` and a 401/403** → the URL is truncated — make sure you
  copied the whole thing including the long token after the last `/`.
- **No Integrations menu** → you don't have "Manage Webhooks" permission on
  that server; use a server you own.
