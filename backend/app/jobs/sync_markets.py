from datetime import UTC, datetime

from app.clients.kalshi import KalshiClient
from app.embeddings import embed_texts
from app.market_text import compose_market_text, text_hash
from app.models import Market


def sync_markets(session, client: KalshiClient | None = None) -> int:
    client = client or KalshiClient()
    fetched = client.fetch_all_markets()

    existing = {m.ticker: m for m in session.query(Market).all()}
    needs_embedding: list[tuple[Market, str]] = []

    for incoming in fetched:
        composed = compose_market_text(incoming)
        digest = text_hash(composed)
        market = existing.get(incoming.ticker)

        if market is None:
            market = Market(ticker=incoming.ticker)
            session.add(market)
            existing[incoming.ticker] = market

        market.event_ticker = incoming.event_ticker
        market.series_ticker = incoming.series_ticker
        market.title = incoming.title
        market.rules_summary = incoming.rules_summary
        market.category = incoming.category
        market.status = incoming.status
        market.close_time = incoming.close_time
        market.yes_price = incoming.yes_price
        market.volume = incoming.volume
        market.updated_at = datetime.now(UTC)

        if market.text_hash != digest:
            market.text_hash = digest
            needs_embedding.append((market, composed))

    vectors = embed_texts([text for _, text in needs_embedding])
    for (market, _), vector in zip(needs_embedding, vectors):
        market.embedding = vector

    session.commit()
    return len(fetched)
