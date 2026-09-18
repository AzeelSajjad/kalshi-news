import type { TrendingMarket, TrendingPage } from "@/lib/types";
import { cents } from "@/lib/format";

function formatVolume(volume: number): string {
  if (volume >= 1_000_000) {
    return `$${(volume / 1_000_000).toFixed(1)}M`;
  }
  return `$${Math.round(volume / 1_000)}K`;
}

function Row({ market, showCoverage }: { market: TrendingMarket; showCoverage?: boolean }) {
  return (
    <a
      href={market.kalshi_url}
      target="_blank"
      rel="noopener noreferrer"
      className="mb-2 block rounded-xl border border-border bg-surface p-3 hover:border-mint"
    >
      <div className="mb-2 text-[13px] font-semibold leading-snug">{market.title}</div>
      <div className="flex items-center justify-between text-[10.5px] text-muted">
        {market.yes_price !== null && (
          <span className="font-bold text-mint">YES {cents(market.yes_price)}</span>
        )}
        {showCoverage
          ? <span>{market.post_count} post{market.post_count === 1 ? "" : "s"}</span>
          : market.volume !== null && <span>{formatVolume(market.volume)} vol</span>}
      </div>
    </a>
  );
}

export function TrendingRail({ trending }: { trending: TrendingPage }) {
  const empty = trending.by_volume.length === 0 && trending.most_covered.length === 0;

  return (
    <aside className="w-[340px] shrink-0">
      {empty && <p className="text-xs text-muted">Nothing trending yet.</p>}

      {trending.by_volume.length > 0 && (
        <>
          <h4 className="mb-2.5 text-[11px] font-bold uppercase tracking-wider text-muted">
            Trending markets
          </h4>
          {trending.by_volume.map((m) => <Row key={m.ticker} market={m} />)}
        </>
      )}

      {trending.most_covered.length > 0 && (
        <>
          <h4 className="mb-2.5 mt-5 text-[11px] font-bold uppercase tracking-wider text-muted">
            Most covered today
          </h4>
          {trending.most_covered.map((m) => <Row key={m.ticker} market={m} showCoverage />)}
        </>
      )}
    </aside>
  );
}
