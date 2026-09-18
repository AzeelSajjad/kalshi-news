// frontend/e2e/stub-backend.mjs
//
// A tiny, deterministic stand-in for the real backend, used only by the
// Playwright smoke test. The feed page is a Server Component, so Next
// fetches it from the server -- the browser never issues that request, and
// page.route() in the test can't intercept it. This process serves the same
// three endpoints the frontend's server-side fetches hit, with fixed JSON,
// so the test never reaches the real backend or the internet.
import { createServer } from "node:http";

const PORT = Number(process.env.PORT ?? 9999);

const ITEM = {
  id: 1,
  title: "Shutdown talks collapse",
  url: "https://politico.com/a",
  author_name: "Politico",
  author_handle: null,
  avatar_url: null,
  source_kind: "rss",
  category: "Politics",
  published_at: "2026-09-18T12:00:00.000Z",
  cluster_size: 1,
  body: "Negotiators left without a framework.",
  markets: [],
};

const FEED_PAGE = { items: [ITEM], next_cursor: null };
const TRENDING_PAGE = { by_volume: [], most_covered: [] };

function send(res, status, body) {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(json),
  });
  res.end(json);
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://127.0.0.1:${PORT}`);

  if (url.pathname === "/api/feed") {
    send(res, 200, FEED_PAGE);
    return;
  }

  if (url.pathname === "/api/trending") {
    send(res, 200, TRENDING_PAGE);
    return;
  }

  const postMatch = url.pathname.match(/^\/api\/posts\/(\d+)$/);
  if (postMatch) {
    const id = Number(postMatch[1]);
    if (id === ITEM.id) {
      send(res, 200, ITEM);
    } else {
      send(res, 404, { error: "not found" });
    }
    return;
  }

  send(res, 404, { error: "not found" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`stub backend listening on http://127.0.0.1:${PORT}`);
});
