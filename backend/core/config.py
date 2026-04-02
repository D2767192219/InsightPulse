from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "InsightPulse"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    # Scheduler
    SCHEDULER_ENABLED: bool = True
    CRAWL_INTERVAL_MINUTES: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
