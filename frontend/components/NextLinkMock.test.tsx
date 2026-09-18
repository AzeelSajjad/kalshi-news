import Link from "next/link";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Proves the global next/link mock in vitest.setup.ts works: it renders a
// plain anchor carrying href and children, instead of throwing "invariant
// expected app router to be mounted" the way the real next/link does under
// React Testing Library outside a mounted App Router.
function LinkExample() {
  return <Link href="/markets/example">Example market</Link>;
}

describe("next/link mock", () => {
  it("renders a plain anchor with the given href", () => {
    render(<LinkExample />);
    const anchor = screen.getByText("Example market");
    expect(anchor.tagName).toBe("A");
    expect(anchor).toHaveAttribute("href", "/markets/example");
  });
});
