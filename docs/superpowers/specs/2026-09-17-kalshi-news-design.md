# Kalshi News & Analytics Platform — Design

**Date:** 2026-09-17
**Status:** Approved, ready for implementation planning
**Working name:** `kalshi-news` (directory and repo). The display name is undecided; the UI renders a `<Wordmark/>` component so the final name is a single-file change.

## Purpose

A news and analytics layer for Kalshi that does not exist today: a single-page, chronological feed of news articles and X posts, where every item is automatically tagged with the Kalshi markets it bears on. Clicking an item centers it, shows who published it, links out to the original, and lists the related markets — each deep-linking to that market on Kalshi.

**Primary goal:** a polished, live, publicly reachable demo to send to Kalshi recruiters as evidence of product and engineering capability. This shapes every trade-off below: the deployed URL must always work, monthly cost must stay near zero, and the visible product must make an obvious argument that this feed would drive Kalshi signups and trade volume.

**Explicit non-goals:** user accounts, portfolios, comments, real-time websockets, mobile apps, and any write path to Kalshi. None strengthen the pitch; each costs a week.

## Success Criteria

1. A public URL that loads a populated, current feed at any time, with no manual intervention.
2. Market links are precise enough that a Kalshi employee scrolling the feed does not see an obviously wrong tag. Measured: ≥0.85 precision on the golden set (below).
3. Every post-market link carries a plain-English rationale and a YES/NO directional read.
4. Total running cost under $30/month.
5. The price-impact figure ("▲ 11¢ since this post") is populated for the majority of links older than an hour.

## Constraints Discovered During Design

These are load-bearing facts established by research, not assumptions:

- **Kalshi's public API needs no authentication.** `/series`, `/events`, `/markets`, order books, candlesticks, and trades are all public on `https://external-api.kalshi.com/trade-api/v2`. Only `/portfolio` requires their RSA-signed auth. The entire product is therefore credential-free with respect to Kalshi.
- **X has no usable free tier.** As of 2026-02-06, X replaced tiered pricing with pay-per-use at $0.005 per post read; new developers cannot sign up for Free/Basic/Pro at all. Polling 150 accounts would cost ~$338/month.
- **BeautifulSoup cannot scrape x.com.** The site is a JS-rendered SPA and guest tokens were removed in 2023; a plain HTTP fetch returns an empty shell. Playwright with a logged-in session works but risks account suspension and breaks on frontend changes — an unacceptable property for a link being emailed to recruiters.
- **Vercel's Hobby plan caps cron at once per day.** More frequent expressions fail deployment outright. Scheduling must live outside Vercel regardless of stack.

## Architecture

Four stages connected by the database, never by direct calls. Each is independently runnable and testable.

```
[ Ingestors ]  →  [ Linker ]  →  [ Impact tracker ]  →  [ Web app ]
 news RSS          embed post      snapshot price         feed
 X (oEmbed)        top-10 mkts     at t+0, +1h, +24h      centered post view
 (Reddit later)    Haiku verify    compute delta          trending rail
      ↓                 ↓                 ↓                    ↑
   posts table     post_markets      post_markets      ────────┘
                                                    [ Kalshi sync ]
                                                     markets + embeddings
```

### Stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Ingestion, embeddings, and the linking engine are the complex parts and belong in Python |
| Frontend | Next.js (App Router) | Server-rendered feed for SEO; the pitch depends on organic discovery |
| Database | Neon Postgres + pgvector | Relational data and vector search in one system, one query |
| Scheduling | GitHub Actions cron | Free, 5-minute granularity, avoids the Vercel Hobby cap |
| LLM | Claude Haiku | Link verification; cheap enough to run on every candidate set |
| Embeddings | OpenAI `text-embedding-3-small` (1536-dim) | $0.02/1M tokens; catalog embedding costs cents |
| Hosting |  Railway (backend), Vercel (frontend) | Free tiers, push-to-deploy |

Putting the vector index in Postgres rather than a dedicated vector DB is deliberate: "find candidate markets near this post, joined to live price and volume, filtered to markets that have not settled" is one SQL statement instead of a vector query plus a hydration round-trip.

### Stage 1: Kalshi sync

Runs every 15 minutes. Pulls the full public market catalog, upserts `markets` with current price and volume, and embeds any market whose composed text has changed.

Markets are embedded as composed strings, not bare tickers. `FED-25SEP-T4.50` is meaningless to an embedding model; `"Federal Reserve target rate above 4.50% at the September 2026 meeting, closes 2026-09-17, Economics"` is richly matchable. The composition is `series title + market title + rules summary + close date + category`, and a `text_hash` column prevents re-embedding unchanged markets.

