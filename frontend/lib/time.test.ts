import { describe, expect, it } from "vitest";
import { timeAgo } from "./time";

const NOW = new Date("2026-09-18T12:00:00Z");

describe("timeAgo", () => {
  it("renders minutes under an hour", () => {
    expect(timeAgo("2026-09-18T11:36:00Z", NOW)).toBe("24m ago");
  });
  it("renders hours under a day", () => {
    expect(timeAgo("2026-09-18T09:00:00Z", NOW)).toBe("3h ago");
  });
  it("renders days beyond that", () => {
    expect(timeAgo("2026-09-16T12:00:00Z", NOW)).toBe("2d ago");
  });
  it("renders 'just now' under a minute", () => {
    expect(timeAgo("2026-09-18T11:59:30Z", NOW)).toBe("just now");
  });
});
