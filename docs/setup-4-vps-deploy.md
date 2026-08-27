# Step 4 — Deploy on Your VPS

Goal: the app runs 24/7 on your VPS in Docker, a cron job fires once a day,
generates whatever the calendar says, uploads drafts to YouTube, and pings
you on Discord.

Assumptions:
- Ubuntu or Debian VPS (commands note where other distros differ)
- at least 4 GB RAM (8 GB is comfortable; rendering is memory-hungry)
- you can SSH in as root or a sudo user
- steps 1–3 are done **on your Mac first** (Google Cloud, YouTube auth,
  Discord), because the OAuth step needs a browser

Replace `YOUR_SERVER_IP` and `youruser` with your actual values throughout.

---

## 1. First-time server prep (once)

SSH in:

```bash
ssh youruser@YOUR_SERVER_IP
```

Install Docker (official convenience script, works on Ubuntu/Debian):

```bash
curl -fsSL https://get.docker.com | sudo sh
```

Let your user run Docker without sudo, then re-login to apply it:

```bash
sudo usermod -aG docker $USER
exit
```

```bash
ssh youruser@YOUR_SERVER_IP
docker --version
```

You should see a Docker version line. Also make sure git is present:

```bash
sudo apt-get update && sudo apt-get install -y git
```

(RHEL/Fedora: `sudo dnf install -y git`. The Docker script works there too.)

## 2. Get the code onto the server

```bash
cd ~
git clone https://github.com/Samuel-Oyedeji/moneyprinter.git MoneyPrinterTurbo
cd MoneyPrinterTurbo
```

> The trailing `MoneyPrinterTurbo` matters: the repo is named `moneyprinter`,
> but every path later in this guide assumes `~/MoneyPrinterTurbo`, so we
> clone into that folder name explicitly.
>
> If you don't want to use GitHub, copy the whole project from your Mac (run this **on your Mac**, and note the trailing
> slash after the folder name):
>
> ```bash
> rsync -av --exclude .venv --exclude storage/tasks --exclude storage/cache_videos \
>   ~/Documents/explore/MoneyPrinterTurbo/ youruser@YOUR_SERVER_IP:~/MoneyPrinterTurbo/
> ```

## 3. Set an API key locally, then copy config + credentials to the server

The cron endpoint (and the whole API) should be protected. **On your Mac**,
edit `config.toml` and set a long random value under `[app]`:

```toml
[app]
api_key = "PICK-A-LONG-RANDOM-STRING-HERE"
```

(Generate one with: `openssl rand -hex 32`)

Then copy your working config and the YouTube credentials **from your Mac**:

```bash
cd ~/Documents/explore/MoneyPrinterTurbo
scp config.toml youruser@YOUR_SERVER_IP:~/MoneyPrinterTurbo/
ssh youruser@YOUR_SERVER_IP "mkdir -p ~/MoneyPrinterTurbo/storage/youtube"
scp storage/youtube/client_secret.json storage/youtube/token.json \
    youruser@YOUR_SERVER_IP:~/MoneyPrinterTurbo/storage/youtube/
```

If you already have calendar entries you want to keep:

```bash
ssh youruser@YOUR_SERVER_IP "mkdir -p ~/MoneyPrinterTurbo/storage/schedule"
scp storage/schedule/schedule.json youruser@YOUR_SERVER_IP:~/MoneyPrinterTurbo/storage/schedule/
```

## 4. Build and start the containers

**On the server:**

```bash
cd ~/MoneyPrinterTurbo
docker compose up -d --build
```

The first build takes several minutes (it installs ffmpeg and all Python
deps). When it finishes:

```bash
docker compose ps
```

Both `moneyprinterturbo-webui` and `moneyprinterturbo-api` should show
`running`. Sanity checks:

```bash
curl -s http://127.0.0.1:9000/ping
curl -s http://127.0.0.1:9000/api/v1/schedules -H "x-api-key: YOUR-API-KEY-HERE"
```

