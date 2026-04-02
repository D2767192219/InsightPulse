# ─────────────────────────────────────────────────────────────────────────────
# agents/llms/base.py
#
# 统一的 OpenAI 兼容 LLM 客户端，支持：
#   - Doubao 1.8（豆包火山引擎）
#   - DeepSeek（api.deepseek.com）
#   - Kimi/Moonshot（api.moonshot.cn）
#   - AIHubMix / Gemini（aihubmix.com）
#   - 通义千问 DashScope（dashscope.aliyuncs.com）
#   - SiliconFlow（cloud.siliconflow.com）
#
# 参考 BettaFish 的 LLMClient 实现，增加指数退避重试机制。
# ─────────────────────────────────────────────────────────────────────────────

import os
import time
import logging
from functools import wraps
from typing import Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


LLM_RETRY_CONFIG = {
    "max_attempts": 6,
    "initial_delay": 30,
    "max_delay": 300,
    "exponential_base": 2,
}


def with_retry(config: dict = None):
    """
    指数退避重试装饰器。

    失败后延迟：30s → 60s → 120s → 240s → 300s → 300s（上限）
    每次 attempt 都重新抛出异常，供上层捕获。
    """
    if config is None:
        config = LLM_RETRY_CONFIG

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = config["initial_delay"]
            for attempt in range(config["max_attempts"]):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == config["max_attempts"] - 1:
                        logger.error(
                            f"[LLMClient] 最终失败 after {attempt + 1} attempts: {e}"
                        )
                        raise
                    logger.warning(
                        f"[LLMClient] Attempt {attempt + 1}/{config['max_attempts']} "
                        f"failed: {e}, retrying in {delay}s..."
                    )
                    time.sleep(delay)
                    delay = min(
                        delay * config["exponential_base"],
                        config["max_delay"],
                    )
        return wrapper
    return decorator


@dataclass
class LLMConfig:
    """单个 LLM 实例的配置"""
    api_key: str
    model: str
    base_url: str
    timeout: int = 180
    max_tokens: int = 4096
    temperature: float = 0.7

    @classmethod
    def from_env(
        cls,
        model_env: str,
        base_url_env: str,
        max_tokens_env: str | None = None,
        temperature_env: str | None = None,
        fallback_model: str = "doubao-seed-2-0-lite-260215",
    ) -> "LLMConfig":
        """从环境变量构建配置"""
        return cls(
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=os.environ.get(model_env, fallback_model),
            base_url=os.environ.get(base_url_env, "https://ark.cn-beijing.volces.com/api/v3"),
            max_tokens=int(os.environ.get(max_tokens_env, "4096")) if max_tokens_env else 4096,
            temperature=float(os.environ.get(temperature_env, "0.7")) if temperature_env else 0.7,
        )


