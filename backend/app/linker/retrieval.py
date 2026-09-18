from dataclasses import dataclass
from datetime import UTC, datetime

from app.models import Market, Post


@dataclass(frozen=True)
class Candidate:
    ticker: str
    title: str
    rules_summary: str | None
    close_time: datetime | None
    yes_price: int | None
    volume: int | None
    distance: float


def find_candidates(
    session, post: Post, limit: int = 10, max_distance: float = 0.55
) -> list[Candidate]:
    if post.embedding is None:
        return []

    distance = Market.embedding.cosine_distance(post.embedding).label("distance")
    rows = (
        session.query(Market, distance)
        .filter(Market.embedding.isnot(None))
        .filter(Market.status == "open")
        .filter(Market.close_time > datetime.now(UTC))
        .filter(distance <= max_distance)
        .order_by(distance)
        .limit(limit)
        .all()
    )
    return [
        Candidate(
            ticker=market.ticker,
            title=market.title,
            rules_summary=market.rules_summary,
            close_time=market.close_time,
            yes_price=market.yes_price,
            volume=market.volume,
            distance=float(dist),
        )
        for market, dist in rows
    ]
