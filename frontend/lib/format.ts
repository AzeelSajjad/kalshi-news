/**
 * The single definition of what a price looks like.
 *
 * The plan's constraint was "MarketTag is the only component that formats a
 * price or a delta". TrendingRail took a `TrendingMarket`, which is not a
 * `MarketRef`, so MarketTag could not be reused wholesale and the formatting
 * was quietly duplicated. Pulling the function out satisfies what the
 * constraint was actually protecting: one definition, so the same number
 * cannot render two ways.
 *
 * `MarketTag` remains the only place that picks a *colour* or a sign for a
 * delta. This module formats; it does not decide meaning.
 */
export function cents(value: number): string {
  return `${value}¢`;
}
