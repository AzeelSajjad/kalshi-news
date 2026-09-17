from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    job_token: str = ""
    daily_llm_budget_usd: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
