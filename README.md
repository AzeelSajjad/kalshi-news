# kalshi-news

A news and analytics layer over [Kalshi](https://kalshi.com). It ingests news
articles and X posts, links each one to the prediction markets it bears on
with a YES/NO direction and a plain-English rationale, tracks how those
markets moved afterwards, and serves the result over a read API.

This repository is the backend. The design lives in
[`docs/superpowers/specs/2026-09-17-kalshi-news-design.md`](docs/superpowers/specs/2026-09-17-kalshi-news-design.md)
and the implementation plan in
[`docs/superpowers/plans/2026-09-17-backend-pipeline.md`](docs/superpowers/plans/2026-09-17-backend-pipeline.md).

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
available.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | e.g. `postgresql+psycopg://user:pass@host:5432/kalshi_news` |
| `OPENAI_API_KEY` | yes | embeddings |
| `ANTHROPIC_API_KEY` | yes | link verification |
| `JOB_TOKEN` | yes | shared secret for `POST /api/jobs/{name}`. **Blank fails closed** — every job request is rejected |
| `DAILY_LLM_BUDGET_USD` | no | defaults to `1.0` |

`backend/.env.example` has a working local set.

## Running it

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

## Tests

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
