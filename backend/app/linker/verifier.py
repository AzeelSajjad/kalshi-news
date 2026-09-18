import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.linker.retrieval import Candidate

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
INPUT_USD_PER_TOKEN = 1.0 / 1_000_000
OUTPUT_USD_PER_TOKEN = 5.0 / 1_000_000

SYSTEM = """You match news items to prediction markets on Kalshi.

For each candidate market, decide whether the news item is genuinely
relevant to how that market resolves. Be strict: a shared topic is not
enough. Reject a market whose close date falls outside the timeframe the
news is about.

When related, state the direction the news pushes the market — YES if it
makes the market more likely to resolve YES, NO otherwise — and give a
single-sentence rationale in plain English, quoting the specific fact
that drives it.

Reply with JSON only, no prose:
{"links": [{"ticker": "...", "related": true, "direction": "YES",
            "confidence": 0.0, "rationale": "..."}]}
Include one entry per candidate."""


class VerifiedLink(BaseModel):
    ticker: str
    related: bool
    direction: str = Field(pattern="^(YES|NO)$")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


@dataclass(frozen=True)
class VerificationResult:
    links: list[VerifiedLink]
    input_tokens: int
    output_tokens: int


class VerificationError(Exception):
    """Raised when the Anthropic call itself fails (outage, timeout, overload).

    Carries the token counts already billed by earlier attempts in this call
    (zero if the very first attempt failed) so the caller can still record
    the spend for a call that was charged but never returned a result.
    """

    def __init__(self, message: str, input_tokens: int, output_tokens: int):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def _prompt(post, candidates: list[Candidate]) -> str:
    lines = [f"NEWS ITEM\nSource: {post.author_name}\nHeadline: {post.title}"]
    if post.body:
        lines.append(f"Excerpt: {post.body[:800]}")
    lines.append("\nCANDIDATE MARKETS")
    for candidate in candidates:
        close = candidate.close_time.date().isoformat() if candidate.close_time else "unknown"
        lines.append(
            f"- ticker: {candidate.ticker}\n  question: {candidate.title}\n"
            f"  rules: {candidate.rules_summary or 'n/a'}\n  closes: {close}"
        )
    return "\n".join(lines)


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * INPUT_USD_PER_TOKEN + output_tokens * OUTPUT_USD_PER_TOKEN


def _extract_json(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return raw
    return raw[start : end + 1]


def _parse_links(payload: dict, valid_tickers: set[str]) -> list[VerifiedLink]:
    links: list[VerifiedLink] = []
    for entry in payload["links"]:
        try:
            link = VerifiedLink(**entry)
        except (ValidationError, TypeError):
            continue
        if link.related and link.ticker in valid_tickers:
            links.append(link)
    return links


def verify_candidates(post, candidates: list[Candidate], client=None) -> VerificationResult:
    if not candidates:
        return VerificationResult([], 0, 0)
    client = client or Anthropic(api_key=get_settings().anthropic_api_key)
    valid_tickers = {candidate.ticker for candidate in candidates}
    prompt = _prompt(post, candidates)

    total_input_tokens = 0
    total_output_tokens = 0
    for attempt in range(2):
        try:
            message = client.messages.create(
                model=MODEL,
                max_tokens=2048,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            # The tokens already accumulated from earlier attempts in this
            # call are real, billed charges -- pass them along so the caller
            # can still record the spend even though this call never
            # returns a VerificationResult.
            raise VerificationError(
                f"anthropic request failed on attempt {attempt + 1}: {exc}",
                total_input_tokens,
                total_output_tokens,
            ) from exc
        total_input_tokens += message.usage.input_tokens
        total_output_tokens += message.usage.output_tokens
        try:
            raw = _extract_json(message.content[0].text.strip())
            links = _parse_links(json.loads(raw), valid_tickers)
        except (
            json.JSONDecodeError,
            TypeError,
            KeyError,
            IndexError,
            AttributeError,
        ) as exc:
            logger.warning("verifier returned unusable output (attempt %s): %s", attempt + 1, exc)
            continue
        return VerificationResult(links, total_input_tokens, total_output_tokens)
    return VerificationResult([], total_input_tokens, total_output_tokens)
