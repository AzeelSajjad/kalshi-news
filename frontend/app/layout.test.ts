// frontend/app/layout.test.ts
import { describe, expect, it } from "vitest";

import { metadata } from "./layout";

describe("root metadata", () => {
  // Without a metadataBase Next drops the relative openGraph url that
  // app/posts/[id] emits, and warns on every build.
  it("has a metadataBase so relative Open Graph urls resolve", () => {
    expect(metadata.metadataBase).toBeInstanceOf(URL);
  });

  it("carries no product name", () => {
    expect(metadata.title.toLowerCase()).not.toContain("kalshi");
  });
});
