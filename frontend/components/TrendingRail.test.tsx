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

  it("does not show the by-volume heading when that ranking is empty", () => {
    render(<TrendingRail trending={{ by_volume: [], most_covered: PAGE.most_covered }} />);
    expect(screen.queryByText(/Trending markets/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Most covered today/i)).toBeInTheDocument();
  });

  it("formats volume under a million in thousands", () => {
    const page: TrendingPage = {
      by_volume: [{ ticker: "LOWVOL", title: "Small market", yes_price: 50,
                    volume: 450000, post_count: 0, kalshi_url: "https://kalshi.com/markets/LOWVOL" }],
      most_covered: [],
    };
    render(<TrendingRail trending={page} />);
    expect(screen.getByText("$450K vol")).toBeInTheDocument();
  });

  it("formats volume a million or above in millions", () => {
    render(<TrendingRail trending={PAGE} />);
    expect(screen.getByText("$2.4M vol")).toBeInTheDocument();
  });

  it("renders no volume text when volume is null", () => {
    const page: TrendingPage = {
      by_volume: [{ ticker: "NOVOL", title: "No volume market", yes_price: 50,
                    volume: null, post_count: 0, kalshi_url: "https://kalshi.com/markets/NOVOL" }],
      most_covered: [],
    };
    render(<TrendingRail trending={page} />);
    expect(screen.getByText("No volume market")).toBeInTheDocument();
    expect(screen.queryByText(/vol$/)).not.toBeInTheDocument();
  });

  it("uses singular 'post' for a count of one", () => {
    const page: TrendingPage = {
      by_volume: [],
      most_covered: [{ ticker: "ONE", title: "One post market", yes_price: 50,
                       volume: 100000, post_count: 1, kalshi_url: "https://kalshi.com/markets/ONE" }],
    };
    render(<TrendingRail trending={page} />);
    expect(screen.getByText("1 post")).toBeInTheDocument();
  });
});
