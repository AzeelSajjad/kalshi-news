import "@testing-library/jest-dom/vitest";

import React, { type AnchorHTMLAttributes, type ReactNode } from "react";
import { vi } from "vitest";

// In the App Router, next/link asserts a mounted router and throws
// "invariant expected app router to be mounted" under React Testing
// Library. Mock it globally with a plain anchor so components that render
// links can be tested, and href assertions stay meaningful.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: AnchorHTMLAttributes<HTMLAnchorElement> & {
    href: string;
    children?: ReactNode;
  }) => React.createElement("a", { href, ...rest }, children),
}));
