# Frontend and Deployment — Design

**Date:** 2026-09-18
**Status:** Approved, ready for implementation planning
**Predecessor:** `docs/superpowers/specs/2026-09-17-kalshi-news-design.md` (the product design; its Product Surface section is the authority for what the UI shows)

## Purpose

Turn the completed backend into something a person can open. The pipeline already ingests news and X posts, links each to the Kalshi markets it bears on, tracks how prices moved afterwards, and serves it over a read API. Nothing renders it and nothing is deployed.

This phase delivers: the Next.js frontend, a provisioned database, and a live public URL.

## Scope

**In:** the feed, the centered post view, the trending rail, the header, and the full deploy path (Neon, Railway, Vercel, GitHub Actions cron).

**Out, deliberately:**
- **Newsletter signup and the daily digest.** The `subscribers` table exists; the endpoint, the digest job, and the email sender do not. The floating button renders but is inert this phase.
- **The golden-set harness that runs the real linker.** The ≥0.85 precision target stays unmeasured, and the README continues to say so plainly. It cannot run until the pipeline has met live Kalshi data at least once, which happens during this phase's deploy.
- **The compliance pass** (reframing `direction` as relevance, dropping the public `confidence` field, leading with the observed delta, adding a disclaimer). Deferred by explicit decision, to be revisited once the frontend exists and the changes can be seen rather than imagined.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Frontend host | Vercel | Native Next.js SSR; free; `git push` deploys |
| Backend host | Railway (~$5/mo) | Always warm. The demo's promise is that the link works instantly; a cold start breaks that |
| Database | Neon Postgres (free), pooled endpoint | Already the spec's choice; pooled survives the backend's sleep/wake cycles |
| Rendering | Server Components + ISR, 60s revalidate | Populated HTML for crawlers; cron runs every 10 min so 60s is fresher than the data |
| Product name | None | Header carries category tabs at the left edge and the Kalshi mark at the right as an outbound link |

### Why not Cloudflare

Cloudflare Python Workers can now reach Postgres through Hyperdrive (compatibility date 2026-09-08 or later), FastAPI is a supported dependency, and **only synchronous SQLAlchemy is supported** — which happens to match ours. It was a closer call than expected. Rejected because:

- Hyperdrive support in Python Workers is **beta**, days old at time of writing. The demo must not break when a recruiter opens it.
- **pgvector is unverified** in that environment. Retrieval is one `cosine_distance` query; if it does not work there is no product.
- The jobs are long-running by nature — the linker makes serial Haiku calls — and Workers' CPU limits make the existing synchronous-job constraint materially worse. Alembic migrations need a conventional runtime regardless.

Cloudflare Pages remains a fine host for the frontend alone, but since the backend cannot live on Cloudflare, choosing it buys no single-vendor simplicity while adding the OpenNext adapter as a moving part.

## Branding constraint

The site carries no product name and must not present itself as Kalshi. The Kalshi mark appears **top-right only**, as an outbound attribution link to kalshi.com with an external-link affordance. The left of the header is category tabs.

This is a requirement, not a preference. An unaffiliated site wearing a regulated exchange's mark in the primary brand position invites a trademark complaint, reads to the target audience as not understanding brand boundaries, and — combined with the YES/NO direction the API returns — risks appearing to be the exchange itself giving trading direction.

## Architecture