This stage also drives the trending rail, computed from Kalshi's own volume and 24h price movement — so the sidebar is alive on day one with zero users.

### Stage 2: Ingestors

Runs every 10 minutes. One module per source behind a single interface:

```python
class Ingestor(Protocol):
    kind: str
    def fetch(self, source: Source, since: datetime) -> list[RawPost]: ...
```

Each source runs isolated — a dead RSS feed cannot fail the run. Adding Reddit or Bluesky later means writing one file.

**News** via RSS from major outlets (Reuters, AP, Politico, Bloomberg, CNBC and similar). Free and unlimited.

**X** via a discovery-then-hydration path that costs nothing and does not scrape:

1. **Discovery** — find tweet IDs from free channels: `x.com` links embedded in fetched news articles, a hand-curated account list, and (later) Reddit's free API.
2. **Hydration** — fetch each tweet once through `publish.twitter.com/oembed`, which is officially supported, free, and unauthenticated. The undocumented syndication endpoint (the one `react-tweet` uses) is an enrichment fallback only.
3. **Permanent cache** — each tweet is fetched exactly once and stored. The feed keeps working even if X blocks access entirely.

Primary reliance on the sanctioned oEmbed endpoint is a deliberate choice: the data-provenance story has to hold up if a Kalshi engineer asks how it works.

### Stage 3: Linker

The core of the product. For each unlinked post:

1. **Embed** the post text (title + body excerpt, or tweet text).
2. **Retrieve** the top 10 candidate markets in one SQL query with filters applied inline: status open, `close_time` in the future, cosine distance below a floor. Posts with no candidate above the floor never reach the LLM — this is the main cost lever, since most posts match nothing.
3. **Verify** with a single Haiku call containing the post and all 10 candidates, returning structured JSON:

```json
{ "links": [ { "ticker": "GOVSHUT-25OCT15", "related": true,
    "direction": "YES", "confidence": 0.86,
    "rationale": "Leadership walking out removes the last scheduled path to a deal before the deadline." } ] }
```

4. **Write** only `related: true` rows above the confidence threshold into `post_markets`, capturing `price_at_link`.

Posts matching nothing still appear in the feed, untagged. An untagged post looks normal; a wrongly-tagged one looks broken. Precision is weighted over recall throughout.

The verify step also handles timeframe mismatches, because the candidate text includes the close date — a post about cuts "this year" will be rejected against a market closing in three days.

**Story clustering.** The same story arrives from several outlets. Posts are clustered by embedding similarity within a rolling 24-hour window; the cluster is linked to markets once and rendered as one card with a "+N sources" chip. This saves LLM calls and avoids a feed of six near-identical items.

**Re-linking.** A nightly job re-runs retrieval for the last 48 hours of posts against newly-added markets only, so a market listed this morning picks up yesterday's news.

**Cost.** Roughly $2.70 per 1,000 verified posts at Haiku rates (~1.2k input, ~300 output tokens each). With the similarity floor and prompt caching on the static instructions, expect $15–30/month at ~800 ingested posts/day.

### Stage 4: Impact tracker

Runs hourly. For each link, fills `price_1h` and `price_24h` from Kalshi's public candlesticks and computes the delta against `price_at_link`.

This produces the "▲ 11¢ since this post" figure, which is the strongest single element in the recruiter pitch: it converts the product from "we aggregate news" into "we quantify which news moves which markets."

## Product Surface

One page. No routing beyond filter state.

**Top bar:** wordmark (left), category tabs (All, Politics, Economics, Finance, World, Crypto, Sports, Culture) that filter the feed in place, and the **Kalshi logo top-right** linking out to kalshi.com.

**Feed column:** single chronological stream, newest first, mixing news outlets and X posts. Each card shows source, age, a "+N sources" chip when clustered, category, headline, snippet, and collapsed market tags carrying live price and the move since the story broke.

**Centered post view:** clicking a card dims and blurs the feed and centers that post, showing:
- Author block — avatar, display name, verified mark, and either "News outlet" or `@handle`, plus timestamp and category.
- Full headline and body excerpt.
- **Read the full article ↗** (or **View post on 𝕏 ↗** for X posts) linking to the original.
- **Related markets** below — each a clickable card deep-linking to that market on Kalshi, showing ticker, close date, volume, price move since the post, YES/NO pricing, and the rationale for the link.

**Trending rail (right, 340px):** full market cards with price sparkline, YES/NO pricing, volume, and today's move. Two rankings: trending by Kalshi volume, and "most covered today" by the platform's own link counts. The second ranking is itself an insight — heavily covered markets with low volume are the ones Kalshi should be promoting.

