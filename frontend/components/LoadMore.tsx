// frontend/components/LoadMore.tsx
"use client";

import { useRef, useState } from "react";

import type { FeedItem, FeedPage } from "@/lib/types";
import { PostCard } from "./PostCard";

export function LoadMore({
  initialCursor, category,
}: { initialCursor: string; category: string | undefined }) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(initialCursor);
  const [loading, setLoading] = useState(false);
  // A synchronous guard against double-firing on a rapid double click.
  // `loading` state updates are asynchronous, so two clicks that land in the
  // same tick could both read `loading === false` before either re-render
  // lands; this ref is set/cleared synchronously around the request.
  const requestInFlight = useRef(false);

  async function loadNext() {
    if (!cursor || requestInFlight.current) return;
    requestInFlight.current = true;
    setLoading(true);
    try {
      const params = new URLSearchParams({ cursor });
      if (category) params.set("category", category);
      const response = await fetch(`${window.location.origin}/api/feed?${params}`);
      if (!response.ok) return;
      const page = (await response.json()) as FeedPage;
      setItems((previous) => [...previous, ...page.items]);
      setCursor(page.next_cursor);
    } catch (error) {
      // A genuine network failure (as opposed to a non-2xx response, handled
      // above) rejects the fetch promise. loadNext is fired from onClick with
      // nothing awaiting it, so an uncaught rejection here would surface as
      // an unhandled rejection. Log it the way app/error.tsx does and let the
      // finally block below recover the UI; nothing user-facing changes.
      console.error(error);
    } finally {
      setLoading(false);
      requestInFlight.current = false;
    }
  }

  return (
    <>
      {items.map((item) => <PostCard key={item.id} item={item} />)}
      {cursor && (
        <button
          type="button"
          onClick={loadNext}
          disabled={loading}
          className="mt-2 w-full rounded-lg border border-border bg-surface py-2.5
                     text-xs font-semibold text-muted hover:border-mint"
        >
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </>
  );
}