**Server-rendered by default.** The feed page is a Server Component that fetches the API at render time and ships populated HTML. The browser never contacts Railway directly, so **CORS ceases to be a concern** (resolving the one security note the backend's final review deferred) and the backend URL stays server-side.

**Freshness by ISR**, 60-second revalidation. A visitor is served from cache rather than waiting on a Railway round-trip.

**Category tabs are URLs, not client state.** `/?category=Politics`, read from `searchParams`, tabs rendered as `<Link>`. Each category becomes independently crawlable, and it is less code than lifting filter state into a client component.

**The centered post view uses intercepting routes.** `/posts/[id]` renders into a `@modal` slot: an overlay when reached by clicking from the feed, a standalone page when opened directly or shared. A pure client overlay would have no URL, making stories unshareable and post content invisible to crawlers.

*Named fallback:* if intercepting routes prove troublesome, a plain `/posts/[id]` route plus a client overlay that updates the URL delivers the same user-visible result with less elegance. Deciding this in advance prevents quietly shipping the lesser version under time pressure.

**Pagination** is a thin Next route handler proxying the backend's keyset cursor, called by a `LoadMore` client component — the browser continues to talk only to Vercel.

**Styling** is Tailwind with the spec's palette as CSS variables: background `#0A0D0C`, surface `#14191A`, border `#252C2E`, YES `#00D395`, NO `#FF5A5F`.

## Components

Server Components unless marked.

| Component | Responsibility |
|---|---|
| `app/page.tsx` | Feed route: reads `searchParams.category`, fetches the feed, renders the shell |
| `Header` | Category tabs as `<Link>`s at the left; Kalshi attribution link at the right |
| `PostCard` | One feed item: source, age, `+N sources`, category, headline, snippet, collapsed market tags |
| `MarketTag` | One linked market: question, YES/NO, price, observed delta |
| `TrendingRail` | Both trending rankings: question, YES/NO price, volume, coverage count |
| `PostDetail` | Centered view: author block, body, outbound read link, related markets |
| `LoadMore` | **Client.** The only stateful piece: accumulated pages, calls the proxy route |
| `NewsletterButton` | **Client.** Floating CTA. Renders with no click handler this phase; the newsletter is out of scope |

Two constraints that exist to prevent a class of bug:

- **`MarketTag` is the only place a price or delta is formatted** — cents to string, sign, colour. The same reasoning kept `price_delta` computed in exactly one place on the backend; a number that renders in three places will eventually disagree with itself.
- **`PostDetail` is shared verbatim** between the intercepted overlay and the standalone page. If they diverge, a shared link and a clicked link show different things.

## API contract

Consumed from the existing backend; these shapes are fixed and already implemented.

`GET /api/feed?category=&limit=&cursor=` → `FeedPage`
```
FeedPage   { items: FeedItem[], next_cursor: string | null }
FeedItem   { id, title, url, author_name?, author_handle?, avatar_url?,
             source_kind, category?, published_at, cluster_size, markets: MarketRef[] }
MarketRef  { ticker, title, direction, confidence, rationale,
             yes_price?, volume?, close_time?, price_delta?, kalshi_url }
```

`GET /api/posts/{post_id}` → `PostDetail` (a `FeedItem` plus `body`)

`GET /api/trending?limit=` → `TrendingPage { by_volume: TrendingMarket[], most_covered: TrendingMarket[] }`
where `TrendingMarket { ticker, title, yes_price?, volume?, post_count, kalshi_url }`

Notes the frontend must respect: `limit` is bounded `ge=1`; a malformed or timezone-naive `cursor` returns 422; `price_delta` is `null` until the impact job fills a snapshot; `markets` is frequently empty, by design.

### The mockup promises sparklines the API cannot supply

The approved trending-rail mockup shows a price sparkline per market. **`TrendingMarket` carries no price history** — only `yes_price`, `volume` and `post_count` — and no endpoint exposes a series. Sparklines are therefore **cut from this phase**, not deferred silently: the rail renders question, YES/NO price, volume and coverage count.

Restoring them needs backend work (a price-history endpoint reading the candlesticks the impact tracker already fetches, or persisting a short series per market), which is out of scope here. Recorded so the gap is a decision rather than a discovery mid-build.

## Deploy sequence

Each step verifies the one before it. Account creation and secret entry are the user's; every config file, script, and runbook is prepared in advance.

0. **Capture a real Kalshi payload** — one request to `/trade-api/v2/markets?limit=1&status=open`, pinned as a fixture. This settles the `status` field question empirically and confirms the field names the client parses. It is the cheapest possible de-risking of the assumption that caused the backend's one Critical defect.
1. **Neon** — create the project, take the pooled connection string.
2. **Migrations** — `alembic upgrade head`. This runs `0002_seed_sources`, so feeds exist the moment the schema does. Verify by counting `sources`.
3. **Railway** — deploy `backend/`. Env: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `JOB_TOKEN`, `DAILY_LLM_BUDGET_USD`. Verify `/health`, which touches the database.
4. **Trigger jobs manually, in order** — `sync_markets`, `ingest`, `link`. The first contact with live Kalshi data, and where the `status` fix is proven against reality rather than a recorded payload.
5. **GitHub Actions secrets** — `API_URL`, `JOB_TOKEN`; cron takes over.
6. **Vercel** — deploy `frontend/` with `BACKEND_API_URL`. Verify the feed renders populated.

Secrets never enter the repo. `.env` stays gitignored; `.env.example` documents each key and where its value comes from.

## Testing

Server Components resist unit testing, so the suite splits three ways rather than forcing one tool to do everything.

**Presentational components — Vitest + React Testing Library.** These take props and render; this is where TDD applies cleanly. Required cases:

- A post with **no market tags** renders normally. Untagged is the common case by design, since the linker weights precision over recall.
- `price_delta: null` renders nothing — not `0¢`, not `NaN¢`.
- Negative delta renders red and down; positive renders mint and up.
- `cluster_size > 1` shows `+N sources`; `1` shows nothing.
- An X post shows `@handle` and "View post on 𝕏"; a news post shows the outlet and "Read the full article."
- **An empty feed renders an empty state, not a blank page.** On first deploy the feed is empty until the first cron cycle and untagged until the first link run.

**The API client as a plain module — MSW.** Extracting `fetchFeed()` / `fetchTrending()` makes cursor handling, error shapes, and a 500 from Railway testable without rendering.

**One Playwright smoke test** against a built app with a stubbed backend: the feed renders populated, and clicking a card opens the overlay. It exists to catch what unit tests structurally cannot — that the intercepting-route wiring works.

**No live network in any test**, matching the backend's socket guard. The frontend gets its own CI job beside the backend's, so a broken frontend fails the same pipeline.

## Success criteria

1. A public URL that renders a populated, current feed with no manual intervention.
2. Clicking a post centers it, shows who published it, links to the original, and lists related markets that deep-link to Kalshi.
3. Category tabs filter the feed and produce shareable per-category URLs.
4. The trending rail shows both rankings.
5. The site carries no product name and does not present itself as Kalshi.
6. Frontend CI passes in the same pipeline as the backend.

## Open items

**The first live run is the real test.** Everything in the backend is verified against tests and recorded payloads. Step 4 of the deploy sequence is the first time any of it meets live Kalshi data, and it is the most likely place to find a surprise — most plausibly in the market `status` field or in candlestick availability for thin markets. The plan sequences it early for that reason.
