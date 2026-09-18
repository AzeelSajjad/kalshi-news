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

  it("omits a param that is explicitly undefined, rather than sending the literal string", async () => {
    let seen = "";
    server.use(http.get(`${BASE}/api/feed`, ({ request }) => {
      seen = new URL(request.url).search;
      return HttpResponse.json({ items: [], next_cursor: null });
    }));

    await fetchFeed({ category: undefined, limit: 5, cursor: undefined });

    expect(seen).not.toContain("undefined");
    expect(seen).toContain("limit=5");
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
