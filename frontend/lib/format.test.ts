import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { cents } from "./format";

describe("cents", () => {
  it("renders an integer price in cents", () => {
    expect(cents(64)).toBe("64¢");
    expect(cents(0)).toBe("0¢");
  });
});

describe("the single-formatter constraint", () => {
  // Mechanical, not aspirational. TrendingRail formatted a price inline for
  // the whole of this plan and no test noticed, because "MarketTag is the
  // only component that formats a price" was a sentence in a document rather
  // than an assertion. This is the assertion.
  it("keeps the cents symbol out of every file but lib/format.ts", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      if (file.endsWith("lib/format.ts") || file.endsWith(".test.ts") ||
          file.endsWith(".test.tsx")) {
        continue;
      }
      if (readFileSync(file, "utf8").includes("¢")) offenders.push(file);
    }
    expect(offenders).toEqual([]);
  });
});

function sourceFiles(root = join(import.meta.dirname, "..")): string[] {
  const out: string[] = [];
  for (const dir of ["app", "components", "lib"]) {
    walk(join(root, dir), out);
  }
  return out;
}

function walk(dir: string, out: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path, out);
    else if (/\.tsx?$/.test(entry.name)) out.push(path);
  }
}
