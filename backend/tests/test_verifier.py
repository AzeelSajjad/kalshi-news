import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.linker.retrieval import Candidate
from app.linker.verifier import verify_candidates

NOW = datetime.now(UTC)
POST = MagicMock(
    title="Shutdown talks collapse",
    body="Leadership walked out.",
    author_name="Politico",
    published_at=NOW,
)
CANDIDATES = [
    Candidate(
        "GOVSHUT-26OCT",
        "Shutdown before Oct 15?",
        "Resolves YES on a lapse.",
        NOW + timedelta(days=28),
        64,
        2400000,
        0.11,
    ),
    Candidate(
        "NFL-WEEK3",
        "Chiefs win week 3?",
        "Resolves YES if they win.",
        NOW + timedelta(days=4),
        55,
        90000,
        0.49,
    ),
]


def _client(payload: str):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=payload)],
        usage=MagicMock(input_tokens=1200, output_tokens=300),
    )
    return client


def test_returns_only_related_links():
    payload = json.dumps(
        {
            "links": [
                {
                    "ticker": "GOVSHUT-26OCT",
                    "related": True,
                    "direction": "YES",
                    "confidence": 0.86,
                    "rationale": "Walking out removes the last path to a deal.",
                },
                {
                    "ticker": "NFL-WEEK3",
                    "related": False,
                    "direction": "YES",
                    "confidence": 0.02,
                    "rationale": "Unrelated.",
                },
            ]
        }
    )

    links = verify_candidates(POST, CANDIDATES, client=_client(payload))

    assert [link.ticker for link in links] == ["GOVSHUT-26OCT"]
    assert links[0].direction == "YES"
    assert links[0].confidence == 0.86


def test_hallucinated_tickers_are_discarded():
    payload = json.dumps(
        {
            "links": [
                {
                    "ticker": "NOT-A-REAL-TICKER",
                    "related": True,
                    "direction": "YES",
                    "confidence": 0.99,
                    "rationale": "Invented.",
                }
            ]
        }
    )

    assert verify_candidates(POST, CANDIDATES, client=_client(payload)) == []


def test_malformed_output_retries_once_then_returns_empty():
    client = _client("this is not json")

    links = verify_candidates(POST, CANDIDATES, client=client)

    assert links == []
    assert client.messages.create.call_count == 2


def test_no_candidates_means_no_llm_call():
    client = _client("{}")
    assert verify_candidates(POST, [], client=client) == []
    client.messages.create.assert_not_called()
