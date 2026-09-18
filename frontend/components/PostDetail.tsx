import type { PostDetailData } from "@/lib/types";
import { timeAgo } from "@/lib/time";
import { MarketTag } from "./MarketTag";

export function PostDetail({ post }: { post: PostDetailData }) {
  const isX = post.source_kind === "x";
  const initial = (post.author_name ?? "?").charAt(0).toUpperCase();

  return (
    <article className="mx-auto max-w-2xl rounded-2xl border border-border bg-surface p-6">
      <div className="mb-4 flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-full
                        bg-surface-2 text-sm font-extrabold">{initial}</div>
        <div>
          <div className="text-sm font-bold">{post.author_name}</div>
          <div className="text-[11.5px] text-muted">
            {isX ? post.author_handle : "News outlet"} · {timeAgo(post.published_at)}
            {post.category && ` · ${post.category}`}
          </div>
        </div>
      </div>

      <h1 className="mb-2.5 text-xl font-bold leading-tight">{post.title}</h1>
      {post.body && <p className="mb-4 text-sm leading-relaxed text-muted">{post.body}</p>}

      <a
        href={post.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mb-5 block rounded-lg border border-border bg-surface-2 py-2.5
                   text-center text-[13px] font-semibold"
      >
        {isX ? "View post on 𝕏 ↗" : "Read the full article ↗"}
      </a>

      {post.markets.length > 0 && (
        <>
          <h2 className="mb-2.5 text-[11px] font-bold uppercase tracking-wider text-muted">
            Related markets
          </h2>
          {post.markets.map((market) => (
            <div key={market.ticker}>
              <MarketTag market={market} />
              <p className="mb-2 mt-1 border-l-2 border-mint pl-2 text-[11.5px] text-muted">
                {market.rationale}
              </p>
            </div>
          ))}
        </>
      )}
    </article>
  );
}
