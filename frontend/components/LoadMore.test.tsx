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
    server.use(http.get(`${window.location.origin}/api/feed`, () =>
      HttpResponse.json({ items: [ITEM(2)], next_cursor: "cur2" })));

    render(<LoadMore initialCursor="cur1" category={undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));

    expect(await screen.findByText("Story 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /load more/i })).toBeInTheDocument();
  });

  it("removes the button when the backend returns no further cursor", async () => {
    server.use(http.get(`${window.location.origin}/api/feed`, () =>
      HttpResponse.json({ items: [ITEM(3)], next_cursor: null })));

    render(<LoadMore initialCursor="cur1" category={undefined} />);
    await userEvent.click(screen.getByRole("button", { name: /load more/i }));

    expect(await screen.findByText("Story 3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
  });
});
