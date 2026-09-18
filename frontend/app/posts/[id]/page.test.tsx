// frontend/app/posts/[id]/page.test.tsx
//
// A Server Component is awkward to test, but this one is worth it: it is the
// page a *shared link* lands on, and a pasted link is the product's delivery
// mechanism. It shipped with no header and no route back into the product,
// and with no per-post metadata, so every shared story unfurled identically.
//
// The component is an async function returning JSX, so it can be awaited and
// the result handed to RTL. Its data comes through lib/api, which MSW
// intercepts.
import { render, screen, within } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import PostPage, { generateMetadata } from "./page";

const BACKEND = "http://backend.test";
process.env.BACKEND_API_URL = BACKEND;

const POST = {
  id: 7,
  title: "Leadership walks out of shutdown talks",
  url: "https://politico.com/shutdown",
  author_name: "Politico Politics",
  author_handle: null,
  avatar_url: null,
  source_kind: "rss",
  category: "Politics",
  published_at: "2026-09-18T12:00:00+00:00",
  cluster_size: 1,
  body: "Congressional leaders left the room without a deal, according to two aides.",
  markets: [],
};

const server = setupServer(
  http.get(`${BACKEND}/api/posts/7`, () => HttpResponse.json(POST)),
  http.get(`${BACKEND}/api/trending`, () =>
    HttpResponse.json({ by_volume: [], most_covered: [] })),
);
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const params = Promise.resolve({ id: "7" });

describe("the standalone post page", () => {
  it("renders the post inside the same shell the feed uses", async () => {
    render(await PostPage({ params }));

    expect(screen.getByText(POST.title)).toBeInTheDocument();
    // The header, with its category tabs and the Kalshi attribution.
    expect(screen.getByTestId("kalshi-attribution")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Politics" })).toBeInTheDocument();
  });

  it("offers a way back into the feed", async () => {
    render(await PostPage({ params }));

    const back = screen.getByTestId("back-to-feed");
    expect(back).toHaveAttribute("href", "/");
  });

  it("links back into the story's own category, not just the front page", async () => {
    render(await PostPage({ params }));

    const nav = screen.getByRole("navigation");
    expect(within(nav).getByRole("link", { name: "Politics" }))
      .toHaveAttribute("href", "/?category=Politics");
  });
});

describe("generateMetadata", () => {
  it("titles the unfurl with the story, not the site", async () => {
    const meta = await generateMetadata({ params });
    expect(meta.title).toBe(POST.title);
  });

  it("describes the unfurl with the story body", async () => {
    const meta = await generateMetadata({ params });
    expect(meta.description).toContain("Congressional leaders left the room");
  });

  it("truncates a long body rather than emitting the whole article", async () => {
    server.use(http.get(`${BACKEND}/api/posts/7`, () =>
      HttpResponse.json({ ...POST, body: "word ".repeat(200) })));

    const meta = await generateMetadata({ params });
    expect(meta.description!.length).toBeLessThanOrEqual(200);
    expect(meta.description).toMatch(/…$/);
  });

  it("falls back to the title when the post carries no body", async () => {
    server.use(http.get(`${BACKEND}/api/posts/7`, () =>
      HttpResponse.json({ ...POST, body: null })));

    const meta = await generateMetadata({ params });
    expect(meta.description).toBe(POST.title);
  });

  it("does not throw for a post that no longer exists", async () => {
    server.use(http.get(`${BACKEND}/api/posts/7`, () =>
      HttpResponse.json({ error: "not found" }, { status: 404 })));

    await expect(generateMetadata({ params })).resolves.toBeTruthy();
  });
});
