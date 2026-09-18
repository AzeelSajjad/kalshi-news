// frontend/app/api/feed/route.test.ts
//
// This handler had zero tests at any level. LoadMore.test.tsx mocks the
// route's own URL with MSW, which *replaces* the handler rather than
// exercising it, and the Playwright smoke test stubs next_cursor: null so
// LoadMore never renders at all. The one piece of server code the browser
// actually talks to was untouched by the suite.
//
// Here the exported GET is imported and called directly, with MSW standing
// in for the backend it proxies.
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { GET } from "./route";

const BACKEND = "http://backend.test";
process.env.BACKEND_API_URL = BACKEND;

const PAGE = { items: [], next_cursor: null };

const server = setupServer();
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function call(query: string) {
  return GET(new Request(`http://frontend.test/api/feed${query}`));
}

describe("GET /api/feed", () => {
  it("forwards category and cursor to the backend", async () => {
    let seen: URL | undefined;
    server.use(http.get(`${BACKEND}/api/feed`, ({ request }) => {
      seen = new URL(request.url);
      return HttpResponse.json(PAGE);
    }));

    const response = await call("?category=Politics&cursor=2026-09-18T12%3A00%3A00%2B00%3A00%7C41");

    expect(response.status).toBe(200);
    expect(seen!.searchParams.get("category")).toBe("Politics");
    expect(seen!.searchParams.get("cursor")).toBe("2026-09-18T12:00:00+00:00|41");
  });

  // Every real cursor contains a timezone offset. A `+` in a query string is
  // also the legacy encoding for a space, so a cursor survives the round trip
  // only if every hop encodes it properly. This is the assertion that says so.
  it("preserves the + in a cursor's timezone offset rather than turning it into a space", async () => {
    let raw = "";
    server.use(http.get(`${BACKEND}/api/feed`, ({ request }) => {
      raw = request.url;
      return HttpResponse.json(PAGE);
    }));

    await call("?cursor=2026-09-18T12%3A00%3A00%2B00%3A00%7C41");

    expect(raw).toContain("%2B00%3A00");
    expect(new URL(raw).searchParams.get("cursor")).not.toContain(" ");
  });

  it("omits category when the request carries none", async () => {
    let seen: URL | undefined;
    server.use(http.get(`${BACKEND}/api/feed`, ({ request }) => {
      seen = new URL(request.url);
      return HttpResponse.json(PAGE);
    }));

    await call("");

    expect(seen!.searchParams.has("category")).toBe(false);
    expect(seen!.searchParams.has("cursor")).toBe(false);
  });

  it("returns the backend's page unchanged on success", async () => {
    const page = { items: [{ id: 1 }], next_cursor: "next" };
    server.use(http.get(`${BACKEND}/api/feed`, () => HttpResponse.json(page)));

    expect(await (await call("")).json()).toEqual(page);
  });

  it("maps a backend failure to a status without leaking the upstream message", async () => {
    server.use(http.get(`${BACKEND}/api/feed`, () =>
      HttpResponse.json(
        { detail: "psycopg.OperationalError: connection to server at 10.0.0.4 failed" },
        { status: 500 },
      )));

    const response = await call("");
    const body = await response.text();

    expect(response.status).toBe(500);
    expect(body).toContain("feed unavailable");
    expect(body).not.toContain("psycopg");
    expect(body).not.toContain("10.0.0.4");
    expect(body).not.toContain(BACKEND);
    expect(body).not.toContain("backend responded");
  });

  it("passes a 422 on a malformed cursor through as a client error", async () => {
    server.use(http.get(`${BACKEND}/api/feed`, () =>
      HttpResponse.json({ detail: "invalid cursor" }, { status: 422 })));

    expect((await call("?cursor=garbage")).status).toBe(422);
  });

  it("answers 502 when the backend is unreachable", async () => {
    server.use(http.get(`${BACKEND}/api/feed`, () => HttpResponse.error()));

    const response = await call("");

    expect(response.status).toBe(502);
    expect(await response.text()).toContain("feed unavailable");
  });
});
