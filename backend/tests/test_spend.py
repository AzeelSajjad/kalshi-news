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
