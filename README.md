# kalshi-news

A news and analytics layer over [Kalshi](https://kalshi.com). It ingests news
articles and X posts, links each one to the prediction markets it bears on
with a YES/NO direction and a plain-English rationale, tracks how those
markets moved afterwards, and serves the result over a read API.

Two parts: a Python pipeline and read API in `backend/`, and a
server-rendered Next.js frontend in `frontend/`. The browser never contacts
the backend directly — Server Components fetch at render time and one thin
route handler proxies pagination.

The designs live in
[`docs/superpowers/specs/2026-09-17-kalshi-news-design.md`](docs/superpowers/specs/2026-09-17-kalshi-news-design.md)
(the pipeline) and
[`docs/superpowers/specs/2026-09-18-frontend-and-deploy-design.md`](docs/superpowers/specs/2026-09-18-frontend-and-deploy-design.md)
(the frontend and the deploy path), with their implementation plans beside
them in `docs/superpowers/plans/`.

## Architecture

Four stages, connected only through Postgres — never by direct calls. Each is
an idempotent job behind an authenticated HTTP endpoint that GitHub Actions
cron invokes on a schedule.

```
[ Kalshi sync ]   mirrors the public market catalog, embeds changed markets
[ Ingestors   ]   RSS feeds; X hydrated via publish.twitter.com/oembed
[ Linker      ]   pgvector picks 10 candidate markets -> one Claude Haiku call
                  confirms relevance, direction and rationale
[ Impact      ]   fills price_1h / price_24h from Kalshi candlesticks
[ Read API    ]   /api/feed, /api/posts/{id}, /api/trending
```

Kalshi is used through its **public, unauthenticated** endpoints only. No auth
headers are ever sent and `/portfolio` is never called. X is read only through
the sanctioned oEmbed endpoint — no scraping, no headless browser, no
logged-in session.

- Embeddings: OpenAI `text-embedding-3-small`, 1536 dimensions.
- LLM: `claude-haiku-4-5-20251001`, with a hard daily spend cap held in the
  database. On hit, linking **pauses** (posts render untagged) rather than
  crashing or running up a bill.
- Precision is weighted over recall throughout: a missing tag is invisible, a
  wrong one looks broken.

## Requirements

Python 3.11 and a Postgres database with the `vector` (pgvector) extension
available, for the backend. Node 22 for the frontend.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | e.g. `postgresql+psycopg://user:pass@host:5432/kalshi_news` |
| `OPENAI_API_KEY` | yes | embeddings |
| `ANTHROPIC_API_KEY` | yes | link verification |
| `JOB_TOKEN` | yes | shared secret for `POST /api/jobs/{name}`. **Blank fails closed** — every job request is rejected |
| `DAILY_LLM_BUDGET_USD` | no | defaults to `1.0` |

`backend/.env.example` has a working local set.

## Running the backend

From `backend/`:

```bash
pip install -e ".[dev]"
alembic upgrade head          # creates the schema and seeds the RSS sources
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

`alembic upgrade head` is not optional beyond the schema: migration `0002`
seeds the `sources` table. Without it there are no feeds, so every stage
downstream is a no-op.

Reuters and AP are seeded **disabled** — as of 2026-09-17 neither serves a
public RSS feed any more (`feeds.reuters.com` was retired; `apnews.com`
answers feed URLs with a bot challenge). Politico, Bloomberg and CNBC are
seeded enabled and verified working. Re-enabling either is a one-row `UPDATE`.

## The frontend

A Next.js 15 App Router application (React 19, TypeScript strict, Tailwind
v4), server-rendered with 60-second ISR. From `frontend/`:

```bash
npm install
npm run dev            # http://localhost:3000
```

It needs one environment variable, `BACKEND_API_URL`, pointing at the
backend — server-side only, never exposed to the browser.
`frontend/.env.example` has a working local set.

The site carries **no product name**. The header is category tabs at the
left and a Kalshi attribution link at the right; it must never present
itself as Kalshi. The category tabs are derived from the categories the
seeded sources actually produce (`Politics`, `Economics`, `Finance`,
`World`) — adding a tab means seeding a source for it first, or it renders
empty forever.

### Frontend tests

```bash
cd frontend
npm test               # Vitest + React Testing Library
npm run typecheck      # tsc --noEmit
npm run build
npx playwright test    # one smoke test against a stubbed backend
```

`npm run build` must be run before `npx playwright test` is meaningful --
Playwright starts `npm run start`, which serves the last build.

The suite splits three ways, because Server Components resist unit testing
rather than because three tools are better than one:

| Layer | Tool | What it covers |
|---|---|---|
| Presentational components | Vitest + React Testing Library | Props in, DOM out — market tags, cards, the header, the empty state |
| Modules that fetch | Vitest + MSW | `lib/api.ts` and the `/api/feed` route handler, called directly with a `Request` |
| The intercepting-route wiring | Playwright | One test: clicking a card opens the overlay over a still-mounted feed |

**No test makes a live network call**, matching the backend's socket guard:
every HTTP call is intercepted by MSW, and Playwright runs against
`e2e/stub-backend.mjs`, a local process serving fixed JSON.

Two mechanical guards exist because the corresponding rules were prose that
a review had to enforce by hand: `lib/palette.test.ts` fails on any colour
outside the palette tokens, and `lib/format.test.ts` fails if a price is
formatted anywhere but `lib/format.ts`.

Frontend CI runs as its own job beside the backend's, so a broken frontend
fails the same pipeline.

## Deploy

The full, ordered path from empty accounts to a live public URL — Neon,
migrations, Railway, the first live job run (with the checkpoint that
matters most), GitHub Actions cron, and Vercel — is
[`docs/RUNBOOK.md`](docs/RUNBOOK.md). Every command in it is copy-pasteable.

Running costs, once deployed:

| Service | Cost |
|---|---|
| Vercel | free tier |
| Neon | free tier |
| Railway | ~$5/mo |
| Anthropic + OpenAI (LLM + embeddings) | ~$15-30/mo |

## Jobs

Each is `POST /api/jobs/{name}` with an `X-Job-Token` header, driven by
`.github/workflows/jobs.yml`.

| Job | Schedule | Work |
|---|---|---|
| `sync_markets` | every 15 min | Upsert the Kalshi catalog; embed markets whose text changed |
| `ingest` | every 10 min | Fetch every enabled source, isolated per source; discover tweet IDs |
| `link` | every 10 min | Embed, cluster, retrieve candidates, verify, write links |
| `impact` | hourly (`:17`) | Fill `price_1h` / `price_24h` from candlesticks |

Jobs run synchronously inside the HTTP request, so each batch is deliberately
small: `link` processes 15 posts per run, which at one run per 10 minutes
clears 2160 posts/day — comfortably above the ~800/day the spec projects. The
cron's `curl` calls carry `--max-time 120`.

Every job writes a `job_runs` row and always reaches a terminal status, and
every job is idempotent: re-running one never duplicates rows or double-charges
an API.

> **GitHub disables scheduled workflows after 60 days of repository
> inactivity.** If the demo goes quiet, the cron silently stops and the feed
> goes stale. Push a commit (or re-enable the workflow from the Actions tab)
> to restart it.

## Backend tests

From `backend/`:

```bash
export DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/kalshi_news_test'
pip install -e ".[dev]"
ruff check .
alembic upgrade head && alembic downgrade base
python -m pytest -v
```

The suite needs a real Postgres with pgvector; it creates and drops its own
schema. **No test may make a live external API call** — `tests/conftest.py`
installs an autouse socket guard that allows only the local database
connection and raises on every other outbound socket, so a forgotten mock
fails loudly instead of quietly reaching the internet.

`tests/test_end_to_end.py` is the one test that crosses every stage boundary:
it runs `sync_markets` → `run_ingest` → `run_link` → `GET /api/feed` against a
recorded-shape Kalshi payload with no network at all.

## Known gap: link precision is not yet measured

The spec sets a target of **≥0.85 precision on a golden set**, and
`tests/golden/golden_set.json` plus `app/eval/golden.py` provide the labelled
cases and the scoring harness. **That number has not been measured.** The
harness scores predictions that are handed to it; nothing yet runs the real
linker over the golden set, because doing so honestly requires recorded market
data for those cases. Until that harness exists, treat the precision target as
a stated goal, not a result.
