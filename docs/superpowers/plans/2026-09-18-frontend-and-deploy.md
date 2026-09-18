# Frontend and Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the existing pipeline as a public, server-rendered feed and deploy it to a live URL.

**Architecture:** A Next.js App Router frontend, server-rendered against the existing FastAPI backend. The browser never contacts the backend directly — Server Components fetch at render time, and a single thin route handler proxies pagination. The centered post view uses intercepting routes so a story is both an overlay and a shareable URL.

**Tech Stack:** Next.js 15 (App Router, React 19), TypeScript, Tailwind CSS v4, Vitest + React Testing Library + jsdom, MSW v2, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-18-frontend-and-deploy-design.md`
**Product surface authority:** `docs/superpowers/specs/2026-09-17-kalshi-news-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- All frontend code lives under `frontend/`. Node 22. TypeScript strict mode on.
- **No product name.** The header is category tabs at the left and the Kalshi mark at the right as an outbound link to `https://kalshi.com` with `target="_blank"` and `rel="noopener noreferrer"`. The site must never present itself as Kalshi.
- **No test may make a live network call.** All HTTP is mocked with MSW; Playwright runs against a stubbed backend.
- Colour tokens, exactly: background `#0A0D0C`, surface `#14191A`, surface-2 `#1B2123`, border `#252C2E`, text `#E9EDEC`, muted `#8B9694`, YES/mint `#00D395`, NO/red `#FF5A5F`.
- **`MarketTag` is the only component that formats a price or a delta.** No other component converts cents to a string or picks a sign colour.
- **`PostDetail` is rendered by both the intercepted overlay and the standalone page**, from one shared component. They must not diverge.
- `price_delta` is `null` until the impact job fills a snapshot — render nothing, never `0¢` or `NaN`.
- `markets` is frequently empty by design (the linker weights precision over recall). An untagged post must look normal.
- Backend base URL comes from `process.env.BACKEND_API_URL`. Never hardcoded, never exposed to the client bundle.
- Commit after every task with a conventional-commit message.

---

### Task 1: Capture a real Kalshi payload and pin it

**Files:**
- Create: `backend/tests/fixtures/kalshi_markets_live.json`
- Create: `backend/tests/test_live_payload_shape.py`

**Interfaces:**
- Consumes: `app.clients.kalshi.KalshiClient`, `app.jobs.sync_markets.sync_markets`.
- Produces: a recorded real payload other tests can replay.

**Why first:** the backend's one Critical defect was a `status` value assumed rather than observed. One real request settles it, and it costs nothing. This task is backend-only and independent of everything after it.

- [ ] **Step 1: Capture the payload**

```bash
curl -sS "https://external-api.kalshi.com/trade-api/v2/markets?limit=3&status=open" \
  -o backend/tests/fixtures/kalshi_markets_live.json
python3 -c "import json;d=json.load(open('backend/tests/fixtures/kalshi_markets_live.json'));m=d['markets'][0];print({k:m[k] for k in ('ticker','status','close_time','yes_bid','yes_ask','volume') if k in m})"
```

Record the printed `status` value in the task report. This is the observation the whole task exists for.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_live_payload_shape.py
import json
from pathlib import Path

import httpx
import respx

from app.clients.kalshi import BASE_URL, KalshiClient

LIVE = json.loads((Path(__file__).parent / "fixtures" / "kalshi_markets_live.json").read_text())


@respx.mock
def test_client_parses_a_real_recorded_payload():
    respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=LIVE))

    markets = KalshiClient().fetch_all_markets()

    assert markets, "recorded payload produced no markets"
    first = markets[0]
    assert first.ticker
    assert first.title
    assert first.close_time is not None and first.close_time.tzinfo is not None


@respx.mock
def test_synced_markets_are_retrievable_regardless_of_status_value(session):
    """The status field is advisory; retrieval must not depend on its value."""
    from app.linker.retrieval import find_candidates
    from app.models import Market, Post, Source

    respx.get(f"{BASE_URL}/markets").mock(return_value=httpx.Response(200, json=LIVE))
    from unittest.mock import patch
    with patch("app.jobs.sync_markets.embed_texts") as embed:
        embed.side_effect = lambda texts: [[0.1] * 1536 for _ in texts]
        from app.jobs.sync_markets import sync_markets
        sync_markets(session)

    stored = session.query(Market).first()
    assert stored is not None
    source = Source(kind="rss", name="R", feed_url="u", category="Economics")
    session.add(source)
    session.flush()
    post = Post(source_id=source.id, external_id="p", url="u", title="t",
                published_at=stored.close_time, embedding=[0.1] * 1536)
    session.add(post)
    session.commit()

    assert find_candidates(session, post, max_distance=2.0), (
        "a freshly synced market was not retrievable — retrieval is coupled to status again"
    )
```

- [ ] **Step 3: Run the tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_live_payload_shape.py -v`
Expected: PASS. If the second test fails, retrieval has been re-coupled to `status` — that is the regression this fixture exists to catch.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/fixtures/kalshi_markets_live.json backend/tests/test_live_payload_shape.py
git commit -m "test: pin a real Kalshi payload and prove retrieval ignores status"
```

---

### Task 2: Frontend scaffold, theme tokens, and CI

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.ts`
- Create: `frontend/postcss.config.mjs`, `frontend/vitest.config.ts`, `frontend/vitest.setup.ts`
- Create: `frontend/app/globals.css`, `frontend/app/layout.tsx`
- Create: `frontend/components/Wordmark.test.tsx` *(smoke test proving the harness runs)*
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: a working Vitest + RTL harness, Tailwind v4 with the palette as `@theme` tokens, and a `frontend` CI job.

- [ ] **Step 1: Scaffold**

```bash
cd frontend && npm init -y
npm i next@15 react@19 react-dom@19
npm i -D typescript @types/react @types/node @types/react-dom \
  vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/jest-dom \
  tailwindcss @tailwindcss/postcss msw
```

`frontend/package.json` scripts:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  }
}
```

- [ ] **Step 2: Theme tokens and config**

```css
/* frontend/app/globals.css */
@import "tailwindcss";

