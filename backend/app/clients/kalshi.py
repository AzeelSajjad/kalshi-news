import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

# At limit=1000 per page, 50 pages is 50,000 markets -- far above Kalshi's catalog size.
# A repeated/sticky cursor is broken out of separately (see fetch_all_markets); this cap
# is a second, independent backstop against an unbounded pagination loop.
MAX_PAGES = 50


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


def _parse_dollars_to_cents(value: object) -> int | None:
    """Convert a dollars-denominated field (e.g. '0.6400' -> 64 cents).

    Uses Decimal rather than float: float(value) * 100 is exposed to binary
    floating-point representation error on some inputs, and plain round()
    breaks an exact half-cent to the nearest *even* cent (banker's
    rounding) rather than consistently away from zero. Decimal with
    ROUND_HALF_UP makes the rounding rule at a half-cent boundary explicit
    and independent of float representation -- this is a money value the
    UI presents as fact, so "quietly different depending on how you read
    the code" is not acceptable here.

    Tolerates None, '', and garbage strings by returning None -- one
    unparseable market must not abort a sync of thousands.
    """
    if value is None or value == "":
        return None
    try:
        cents = (Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return int(cents)
    except (TypeError, ValueError, InvalidOperation, ArithmeticError):
        return None


def _parse_fixed_point_to_int(value: object) -> int | None:
    """Convert a fixed-point string field (e.g. '2400000.00' -> 2400000).

    Tolerates None, '', and garbage strings by returning None.
    """
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    """Coerce the pre-fallback field values (already integer cents/counts).

    Tolerates None, '', and garbage strings by returning None.
    """
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _price_field_cents(raw: dict, new_key: str, old_key: str) -> int | None:
    """Read a price field, preferring the *_dollars name the live API sends.

    The new field is a dollars string ('0.6400' -> 64 cents). The old
    field (used by the pre-existing fixtures/tests) is already integer
    cents, so it is coerced directly rather than run through dollar
    parsing.

    Falls back to the old key whenever the new key isn't *usable* --
    absent, None, or '' -- not merely whenever it's absent. A Kalshi
    field-migration window could plausibly ship both field styles in the
    same payload with the new one null; keying the fallback on presence
    alone would let that null new key permanently shadow a perfectly
    usable old one.
    """
    new_value = raw.get(new_key)
    if new_value not in (None, ""):
        return _parse_dollars_to_cents(new_value)
    return _safe_int(raw.get(old_key))


def _price_cents(raw: dict) -> int | None:
    """yes_price, in integer cents.

    1. last_price when present and > 0 (a real trade happened).
    2. else the bid/ask midpoint when at least one side is non-zero (a live quote exists).
    3. else None -- an untraded market with no two-sided quote shows no price rather than a
       confident-looking midpoint of a 0/1.00 spread nobody would trade at.
    """
    last = _price_field_cents(raw, "last_price_dollars", "last_price")
    if last is not None and last > 0:
        return last

    bid = _price_field_cents(raw, "yes_bid_dollars", "yes_bid")
    ask = _price_field_cents(raw, "yes_ask_dollars", "yes_ask")
    if bid or ask:
        return _midpoint(bid, ask)

    return None


def _volume(raw: dict) -> int | None:
    """Read volume, preferring the fixed-point volume_fp the live API sends.

    volume_fp is a fixed-point string ('2400000.00' -> 2400000). The old
    `volume` field (used by the pre-existing fixtures/tests) is already an
    int, so it is coerced directly. Falls back to `volume` whenever
    `volume_fp` isn't usable -- absent, None, or '' -- not merely when
    it's absent (see `_price_field_cents` for why).
    """
    fp_value = raw.get("volume_fp")
    if fp_value not in (None, ""):
        return _parse_fixed_point_to_int(fp_value)
    return _safe_int(raw.get("volume"))


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
        for _page in range(MAX_PAGES):
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
                    yes_price=_price_cents(raw),
                    volume=_volume(raw),
                ))
            next_cursor = payload.get("cursor") or ""
            if not next_cursor or next_cursor == cursor:
                # Either there is no more data, or Kalshi handed back the same
                # cursor we just sent -- a sticky/repeated cursor previously
                # spun `fetch_all_markets` forever at ~95% CPU (see issue #43).
                return markets
            cursor = next_cursor

        logger.warning(
            "fetch_all_markets hit MAX_PAGES=%d without exhausting pagination; "
            "returning %d markets collected so far", MAX_PAGES, len(markets),
        )
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
