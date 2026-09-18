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
