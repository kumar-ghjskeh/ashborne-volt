# Deploying Ashborne Volt

```
GitHub Actions ──▶ frontend/public/data (committed) ──▶ Vercel (static site + data)
Browser ──▶ Vercel  ·  Browser ──▶ Render API (Virginia) ──▶ Neon Postgres (us-east-1)
```

Never paste a password, key or connection string into chat or into this repo.
Secrets go straight from one dashboard into another.

## 1. GitHub (done)

Repository `kumar-ghjskeh/ashborne-volt`, public. Secret scanning, push
protection, Dependabot alerts + security updates and private vulnerability
reporting are on (Settings → Advanced Security).

## 2. Neon database (≈3 min)

1. https://console.neon.tech → **New Project**
2. Name `ashborne-volt` · Postgres: default · Cloud: **AWS** · Region:
   **AWS US East 1 (N. Virginia)** → **Create project**
3. **Connect** → turn **Connection pooling ON** (host contains `-pooler`) →
   copy the `postgresql://…` string into a private note. It goes into Render.

## 3. Gemini API key (≈2 min, optional — enables "Generate with Gemini")

1. https://aistudio.google.com/apikey → **Create API key**
2. Project: **Default Gemini Project** → copy the key into your private note.

## 4. Render (≈8 min)

1. https://dashboard.render.com → workspace name (top-left) → **+ New
   Workspace** → `Ashborne Volt`, Hobby (free). Stay in this workspace.
2. **New +** → **Blueprint** → connect GitHub → **Only select repositories** →
   `ashborne-volt` → Save → select the repo → **Connect**.
3. Blueprint name `ashborne-volt`. It creates `ashborne-volt-api` (region
   Virginia, from `render.yaml`) and asks for three secret values:
   * `DATABASE_URL` → the Neon string
   * `GEMINI_API_KEY` → the Gemini key (or leave blank)
   * `VAPID_PRIVATE_KEY` → the line in
     `C:\Users\saith\Ashborne-Volt-Secrets\VAPID_PRIVATE_KEY.txt`
4. **Apply** → wait for **Live**. Open the service and copy its URL
   (`https://ashborne-volt-api….onrender.com`).
5. Check `https://<that URL>/health` shows `"db":"ok"` and `"ai":"enabled"`.

## 5. Vercel (≈5 min)

1. https://vercel.com/new → **Import Git Repository** → `ashborne-volt` (if it
   is missing: **Adjust GitHub App Permissions** → add it → Save).
2. Project name `ashborne-volt` · Framework: Vite · **Root Directory: Edit →
   `frontend` → Continue**.
3. **Environment Variables**: `VITE_API_BASE` = the Render URL from step 4.
4. **Deploy**. Your site is `https://ashborne-volt.vercel.app` (if Vercel
   picked another name, set `CORS_ORIGINS` in Render to the real one).

## 6. Uptime pinger (≈2 min)

UptimeRobot → **+ New monitor** → HTTP(s) → `https://<render URL>/health` →
every 5 minutes. Keeps the free API awake during the day.

## Operations

* Scrapes run every 3 hours (Actions → **Scrape jobs**; "Run workflow" to run
  one now). A failed shard keeps its companies' previous data.
* Data Health in the app shows per-source status; quarantined/stalled sources
  need a config fix in `config/companies.yaml`.
* Vercel Hobby is for non-commercial use; move to Pro before charging money.
