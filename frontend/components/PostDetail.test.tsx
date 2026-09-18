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

  it("labels the outbound link for a news article and opens it safely", () => {
    render(<PostDetail post={NEWS} />);
    const link = screen.getByRole("link", { name: /Read the full article/i });
    expect(link).toHaveAttribute("href", "https://politico.com/a");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("labels the outbound link for an X post, shows the handle, and opens it safely", () => {
    render(<PostDetail post={{ ...NEWS, source_kind: "x", author_handle: "@NickTimiraos" }} />);
    const link = screen.getByRole("link", { name: /View post on/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(screen.getByText(/@NickTimiraos/)).toBeInTheDocument();
  });

  it("renders a post with no related markets without an empty heading", () => {
    render(<PostDetail post={{ ...NEWS, markets: [] }} />);
    expect(screen.queryByText(/Related markets/i)).toBeNull();
  });
});