@theme {
  --color-bg: #0A0D0C;
  --color-surface: #14191A;
  --color-surface-2: #1B2123;
  --color-border: #252C2E;
  --color-text: #E9EDEC;
  --color-muted: #8B9694;
  --color-mint: #00D395;
  --color-negative: #FF5A5F;
}

body { background: var(--color-bg); color: var(--color-text); }
```

```ts
// frontend/vitest.config.ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", setupFiles: ["./vitest.setup.ts"], globals: true },
  resolve: { alias: { "@": new URL("./", import.meta.url).pathname } },
});
```

```ts
// frontend/vitest.setup.ts
import "@testing-library/jest-dom/vitest";
```

```tsx
// frontend/app/layout.tsx
import "./globals.css";

export const metadata = {
  title: "News × Prediction Markets",
  description: "Breaking news and posts, linked to the Kalshi markets they bear on.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">{children}</body>
    </html>
  );
}
```

- [ ] **Step 3: Write the harness smoke test**

```tsx
// frontend/components/Wordmark.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function Wordmark() {
  return <span>News × Prediction Markets</span>;
}

describe("test harness", () => {
  it("renders a component", () => {
    render(<Wordmark />);
    expect(screen.getByText("News × Prediction Markets")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run it**

Run: `cd frontend && npm test`
Expected: 1 passing.

- [ ] **Step 5: Add the CI job**

Add to `.github/workflows/ci.yml`, as a second job beside `backend`:

```yaml
  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
      - run: npm run typecheck
      - run: npm test
```

- [ ] **Step 6: Commit**

```bash
git add frontend/ .github/workflows/ci.yml
git commit -m "chore: scaffold Next.js frontend with theme tokens and CI"
```

---

### Task 3: API types and client

**Files:**
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/api.test.ts`

**Interfaces:**
- Produces:
  - Types `MarketRef`, `FeedItem`, `PostDetailData`, `TrendingMarket`, `TrendingPage`, `FeedPage` — mirroring the backend contract exactly.
  - `fetchFeed(opts?: { category?: string; limit?: number; cursor?: string }): Promise<FeedPage>`
  - `fetchPost(id: number): Promise<PostDetailData | null>` — `null` on 404.
  - `fetchTrending(limit?: number): Promise<TrendingPage>`
  - All three throw `ApiError` on a non-OK, non-404 response.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/api.test.ts
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ApiError, fetchFeed, fetchPost, fetchTrending } from "./api";

const BASE = "http://backend.test";
process.env.BACKEND_API_URL = BASE;

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ITEM = {
  id: 1, title: "Shutdown talks collapse", url: "https://politico.com/a",
  author_name: "Politico", author_handle: null, avatar_url: null,
  source_kind: "rss", category: "Politics", published_at: "2026-09-18T12:00:00Z",
  cluster_size: 3, markets: [],
};

describe("fetchFeed", () => {
  it("passes category, limit and cursor through as query params", async () => {
    let seen = "";
    server.use(http.get(`${BASE}/api/feed`, ({ request }) => {
      seen = new URL(request.url).search;
      return HttpResponse.json({ items: [ITEM], next_cursor: "abc" });
    }));

    const page = await fetchFeed({ category: "Politics", limit: 5, cursor: "xyz" });

    expect(seen).toContain("category=Politics");
    expect(seen).toContain("limit=5");
    expect(seen).toContain("cursor=xyz");
    expect(page.items[0].title).toBe("Shutdown talks collapse");
    expect(page.next_cursor).toBe("abc");
  });

  it("omits params that were not supplied", async () => {
    let seen = "";
    server.use(http.get(`${BASE}/api/feed`, ({ request }) => {
      seen = new URL(request.url).search;
      return HttpResponse.json({ items: [], next_cursor: null });
    }));

    await fetchFeed();

    expect(seen).not.toContain("category=");
    expect(seen).not.toContain("cursor=");
  });

  it("throws ApiError when the backend fails", async () => {
    server.use(http.get(`${BASE}/api/feed`, () => new HttpResponse(null, { status: 500 })));
    await expect(fetchFeed()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("fetchPost", () => {
  it("returns null for a missing post rather than throwing", async () => {
    server.use(http.get(`${BASE}/api/posts/99`, () => new HttpResponse(null, { status: 404 })));
    expect(await fetchPost(99)).toBeNull();
  });

  it("returns the post body", async () => {
    server.use(http.get(`${BASE}/api/posts/1`,
      () => HttpResponse.json({ ...ITEM, body: "Negotiators left." })));
    const post = await fetchPost(1);
    expect(post?.body).toBe("Negotiators left.");
  });
});

describe("fetchTrending", () => {
  it("returns both rankings", async () => {
    server.use(http.get(`${BASE}/api/trending`, () => HttpResponse.json({
      by_volume: [{ ticker: "A", title: "A?", yes_price: 60, volume: 10,
                    post_count: 0, kalshi_url: "https://kalshi.com/markets/A" }],
      most_covered: [],
    })));
    const page = await fetchTrending();
    expect(page.by_volume[0].ticker).toBe("A");
    expect(page.most_covered).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- lib/api.test.ts`
Expected: FAIL — cannot resolve `./api`.

- [ ] **Step 3: Implement**

```ts
// frontend/lib/types.ts
export interface MarketRef {
  ticker: string;
  title: string;
  direction: string;
  confidence: number;
  rationale: string;
  yes_price: number | null;
  volume: number | null;
  close_time: string | null;
  price_delta: number | null;
  kalshi_url: string;
}

export interface FeedItem {
  id: number;
  title: string;
  url: string;
  author_name: string | null;
  author_handle: string | null;
  avatar_url: string | null;
  source_kind: string;
  category: string | null;
  published_at: string;
  cluster_size: number;
  markets: MarketRef[];
}

export interface PostDetailData extends FeedItem {
  body: string | null;
}

export interface TrendingMarket {
  ticker: string;
  title: string;
  yes_price: number | null;
  volume: number | null;
  post_count: number;
  kalshi_url: string;
}

export interface TrendingPage {
  by_volume: TrendingMarket[];
  most_covered: TrendingMarket[];
}

export interface FeedPage {
  items: FeedItem[];
  next_cursor: string | null;
}
```

```ts
// frontend/lib/api.ts
import type { FeedPage, PostDetailData, TrendingPage } from "./types";

export class ApiError extends Error {
  constructor(readonly status: number, path: string) {
    super(`backend responded ${status} for ${path}`);
    this.name = "ApiError";
  }
}

function base(): string {
  const url = process.env.BACKEND_API_URL;
  if (!url) throw new Error("BACKEND_API_URL is not set");
  return url.replace(/\/$/, "");
}

async function get<T>(path: string, params?: Record<string, string | number | undefined>) {
  const url = new URL(`${base()}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  const response = await fetch(url, { next: { revalidate: 60 } });
  if (!response.ok) throw new ApiError(response.status, path);
  return (await response.json()) as T;
}

export function fetchFeed(opts: { category?: string; limit?: number; cursor?: string } = {}) {
  return get<FeedPage>("/api/feed", opts);
}

export async function fetchPost(id: number): Promise<PostDetailData | null> {
  const response = await fetch(`${base()}/api/posts/${id}`, { next: { revalidate: 60 } });
  if (response.status === 404) return null;
  if (!response.ok) throw new ApiError(response.status, `/api/posts/${id}`);
  return (await response.json()) as PostDetailData;
}

export function fetchTrending(limit?: number) {
  return get<TrendingPage>("/api/trending", { limit });
}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test -- lib/api.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/
git commit -m "feat: add typed API client for the backend"
```

---

### Task 4: MarketTag — the only place a price is formatted

**Files:**
- Create: `frontend/components/MarketTag.tsx`
- Create: `frontend/components/MarketTag.test.tsx`

**Interfaces:**
- Consumes: `MarketRef` from `lib/types`.
- Produces: `<MarketTag market={ref} />`. This component owns cents-to-string conversion, delta sign, and direction colour. No other component may format a price.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/components/MarketTag.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MarketRef } from "@/lib/types";
import { MarketTag } from "./MarketTag";

const BASE: MarketRef = {
  ticker: "GOVSHUT-26OCT15",
  title: "Government shutdown before October 15?",
  direction: "YES",
  confidence: 0.86,
  rationale: "Leadership walked out with no path to a deal.",
  yes_price: 64,
  volume: 2400000,
  close_time: "2026-10-15T20:00:00Z",
  price_delta: 11,
  kalshi_url: "https://kalshi.com/markets/GOVSHUT-26OCT15?utm_source=kalshi-news",
};

describe("MarketTag", () => {
  it("shows the question and the YES price in cents", () => {
    render(<MarketTag market={BASE} />);
    expect(screen.getByText("Government shutdown before October 15?")).toBeInTheDocument();
    expect(screen.getByText(/64¢/)).toBeInTheDocument();
  });

  it("renders a positive delta with an up arrow", () => {
    render(<MarketTag market={BASE} />);
    const delta = screen.getByTestId("price-delta");
    expect(delta).toHaveTextContent("▲ 11¢");
  });

  it("renders a negative delta with a down arrow and no minus sign", () => {
    render(<MarketTag market={{ ...BASE, price_delta: -7 }} />);
    const delta = screen.getByTestId("price-delta");
    expect(delta).toHaveTextContent("▼ 7¢");
    expect(delta).not.toHaveTextContent("-7");
  });

  it("renders no delta element at all when price_delta is null", () => {
    render(<MarketTag market={{ ...BASE, price_delta: null }} />);
    expect(screen.queryByTestId("price-delta")).toBeNull();
    expect(screen.queryByText(/0¢/)).toBeNull();
    expect(screen.queryByText(/NaN/)).toBeNull();
  });

  it("renders no price when yes_price is null", () => {
    render(<MarketTag market={{ ...BASE, yes_price: null }} />);
    expect(screen.queryByText(/¢/)).toBeNull();
  });

  it("links to Kalshi with the UTM-tagged url, opening in a new tab safely", () => {
    render(<MarketTag market={BASE} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", BASE.kalshi_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- components/MarketTag.test.tsx`
Expected: FAIL — cannot resolve `./MarketTag`.

- [ ] **Step 3: Implement**

```tsx
// frontend/components/MarketTag.tsx
import type { MarketRef } from "@/lib/types";

function cents(value: number): string {
  return `${value}¢`;
}

export function MarketTag({ market }: { market: MarketRef }) {
  const isYes = market.direction === "YES";
  const delta = market.price_delta;

  return (
    <a
      href={market.kalshi_url}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-1.5 flex items-center gap-2 rounded-lg border border-border
                 bg-surface-2 px-3 py-2 text-sm hover:border-mint"
    >
      <span className="flex-1 text-text">{market.title}</span>
      {market.yes_price !== null && (
        <span className={`font-bold ${isYes ? "text-mint" : "text-negative"}`}>
          {market.direction} {cents(market.yes_price)}
        </span>
      )}
      {delta !== null && (
        <span
          data-testid="price-delta"
          className={`text-xs font-semibold ${delta >= 0 ? "text-mint" : "text-negative"}`}
        >
          {delta >= 0 ? "▲" : "▼"} {cents(Math.abs(delta))}
        </span>
      )}
    </a>
  );
}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test -- components/MarketTag.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/MarketTag.tsx frontend/components/MarketTag.test.tsx
git commit -m "feat: add MarketTag as the single price formatter"
```

---

### Task 5: PostCard and relative time

**Files:**
- Create: `frontend/lib/time.ts`
- Create: `frontend/lib/time.test.ts`
- Create: `frontend/components/PostCard.tsx`
- Create: `frontend/components/PostCard.test.tsx`

**Interfaces:**
- Consumes: `FeedItem`, `MarketTag`.
- Produces: `timeAgo(iso: string, now?: Date): string`; `<PostCard item={feedItem} />`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/lib/time.test.ts
import { describe, expect, it } from "vitest";
import { timeAgo } from "./time";

const NOW = new Date("2026-09-18T12:00:00Z");

describe("timeAgo", () => {
  it("renders minutes under an hour", () => {
    expect(timeAgo("2026-09-18T11:36:00Z", NOW)).toBe("24m ago");
  });
  it("renders hours under a day", () => {
    expect(timeAgo("2026-09-18T09:00:00Z", NOW)).toBe("3h ago");
  });
  it("renders days beyond that", () => {
    expect(timeAgo("2026-09-16T12:00:00Z", NOW)).toBe("2d ago");
  });
  it("renders 'just now' under a minute", () => {
    expect(timeAgo("2026-09-18T11:59:30Z", NOW)).toBe("just now");
  });
});
```

```tsx
// frontend/components/PostCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { FeedItem } from "@/lib/types";
import { PostCard } from "./PostCard";

const NEWS: FeedItem = {
  id: 1,
  title: "Shutdown talks collapse as leadership walks out",
  url: "https://politico.com/a",
  author_name: "Politico",
  author_handle: null,
  avatar_url: null,
  source_kind: "rss",
  category: "Politics",
  published_at: new Date(Date.now() - 60_000).toISOString(),
  cluster_size: 1,
  markets: [],
};

describe("PostCard", () => {
  it("renders an untagged post normally", () => {
    render(<PostCard item={NEWS} />);
    expect(screen.getByText(/Shutdown talks collapse/)).toBeInTheDocument();
    expect(screen.getByText("POLITICO")).toBeInTheDocument();
  });

  it("shows +N sources only when the cluster has more than one post", () => {
    const { rerender } = render(<PostCard item={NEWS} />);
    expect(screen.queryByText(/sources/)).toBeNull();

    rerender(<PostCard item={{ ...NEWS, cluster_size: 4 }} />);
    expect(screen.getByText("+3 sources")).toBeInTheDocument();
  });

  it("shows the @handle for an X post", () => {
    render(<PostCard item={{ ...NEWS, source_kind: "x", author_name: "Nick Timiraos",
                             author_handle: "@NickTimiraos" }} />);
    expect(screen.getByText("@NickTimiraos")).toBeInTheDocument();
  });

  it("renders one MarketTag per linked market", () => {
    render(<PostCard item={{ ...NEWS, markets: [
      { ticker: "A", title: "Market A?", direction: "YES", confidence: 0.9, rationale: "r",
        yes_price: 60, volume: 1, close_time: null, price_delta: null,
        kalshi_url: "https://kalshi.com/markets/A" },
      { ticker: "B", title: "Market B?", direction: "NO", confidence: 0.8, rationale: "r",
        yes_price: 30, volume: 1, close_time: null, price_delta: null,
        kalshi_url: "https://kalshi.com/markets/B" },
    ] }} />);
    expect(screen.getByText("Market A?")).toBeInTheDocument();
    expect(screen.getByText("Market B?")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- lib/time.test.ts components/PostCard.test.tsx`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

```ts
// frontend/lib/time.ts
export function timeAgo(iso: string, now: Date = new Date()): string {
  const seconds = Math.floor((now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
```

```tsx
// frontend/components/PostCard.tsx
import Link from "next/link";

import type { FeedItem } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import { MarketTag } from "./MarketTag";

export function PostCard({ item }: { item: FeedItem }) {
  const isX = item.source_kind === "x";
  const byline = isX ? item.author_handle : item.author_name?.toUpperCase();

  return (
    <article className="mb-2.5 rounded-xl border border-border bg-surface px-4 py-3.5">
      <div className="mb-2 flex items-center gap-2 text-[11px] text-muted">
        {isX && <span className="rounded bg-[#1D9BF0] px-1.5 font-bold text-white">𝕏</span>}
        <span className="font-semibold tracking-wide text-text">{byline}</span>
        <span>· {timeAgo(item.published_at)}</span>
        {item.cluster_size > 1 && (
          <span className="rounded-full border border-border px-2 py-0.5">
            +{item.cluster_size - 1} sources
          </span>
        )}
        {item.category && (
          <span className="rounded-full border border-border px-2 py-0.5">{item.category}</span>
        )}
      </div>

      <Link href={`/posts/${item.id}`} className="block">
        <h2 className="text-[15px] font-semibold leading-snug">{item.title}</h2>
      </Link>

      {item.markets.map((market) => (
        <MarketTag key={market.ticker} market={market} />
      ))}
    </article>
  );
}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test`
Expected: PASS (all suites).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/time.ts frontend/lib/time.test.ts frontend/components/PostCard.tsx frontend/components/PostCard.test.tsx
git commit -m "feat: add PostCard and relative time formatting"
```

---

### Task 6: Header with category tabs and Kalshi attribution

**Files:**
- Create: `frontend/components/Header.tsx`
- Create: `frontend/components/Header.test.tsx`

**Interfaces:**
- Produces: `<Header active={category ?? null} />`; exported `CATEGORIES` array.

**Branding constraint is tested here.** The site carries no product name; the Kalshi mark is an outbound link at the right only.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/components/Header.test.tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CATEGORIES, Header } from "./Header";

describe("Header", () => {
  it("renders a link per category, plus All", () => {
    render(<Header active={null} />);
    for (const category of CATEGORIES) {
      expect(screen.getByRole("link", { name: category })).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "All" })).toHaveAttribute("href", "/");
  });

  it("points each tab at its own filtered url", () => {
    render(<Header active={null} />);
    expect(screen.getByRole("link", { name: "Politics" }))
      .toHaveAttribute("href", "/?category=Politics");
  });

  it("marks the active tab", () => {
    render(<Header active="Politics" />);
    expect(screen.getByRole("link", { name: "Politics" }))
      .toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Economics" }))
      .not.toHaveAttribute("aria-current");
  });

  it("links to kalshi.com safely and does not claim to be Kalshi", () => {
    render(<Header active={null} />);
    const attribution = screen.getByTestId("kalshi-attribution");
    const link = within(attribution).getByRole("link");
    expect(link).toHaveAttribute("href", "https://kalshi.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- components/Header.test.tsx`
Expected: FAIL — cannot resolve `./Header`.

- [ ] **Step 3: Implement**

```tsx
// frontend/components/Header.tsx
import Link from "next/link";

export const CATEGORIES = [
  "Politics", "Economics", "Finance", "World", "Crypto", "Sports", "Culture",
] as const;

function tabClass(isActive: boolean) {
  return isActive
    ? "rounded-md bg-mint px-2.5 py-1.5 text-[12.5px] font-semibold text-[#06120F]"
    : "rounded-md px-2.5 py-1.5 text-[12.5px] text-muted hover:text-text";
}

export function Header({ active }: { active: string | null }) {
  return (
    <header className="flex items-center gap-4 border-b border-border bg-[#0D1211] px-4 py-2.5">
      <nav className="flex flex-1 gap-1 overflow-x-auto">
        <Link href="/" className={tabClass(active === null)}
              aria-current={active === null ? "page" : undefined}>
          All
        </Link>
        {CATEGORIES.map((category) => (
          <Link
            key={category}
            href={`/?category=${category}`}
            className={tabClass(active === category)}
            aria-current={active === category ? "page" : undefined}
          >
            {category}
          </Link>
        ))}
      </nav>

      <div data-testid="kalshi-attribution" className="shrink-0">
        <a
          href="https://kalshi.com"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 rounded-lg border border-border bg-surface-2
                     px-3 py-1.5 text-xs font-semibold"
        >
          <span className="size-4 rounded bg-mint" aria-hidden />
          Kalshi <span className="font-normal text-muted">↗</span>
        </a>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test -- components/Header.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/Header.tsx frontend/components/Header.test.tsx
git commit -m "feat: add header with category tabs and Kalshi attribution"
```

---

### Task 7: TrendingRail

**Files:**
- Create: `frontend/components/TrendingRail.tsx`
- Create: `frontend/components/TrendingRail.test.tsx`

**Interfaces:**
- Consumes: `TrendingPage`.
- Produces: `<TrendingRail trending={page} />`.

**No sparklines** — the API supplies no price history. See the spec's "The mockup promises sparklines the API cannot supply."

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/components/TrendingRail.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { TrendingPage } from "@/lib/types";
import { TrendingRail } from "./TrendingRail";

const PAGE: TrendingPage = {
  by_volume: [{ ticker: "GOVSHUT", title: "Shutdown before Oct 15?", yes_price: 64,
                volume: 2400000, post_count: 0, kalshi_url: "https://kalshi.com/markets/GOVSHUT" }],
  most_covered: [{ ticker: "FED", title: "Fed cuts in September?", yes_price: 72,
                   volume: 5100000, post_count: 11, kalshi_url: "https://kalshi.com/markets/FED" }],
};

describe("TrendingRail", () => {
  it("renders both rankings under their own headings", () => {
    render(<TrendingRail trending={PAGE} />);
    expect(screen.getByText(/Trending markets/i)).toBeInTheDocument();
    expect(screen.getByText(/Most covered today/i)).toBeInTheDocument();
    expect(screen.getByText("Shutdown before Oct 15?")).toBeInTheDocument();
    expect(screen.getByText("Fed cuts in September?")).toBeInTheDocument();
  });

  it("shows the coverage count only in the most-covered ranking", () => {
    render(<TrendingRail trending={PAGE} />);
    expect(screen.getByText("11 posts")).toBeInTheDocument();
  });

  it("renders an empty rail without crashing", () => {
    render(<TrendingRail trending={{ by_volume: [], most_covered: [] }} />);
    expect(screen.getByText(/Nothing trending yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- components/TrendingRail.test.tsx`
Expected: FAIL — cannot resolve `./TrendingRail`.

- [ ] **Step 3: Implement**

```tsx
// frontend/components/TrendingRail.tsx
import type { TrendingMarket, TrendingPage } from "@/lib/types";

function Row({ market, showCoverage }: { market: TrendingMarket; showCoverage?: boolean }) {
  return (
    <a
      href={market.kalshi_url}
      target="_blank"
      rel="noopener noreferrer"
      className="mb-2 block rounded-xl border border-border bg-surface p-3 hover:border-mint"
    >
      <div className="mb-2 text-[13px] font-semibold leading-snug">{market.title}</div>
      <div className="flex items-center justify-between text-[10.5px] text-muted">
        {market.yes_price !== null && (
          <span className="font-bold text-mint">YES {market.yes_price}¢</span>
        )}
        {showCoverage
          ? <span>{market.post_count} posts</span>
          : market.volume !== null && <span>${(market.volume / 1_000_000).toFixed(1)}M vol</span>}
      </div>
    </a>
  );
}

export function TrendingRail({ trending }: { trending: TrendingPage }) {
  const empty = trending.by_volume.length === 0 && trending.most_covered.length === 0;

  return (
    <aside className="w-[340px] shrink-0">
      <h4 className="mb-2.5 text-[11px] font-bold uppercase tracking-wider text-muted">
        Trending markets
      </h4>
      {empty && <p className="text-xs text-muted">Nothing trending yet.</p>}
      {trending.by_volume.map((m) => <Row key={m.ticker} market={m} />)}

      {trending.most_covered.length > 0 && (
        <>
          <h4 className="mb-2.5 mt-5 text-[11px] font-bold uppercase tracking-wider text-muted">
            Most covered today
          </h4>
          {trending.most_covered.map((m) => <Row key={m.ticker} market={m} showCoverage />)}
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test -- components/TrendingRail.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/TrendingRail.tsx frontend/components/TrendingRail.test.tsx
git commit -m "feat: add trending rail with both rankings"
```

---

### Task 8: Feed page and empty state

**Files:**
- Create: `frontend/components/EmptyState.tsx`
- Create: `frontend/components/EmptyState.test.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/.env.example`

**Interfaces:**
- Consumes: `fetchFeed`, `fetchTrending`, `Header`, `PostCard`, `TrendingRail`, `EmptyState`.
- Produces: the `/` route. `searchParams` is a Promise in Next 15 and must be awaited.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/components/EmptyState.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("explains an empty feed rather than rendering blank", () => {
    render(<EmptyState category={null} />);
    expect(screen.getByText(/No stories yet/i)).toBeInTheDocument();
  });

  it("names the category when one is filtered", () => {
    render(<EmptyState category="Sports" />);
    expect(screen.getByText(/Sports/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- components/EmptyState.test.tsx`
Expected: FAIL — cannot resolve `./EmptyState`.

- [ ] **Step 3: Implement**

```tsx
// frontend/components/EmptyState.tsx
export function EmptyState({ category }: { category: string | null }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-6 py-12 text-center">
      <p className="text-sm font-semibold">No stories yet</p>
      <p className="mt-1 text-xs text-muted">
        {category
          ? `Nothing filed under ${category} in the current window.`
          : "The feed fills as stories are ingested and linked to markets."}
      </p>
    </div>
  );
}
```

```tsx
// frontend/app/page.tsx
import { Header } from "@/components/Header";
import { PostCard } from "@/components/PostCard";
import { TrendingRail } from "@/components/TrendingRail";
import { EmptyState } from "@/components/EmptyState";
import { NewsletterButton } from "@/components/NewsletterButton";
import { fetchFeed, fetchTrending } from "@/lib/api";

export const revalidate = 60;

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<{ category?: string }>;
}) {
  const { category } = await searchParams;
  const [feed, trending] = await Promise.all([
    fetchFeed({ category }),
    fetchTrending(),
  ]);

  return (
    <div className="relative mx-auto max-w-6xl">
      <Header active={category ?? null} />
      <div className="flex gap-4 p-4">
        <main className="flex-1">
          {feed.items.length === 0
            ? <EmptyState category={category ?? null} />
            : feed.items.map((item) => <PostCard key={item.id} item={item} />)}
        </main>
        <TrendingRail trending={trending} />
      </div>
      <NewsletterButton />
    </div>
  );
}
```

```bash
# frontend/.env.example
BACKEND_API_URL=http://localhost:8000
```

Also create the inert CTA:

```tsx
// frontend/components/NewsletterButton.tsx
"use client";

export function NewsletterButton() {
  return (
    <button
      type="button"
      disabled
      title="Coming soon"
      className="fixed bottom-4 right-4 rounded-full bg-mint px-4 py-2.5
                 text-xs font-bold text-[#06120F] opacity-90"
    >
      ✉ Join the newsletter
    </button>
  );
}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/page.tsx frontend/components/EmptyState.tsx frontend/components/EmptyState.test.tsx frontend/components/NewsletterButton.tsx frontend/.env.example
git commit -m "feat: add feed page with empty state"
```

---

### Task 9: PostDetail, standalone route, and intercepted overlay

**Files:**
- Create: `frontend/components/PostDetail.tsx`
- Create: `frontend/components/PostDetail.test.tsx`
- Create: `frontend/app/posts/[id]/page.tsx`
- Create: `frontend/app/@modal/default.tsx`
- Create: `frontend/app/@modal/(.)posts/[id]/page.tsx`
- Create: `frontend/components/Modal.tsx`
- Modify: `frontend/app/layout.tsx` (accept the `modal` slot)

**Interfaces:**
- Consumes: `fetchPost`, `PostDetailData`, `MarketTag`.
- Produces: `<PostDetail post={data} />`, rendered identically by both routes.

**The fallback, if intercepting routes fight you:** keep `/posts/[id]` as a plain route and drop the `@modal` slot; clicking a card navigates to the full page. Report it as a concern rather than half-building the overlay.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/components/PostDetail.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PostDetailData } from "@/lib/types";
import { PostDetail } from "./PostDetail";

const NEWS: PostDetailData = {
  id: 1, title: "Shutdown talks collapse", url: "https://politico.com/a",
  author_name: "Politico", author_handle: null, avatar_url: null,
  source_kind: "rss", category: "Politics",
  published_at: new Date().toISOString(), cluster_size: 1,
  body: "Negotiators left without a framework.",
  markets: [{ ticker: "GOVSHUT", title: "Shutdown before Oct 15?", direction: "YES",
              confidence: 0.86, rationale: "No path to a deal remains.", yes_price: 64,
              volume: 2400000, close_time: null, price_delta: 11,
              kalshi_url: "https://kalshi.com/markets/GOVSHUT" }],
};

describe("PostDetail", () => {
  it("shows the author, body and related markets", () => {
    render(<PostDetail post={NEWS} />);
    expect(screen.getByText("Politico")).toBeInTheDocument();
    expect(screen.getByText(/Negotiators left/)).toBeInTheDocument();
    expect(screen.getByText("Shutdown before Oct 15?")).toBeInTheDocument();
    expect(screen.getByText(/No path to a deal remains./)).toBeInTheDocument();
  });

  it("labels the outbound link for a news article", () => {
    render(<PostDetail post={NEWS} />);
    const link = screen.getByRole("link", { name: /Read the full article/i });
    expect(link).toHaveAttribute("href", "https://politico.com/a");
  });

  it("labels the outbound link for an X post", () => {
    render(<PostDetail post={{ ...NEWS, source_kind: "x", author_handle: "@NickTimiraos" }} />);
    expect(screen.getByRole("link", { name: /View post on/i })).toBeInTheDocument();
  });

  it("renders a post with no related markets without an empty heading", () => {
    render(<PostDetail post={{ ...NEWS, markets: [] }} />);
    expect(screen.queryByText(/Related markets/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- components/PostDetail.test.tsx`
Expected: FAIL — cannot resolve `./PostDetail`.

- [ ] **Step 3: Implement the component**

```tsx
// frontend/components/PostDetail.tsx
import type { PostDetailData } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import { MarketTag } from "./MarketTag";

export function PostDetail({ post }: { post: PostDetailData }) {
  const isX = post.source_kind === "x";
  const initial = (post.author_name ?? "?").charAt(0).toUpperCase();

  return (
    <article className="mx-auto max-w-2xl rounded-2xl border border-[#33403F] bg-surface p-6">
      <div className="mb-4 flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-full
                        bg-surface-2 text-sm font-extrabold">{initial}</div>
        <div>
          <div className="text-sm font-bold">{post.author_name}</div>
          <div className="text-[11.5px] text-muted">
            {isX ? post.author_handle : "News outlet"} · {timeAgo(post.published_at)}
            {post.category && ` · ${post.category}`}
          </div>
        </div>
      </div>

      <h1 className="mb-2.5 text-xl font-bold leading-tight">{post.title}</h1>
      {post.body && <p className="mb-4 text-sm leading-relaxed text-[#B9C2C0]">{post.body}</p>}

      <a
        href={post.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mb-5 block rounded-lg border border-[#3A4446] bg-surface-2 py-2.5
                   text-center text-[13px] font-semibold"
      >
        {isX ? "View post on 𝕏 ↗" : "Read the full article ↗"}
      </a>

      {post.markets.length > 0 && (
        <>
          <h2 className="mb-2.5 text-[11px] font-bold uppercase tracking-wider text-muted">
            Related markets
          </h2>
          {post.markets.map((market) => (
            <div key={market.ticker}>
              <MarketTag market={market} />
              <p className="mb-2 mt-1 border-l-2 border-mint pl-2 text-[11.5px] text-muted">
                {market.rationale}
              </p>
            </div>
          ))}
        </>
      )}
    </article>
  );
}
```

- [ ] **Step 4: Wire both routes**

```tsx
// frontend/app/posts/[id]/page.tsx
import { notFound } from "next/navigation";
import { PostDetail } from "@/components/PostDetail";
import { fetchPost } from "@/lib/api";

export const revalidate = 60;

export default async function PostPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const post = await fetchPost(Number(id));
  if (!post) notFound();
  return <div className="p-6">
    <PostDetail post={post} />
  </div>;
}
```

```tsx
// frontend/components/Modal.tsx
"use client";

import { useRouter } from "next/navigation";

export function Modal({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  return (
    <div
      role="dialog"
      aria-modal="true"
      onClick={() => router.back()}
      className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-6 backdrop-blur-sm"
    >
      <div onClick={(event) => event.stopPropagation()}>{children}</div>
    </div>
  );
}
```

```tsx
// frontend/app/@modal/(.)posts/[id]/page.tsx
import { notFound } from "next/navigation";
import { Modal } from "@/components/Modal";
import { PostDetail } from "@/components/PostDetail";
import { fetchPost } from "@/lib/api";

export default async function InterceptedPost({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const post = await fetchPost(Number(id));
  if (!post) notFound();
  return <Modal><PostDetail post={post} /></Modal>;
}
```

```tsx
// frontend/app/@modal/default.tsx
export default function Default() {
  return null;
}
```

Modify `frontend/app/layout.tsx` to accept the slot:

```tsx
export default function RootLayout({
  children, modal,
}: { children: React.ReactNode; modal: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">
        {children}
        {modal}
      </body>
    </html>
  );
}
```

- [ ] **Step 5: Run to verify passing**

Run: `cd frontend && npm test && npm run typecheck && npm run build`
Expected: PASS, no type errors, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/components/PostDetail.tsx frontend/components/PostDetail.test.tsx frontend/components/Modal.tsx frontend/app/posts frontend/app/@modal frontend/app/layout.tsx
git commit -m "feat: add post detail as both overlay and standalone page"
```

---

### Task 10: LoadMore and the pagination proxy

**Files:**
- Create: `frontend/app/api/feed/route.ts`
- Create: `frontend/components/LoadMore.tsx`
- Create: `frontend/components/LoadMore.test.tsx`
- Modify: `frontend/app/page.tsx` (render `LoadMore` when `next_cursor` is present)

**Interfaces:**
- Consumes: `fetchFeed`, `FeedItem`, `PostCard`.
- Produces: `GET /api/feed` route handler proxying `category` and `cursor`; `<LoadMore initialCursor={...} category={...} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/components/LoadMore.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { LoadMore } from "./LoadMore";

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const ITEM = (id: number) => ({
  id, title: `Story ${id}`, url: "u", author_name: "Reuters", author_handle: null,
  avatar_url: null, source_kind: "rss", category: "World",
  published_at: new Date().toISOString(), cluster_size: 1, markets: [],
});

describe("LoadMore", () => {
  it("appends the next page and keeps the button while more remain", async () => {
    server.use(http.get("/api/feed", () =>
      HttpResponse.json({ items: [ITEM(2)], next_cursor: "cur2" })));

    render(<LoadMore initialCursor="cur1" category={undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));

    expect(await screen.findByText("Story 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
  });

  it("removes the button when the backend returns no further cursor", async () => {
    server.use(http.get("/api/feed", () =>
      HttpResponse.json({ items: [ITEM(3)], next_cursor: null })));

    render(<LoadMore initialCursor="cur1" category={undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));

    expect(await screen.findByText("Story 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });
});
```

Install the interaction library: `npm i -D @testing-library/user-event`

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- components/LoadMore.test.tsx`
Expected: FAIL — cannot resolve `./LoadMore`.

- [ ] **Step 3: Implement**

```ts
// frontend/app/api/feed/route.ts
import { NextResponse } from "next/server";
import { ApiError, fetchFeed } from "@/lib/api";

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  try {
    const page = await fetchFeed({
      category: params.get("category") ?? undefined,
      cursor: params.get("cursor") ?? undefined,
    });
    return NextResponse.json(page);
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 502;
    return NextResponse.json({ error: "feed unavailable" }, { status });
  }
}
```

```tsx
// frontend/components/LoadMore.tsx
"use client";

import { useState } from "react";

import type { FeedItem, FeedPage } from "@/lib/types";
import { PostCard } from "./PostCard";

export function LoadMore({
  initialCursor, category,
}: { initialCursor: string; category: string | undefined }) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [loading, setLoading] = useState(false);

  async function loadNext() {
    if (!cursor) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ cursor });
      if (category) params.set("category", category);
      const response = await fetch(`/api/feed?${params}`);
      if (!response.ok) return;
      const page = (await response.json()) as FeedPage;
      setItems((previous) => [...previous, ...page.items]);
      setCursor(page.next_cursor);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      {items.map((item) => <PostCard key={item.id} item={item} />)}
      {cursor && (
        <button
          type="button"
          onClick={loadNext}
          disabled={loading}
          className="mt-2 w-full rounded-lg border border-border bg-surface py-2.5
                     text-xs font-semibold text-muted hover:border-mint"
        >
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </>
  );
}
```

In `frontend/app/page.tsx`, after the `feed.items.map(...)`, add:

```tsx
{feed.next_cursor && (
  <LoadMore initialCursor={feed.next_cursor} category={category} />
)}
```

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npm test && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/api frontend/components/LoadMore.tsx frontend/components/LoadMore.test.tsx frontend/app/page.tsx frontend/package.json
git commit -m "feat: add cursor pagination via a proxy route"
```

---

### Task 11: Playwright smoke test

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/feed.spec.ts`
- Modify: `.github/workflows/ci.yml` (add the e2e step to the frontend job)

**Interfaces:**
- Consumes: the built app.
- Produces: one end-to-end proof that the intercepting-route wiring works.

**Why exactly one:** unit tests cannot verify that clicking a card renders the `@modal` slot. That is the single behaviour worth the weight of a browser.

- [ ] **Step 1: Install and configure**

```bash
cd frontend && npm i -D @playwright/test && npx playwright install --with-deps chromium
```

```ts
// frontend/playwright.config.ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:3000" },
  webServer: {
    command: "npm run start",
    url: "http://127.0.0.1:3000",
    reuseExistingServer: false,
    env: { BACKEND_API_URL: "http://127.0.0.1:9999" },
  },
});
```

- [ ] **Step 2: Write the failing test**

```ts
// frontend/e2e/feed.spec.ts
import { expect, test } from "@playwright/test";

const ITEM = {
  id: 1, title: "Shutdown talks collapse", url: "https://politico.com/a",
  author_name: "Politico", author_handle: null, avatar_url: null,
  source_kind: "rss", category: "Politics",
  published_at: new Date().toISOString(), cluster_size: 1,
  body: "Negotiators left without a framework.",
  markets: [],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/feed*", (route) =>
    route.fulfill({ json: { items: [ITEM], next_cursor: null } }));
  await page.route("**/api/trending*", (route) =>
    route.fulfill({ json: { by_volume: [], most_covered: [] } }));
  await page.route("**/api/posts/1", (route) => route.fulfill({ json: ITEM }));
});

test("the feed renders and a card opens as an overlay", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Shutdown talks collapse")).toBeVisible();

  await page.getByText("Shutdown talks collapse").click();

  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText(/Negotiators left/)).toBeVisible();
  expect(page.url()).toContain("/posts/1");
});
```

- [ ] **Step 3: Run it**

Run: `cd frontend && npm run build && npx playwright test`
Expected: PASS. If the overlay does not appear but `/posts/1` renders as a full page, the intercepting route is misconfigured — fix it, or invoke Task 9's named fallback and report the change.

- [ ] **Step 4: Add to CI**

Append to the `frontend` job in `.github/workflows/ci.yml`:

```yaml
      - run: npx playwright install --with-deps chromium
      - run: npm run build
        env:
          BACKEND_API_URL: http://127.0.0.1:9999
      - run: npx playwright test
```

- [ ] **Step 5: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e .github/workflows/ci.yml frontend/package.json
git commit -m "test: add a Playwright smoke test for the feed overlay"
```

---

### Task 12: Deploy configuration and runbook

**Files:**
- Create: `frontend/vercel.json`
- Modify: `README.md` (add a Deploy section)
- Create: `docs/RUNBOOK.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the documented, ordered path from an empty account to a live URL.

**This task writes documentation and config only.** Account creation and secret entry are the user's; the runbook must say plainly which steps a person performs.

- [ ] **Step 1: Write the Vercel config**

```json
{
  "buildCommand": "npm run build",
  "framework": "nextjs"
}
```

Set Vercel's project root directory to `frontend/` in the dashboard — note this in the runbook, since it is the single most common cause of a failed first deploy in a monorepo.

- [ ] **Step 2: Write the runbook**

`docs/RUNBOOK.md` must contain, in this order, with the exact commands:

1. **Neon** — create a project; copy the **pooled** connection string; explain that the pooled endpoint is required because Railway holds a persistent pool.
2. **Migrations** — `cd backend && DATABASE_URL=<neon-pooled> alembic upgrade head`, then verify: `psql <neon> -c "select count(*) from sources;"` should be non-zero because `0002_seed_sources` ran.
3. **Railway** — new project from the repo, root `backend/`; set `DATABASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `JOB_TOKEN` (generate with `openssl rand -hex 32`), `DAILY_LLM_BUDGET_USD=1.0`. Verify `curl https://<railway>/health` returns `{"status":"ok"}`.
4. **First job run, in order** — `sync_markets`, then `ingest`, then `link`, each as
   `curl -X POST https://<railway>/api/jobs/<job> -H "X-Job-Token: $JOB_TOKEN" --max-time 120`.
   State plainly: this is the first contact with live Kalshi data. Check `select count(*) from markets;` after the first, `posts` after the second, `post_markets` after the third. **If `post_markets` is zero while `markets` and `posts` are both non-empty, retrieval is finding no candidates** — capture a market row and a post row and stop; that is the failure mode the backend's Critical defect produced.
5. **GitHub secrets** — `API_URL` and `JOB_TOKEN` in repo settings; then enable the scheduled workflow.
6. **Vercel** — import the repo, set root directory `frontend/`, set `BACKEND_API_URL` to the Railway URL, deploy. Verify the feed renders populated.

Include a short "if it's broken" section: empty feed → check `posts`; untagged feed → check `post_markets` and the job logs; 502 from the frontend → `BACKEND_API_URL` wrong or Railway asleep.

- [ ] **Step 3: Update the README**

Add a Deploy section linking to `docs/RUNBOOK.md`, and record the running cost: Vercel free, Neon free, Railway ~$5/mo, LLM and embeddings ~$15-30/mo.

- [ ] **Step 4: Verify the docs are runnable**

Read `docs/RUNBOOK.md` top to bottom as if you had never seen the project. Every command must be copy-pasteable with only a substitution the reader can obviously make. No step may say "configure appropriately."

- [ ] **Step 5: Commit**

```bash
git add frontend/vercel.json docs/RUNBOOK.md README.md
git commit -m "docs: add deployment runbook and Vercel config"
```

---

## Self-Review Notes

**Spec coverage.** Server rendering + ISR → Tasks 3, 8. Category tabs as URLs → Task 6, 8. Intercepting routes → Task 9. Pagination proxy → Task 10. Tailwind palette → Task 2. Component table → Tasks 4-10. No-product-name branding constraint → Task 6, with a test. API contract → Task 3. Deploy sequence → Task 12, with the payload capture pulled forward to Task 1. Testing strategy → Tasks 2-11. Empty-feed degradation → Task 8.

**Deliberately deferred, per the spec's Scope section:** newsletter signup and digest (the button renders inert in Task 8), the golden-set harness that runs the real linker, and the compliance pass on `direction`/`confidence`.

**Known gap, stated rather than hidden:** no task unit-tests `app/page.tsx` itself. Async Server Components cannot be rendered by React Testing Library, and a test that mocks its way around that would assert nothing. Coverage for the page comes from Task 11's Playwright smoke test, which exercises it for real. This is the honest trade, not an oversight.
