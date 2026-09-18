import hashlib

from app.clients.kalshi import KalshiMarket


def compose_market_text(market: KalshiMarket) -> str:
    """Build the string a market is embedded as.

    Tickers like FED-26SEP-T4.50 carry no semantic signal, so they are
    deliberately excluded — only human-readable fields are embedded.
    """
    parts = [market.title]
    if market.rules_summary:
        parts.append(market.rules_summary)
    if market.category:
        parts.append(f"Category: {market.category}")
    if market.close_time:
        parts.append(f"Closes {market.close_time.date().isoformat()}")
    return " — ".join(parts)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