class LLMClient:
    """
    统一 OpenAI 兼容 LLM 客户端。

    支持任意 OpenAI API 兼容服务端点：
    - Doubao:    https://ark.cn-beijing.volces.com/api/v3
    - DeepSeek:  https://api.deepseek.com/v1
    - Kimi:      https://api.moonshot.cn/v1
    - Gemini:    https://aihubmix.com/v1
    - Qwen:      https://dashscope.aliyuncs.com/compatible-mode/v1
    - Silicon:   https://api.siliconflow.cn/v1
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "doubao-seed-2-0-lite-260215",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        timeout: int = 180,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

        if not self.api_key:
            logger.warning("[LLMClient] API key not found in env LLM_API_KEY")

        self._client = None

    @property
    def client(self):
        """延迟初始化 OpenAI 客户端"""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        return self._client

    @with_retry(LLM_RETRY_CONFIG)
    def invoke(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
        **kwargs,
    ) -> str:
        """
        同步调用 LLM，返回文本内容。

        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": "..."}]
            max_tokens: 覆盖默认 max_tokens
            temperature: 覆盖默认 temperature
            json_mode: 是否启用 JSON 模式（response_format）
        """
        from datetime import datetime, timezone

        # 注入当前时间到首条 system 消息
        enriched_messages = self._inject_time_context(messages)

        request_kwargs = {
            "model": self.model,
            "messages": enriched_messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }

        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}

        request_kwargs.update(kwargs)

        response = self.client.chat.completions.create(**request_kwargs)
        content = response.choices[0].message.content
        return content.strip() if content else ""

    @with_retry(LLM_RETRY_CONFIG)
    async def ainvoke(
        self,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool = False,
        **kwargs,
    ) -> str:
        """
        异步调用 LLM，返回文本内容。

        内部使用 httpx 的异步 client 实现。
        """
        import httpx
        from datetime import datetime, timezone

        enriched_messages = self._inject_time_context(messages)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in enriched_messages],
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as http_client:
            response = await http_client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        return content.strip() if content else ""

    def _inject_time_context(
        self,
        messages: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """向 system 消息注入当前时间上下文"""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        time_context = f"\n[当前时间: {now} UTC]\n"

        if not messages:
            return [{"role": "system", "content": time_context}]

        enriched = list(messages)
        if enriched[0]["role"] == "system":
            enriched[0] = {
                "role": "system",
                "content": time_context + enriched[0]["content"],
            }
        else:
            enriched.insert(0, {"role": "system", "content": time_context})

        return enriched

    def _extract_json(self, response: str) -> Optional[dict | list]:
        """健壮的 JSON 提取（参考 BettaFish）"""
        import json
        import re

        if not response or not response.strip():
            return None

        text = response.strip()

        # 尝试从 ```json ... ``` 代码块中提取
        for marker in ["```json", "```"]:
            if marker in text:
                parts = text.split(marker, 1)
                if len(parts) > 1:
                    code = parts[1]
                    end = code.rfind("```")
                    text = code[:end] if end != -1 else code
                    break

        text = text.strip()

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 对象
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # 尝试提取 JSON 数组
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None


# ─────────────────────────────────────────────────────────────────────────────
# 工厂函数：按 Agent 类型创建 LLMClient
# ─────────────────────────────────────────────────────────────────────────────

def create_llm_client(
    agent_type: str,
    api_key: str | None = None,
) -> LLMClient:
    """
    根据 Agent 类型创建配置好的 LLMClient。

    Args:
        agent_type: hot_topics | deep_summary | trend | report_composer
        api_key: 可选，覆盖默认 key
    """
    configs = {
        "hot_topics": {
            "model": os.environ.get("HOT_TOPICS_MODEL", "doubao-seed-2-0-lite-260215"),
            "base_url": os.environ.get(
                "HOT_TOPICS_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
            ),
            "max_tokens": int(os.environ.get("HOT_TOPICS_MAX_TOKENS", "2048")),
            "temperature": float(os.environ.get("HOT_TOPICS_TEMPERATURE", "0.5")),
        },
        "deep_summary": {
            "model": os.environ.get("DEEP_SUMMARY_MODEL", "doubao-seed-2-0-lite-260215"),
            "base_url": os.environ.get(
                "DEEP_SUMMARY_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
            ),
            "max_tokens": int(os.environ.get("DEEP_SUMMARY_MAX_TOKENS", "4096")),
            "temperature": float(os.environ.get("DEEP_SUMMARY_TEMPERATURE", "0.7")),
        },
        "trend": {
            "model": os.environ.get("TREND_MODEL", "doubao-seed-2-0-lite-260215"),
            "base_url": os.environ.get(
                "TREND_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
            ),
            "max_tokens": int(os.environ.get("TREND_MAX_TOKENS", "4096")),
            "temperature": float(os.environ.get("TREND_TEMPERATURE", "0.7")),
        },
        "report_composer": {
            "model": os.environ.get("REPORT_MODEL", "doubao-seed-2-0-lite-260215"),
            "base_url": os.environ.get(
                "REPORT_BASE_URL",
                "https://ark.cn-beijing.volces.com/api/v3",
            ),
            "max_tokens": int(os.environ.get("REPORT_MAX_TOKENS", "4096")),
            "temperature": float(os.environ.get("REPORT_TEMPERATURE", "0.7")),
        },
    }

    config = configs.get(agent_type, {})
    return LLMClient(
        api_key=api_key or os.environ.get("LLM_API_KEY", ""),
        model=config.get("model", "doubao-seed-2-0-lite-260215"),
        base_url=config.get(
            "base_url",
            "https://ark.cn-beijing.volces.com/api/v3",
        ),
        max_tokens=config.get("max_tokens", 4096),
        temperature=config.get("temperature", 0.7),
    )
