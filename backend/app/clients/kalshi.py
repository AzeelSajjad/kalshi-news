from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class KalshiMarket:
    ticker: str
    event_ticker: str | None
    series_ticker: str | None
    title: str
    rules_summary: str | None
    category: str | None
    status: str
    close_time: datetime | None
    yes_price: int | None
    volume: int | None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _midpoint(bid, ask) -> int | None:
    if bid is None and ask is None:
        return None
    if bid is None or ask is None:
        return bid if ask is None else ask
    return round((bid + ask) / 2)


def _is_retryable(exc: BaseException) -> bool:
    """Only retry failures a retry could plausibly fix.

    Retrying on *any* exception meant a permanent 404 (a delisted series, a
    market with no candlesticks) cost three requests and two backoff sleeps
    before failing anyway -- multiplied by every dead link the impact job
    walks. Transport errors, 5xx and 429 are transient; a 4xx is an answer.
    """
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


class KalshiClient:
    """Read-only client for Kalshi's public endpoints. Never sends auth headers."""

    def __init__(self, timeout: float = 20.0):
        self._client = httpx.Client(timeout=timeout, headers={"Accept": "application/json"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @retry(retry=retry_if_exception(_is_retryable), stop=stop_after_attempt(3),
           wait=wait_exponential(min=1, max=10), reraise=True)
    def _get(self, path: str, params: dict) -> dict:
        response = self._client.get(f"{BASE_URL}{path}", params=params)
        response.raise_for_status()
        return response.json()

    def fetch_all_markets(self, status: str = "open") -> list[KalshiMarket]:
        markets: list[KalshiMarket] = []
        cursor = ""
        while True:
            params = {"limit": 1000, "status": status}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/markets", params)
            for raw in payload.get("markets", []):
                markets.append(KalshiMarket(
                    ticker=raw["ticker"],
                    event_ticker=raw.get("event_ticker"),
                    series_ticker=raw.get("series_ticker"),
                    title=raw.get("title", ""),
                    rules_summary=raw.get("rules_primary"),
                    category=raw.get("category"),
                    status=raw.get("status", "unknown"),
                    close_time=_parse_ts(raw.get("close_time")),
                    yes_price=_midpoint(raw.get("yes_bid"), raw.get("yes_ask")),
                    volume=raw.get("volume"),
                ))
            cursor = payload.get("cursor") or ""
            if not cursor:
                return markets

    def fetch_candlesticks(self, ticker: str, start: datetime, end: datetime,
                            series_ticker: str | None = None,
                            period_interval: int = 60) -> list[tuple[datetime, int]]:
        series = series_ticker or ticker.split("-")[0]
        payload = self._get(
            f"/series/{series}/markets/{ticker}/candlesticks",
            {"start_ts": int(start.timestamp()), "end_ts": int(end.timestamp()),
             "period_interval": period_interval},
        )
        points = []
        for candle in payload.get("candlesticks", []):
            close = (candle.get("price") or {}).get("close")
            if close is None:
                continue
            points.append((datetime.fromtimestamp(candle["end_period_ts"], tz=UTC), close))
        return points
