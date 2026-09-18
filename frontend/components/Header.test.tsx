import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CATEGORIES, Header } from "./Header";

describe("Header", () => {
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
