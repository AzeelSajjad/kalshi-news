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

// A realistic cursor, not a placeholder. Every cursor the backend emits is
// "<isoformat timestamp>|<post id>", and every one of those contains a
// "+00:00" offset. `+` is also the legacy query-string encoding for a space,
// so the value only survives the three encoding hops -- URLSearchParams here,
// the route handler's URL parse, the outbound URL to the backend -- if each
// one encodes it properly. They all do; "cur1" proved none of it.
const CURSOR = "2026-09-18T12:00:00+00:00|41";
const NEXT_CURSOR = "2026-09-18T11:00:00+00:00|17";

const ITEM = (id: number) => ({
  id, title: `Story ${id}`, url: "u", author_name: "Reuters", author_handle: null,
  avatar_url: null, source_kind: "rss", category: "World",
  published_at: new Date().toISOString(), cluster_size: 1, markets: [],
});

describe("LoadMore", () => {
  it("appends the next page and keeps the button while more remain", async () => {
    server.use(http.get(`${window.location.origin}/api/feed`, () =>
      HttpResponse.json({ items: [ITEM(2)], next_cursor: NEXT_CURSOR })));

    render(<LoadMore initialCursor={CURSOR} category={undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));

    expect(await screen.findByText("Story 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
  });

  it("removes the button when the backend returns no further cursor", async () => {
    server.use(http.get(`${window.location.origin}/api/feed`, () =>
      HttpResponse.json({ items: [ITEM(3)], next_cursor: null })));

    render(<LoadMore initialCursor={CURSOR} category={undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));

    expect(await screen.findByText("Story 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });

  it("accumulates items across two clicks instead of replacing the previous page", async () => {
    server.use(http.get(`${window.location.origin}/api/feed`, ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      if (cursor === CURSOR) {
        return HttpResponse.json({ items: [ITEM(2)], next_cursor: NEXT_CURSOR });
      }
      if (cursor === NEXT_CURSOR) {
        return HttpResponse.json({ items: [ITEM(3)], next_cursor: null });
      }
      throw new Error(`unexpected cursor: ${String(cursor)}`);
    }));

    render(<LoadMore initialCursor={CURSOR} category={undefined} />);

    await userEvent.click(screen.getByRole("button", { name: /load more/i }));
    expect(await screen.findByText("Story 2")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /load more/i }));
    expect(await screen.findByText("Story 3")).toBeInTheDocument();

    // The whole point of this test: both pages' items must be present at
    // once. setItems(page.items) (replace, instead of the correct
    // setItems(prev => [...prev, ...page.items])) would pass every assertion
    // above individually but drop Story 2 here.
    expect(screen.getByText("Story 2")).toBeInTheDocument();
    expect(screen.getByText("Story 3")).toBeInTheDocument();
  });
});
