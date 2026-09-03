# Step 1 — Google Cloud Setup (for YouTube uploads)

Goal: get a `client_secret.json` file that lets MoneyPrinterTurbo talk to the
YouTube API on behalf of your Google account. Free, takes about 10 minutes,
no billing card required.

Do this on your Mac in a normal browser, signed in to the **Google account
that owns your YouTube channel**.

---

## 1. Create a Google Cloud project

1. Open <https://console.cloud.google.com> and sign in.
2. At the top-left, next to the "Google Cloud" logo, click the **project
   selector dropdown** (it shows your current project name, or "Select a
   project").
3. In the dialog that opens, click **NEW PROJECT** (top-right).
4. Fill in:
   - **Project name**: `MoneyPrinterTurbo` (anything works)
   - **Location**: leave as "No organization"
5. Click **CREATE**.
6. Wait ~10 seconds. A notification bell (top-right) shows when it's ready.
   Click the project selector dropdown again and **select your new project**
   so everything below happens inside it. The dropdown at the top should now
   read `MoneyPrinterTurbo`.

## 2. Enable the YouTube Data API v3

1. Open the left-hand ☰ menu → **APIs & Services** → **Library**.
   (Or go straight to <https://console.cloud.google.com/apis/library>.)
2. In the search box type: `YouTube Data API v3`
3. Click the result named **YouTube Data API v3**.
4. Click the blue **ENABLE** button.
5. You'll land on the API's overview page — that means it's enabled. Done.

## 3. Configure the OAuth consent screen

Google requires this before it will issue credentials. You are the only
user, so the minimal setup is fine.

1. ☰ menu → **APIs & Services** → **OAuth consent screen**.
2. If you see a "Get started" / branding wizard (newer console UI):
   - **App name**: `MoneyPrinterTurbo`
   - **User support email**: pick your email from the dropdown
   - **Audience**: choose **External** ("Internal" is only available for
     Google Workspace organizations)
   - **Contact information**: your email again
   - Agree to the policy checkbox → **CREATE** / **CONTINUE** through the
     remaining steps. You do NOT need to add scopes or upload a logo.
3. Add yourself as a test user:
   - Still under **APIs & Services → OAuth consent screen**, find the
     **Audience** section (older UI: "Test users" section on the main page;
     newer UI: left sidebar → **Audience**).
   - Under **Test users**, click **+ ADD USERS**.
   - Enter the Gmail address of the account that owns your YouTube channel.
   - Click **SAVE**.
4. Set **Publishing status** to **In production** (**Publish app** →
   confirm). This matters: **while the app stays in "Testing", the refresh
   token expires after exactly 7 days** and every upload after that fails
   with `invalid_grant: Token has been expired or revoked`. Publishing does
   not force you through Google's verification review — an unverified app
   using a sensitive scope just shows an "unverified app" warning on the
   consent screen (click **Advanced → Go to … (unsafe)**) and is capped at
   100 users, which is irrelevant for a personal channel. Its refresh
   tokens do not expire on a timer.

> If you leave the app in Testing anyway, put a weekly reminder in your
> calendar to re-run `python youtube_auth.py` (step 2 doc) and re-copy
> `token.json` to the server — otherwise scheduled uploads stop silently
> after a week.

## 4. Create the OAuth client (Desktop app)

1. ☰ menu → **APIs & Services** → **Credentials**.
2. Click **+ CREATE CREDENTIALS** (top) → **OAuth client ID**.
3. **Application type**: select **Desktop app**.
4. **Name**: `MoneyPrinterTurbo Desktop` (anything).
5. Click **CREATE**.
6. A dialog shows your Client ID and secret. Click **DOWNLOAD JSON**.
   The file downloads as something like
   `client_secret_1234567890-abc123.apps.googleusercontent.com.json`.

## 5. Put the file where the app expects it

In Terminal, from the MoneyPrinterTurbo folder:

```bash
mkdir -p storage/youtube
mv ~/Downloads/client_secret_*.json storage/youtube/client_secret.json
```

Verify:

```bash
ls -la storage/youtube/
```

You should see exactly one file: `client_secret.json`.

---

**Done.** Continue with [setup-2-youtube-auth.md](setup-2-youtube-auth.md).

## Troubleshooting

- **"Access blocked: MoneyPrinterTurbo has not completed the Google
  verification process"** during sign-in later → you forgot step 3.3 (add
  your email as a **test user**), or you signed in with a different Google
  account than the one you added.
- **Can't find "OAuth consent screen"** → make sure the correct project is
  selected in the top dropdown.
- **ENABLE button missing / greyed out on the API page** → the API is
  already enabled; that's fine.
