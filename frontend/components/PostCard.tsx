import Link from "next/link";

import type { FeedItem } from "@/lib/types";
import { truncate } from "@/lib/format";
import { timeAgo } from "@/lib/time";
import { MarketTag } from "./MarketTag";

const SNIPPET_LENGTH = 180;

export function PostCard({ item }: { item: FeedItem }) {
  const isX = item.source_kind === "x";
  const byline = isX ? item.author_handle : item.author_name?.toUpperCase();
  // An X post's title already *is* the tweet text, so a snippet would print
  // the same sentence twice.
  const snippet = !isX && item.body ? truncate(item.body, SNIPPET_LENGTH) : null;

  return (
    <article className="mb-2.5 rounded-xl border border-border bg-surface px-4 py-3.5">
      <div className="mb-2 flex items-center gap-2 text-[11px] text-muted">
        {isX && <span className="rounded bg-[#1D9BF0] px-1.5 font-bold text-white">𝕏</span>}
        <span className="font-semibold tracking-wide text-text">{byline}</span>
        <span>· {timeAgo(item.published_at)}</span>
        {item.cluster_size > 1 && (
          <span className="rounded-full border border-border px-2 py-0.5">
            +{item.cluster_size - 1} sources
          </span>
        )}
        {item.category && (
          <span className="rounded-full border border-border px-2 py-0.5">{item.category}</span>
        )}
      </div>

      <Link href={`/posts/${item.id}`} className="block">
        <h2 className="text-[15px] font-semibold leading-snug">{item.title}</h2>
        {snippet && (
          <p data-testid="snippet" className="mt-1 text-[13px] leading-relaxed text-muted">
            {snippet}
          </p>
        )}
      </Link>

      {item.markets.map((market) => (
        <MarketTag key={market.ticker} market={market} />
      ))}
    </article>
  );
}
