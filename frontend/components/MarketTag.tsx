import type { MarketRef } from "@/lib/types";
import { cents } from "@/lib/format";

/**
 * One linked market.
 *
 * Three facts sit in this row and each is rendered as its own thing:
 *
 * - **direction** — which way the news pushes the market. A chip.
 * - **yes_price** — always the YES contract's price, whatever the direction
 *   is. Labelled "YES" every time, including when the direction is also YES.
 *   The redundancy in that case is the price of never being wrong in the
 *   other one: "NO 64" with a cents sign reads to anyone who trades these
 *   as "NO is 64 cents", when NO is 36 and the claim being made is about a
 *   market trading at 64.
 * - **price_delta** — how far it moved after the link was made.
 *
 * Mint and red belong to the delta alone. They previously did double duty —
 * YES/NO on the price, up/down on the delta — two meanings for two colours
 * 8px apart. The direction chip and the price are now neutral, which also
 * stops the page shouting a trading direction in exchange-green at a reader.
 *
 * A delta of exactly 0 renders nothing. The badge reports movement; no
 * movement is the absence of what it reports, and an up arrow over a zero
 * in mint read as a rise. (`null` -- not yet measured -- has always
 * rendered nothing.)
 */
export function MarketTag({ market }: { market: MarketRef }) {
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

      <span
        data-testid="market-direction"
        className="shrink-0 rounded border border-border px-1.5 py-0.5
                   text-[10px] font-bold uppercase tracking-wider text-muted"
      >
        {market.direction}
      </span>

      {market.yes_price !== null && (
        <span data-testid="market-price" className="shrink-0 font-bold text-text">
          <span className="font-normal text-muted">YES </span>
          {cents(market.yes_price)}
        </span>
      )}

      {market.yes_price !== null && delta !== null && delta !== 0 && (
        <span
          data-testid="price-delta"
          className={`shrink-0 text-xs font-semibold ${delta > 0 ? "text-mint" : "text-negative"}`}
        >
          {delta > 0 ? "▲" : "▼"} {cents(Math.abs(delta))}
        </span>
      )}
    </a>
  );
}