The second command should return JSON with `"status":200`.

View logs any time:

```bash
docker compose logs -f api      # Ctrl-C to stop watching
docker compose logs -f webui
```

Both ports are bound to `127.0.0.1` on the server, so **nothing is exposed
to the internet**. That's intentional — see step 7 for how you access the UI.

## 5. The daily cron job

**On the server**, open your crontab:

```bash
crontab -e
```

Add this line (runs every day at 06:00 server time — check the server
timezone with `timedatectl` first; adjust the hour to taste):

```
0 6 * * * curl -s -X POST http://127.0.0.1:9000/api/v1/schedules/run -H "x-api-key: YOUR-API-KEY-HERE" -H "Content-Type: application/json" -d '{}' >> $HOME/mpt-schedule.log 2>&1
```

Save and exit. Verify it registered:

```bash
crontab -l
```

Notes:
- The endpoint returns immediately; generation runs in the background
  inside the API container. A busy day (several videos) can take an hour+ —
  that's fine.
- If the server was off/rebooting at 06:00, the *next* run automatically
  catches up: entries stay `pending` until a run actually processes them.
- To trigger a run manually right now:

  ```bash
  curl -s -X POST http://127.0.0.1:9000/api/v1/schedules/run -H "x-api-key: YOUR-API-KEY-HERE" -H "Content-Type: application/json" -d '{}'
  ```

## 6. Test the whole pipeline once (recommended)

1. Open the WebUI via the SSH tunnel (step 7) → **Schedule** page → add an
   entry for **today** with 1 video, any topic.
2. Trigger a manual run with the curl command above.
3. Watch it work:

   ```bash
   docker compose logs -f api
   ```

4. Within ~5–15 minutes you should get the Discord alert; the video will be
   sitting in YouTube Studio as **Private**.

## 7. Accessing the WebUI remotely (SSH tunnel)

Don't open ports. From **your Mac**, run:

```bash
ssh -L 8501:127.0.0.1:8501 -L 9000:127.0.0.1:9000 youruser@YOUR_SERVER_IP
```

While that SSH session stays open, `http://127.0.0.1:8501` in your Mac's
browser IS the server's WebUI (and `:9000` the API). Manage the calendar
from there exactly like you did locally.

## 8. Updating the app later

```bash
cd ~/MoneyPrinterTurbo
git pull                        # or re-run the rsync from your Mac
docker compose up -d --build
```

Config, schedule and YouTube tokens survive updates — they live in
`config.toml` and `storage/`, which are bind-mounted, not baked into the
image.

## 9. Housekeeping

Rendered videos accumulate in `storage/tasks/` (hundreds of MB each run).
Add a weekly cleanup cron that deletes task folders older than 14 days
(the videos are already on YouTube by then):

```
0 5 * * 0 find $HOME/MoneyPrinterTurbo/storage/tasks -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
```

Disk check when curious: `df -h` and `du -sh ~/MoneyPrinterTurbo/storage/*`.

---

## Troubleshooting

- **`docker compose up` fails with "permission denied on the docker
  socket"** → you skipped the re-login after `usermod -aG docker`. Log out
  and back in.
- **Container killed mid-render / videos fail on big batches** → RAM. Check
  with `free -h`. Add swap as a cheap fix:

  ```bash
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

- **Cron didn't fire** → check `grep CRON /var/log/syslog` (Ubuntu) and that
  the crontab line has no line breaks. Test the curl command by hand first.
- **YouTube upload fails with `quotaExceeded`** → more than ~6 uploads that
  day; the rest upload tomorrow if you set the entry back to `pending`
  (Schedule page → Retry), or request a quota increase.
- **Upload fails with invalid credentials** → re-run
  `.venv/bin/python youtube_auth.py` on your Mac and re-copy
  `storage/youtube/token.json` to the server.
