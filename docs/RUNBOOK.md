# Deploy runbook

The ordered path from four empty accounts to a live, publicly reachable
feed. Follow the steps in order — each one verifies the step before it, so
if a verification fails, stop and fix that step before moving on.

Every command below is copy-pasteable once you substitute the bracketed
placeholders (`<railway-domain>`, `<neon-connection-string>`, etc.) with
your own values.

You will need accounts on: [Neon](https://neon.tech) (Postgres), Railway
(backend host), Vercel (frontend host), plus an Anthropic API key
([console.anthropic.com](https://console.anthropic.com)) and an OpenAI API
key ([platform.openai.com](https://platform.openai.com)). Creating these
accounts and entering the keys is on you — nothing here does it for you.

## Step 1 — Neon: create the database

1. Create a Neon account and a new project (any region; pick one close to
   where you'll run Railway).
2. On the project dashboard, click **Connect**. The connection widget has a
   **Connection pooling** toggle — leave it **on** (it's on by default for
   new projects). Copy the connection string it shows you. It looks like:

   ```
   postgresql://<user>:<password>@ep-xxxx-pooler.<region>.aws.neon.tech/<dbname>?sslmode=require
   ```

   The hostname contains `-pooler` — that's how you know you copied the
   pooled string, not the direct one. This matters because Railway (Step 3)
   holds its own persistent SQLAlchemy connection pool; pointing that at
   Neon's direct (unpooled) endpoint means every app connection holds a
   Postgres backend connection open indefinitely, which exhausts Neon's
   free-tier connection limit under real traffic. The pooled endpoint
   (PgBouncer) is built to absorb that.
3. Save this string somewhere you can get it back — you'll paste it twice:
   once for the migration in Step 2, once into Railway in Step 3.

## Step 2 — Run migrations

Run this once, from your own machine, against the Neon pooled string from
Step 1. The app and Alembic both read `DATABASE_URL` through SQLAlchemy,
which needs the `+psycopg` driver prefix — Neon's copied string starts with
plain `postgresql://`, so add `+psycopg` when you paste it in:

```bash
cd backend
pip install -e ".[dev]"
DATABASE_URL='postgresql+psycopg://<user>:<password>@ep-xxxx-pooler.<region>.aws.neon.tech/<dbname>?sslmode=require' alembic upgrade head
```

This applies two migrations: `0001_initial` (schema, including the
`vector` extension) and `0002_seed_sources` (seeds the `sources` table with
RSS feeds and one X source). **`0002_seed_sources` is not optional** —
skip it and there are no sources for `ingest` to read, so every stage
downstream of it is permanently a no-op.

**Verify:**

```bash
psql 'postgresql://<user>:<password>@ep-xxxx-pooler.<region>.aws.neon.tech/<dbname>?sslmode=require' -c "select count(*) from sources;"
```

(Use the plain `postgresql://` string here, without `+psycopg` — `psql`
doesn't understand the SQLAlchemy driver suffix.)

Expect a non-zero count (9 rows, as seeded by the current migration). If
it's `0`, the seed migration didn't run — re-run `alembic upgrade head` and
read the output for errors before continuing.

## Step 3 — Railway: deploy the backend

1. Create a Railway account, then **New Project → Deploy from GitHub repo**
   and select this repository.
2. Generate the job token now, before you fill in variables — you'll need
   the same value again in Step 5:

   ```bash
   openssl rand -hex 32
   ```

   Save the output; treat it like a password.
3. In the service's **Settings → Service**, set **Root Directory** to
   `backend/`. This is required for Railway's builder (Nixpacks) to see
   `backend/pyproject.toml` and detect a Python app at all. With the root
   directory set this way, Railway also picks up `backend/Procfile`
   automatically and uses it as the start command — nothing else to
   configure. `Procfile` lives in `backend/`, not the repository root; if
   you ever point Root Directory at the repo root instead, Railway won't
   find it and the deploy will build but never start.
4. In **Settings → Variables**, add:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | the same `postgresql+psycopg://...` string from Step 2 |
   | `ANTHROPIC_API_KEY` | your key from console.anthropic.com |
   | `OPENAI_API_KEY` | your key from platform.openai.com |
   | `JOB_TOKEN` | the value from `openssl rand -hex 32` (item 2 above) |
   | `DAILY_LLM_BUDGET_USD` | `1.0` |
5. Deploy. Once the build finishes, give the service a public URL:
   **Settings → Networking → Generate Domain**. Railway does not expose a
   domain by default. Note the resulting URL (e.g.
   `https://kalshi-news-backend-production.up.railway.app`) — every step
   from here on calls it `<railway-domain>`.
6. **Verify:**

   ```bash
   curl https://<railway-domain>/health
   ```

   Expect `{"status":"ok"}`. `{"status":"error"}` means the app started but
   can't reach the database — recheck `DATABASE_URL`. A timeout or
   connection refused means the deploy is still building or crashed — check
   the Railway deploy logs before continuing.

## Step 4 — First job run: first contact with live Kalshi data

Everything up to this point has been verified against tests and recorded
payloads. This is the first time the pipeline runs against **live, real**
Kalshi and RSS data. Run the four jobs in this exact order — each depends
on rows the previous one wrote — and check the database after each one.

```bash
export JOB_TOKEN='<value generated in Step 3>'
export API=https://<railway-domain>
export DB='<neon connection string from step 1, without +psycopg>'
```

**1. Sync markets:**

```bash
curl -X POST "$API/api/jobs/sync_markets" -H "X-Job-Token: $JOB_TOKEN" --max-time 120
```

```bash
psql "$DB" -c "select count(*) from markets;"
```

Expect non-zero. If it's `0`, `sync_markets` couldn't reach or parse
Kalshi's public market catalog — check the Railway logs for that request.

**2. Ingest:**

```bash
curl -X POST "$API/api/jobs/ingest" -H "X-Job-Token: $JOB_TOKEN" --max-time 120
```

```bash
psql "$DB" -c "select count(*) from posts;"
```

Expect non-zero — the enabled RSS feeds parsed into rows.

**3. Link:**

```bash
curl -X POST "$API/api/jobs/link" -H "X-Job-Token: $JOB_TOKEN" --max-time 120
```

```bash
psql "$DB" -c "select count(*) from post_markets;"
```

**4. Impact — and why the demo needs a day before you share it:**

```bash
curl -X POST "$API/api/jobs/impact" -H "X-Job-Token: $JOB_TOKEN" --max-time 120
```

Expect this to fill **nothing** the first time, and that is correct.
`app/jobs/impact.py` skips any link younger than an hour, because a "how
far did it move in the first hour" number cannot exist before an hour has
passed. So immediately after the first `link` run, every `price_delta` in
the API is `null`, and the observed-move badge — the single most compelling
element of the whole demo, the thing that turns "this news relates to this
market" into "this news moved this market" — renders **nowhere**.

Deltas start appearing about an hour after the first `link` run and fill
out over the following 24 hours as the hourly cron keeps calling `impact`.
Check progress with:

```bash
psql "$DB" -c "select count(*) from post_markets where price_1h is not null;"
```

`0` an hour or more after the first `link` run, with `post_markets > 0`,
means candlesticks aren't coming back for these tickers — check
`job_runs.error` for the `impact` job. Anything above `0` means the badge
is live.

**Deploy a day before you send anyone the URL.** A site opened an hour
after deploy is a correct site showing its least interesting face, and a
recruiter only opens the link once.

### Read this before you touch Step 5

- **`markets` > 0, `posts` > 0, `post_markets` > 0:** retrieval and linking
  worked. Continue to Step 5.
- **`markets` > 0, `posts` > 0, `post_markets` is `0`:** retrieval is
  finding no candidates for any post at all. **Stop here.** Do not proceed
  to the frontend — it will render a feed that looks complete but is
  silently, permanently untagged, and nothing about it will look broken
  from the outside. This is the exact failure mode this project has
  already shipped twice, invisible both times because every test passed.
  Investigate before deploying anything on top of it:

  ```bash
  psql "$DB" -c "select ticker, title, close_time, (embedding is not null) as has_embedding from markets limit 5;"
  psql "$DB" -c "select id, title, published_at, (embedding is not null) as has_embedding from posts limit 5;"
  psql "$DB" -c "select job, status, items_processed, error from job_runs order by started_at desc limit 5;"
  ```

  Retrieval and the read API both filter markets on `close_time > now()` —
  if every synced market has already closed, nothing is eligible to match.
  Retrieval is a pgvector similarity search over the `embedding` column on
  both sides — a null embedding on either markets or posts means that row
  is never compared. Check `job_runs.error` for the `link` job's most
  recent row for an explicit failure message.
- **`markets` is `0`:** `sync_markets` didn't write anything even though
  Step 3's health check passed. Re-check the Railway logs for that job
  specifically.
- **`posts` is `0` while `markets` > 0:** either every source errored, or
  none are enabled. Check:

  ```bash
  psql "$DB" -c "select count(*) from sources where enabled;"
  ```

  Expect `7` (6 RSS feeds plus the X source; Reuters and AP are seeded
  disabled — see `README.md`). If that's `0`, Step 2's seed migration
  didn't apply correctly.

## Step 5 — GitHub Actions: turn on the cron

1. In the GitHub repo: **Settings → Secrets and variables → Actions → New
   repository secret**. Add two:

   | Name | Value |
   |---|---|
   | `API_URL` | `https://<railway-domain>` (no trailing slash) |
   | `JOB_TOKEN` | the same value from Step 3 |
2. `.github/workflows/jobs.yml` already defines the schedule (`sync_markets`
   every 15 minutes, `ingest`+`link` every 10 minutes, `impact` hourly) and
   is committed to the repo — nothing to write here. Confirm it's active:
   **Actions tab → "Scheduled jobs"** — if GitHub shows it as disabled,
   click **Enable workflow**.
3. Optional: trigger it once by hand to confirm the secrets are correct —
   **Actions → "Scheduled jobs" → Run workflow** (the workflow accepts
   `workflow_dispatch`).

GitHub automatically disables scheduled workflows after 60 days with no
commits to the repository. If the demo goes quiet, the cron silently stops;
push a commit or re-enable it manually from the Actions tab to restart it.

## Step 6 — Vercel: deploy the frontend

1. Create a Vercel account, then **New Project → Import** this GitHub
   repository.
2. On the import screen, set **Root Directory** to `frontend/`. **This is
   the single most common cause of a failed first deploy in a monorepo** —
   left at the default (repo root), Vercel won't find `package.json` or
   `next.config.ts` and the build fails immediately. `frontend/vercel.json`
   (already in the repo) pins the framework and build command once the root
   directory is set correctly:

   ```json
   {
     "buildCommand": "npm run build",
     "framework": "nextjs"
   }
   ```
3. Add an environment variable (on the import screen, or later under
   **Settings → Environment Variables**):

   | Name | Value |
   |---|---|
   | `BACKEND_API_URL` | `https://<railway-domain>` (no trailing slash) |
4. Deploy.
5. **Verify:** open the deployed URL. The feed should render populated
   posts, not an empty state. If Step 4's checkpoint passed cleanly, each
   post should also show at least one linked market. Market tags will carry
   **no observed-move badge yet** — see Step 4.4; that is expected for the
   first hour and is not a deploy failure.

## If it's broken

- **Feed page loads but shows no posts at all** — `select count(*) from
  posts;` on Neon is `0`, or `BACKEND_API_URL` in Vercel points at the
  wrong Railway URL. Recheck Step 4 and Step 6.3.
- **Feed renders but nothing has a market attached** — `select count(*)
  from post_markets;` is `0`. This is the Step 4 checkpoint failure; go
  back and work through that section, starting with `job_runs.error` for
  the `link` job.
- **Markets show but no observed-move badge, hours after deploy** —
  `select count(*) from post_markets where price_1h is not null;` is still
  `0`. Confirm the `impact` job is actually running (`select job, status,
  items_processed, error from job_runs where job = 'impact' order by
  started_at desc limit 5;`). An hourly job that has never run means the
  GitHub Actions cron is off — see Step 5.
- **Frontend shows a 502/504, or an error page mentioning the backend** —
  `BACKEND_API_URL` is wrong, or Railway is asleep or crashed. Run `curl
  https://<railway-domain>/health` directly: anything other than
  `{"status":"ok"}` means the problem is on Railway's side, not Vercel's.
- **Railway build succeeds but the app never starts** — confirm Root
  Directory is set to `backend/` (Step 3.3). `Procfile` lives in
  `backend/`, not the repository root; if Root Directory is left at the
  repo root, Railway won't find it and has no start command to run.
- **`alembic upgrade head` can't connect** — confirm the connection string
  has `-pooler` in the hostname, `+psycopg` added after `postgresql`, and
  `?sslmode=require` at the end.

## Running costs

| Service | Cost |
|---|---|
| Vercel | free tier |
| Neon | free tier |
| Railway | ~$5/mo |
| Anthropic + OpenAI (LLM + embeddings) | ~$15-30/mo |
