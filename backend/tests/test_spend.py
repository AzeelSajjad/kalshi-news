from datetime import UTC, datetime
from unittest.mock import patch

from app.models import LlmSpend
from app.spend import budget_remaining, record_spend


def test_budget_starts_at_the_configured_daily_limit(session):
    assert budget_remaining(session) == 1.0


def test_spend_accumulates_within_the_same_day(session):
    record_spend(session, 0.25)
    record_spend(session, 0.10)
    assert round(budget_remaining(session), 4) == 0.65


def test_budget_never_reports_negative(session):
    record_spend(session, 5.0)
    assert budget_remaining(session) == 0.0


def test_record_spend_keys_by_utc_calendar_day_not_local_day(session):
    fixed_now = datetime(2026, 1, 2, 23, 30, tzinfo=UTC)
    with patch("app.spend.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        record_spend(session, 0.10)

    row = session.get(LlmSpend, fixed_now.date())
    assert row is not None
    assert round(float(row.usd), 4) == 0.10


def test_budget_remaining_reads_the_same_utc_calendar_day(session):
    fixed_now = datetime(2026, 1, 2, 23, 30, tzinfo=UTC)
    with patch("app.spend.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        record_spend(session, 0.40)
        remaining = budget_remaining(session)

    assert round(remaining, 4) == 0.60
