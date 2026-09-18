import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("explains an empty feed rather than rendering blank", () => {
    render(<EmptyState category={null} />);
    expect(screen.getByText(/No stories yet/i)).toBeInTheDocument();
  });

  it("names the category when one is filtered", () => {
    render(<EmptyState category="Sports" />);
    expect(screen.getByText(/Sports/)).toBeInTheDocument();
  });
});
