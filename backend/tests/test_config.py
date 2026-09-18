from app.config import get_settings


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai-test")
    monkeypatch.setenv("JOB_TOKEN", "secret")
    get_settings.cache_clear()

    try:
        settings = get_settings()

        assert settings.database_url == "postgresql://u:p@localhost/db"
        assert settings.job_token == "secret"
        assert settings.daily_llm_budget_usd == 1.0
    finally:
        # get_settings is lru_cache'd at module scope; without clearing it here,
        # this test's monkeypatched env values leak into every later test in the
        # session (monkeypatch only restores os.environ, not the cache).
        get_settings.cache_clear()
