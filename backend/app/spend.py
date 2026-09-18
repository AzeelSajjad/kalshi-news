from datetime import date

from app.config import get_settings
from app.models import LlmSpend


def record_spend(session, usd: float) -> None:
    today = date.today()
    row = session.get(LlmSpend, today)
    if row is None:
        row = LlmSpend(day=today, usd=0)
        session.add(row)
    row.usd = float(row.usd) + usd
    session.commit()


def budget_remaining(session) -> float:
    row = session.get(LlmSpend, date.today())
    spent = float(row.usd) if row else 0.0
    return max(0.0, get_settings().daily_llm_budget_usd - spent)
