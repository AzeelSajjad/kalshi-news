import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

function Wordmark() {
  return <span>News × Prediction Markets</span>;
}

describe("test harness", () => {
  it("renders a component", () => {
    render(<Wordmark />);
    expect(screen.getByText("News × Prediction Markets")).toBeInTheDocument();
  });
});
