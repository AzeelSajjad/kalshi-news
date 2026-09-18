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

// --- direction is not the price --------------------------------------------
//
// `direction` is which way the news pushes the market; `yes_price` is always
// the YES contract's price. Rendering them as one token ("NO 64¢") reads to
// any prediction-market user as "NO trades at 64¢", when NO is 36¢. That is
// the wrong number on the product's central claim, in front of an audience
// that will read it correctly and conclude the opposite of what is meant.
describe("MarketTag, NO direction", () => {
  const NO_MARKET: MarketRef = { ...BASE, direction: "NO" };

  it("labels the price as the YES price even when the direction is NO", () => {
    render(<MarketTag market={NO_MARKET} />);

    const price = screen.getByTestId("market-price");
    expect(price).toHaveTextContent("YES 64¢");
    expect(screen.getByTestId("market-direction")).toHaveTextContent("NO");
  });

  it("never renders the direction immediately followed by the price", () => {
    render(<MarketTag market={NO_MARKET} />);
    expect(screen.queryByText(/NO\s*64¢/)).toBeNull();
  });

  it("keeps the direction visible as its own signal", () => {
    render(<MarketTag market={{ ...NO_MARKET, yes_price: null }} />);
    expect(screen.getByTestId("market-direction")).toHaveTextContent("NO");
    expect(screen.queryByTestId("market-price")).toBeNull();
  });

  // mint/red on the price meant YES/NO while mint/red on the delta meant
  // up/down -- two meanings for the same two colours, 8px apart. The delta
  // now owns them outright.
  it("reserves mint and red for the delta, so each colour means one thing", () => {
    render(<MarketTag market={NO_MARKET} />);
    for (const testid of ["market-direction", "market-price"]) {
      const node = screen.getByTestId(testid);
      expect(node.className).not.toMatch(/text-mint|text-negative/);
    }
    expect(screen.getByTestId("price-delta").className).toMatch(/text-mint/);
  });
});

describe("MarketTag, zero delta", () => {
  it("renders no movement rather than an up arrow in mint", () => {
    render(<MarketTag market={{ ...BASE, price_delta: 0 }} />);
    expect(screen.queryByTestId("price-delta")).toBeNull();
    expect(screen.queryByText(/▲/)).toBeNull();
  });
});
