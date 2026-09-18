// frontend/lib/palette.test.ts
//
// "Palette tokens only" was a bullet in a plan for thirteen tasks and
// produced eight violations in its own reference code. A sentence in a
// document cannot fail a build; this can. It scans every file the UI is made
// of and fails on a raw colour, so the next one is caught at the point it is
// written rather than at a final review.
//
// The tokens themselves are defined once, in app/globals.css, as Tailwind
// theme variables. That file is the one place a hex is allowed to exist.
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "..");
const SCANNED = ["app", "components"];
// The single definition site for the palette.
const TOKEN_FILE = join(ROOT, "app", "globals.css");

const ANY_HEX = /#[0-9a-fA-F]{3,8}\b/g;

// Tailwind's own colour scales and the bare white/black keywords. Our tokens
// (bg, surface, surface-2, border, text, muted, mint, negative) are not in
// this list, so `bg-surface-2` and `text-muted` pass while `text-white` and
// `bg-slate-800` do not.
const UTILITY_PREFIX =
  "bg|text|border|ring|outline|fill|stroke|shadow|accent|caret|decoration|divide|" +
  "placeholder|from|via|to";
const TAILWIND_SCALE =
  "white|black|slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|" +
  "green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const NON_PALETTE_UTILITY =
  new RegExp(`\\b(?:${UTILITY_PREFIX})-(?:${TAILWIND_SCALE})(?:-\\d{2,3})?\\b`, "g");

// bg-[#1D9BF0], text-[rgb(...)], border-[hsl(...)] -- an arbitrary value that
// is a colour. Arbitrary *sizes* (text-[12.5px]) are deliberately fine.
const ARBITRARY_COLOUR =
  new RegExp(`\\b(?:${UTILITY_PREFIX})-\\[(?:#|rgb|hsl|oklch|lab|lch|color\\()`, "g");

describe("the palette", () => {
  it("has no raw hex outside the token definitions", () => {
    expect(scan(ANY_HEX, { skipTokenFile: true })).toEqual([]);
  });

  it("uses no Tailwind default colour utility", () => {
    expect(scan(NON_PALETTE_UTILITY)).toEqual([]);
  });

  it("uses no arbitrary colour value", () => {
    expect(scan(ARBITRARY_COLOUR)).toEqual([]);
  });

  // A guard that cannot fail is not a guard.
  it("would catch a violation if one were introduced", () => {
    const sample = 'className="rounded bg-[#1D9BF0] px-1.5 font-bold text-white"';
    expect(sample.match(ANY_HEX)).not.toBeNull();
    expect(sample.match(NON_PALETTE_UTILITY)).not.toBeNull();
    expect(sample.match(ARBITRARY_COLOUR)).not.toBeNull();
  });
});

function scan(pattern: RegExp, opts: { skipTokenFile?: boolean } = {}): string[] {
  const offenders: string[] = [];
  for (const file of sourceFiles()) {
    if (opts.skipTokenFile && file === TOKEN_FILE) continue;
    const hits = readFileSync(file, "utf8").match(new RegExp(pattern.source, "g"));
    if (hits) offenders.push(`${relative(ROOT, file)}: ${[...new Set(hits)].join(", ")}`);
  }
  return offenders;
}

function sourceFiles(): string[] {
  const out: string[] = [];
  for (const dir of SCANNED) walk(join(ROOT, dir), out);
  return out;
}

function walk(dir: string, out: string[]): void {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path, out);
    else if (/\.(tsx?|css)$/.test(entry.name)) out.push(path);
  }
}
