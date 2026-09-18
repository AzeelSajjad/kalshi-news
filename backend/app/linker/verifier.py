import json
import logging

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


class _Response(BaseModel):
    links: list[VerifiedLink]


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


def verify_candidates(post, candidates: list[Candidate], client=None) -> list[VerifiedLink]:
    if not candidates:
        return []
    client = client or Anthropic(api_key=get_settings().anthropic_api_key)
    valid_tickers = {candidate.ticker for candidate in candidates}
    prompt = _prompt(post, candidates)

    for attempt in range(2):
        message = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json").strip()
        try:
            parsed = _Response(**json.loads(raw))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning("verifier returned unusable output (attempt %s): %s", attempt + 1, exc)
            continue
        return [link for link in parsed.links if link.related and link.ticker in valid_tickers]
    return []
