from pathlib import Path

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "InsightPulse"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ── Scheduler ──────────────────────────────────────────────────────────
    SCHEDULER_ENABLED: bool = True

    # ── Database ──────────────────────────────────────────────────────────────
    DB_DIR: Path = Path(__file__).parent.parent / "data"
    DB_NAME: str = "insightpulse.db"
    CRAWL_INTERVAL_MINUTES: int = 30

    # ── LLM API ─────────────────────────────────────────────────────────────
    # 主模型提供商（Doubao Seed 或其他 OpenAI 兼容端点）
    LLM_API_KEY: Optional[str] = None
    LLM_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    LLM_MODEL: str = "doubao-seed-2-0-lite-260215"
    LLM_TIMEOUT: int = 180
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7

    # ── LLM 模型配置（按 Agent 分组）────────────────────────────────────────
    # HotTopics Agent — 批量文章打分，速度优先
    HOT_TOPICS_MODEL: str = "doubao-seed-2-0-lite-260215"
    HOT_TOPICS_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    HOT_TOPICS_MAX_TOKENS: int = 2048
    HOT_TOPICS_TEMPERATURE: float = 0.5

    # DeepSummary Agent — 长文本理解，深度摘要
    DEEP_SUMMARY_MODEL: str = "doubao-seed-2-0-lite-260215"
    DEEP_SUMMARY_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DEEP_SUMMARY_MAX_TOKENS: int = 4096
    DEEP_SUMMARY_TEMPERATURE: float = 0.7

    # Trend Agent — 逻辑推理，趋势归纳
    TREND_MODEL: str = "doubao-seed-2-0-lite-260215"
    TREND_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    TREND_MAX_TOKENS: int = 4096
    TREND_TEMPERATURE: float = 0.7

    # Report Composer — 综合写作，结构化输出
    REPORT_MODEL: str = "doubao-seed-2-0-lite-260215"
    REPORT_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    REPORT_MAX_TOKENS: int = 4096
    REPORT_TEMPERATURE: float = 0.7

    # ── 日报生成配置 ────────────────────────────────────────────────────────
    REPORT_DAYS: int = 7
    REPORT_LANGUAGE: str = "mixed"   # zh / en / mixed

    class Config:
        env_file = Path(__file__).parent.parent / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