**Newsletter:** floating button bottom-right. Email plus category checkboxes, no passwords and no user accounts — an email, a set of topics, and an unsubscribe token. A daily digest job sends stories that moved the subscriber's chosen markets.

**Visual language:** Kalshi-adjacent — near-black background (`#0A0D0C`), mint green for YES (`#00D395`), red for NO (`#FF5A5F`), dense data-first cards, compact sans typography. Exact brand hex values to be sampled from kalshi.com during frontend work.

**Attribution:** all outbound Kalshi links carry UTM parameters, so referral attribution already exists if Kalshi ever wires up their side. Worth naming explicitly in the recruiter email.

## Data Model

Neon Postgres with the `vector` extension.

| Table | Purpose | Notable columns |
|---|---|---|
| `sources` | Feed and account registry | `kind` (rss/x/reddit), `feed_url`, `handle`, `category`, `enabled` |
| `posts` | Every ingested item | `source_id`, `external_id` (unique per source), `author_name`, `author_handle`, `avatar_url`, `url`, `title`, `body`, `published_at`, `embedding vector(1536)`, `cluster_id`, `category` |
| `clusters` | Same story across outlets | `representative_post_id`, `post_count` |
| `markets` | Kalshi mirror | `ticker` (PK), `event_ticker`, `series_ticker`, `title`, `rules_summary`, `category`, `status`, `close_time`, `yes_price`, `volume`, `embedding`, `text_hash` |
| `post_markets` | The links | PK `(post_id, ticker)`, `direction`, `confidence`, `rationale`, `price_at_link`, `price_1h`, `price_24h` |
| `subscribers` | Newsletter | `email`, `categories[]`, `unsub_token`, `confirmed_at` |
| `job_runs` | Observability | `job`, `status`, `items_processed`, `error`, timings |

Price impact lives on `post_markets` rather than a separate table — a fixed set of three snapshots per link means extra rows buy nothing.

## Jobs

All GitHub Actions workflows calling authenticated FastAPI endpoints.

| Job | Schedule | Work |
|---|---|---|
| `sync_markets` | every 15 min | Kalshi catalog upsert; embed changed markets |
| `ingest` | every 10 min | Fetch all enabled sources, isolated per source |
| `link` | every 10 min, after ingest | Retrieve, verify, write links |
| `impact` | hourly | Fill `price_1h` / `price_24h` from candlesticks |
| `relink` | nightly | Last 48h of posts against newly-listed markets |
| `digest` | daily 8am ET | Newsletter send |

## Error Handling and Resilience

Designed around one requirement: a recruiter's click must never land on a broken or empty page.

- **Idempotency everywhere.** `external_id` and `text_hash` uniqueness make re-runs free, which matters because GitHub Actions cron fires late under load.
- **Hard daily LLM spend cap** enforced by a counter table. On hit, linking pauses and posts render untagged. A surprise bill is impossible.
- **Kalshi sync failure** serves last-known prices with an "as of" timestamp rather than blanks.
- **Malformed LLM output** is caught by Pydantic validation, retried once, then the post ships untagged. A missing tag is invisible; a crashed page is not.
- **Per-source isolation** in ingestion; one failing feed is logged to `job_runs` and skipped.
- **X posts cached permanently** on first fetch, so the feed survives X cutting off access.
- **Backoff** on all external calls (Kalshi, oEmbed, OpenAI, Anthropic).

## Testing Strategy

Test-driven throughout, but the effort is deliberately concentrated:

**Golden set (the important one).** ~40 hand-labeled `(post → expected markets)` pairs run as a test reporting precision and recall against the thresholds in Success Criteria. Without it there is no way to know whether a prompt change improved linking or quietly wrecked it. It is also a strong artifact to point at in the recruiter email.

**Unit tests** on ingest normalization, market text composition, clustering, and threshold logic, against recorded RSS and oEmbed fixtures.

**Contract tests** using recorded Kalshi API responses (VCR-style). CI never hits a live external API.

**Frontend** component tests for the card, centered post view, and trending rail, plus a smoke test that the feed renders with an empty database.

## Repository Layout

```
kalshi-news/
├── backend/            FastAPI app, ingestors, linker, jobs
├── frontend/           Next.js app
├── .github/workflows/  cron schedules + CI
└── docs/superpowers/   specs and plans
```

`.superpowers/` (brainstorming mockups) is gitignored.

## Open Items

**Product display name.** Deliberately deferred by the user. The UI uses a `<Wordmark/>` component and the repo/directory use the working name `kalshi-news`; renaming touches one component and the README.
