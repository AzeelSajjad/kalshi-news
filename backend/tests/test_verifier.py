import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.linker.retrieval import Candidate
from app.linker.verifier import VerificationError, VerificationResult, verify_candidates

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

RELATED_PAYLOAD = json.dumps(
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


def _message(text: str, input_tokens: int = 1200, output_tokens: int = 300):
    return MagicMock(
        content=[MagicMock(text=text)],
        usage=MagicMock(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _client(payload: str, input_tokens: int = 1200, output_tokens: int = 300):
    client = MagicMock()
    client.messages.create.return_value = _message(payload, input_tokens, output_tokens)
    return client


def _client_with_sequence(*messages):
    client = MagicMock()
    client.messages.create.side_effect = list(messages)
    return client


def test_returns_only_related_links():
    result = verify_candidates(POST, CANDIDATES, client=_client(RELATED_PAYLOAD))

    assert [link.ticker for link in result.links] == ["GOVSHUT-26OCT"]
    assert result.links[0].direction == "YES"
    assert result.links[0].confidence == 0.86
    assert result.input_tokens == 1200
    assert result.output_tokens == 300


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

    result = verify_candidates(POST, CANDIDATES, client=_client(payload))

    assert result.links == []


def test_malformed_output_retries_once_then_returns_empty():
    client = _client("this is not json")

    result = verify_candidates(POST, CANDIDATES, client=client)

    assert result.links == []
    assert client.messages.create.call_count == 2
    # Both attempts are real charges: usage accumulates even when parsing fails.
    assert result.input_tokens == 2400
    assert result.output_tokens == 600


def test_no_candidates_means_no_llm_call():
    client = _client("{}")

    result = verify_candidates(POST, [], client=client)

    assert result == VerificationResult([], 0, 0)
    client.messages.create.assert_not_called()


def test_accumulated_tokens_sum_across_both_attempts_after_a_retry():
    client = _client_with_sequence(
        _message("this is not json", input_tokens=700, output_tokens=150),
        _message(RELATED_PAYLOAD, input_tokens=1200, output_tokens=300),
    )

    result = verify_candidates(POST, CANDIDATES, client=client)

    assert [link.ticker for link in result.links] == ["GOVSHUT-26OCT"]
    assert result.input_tokens == 700 + 1200
    assert result.output_tokens == 150 + 300


def test_empty_content_list_returns_empty_result_without_raising():
    client = MagicMock()
    client.messages.create.return_value = MagicMock(
        content=[], usage=MagicMock(input_tokens=500, output_tokens=50)
    )

    result = verify_candidates(POST, CANDIDATES, client=client)

    assert result.links == []
    assert client.messages.create.call_count == 2
    assert result.input_tokens == 1000
    assert result.output_tokens == 100


def test_uppercase_json_fence_is_parsed():
    fenced = f"```JSON\n{RELATED_PAYLOAD}\n```"

    result = verify_candidates(POST, CANDIDATES, client=_client(fenced))

    assert [link.ticker for link in result.links] == ["GOVSHUT-26OCT"]


def test_leading_prose_before_fence_is_parsed():
    prefixed = f"Here are the results:\n```json\n{RELATED_PAYLOAD}\n```"

    result = verify_candidates(POST, CANDIDATES, client=_client(prefixed))

    assert [link.ticker for link in result.links] == ["GOVSHUT-26OCT"]


def test_one_invalid_entry_does_not_discard_the_rest_of_the_batch():
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
                    "related": True,
                    "direction": "N/A",
                    "confidence": 0.1,
                    "rationale": "Not applicable.",
                },
            ]
        }
    )

    result = verify_candidates(POST, CANDIDATES, client=_client(payload))

    assert [link.ticker for link in result.links] == ["GOVSHUT-26OCT"]


def test_provider_error_on_retry_raises_verification_error_with_first_attempts_tokens():
    # Attempt 1 returns malformed output (a real, billed call) and attempt 2
    # -- the retry -- fails at the transport level. The 700/150 tokens from
    # attempt 1 must not be lost: they are wrapped into the raised error so
    # the caller can still record that spend.
    client = MagicMock()
    client.messages.create.side_effect = [
        _message("this is not json", input_tokens=700, output_tokens=150),
        RuntimeError("provider overloaded"),
    ]

    with pytest.raises(VerificationError) as exc_info:
        verify_candidates(POST, CANDIDATES, client=client)

    assert exc_info.value.input_tokens == 700
    assert exc_info.value.output_tokens == 150
    assert "provider overloaded" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert client.messages.create.call_count == 2


def test_non_list_links_value_consumes_the_retry_instead_of_silently_returning_empty():
    """{"links": "no relevant markets"} would otherwise iterate the string
    character by character, reject each one-character "entry" as invalid,
    and return an empty list *normally* -- so the retry is never consumed
    and the post is billed for a call that silently produced nothing.
    _parse_links now raises on a non-list value, routing it into the same
    retry path a malformed-JSON response takes."""
    non_list_payload = json.dumps({"links": "no relevant markets"})
    client = _client_with_sequence(
        _message(non_list_payload, input_tokens=700, output_tokens=150),
        _message(RELATED_PAYLOAD, input_tokens=1200, output_tokens=300),
    )

    result = verify_candidates(POST, CANDIDATES, client=client)

    assert client.messages.create.call_count == 2
    assert [link.ticker for link in result.links] == ["GOVSHUT-26OCT"]
    assert result.input_tokens == 700 + 1200
    assert result.output_tokens == 150 + 300


def test_provider_error_on_first_attempt_raises_verification_error_with_zero_tokens():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("provider overloaded")

    with pytest.raises(VerificationError) as exc_info:
        verify_candidates(POST, CANDIDATES, client=client)

    assert exc_info.value.input_tokens == 0
    assert exc_info.value.output_tokens == 0
    assert client.messages.create.call_count == 1
