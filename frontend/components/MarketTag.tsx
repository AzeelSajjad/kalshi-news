import type { MarketRef } from "@/lib/types";

function cents(value: number): string {
  return `${value}¢`;
}

export function MarketTag({ market }: { market: MarketRef }) {
  const isYes = market.direction === "YES";
  const delta = market.price_delta;

  return (
    <a
      href={market.kalshi_url}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-1.5 flex items-center gap-2 rounded-lg border border-border
                 bg-surface-2 px-3 py-2 text-sm hover:border-mint"
    >
      <span className="flex-1 text-text">{market.title}</span>
      {market.yes_price !== null && (
        <span className={`font-bold ${isYes ? "text-mint" : "text-negative"}`}>
          {market.direction} {cents(market.yes_price)}
        </span>
      )}
      {market.yes_price !== null && delta !== null && (
        <span
          data-testid="price-delta"
          className={`text-xs font-semibold ${delta >= 0 ? "text-mint" : "text-negative"}`}
        >
          {delta >= 0 ? "▲" : "▼"} {cents(Math.abs(delta))}
        </span>
      )}
    </a>
  );
}
