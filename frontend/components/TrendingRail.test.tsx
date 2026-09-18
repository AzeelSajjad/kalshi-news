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
