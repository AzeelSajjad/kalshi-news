import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CATEGORIES, Header } from "./Header";

describe("Header", () => {
  // The seeded sources (backend/migrations/versions/0002_seed_sources.py)
  // carry exactly four categories among rows with enabled=true: Politics,
  // Economics and Finance from the RSS feeds, and World from the X source.
  // backend/app/jobs/ingest.py sets post.category = source.category
  // unconditionally, so a post can never carry any other value. A tab
  // outside this list is permanently empty on the live site -- and the
  // empty-state copy ("Nothing filed under X in the current window")
  // promises transience for a state that never changes.
  it("offers only categories a seeded, enabled source can actually produce", () => {
    expect([...CATEGORIES]).toEqual(["Politics", "Economics", "Finance", "World"]);
  });

  it("offers no tab that can never be filled", () => {
    render(<Header active={null} />);
    for (const dead of ["Crypto", "Sports", "Culture"]) {
      expect(screen.queryByRole("link", { name: dead })).toBeNull();
    }
  });

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
