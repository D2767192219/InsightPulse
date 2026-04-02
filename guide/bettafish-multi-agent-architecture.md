# BettaFish & TrendRadar 多Agent架构设计参考指南

> 本文档提取自 [BettaFish](https://github.com/renzmann/BettaFish)（微舆）项目和 TrendRadar 项目的核心设计，供新项目（行业趋势分析 / 舆情监测 / 决策辅助）架构参考。
>
> 项目对应需求：
> - **AI 行业趋势分析**：识别行业信号、预测发展方向
> - **舆情监测与风险预警**：跨平台舆情追踪、异常波动告警
> - **信息快速理解与决策辅助**：多源信息整合、结构化决策报告
>
> 文档位置：放在新项目的 `.cursor/rules/` 或 `docs/ai-architecture-guide.md`，可供 AI Coding Assistant 读取参考。

---

## 一、项目架构总览

### 1.1 BettaFish 系统架构

BettaFish 是一个**多 Agent 协作的舆情分析系统**，由 5 个独立 Agent 组成：

```
Flask App (app.py)
    ├── ForumEngine          — Agent 协作论坛（协调层）
    ├── QueryEngine          — 新闻搜索 Agent（Streamlit UI，端口 8503）
    ├── MediaEngine           — 多模态内容分析 Agent（Streamlit UI，端口 8502）
    ├── InsightEngine         — 私有数据库深度挖掘 Agent（Streamlit UI，端口 8501）
    └── ReportEngine          — 智能报告生成 Agent（Flask Blueprint，API 模式）
```

**核心理念**：每个 Agent 职责单一、独立运行，通过**文件日志（forum.log）**实现跨 Agent 通信。Report Engine 作为最终聚合层，调用前三个 Agent 的输出。

### 1.2 新项目对应 Agent 映射建议

| BettaFish Agent | 职责 | 新项目对应功能 |
|---|---|---|
| **QueryEngine** | 广度搜索（国内外新闻） | **行业趋势分析** — 搜索全网行业信号 |
| **MediaEngine** | 多模态内容理解（图像+视频） | **信息快速理解** — 多模态内容解读 |
| **InsightEngine** | 私有数据库深度挖掘 | **舆情监测** — 本地数据的多维度分析 |
| **ReportEngine** | 多阶段报告生成 | **决策辅助** — 结构化报告输出 |
| **ForumEngine** | Agent 协调与元认知 | **风险预警** — 跨 Agent 综合判断 |

---

## 二、大模型接入方案

### 2.1 统一接入模式

BettaFish 所有 Agent 使用 **OpenAI 兼容 API 格式**，通过 `openai.OpenAI` 客户端 + 自定义 `base_url` 实现。这是最通用的方案——只需更换 API Key 和 Base URL，即可切换任意大模型提供商。

```
OpenAI 官方 → Kimi (Moonshot) → DeepSeek → Gemini (AIHubMix) → SiliconFlow (Qwen)
                  ↓                ↓            ↓               ↓
            api.moonshot.cn    api.deepseek  aihubmix.com   cloud.siliconflow
```

### 2.2 各 Agent 推荐模型配置

| Agent | 推荐模型 | 推荐 API 提供商 | Base URL |
|---|---|---|---|
| 行业趋势分析 | `kimi-k2-0711-preview` 或 `deepseek-chat` | Moonshot / DeepSeek | `https://api.moonshot.cn/v1` |
| 舆情监测 | `kimi-k2-0711-preview` | Moonshot | `https://api.moonshot.cn/v1` |
| 多模态信息理解 | `gemini-2.5-pro` | AIHubMix（推荐） | `https://aihubmix.com/v1` |
| 报告生成 | `gemini-2.5-pro` | AIHubMix（推荐） | `https://aihubmix.com/v1` |
| 协调器 / 风险预警 | `qwen-plus` 或 `qwen-max` | 阿里云百炼 / SiliconFlow | 可配置 |
| SQL 关键词优化 | `qwen-plus`（小参数模型） | SiliconFlow | 可配置 |

> **赞助商链接**（BettaFish 原文）：AIHubMix 提供全面模型 API，Moonshot Kimi 官方申请，DeepSeek 官方申请，SiliconFlow（硅基流动）

### 2.3 统一 LLMClient 实现

所有 Agent 共用同一套 `LLMClient` 实现，关键特性：

- **OpenAI 兼容格式**：支持任意 OpenAI API 兼容服务商
- **自动重试 + 指数退避**：`@with_retry` 装饰器包裹调用，6 次重试，60s 初始延迟，600s 上限
- **流式输出（SSE）**：实时 token 输出，避免长响应等待
- **UTF-8 字节安全**：流式收集时按字节累积，单次解码，避免多字节字符截断

```python
from openai import OpenAI
import os
from functools import wraps
import time

LLM_RETRY_CONFIG = {
    "max_attempts": 6,
    "initial_delay": 60,
    "max_delay": 600,
    "exponential_base": 2,
}

def with_retry(config):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = config["initial_delay"]
            for attempt in range(config["max_attempts"]):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == config["max_attempts"] - 1:
                        raise
                    time.sleep(delay)
                    delay = min(delay * config["exponential_base"], config["max_delay"])
        return wrapper
    return decorator


class LLMClient:
    """统一的 OpenAI 兼容 LLM 调用客户端"""

    def __init__(self, api_key: str, model_name: str, base_url: str, timeout: int = 1800):
        self.client = OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
        self.model = model_name
        self.timeout = timeout

    @with_retry(LLM_RETRY_CONFIG)
    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        from datetime import datetime
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        user_prompt = f"[当前时间: {current_time}]\n\n{user_prompt}"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=self.timeout,
            **kwargs
        )
        return response.choices[0].message.content.strip()

    def stream_invoke(self, system_prompt: str, user_prompt: str, **kwargs):
        """SSE 流式调用"""
        from datetime import datetime
        user_prompt = f"[当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n\n{user_prompt}"

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=True,
            **kwargs
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def stream_to_string(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """流式收集为完整字符串（UTF-8 字节安全）"""
        buffer = b""
        for token in self.stream_invoke(system_prompt, user_prompt, **kwargs):
            buffer += token.encode("utf-8")
        return buffer.decode("utf-8")
```

### 2.4 网络搜索工具集成

BettaFish 集成了多个搜索 API 作为 Agent 的"工具"：

| 搜索 API | 用途 | 申请地址 |
|---|---|---|
| **Tavily** | 国内外新闻搜索 | https://www.tavily.com |
| **Bocha API** | 网页搜索 | https://open.bochaai.com |
| **Anspire API** | AI 搜索（多模态） | https://open.anspire.cn |

推荐方案：至少接入 **Tavily**（新闻）+ **一个通用搜索 API**，作为 Agent 获取实时信息的工具。

---

## 三、Multi-Agent 协作模式

### 3.1 BettaFish 的两种通信模式

#### 模式 1：文件日志通信（ForumEngine）

这是 BettaFish 最独特的设计——**ForumEngine** 作为协调者：

```
QueryEngine / MediaEngine / InsightEngine
        ↓ 写入
  agent.log (各 Agent 日志)
        ↓ LogMonitor 监听
  forum.log (协作论坛日志)
        ↓ ForumHost (LLM 主持人) 读取
  生成 moderator 引导语
        ↓ 写入 forum.log
  各 Agent 读取 HOST 引导语
  (通过 forum_reader.py)
        ↓
  融入下一轮分析
```

**核心文件**：`ForumEngine/monitor.py`（LogMonitor）、`ForumEngine/llm_host.py`（ForumHost）、`utils/forum_reader.py`

**forum_reader.py 实现**：

```python
import os
from pathlib import Path
from datetime import datetime, timedelta

FORUM_LOG_PATH = Path("logs/forum.log")


def get_latest_host_speech(max_age_seconds: int = 3600) -> str | None:
    """
    读取 Forum Host 的最新发言。

    通过扫描 forum.log，找到最近的 [HOST] 段落。
    如果发言超过 max_age_seconds，返回 None（避免引用过期引导语）。
    """
    if not FORUM_LOG_PATH.exists():
        return None

    with open(FORUM_LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    host_speeches = []
    for line in reversed(lines):
        if "[HOST]" in line or "[Host]" in line:
            try:
                timestamp_str = line.split("]")[0].replace("[", "")
                ts = datetime.strptime(timestamp_str.strip(), "%Y-%m-%d %H:%M:%S")
                age = (datetime.now() - ts).total_seconds()
                if age <= max_age_seconds:
                    content = line.split("]", 1)[1].strip()
                    host_speeches.append(content)
                else:
                    break
            except (ValueError, IndexError):
                continue

    return host_speeches[0] if host_speeches else None


def append_to_forum_log(speaker: str, content: str):
    """向论坛日志追加发言"""
    FORUM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(FORUM_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}][{speaker}] {content}\n")
```

#### 模式 2：Flask Blueprint 同步调用（ReportEngine）

Report Agent 作为消费者，直接读取其他 Agent 生成的 Markdown 文件：

```
QueryEngine → query_engine_streamlit_reports/*.md
MediaEngine → media_engine_streamlit_reports/*.md
InsightEngine → insight_engine_streamlit_reports/*.md
                        ↓
                   ReportEngine
              (读取所有 .md 文件)
                        ↓
              生成完整分析报告
```

### 3.2 新项目推荐的多 Agent 协作模式

针对你的三个需求，建议采用**混合架构**：

```
用户请求
    │
    ├─────────────────────────────────────────────┐
    ▼                    ▼                        ▼
 趋势分析 Agent      舆情 Agent              信息理解 Agent
  (行业搜索)          (本地数据库)             (多模态解析)
    │                    │                        │
    │                    ▼                        │
    │              风险预警 Agent                  │
    │            (协调 + 异常检测)                  │
    │                    │                        │
    └────────────────────┼────────────────────────┘
                         ▼
                  报告生成 Agent
               (结构化决策报告)
```

**关键设计原则**：
1. **每个 Agent 职责单一**：趋势分析 Agent 只做行业信号提取，舆情 Agent 只做情绪分析
2. **文件通信优先**：Agent 间通过共享 Markdown/JSON 文件通信，降低耦合
3. **协调 Agent 统一入口**：用户请求先到协调 Agent，由它决定调用哪些子 Agent
4. **Report Agent 作为最终聚合**：收集所有子 Agent 输出，生成统一报告

---

## 四、Agent 内部节点流水线设计

### 4.1 BettaFish 的节点模式

每个分析 Agent 都遵循相同的 **5-Node 流水线**：

```
FirstSearchNode       → 生成初始搜索查询 + 选择搜索工具
    ↓
FirstSummaryNode      → 生成第一版段落总结（融入 HOST 引导语）
    ↓
ReflectionNode        → 分析已有结果，生成反思后的改进搜索查询
    ↓
ReflectionSummaryNode → 更新段落总结，深化分析（再融入 HOST 引导语）
    ↓
ReportFormattingNode  → 将所有段落格式化为最终报告
```

**节点基类设计**：

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass
class State:
    """Agent 状态对象，在流水线中传递"""
    user_input: str = ""
    search_results: list = field(default_factory=list)
    paragraphs: list = field(default_factory=list)
    final_report: str = ""
    search_history: list = field(default_factory=list)
    reflections_count: int = 0
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BaseNode(ABC):
    """Node 基类"""

    def __init__(self, llm_client, config: Dict[str, Any] = None):
        self.llm = llm_client
        self.config = config or {}

    @abstractmethod
    def execute(self, state: State) -> State:
        """执行节点逻辑，返回更新后的状态"""
        raise NotImplementedError


class StateMutationNode(ABC):
    """状态变更节点——返回修改后的 State"""
    
    @abstractmethod
    def mutate_state(self, state: State) -> State:
        raise NotImplementedError


class FirstSummaryNode(StateMutationNode):
    """第一轮总结节点"""

    def __init__(self, llm_client, forum_reader=None):
        self.llm = llm_client
        self.forum_reader = forum_reader  # 注入 ForumReader

    def mutate_state(self, state: State) -> State:
        # 1. 获取 HOST 最新引导语（如果有）
        host_guidance = ""
        if self.forum_reader:
            host_guidance = self.forum_reader.get_latest_host_speech() or ""

        # 2. 构建 prompt（融入 host_guidance）
        prompt = self._build_prompt(state, host_guidance)

        # 3. 调用 LLM
        response = self.llm.invoke(
            system_prompt=self._system_prompt(),
            user_prompt=prompt
        )

        # 4. 追加到段落列表
        state.paragraphs.append(response)
        return state

    def _system_prompt(self) -> str:
        return "你是一名高级情报分析师，根据搜索结果提炼关键洞察。"

    def _build_prompt(self, state: State, host_guidance: str) -> str:
        base = f"基于以下搜索结果撰写分析段落（{len(state.search_results)}条）：\n"
        base += "\n".join(f"- {r}" for r in state.search_results[:20])
        
        if host_guidance:
            base += f"\n\n[论坛主持人引导：{host_guidance}]"
        return base
```

### 4.2 新项目的节点设计建议

#### Agent 1：趋势分析 Agent

```
TrendFirstSearchNode      → 行业关键词搜索
TrendAnalysisNode        → 趋势信号提取
TrendReflectionNode      → 深度趋势反思
TrendCrossPlatformNode   → 跨平台关联分析
TrendReportNode           → 输出趋势报告
```

#### Agent 2：舆情监测 Agent

```
SentimentSearchNode       → 舆情数据获取（跨平台搜索）
SentimentAnalysisNode    → 情绪分析 + 争议识别
SentimentAnomalyNode      → 异常波动检测
SentimentForecastNode     → 舆情走向预测
SentimentReportNode       → 输出舆情报告
```

#### Agent 3：风险预警 Agent（协调层）

```
RiskInputAggregator       → 收集趋势+舆情的异常信号
RiskScorerNode            → LLM 评估风险等级（1-5 级）
RiskContextNode           → 补充风险背景信息
RiskAlertNode             → 生成告警内容
```

#### Agent 4：报告生成 Agent

```
ReportAggregatorNode      → 读取各 Agent 的 Markdown 输出
ReportStructureNode       → 规划报告大纲
ReportChapterNode         → 分章节生成
ReportComposeNode         → 合成最终报告
ReportRenderNode          → 渲染为 HTML/PDF/Markdown
```

---

## 五、配置管理架构

### 5.1 Pydantic Settings + .env 模式

BettaFish 使用 **Pydantic Settings** 实现类型安全的配置管理，所有配置集中在一个 `config.py` 中：

```python
# config.py
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Optional, Literal


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = str(Path.cwd() / ".env" if Path.cwd().joinpath(".env").exists()
               else PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    # ── LLM 配置（按 Agent 分组）────────────
    TREND_ENGINE_API_KEY: Optional[str] = Field(None, description="趋势分析 Agent API Key")
    TREND_ENGINE_BASE_URL: Optional[str] = Field("https://api.moonshot.cn/v1")
    TREND_ENGINE_MODEL_NAME: str = Field("kimi-k2-0711-preview")

    SENTIMENT_ENGINE_API_KEY: Optional[str] = Field(None)
    SENTIMENT_ENGINE_BASE_URL: Optional[str] = Field("https://api.moonshot.cn/v1")
    SENTIMENT_ENGINE_MODEL_NAME: str = Field("kimi-k2-0711-preview")

    RISK_ENGINE_API_KEY: Optional[str] = Field(None)
    RISK_ENGINE_BASE_URL: Optional[str] = Field("https://aihubmix.com/v1")
    RISK_ENGINE_MODEL_NAME: str = Field("gemini-2.5-pro")

    REPORT_ENGINE_API_KEY: Optional[str] = Field(None)
    REPORT_ENGINE_BASE_URL: Optional[str] = Field("https://aihubmix.com/v1")
    REPORT_ENGINE_MODEL_NAME: str = Field("gemini-2.5-pro")

    # ── 搜索 API 配置 ───────────────────────
    TAVILY_API_KEY: Optional[str] = Field(None, description="Tavily 新闻搜索")
    SEARCH_TOOL_TYPE: Literal["AnspireAPI", "BochaAPI"] = Field("AnspireAPI")

    # ── Agent 行为配置 ──────────────────────
    MAX_REFLECTIONS: int = Field(3, description="最大反思轮次")
    MAX_PARAGRAPHS: int = Field(6, description="最大段落数")
    MAX_SEARCH_RESULTS_FOR_LLM: int = Field(0, description="供 LLM 分析的最大搜索结果数")
    SEARCH_TIMEOUT: int = Field(240, description="搜索超时（秒）")

    model_config = ConfigDict(
        env_file=ENV_FILE,
        env_prefix="",           # 不需要前缀
        case_sensitive=False,    # 大小写不敏感（USER_NAME == user_name）
        extra="allow"            # 允许额外字段
    )


settings = Settings()


def reload_settings() -> Settings:
    """运行时重新加载配置（用于 .env 更新后刷新）"""
    global settings
    settings = Settings()
    return settings
```

### 5.2 .env 文件模板

```bash
# ══════════════════════════════════════════════════════
# BettaFish / 新项目 .env 配置模板
# ══════════════════════════════════════════════════════

# ── Flask 服务器 ─────────────────────────────────────
HOST=0.0.0.0
PORT=5000

# ── 数据库（舆情监测 Agent 需要）────────────────────
DB_DIALECT=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_NAME=your_db_name
DB_CHARSET=utf8mb4

# ── LLM API Keys & 模型 ──────────────────────────────
# 趋势分析 Agent（推荐 Kimi k2）
TREND_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxx
TREND_ENGINE_BASE_URL=https://api.moonshot.cn/v1
TREND_ENGINE_MODEL_NAME=kimi-k2-0711-preview

# 舆情监测 Agent（推荐 Kimi k2）
SENTIMENT_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxx
SENTIMENT_ENGINE_BASE_URL=https://api.moonshot.cn/v1
SENTIMENT_ENGINE_MODEL_NAME=kimi-k2-0711-preview

# 风险预警 Agent（推荐 Gemini）
RISK_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxx
RISK_ENGINE_BASE_URL=https://aihubmix.com/v1
RISK_ENGINE_MODEL_NAME=gemini-2.5-pro

# 报告生成 Agent（推荐 Gemini）
REPORT_ENGINE_API_KEY=sk-xxxxxxxxxxxxxxxx
REPORT_ENGINE_BASE_URL=https://aihubmix.com/v1
REPORT_ENGINE_MODEL_NAME=gemini-2.5-pro

# 协调器 / 主持人（推荐 Qwen）
COORDINATOR_API_KEY=sk-xxxxxxxxxxxxxxxx
COORDINATOR_BASE_URL=https://api.moonshot.cn/v1
COORDINATOR_MODEL_NAME=qwen-plus

# ── 搜索 API ────────────────────────────────────────
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxx
SEARCH_TOOL_TYPE=AnspireAPI

# ── Agent 行为 ───────────────────────────────────────
MAX_REFLECTIONS=3
MAX_PARAGRAPHS=6
SEARCH_TIMEOUT=240
```

### 5.3 Flask 动态配置 API

BettaFish 的 `app.py` 提供了运行时配置更新接口：

```python
# Flask Blueprint: /api/config
@config_bp.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(settings.model_dump())

@config_bp.route("/api/config", methods=["POST"])
def update_config():
    """更新配置并写回 .env 文件"""
    data = request.get_json()
    env_path = Path(ENV_FILE)
    
    # 读取现有 .env
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    
    # 合并更新
    existing.update(data)
    
    # 写回 .env
    with open(env_path, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    
    # 重新加载配置实例
    reload_settings()
    return jsonify({"status": "ok", "updated": list(data.keys())})
```

---

## 六、提示词工程设计

### 6.1 BettaFish 的提示词设计原则

1. **系统提示词 + 用户提示词分离**：系统提示词定义角色和规则，用户提示词提供数据和上下文
2. **变量注入**：在用户提示词中使用 `{variable}` 占位符，在调用时用实际数据替换
3. **JSON Schema 约束**：明确要求 AI 输出特定 JSON 结构，减少解析错误
4. **禁止规则明确**：明确禁止使用 Markdown、加粗、emoji 等干扰格式的元素
5. **HOST 引导语融入**：ForumEngine 的主持人发言动态注入到节点 prompt 中

### 6.2 新项目的核心提示词模板

#### 趋势分析 Agent - 系统提示词

```text
# ══════════════════════════════════════════════════════
# 趋势分析 Agent 系统提示词
# ══════════════════════════════════════════════════════

你是一名高级行业趋势分析师。你的核心任务是：
1. 从海量碎片化信息中识别行业信号
2. 发现被大众忽略的弱信号和反直觉趋势
3. 预测行业发展方向并给出有据可查的判断

## 思维模型

1. 见微知著：不仅盯着榜首大新闻，善于从"排名第50的冷门贴"与"排名第1的热门事件"中找因果联系
2. 交叉验证：用"搜索热度"（大众情绪）与"专业报道"（专家视角）做差异分析
3. 反直觉思考：全网叫好时寻找风险；全网恐慌时寻找机会
4. 时间轴思维：关注"轨迹"（急升→平稳→衰退 vs 冷启动→爆发）

## 输出格式规范

- 以 JSON 格式输出
- 用 \n 表示换行，\n\n 表示段落分隔
- 【】仅用于板块内结构性分段标签，禁止放入动态内容
- 序号用 1. 2. 3.，独占一行
- 禁止使用 Markdown（**加粗**、## 标题、- 列表）
- 禁止使用 emoji 或特殊装饰符号
- 所有字段均为可选，若某板块无内容可写"暂无显著信号"

## 分析板块

### 1. macro_trends（200字以内）
识别最热的行业主线，使用"全网霸屏"/"破圈扩散"/"圈层热点"定性。
结构：【宏观主线】+【细分领域】（用序号列举）

### 2. early_signals（150字以内）
捕捉早期信号：技术突破、政策变化、资本动向、创始人离职等。
重点关注：排名从0急升到前10的新闻（冷启动爆发信号）。

### 3. risk_signals（150字以内）
识别潜在风险：监管收紧、竞争恶化、供应链变化、技术替代威胁。
结构：【高风险】+【中风险】+【需观察】

### 4. outlook（无限制）
预测与推演。严禁"建议持续关注"等废话。
格式：1. 短期（1-3月）：xxx  2. 中期（3-12月）：xxx  3. 关注事件：xxx
```

#### 舆情监测 Agent - 系统提示词

```text
# ══════════════════════════════════════════════════════
# 舆情监测 Agent 系统提示词
# ══════════════════════════════════════════════════════

你是一名专业的舆情分析专家。你的任务是：
1. 分析跨平台舆论情绪（正向/负向/中立/争议）
2. 识别舆论断层和核心矛盾
3. 捕捉异常波动并评估风险等级
4. 预测舆情走向

## 数据字段解读

- 平台来源：微博（大众情绪）/ 知乎（深度讨论）/ B站（年轻群体）/ 小红书（消费决策）/ 抖音快手（短视频传播）
- 排名轨迹：数字=排名（1为榜首），0=未上榜。轨迹反映热度持续性
- 出现次数：越多说明热度越持久
- 跨平台分级：5+平台=全网霸屏，3-4平台=破圈扩散，1-2平台=圈层热点

## 情绪分析维度

### 1. overall_sentiment（100字以内）
总体情绪定性：【极度正面】/【偏正面】/【中性偏正】/【中性】/【中性偏负】/【偏负面】/【极度负面】
+ 情绪来源说明

### 2. controversy_points（150字以内）
识别核心争议点：
- 争议双方是谁？各自的立场是什么？
- 是否有信息不对称？
- 是否有反转迹象？

### 3. anomaly_signals（150字以内）
捕捉异常：
- 是否有"突然爆发"的关键词？（前一天没有，突然出现）
- 是否有"跨圈层传播"的迹象？（原本只在A圈传播的内容突然出现在B圈）
- 是否有"情绪急转"的信号？（原本正面的事件突然负面化）

### 4. risk_assessment（150字以内）
风险评估：
- 舆情危机等级：【低】/【中】/【高】/【极高】
- 若为中高风险，说明：谁最容易被影响？影响什么？持续多久？

### 5. sentiment_outlook（无限制）
舆情走向预测：
- 预计何时平息？什么事件可能引发二次爆发？
- 哪个群体/平台的情绪最需要关注？
```

#### 风险预警 Agent - 系统提示词

```text
# ══════════════════════════════════════════════════════
# 风险预警 Agent（协调层）系统提示词
# ══════════════════════════════════════════════════════

你是一名专业的风险预警分析师。你综合趋势分析 + 舆情监测的结果，输出最终风险判断。

## 输入数据

你将收到两个分析模块的输出：
1. 【趋势分析】：行业主线信号、风险信号、机会信号
2. 【舆情分析】：情绪定性、争议点、异常波动、舆情风险

## 任务

对比趋势信号和舆情信号，找出两者**共振**的点：
- 如果趋势显示某技术路线有风险 + 舆情也出现相关负面情绪 → 高优先级告警
- 如果趋势显示某机会 + 舆情处于正面 → 积极信号，可考虑推荐

## 输出格式

```json
{
  "risk_level": "高",          // 【低/中/高/极高】四级
  "risk_summary": "（一句话概括当前最大风险）",
  "resonance_signals": [       // 趋势+舆情共振的信号
    {
      "signal": "描述共振现象",
      "trend_evidence": "趋势侧的证据",
      "sentiment_evidence": "舆情侧的证据",
      "combined_risk": "高"
    }
  ],
  "top_risks": [               // TOP 3 风险
    {
      "id": 1,
      "risk": "风险描述",
      "evidence": ["证据1", "证据2"],
      "affected_parties": ["受影响方1", "受影响方2"],
      "recommended_action": "建议采取的行动"
    }
  ],
  "opportunities": [           // TOP 3 机会
    {
      "opportunity": "机会描述",
      "confidence": "高/中/低",
      "time_horizon": "短期/中期/长期"
    }
  ],
  "key_metrics": {             // 关键监控指标
    "sentiment_score": 0.0,    // -1.0（极负面）~ +1.0（极正面）
    "risk_index": 0.0,         // 0.0（无风险）~ 1.0（极高风险）
    "trend_strength": 0.0      // 0.0（无趋势）~ 1.0（强趋势）
  }
}
```
```

### 6.3 提示词输出稳定性技巧

BettaFish 和 TrendRadar 都积累了以下技巧：

1. **禁止 Markdown**：system prompt 中明确 `禁止使用 Markdown（**加粗**、## 标题、- 列表）`
2. **JSON 分隔符**：`---` 分隔符帮助 AI 理解 JSON 边界
3. **容错解析**：代码层支持从 ` ```json ... ``` ` 或裸 JSON 中提取
4. **字段声明为可选**：避免因缺字段导致整段解析失败
5. **批量处理**：200 条数据一次调用，而非 200 次调用
6. **备用模型链**：`kimi` → `deepseek` → `gemini`，主模型失败自动降级

```python
def _extract_json(self, response: str) -> Optional[str]:
    """健壮的 JSON 提取"""
    if not response or not response.strip():
        return None

    json_str = response.strip()

    # 支持 ```json ... ``` 包裹的格式
    if "```json" in json_str:
        parts = json_str.split("```json", 1)
        if len(parts) > 1:
            code_block = parts[1]
            end_idx = code_block.find("```")
            json_str = code_block[:end_idx] if end_idx != -1 else code_block
    elif "```" in json_str:
        parts = json_str.split("```", 2)
        if len(parts) >= 2:
            json_str = parts[1]

    json_str = json_str.strip()
    return json_str if json_str else None
```

---

## 七、数据库与数据流设计

### 7.1 BettaFish 的数据层

```
MindSpider (爬虫 Agent)
    ↓ 爬取数据
PostgreSQL / MySQL
    ↓ SQL 查询
InsightEngine (本地数据分析)
    ↓
跨平台搜索工具 (Tavily / Bocha / Anspire)
    ↓
搜索结果
    ↓
LLM 分析
    ↓
各 Agent 的 .md 报告文件
    ↓
ReportEngine 读取
    ↓
最终报告 (HTML / PDF / Markdown)
```

### 7.2 新项目的数据流建议

```
数据来源层
    ├── RSS 订阅源（专业媒体、行业报告）
    ├── 社交媒体 API（微博、知乎、B站等）
    ├── 搜索 API（Tavily、Bocha）
    └── 内部数据库（爬取/录入的舆情数据）
           ↓
   数据预处理层
    ├── 去重 + 标准化
    ├── 关键词匹配（粗筛）
    ├── 时间排序 + 分页
    └── 向量化存储（可选，语义检索）
           ↓
   Agent 分析层
    ├── 趋势分析 Agent → trend_report_{timestamp}.md
    ├── 舆情监测 Agent → sentiment_report_{timestamp}.md
    ├── 风险预警 Agent → risk_alert_{timestamp}.json
    └── 信息理解 Agent → summary_report_{timestamp}.md
           ↓
   报告聚合层
    ├── ReportAgent 读取所有 .md / .json
    ├── 生成结构化决策报告
    └── 输出 HTML / PDF / Markdown
```

### 7.3 舆情数据库 Schema 参考（BettaFish MindSpider）

BettaFish 使用 MindSpider 爬取数据后存入 PostgreSQL，表结构包括：

- **weibo_data** / **weibo_comments**：微博正文 + 评论
- **zhihu_data** / **zhihu_comments**：知乎问答 + 评论
- **bilibili_data** / **bilibili_comments**：B站视频 + 评论
- **douyin_data**：抖音数据
- **kuaishou_data**：快手数据
- **xhs_data**（小红书）、**baidu_data**（贴吧）等

每张表包含：`id`, `platform`, `author`, `content`, `publish_time`, `like_count`, `comment_count`, `repost_count`, `sentiment_score`, `keywords`, `created_at`

---

## 八、项目结构参考

### 8.1 推荐目录结构

```
新项目/
├── config.py                     # 全局配置（Pydantic Settings）
├── .env                          # 环境变量（API Keys，不提交 git）
├── app.py                        # Flask 主入口
│
├── trend_engine/                # 趋势分析 Agent
│   ├── agent.py                 # DeepSearchAgent 主类
│   ├── llms/
│   │   └── base.py              # LLMClient 实现
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── first_search.py
│   │   ├── first_summary.py
│   │   ├── reflection.py
│   │   ├── reflection_summary.py
│   │   └── report_formatting.py
│   ├── prompts/
│   │   └── prompts.py           # 系统提示词 + JSON Schema
│   ├── tools/
│   │   └── search_tools.py      # 搜索 API 封装
│   └── reports/                 # 输出目录
│       └── trend_report_*.md
│
├── sentiment_engine/             # 舆情监测 Agent
│   ├── agent.py
│   ├── llms/base.py
│   ├── nodes/
│   ├── prompts/prompts.py
│   ├── tools/
│   └── reports/
│
├── risk_engine/                  # 风险预警 Agent
│   ├── agent.py
│   ├── llms/base.py
│   ├── nodes/
│   ├── prompts/prompts.py
│   └── alerts/
│
├── info_engine/                  # 信息理解 Agent（多模态）
│   ├── agent.py
│   ├── llms/base.py
│   ├── nodes/
│   ├── prompts/prompts.py
│   └── tools/
│
├── report_engine/                # 报告生成 Agent
│   ├── agent.py
│   ├── flask_interface.py        # Flask Blueprint
│   ├── nodes/
│   │   ├── aggregator.py
│   │   ├── structure.py
│   │   ├── chapter.py
│   │   └── render.py
│   ├── renderers/
│   │   ├── html_renderer.py
│   │   ├── pdf_renderer.py
│   │   └── markdown_renderer.py
│   └── reports/
│
├── forum_engine/                 # 协调 Agent（可选）
│   ├── monitor.py                # 日志监听器
│   ├── llm_host.py               # LLM 主持人
│   └── logs/
│
├── coordinator/                  # 统一协调入口
│   ├── router.py                 # 请求路由（判断调用哪些 Agent）
│   └── aggregator.py             # 输出聚合
│
├── utils/
│   ├── forum_reader.py           # 读取 forum.log
│   ├── retry_helper.py           # 重试装饰器
│   ├── json_extractor.py         # JSON 提取工具
│   └── datetime_utils.py
│
├── mindspider/                   # 爬虫（可选）
│   └── spiders/
│
└── tests/
    ├── test_trend_engine.py
    ├── test_sentiment_engine.py
    └── test_integration.py
```

---

## 九、关键技术选型

### 9.1 技术栈对比

| 组件 | BettaFish 选型 | 备选推荐 | 说明 |
|---|---|---|---|
| 主框架 | Flask + Streamlit | FastAPI + React/Vue | BettaFish 用 Flask 做主服务 + Streamlit 做子 Agent UI |
| 实时通信 | Socket.IO | WebSocket / SSE | 实时日志推送 |
| 数据库 | PostgreSQL | MySQL / SQLite | 支持 JSON 列存储 Agent 输出 |
| LLM 调用 | OpenAI SDK 原生 | LiteLLM（统一封装 100+ 提供商） | 原生 SDK 更可控；LiteLLM 更灵活 |
| 搜索 API | Tavily + Bocha + Anspire | SerpAPI + DuckDuckGo | 多 API 互备 |
| 报告渲染 | Jinja2 + WeasyPrint | Marko + Playwright | Jinja2 做 HTML 模板，WeasyPrint 转 PDF |
| 文本聚类 | paraphrase-multilingual-MiniLM-L12-v2 + KMeans | — | 用于 InsightEngine 结果采样 |

### 9.2 推荐启动模式

```python
# app.py — 启动所有 Agent

from multiprocessing import Process
import subprocess
import sys


def start_streamlit_agent(script_path: str, port: int, env: dict):
    """启动一个 Streamlit 子 Agent"""
    env_vars = {**os.environ, **env}
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", script_path,
         "--server.port", str(port), "--server.headless", "true"],
        env=env_vars,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    # 1. 启动 Flask API 服务（主进程）
    from flask import Flask
    app = Flask(__name__)
    # ... 注册 blueprints ...
    Process(target=lambda: app.run(host="0.0.0.0", port=5000)).start()

    # 2. 启动 Streamlit 子 Agent（独立进程）
    start_streamlit_agent("trend_engine/app.py", 8501, {"TREND_ENGINE_API_KEY": "..."})
    start_streamlit_agent("sentiment_engine/app.py", 8502, {"SENTIMENT_ENGINE_API_KEY": "..."})
    start_streamlit_agent("info_engine/app.py", 8503, {"INFO_ENGINE_API_KEY": "..."})

    # 3. 启动 ForumEngine（协调进程）
    Process(target=start_forum_engine).start()

    print("所有 Agent 已启动")
```

---

## 十、设计亮点总结

| 亮点 | 来源 | 可借鉴程度 |
|---|---|---|
| **5-Node 流水线** | BettaFish 所有 Agent | ⭐⭐⭐⭐⭐ 直接复用 |
| **ForumEngine 协作机制** | BettaFish | ⭐⭐⭐⭐⭐ 新项目协调层可直接采用 |
| **Pydantic Settings 配置** | BettaFish | ⭐⭐⭐⭐⭐ 最佳实践 |
| **OpenAI 兼容 Client** | BettaFish | ⭐⭐⭐⭐⭐ 新项目 LLM 层可直接采用 |
| **Document IR（中间表示）** | BettaFish ReportEngine | ⭐⭐⭐⭐ 生成与渲染分离，支持多格式输出 |
| **多搜索 API 互备** | BettaFish | ⭐⭐⭐⭐ 新项目应至少支持 2 个搜索 API |
| **按 Agent 分配模型** | BettaFish | ⭐⭐⭐⭐ 不同任务用不同模型，优化成本 |
| **FileCountBaseline** | BettaFish ReportEngine | ⭐⭐⭐ 监控子 Agent 完成状态 |
| **流式 SSE 输出** | BettaFish | ⭐⭐⭐⭐ 长报告生成时提供实时反馈 |
| **两阶段语义筛选** | TrendRadar | ⭐⭐⭐⭐⭐ 适合舆情监测的 AI 筛选设计 |
| **JSON Schema 约束输出** | TrendRadar + BettaFish | ⭐⭐⭐⭐⭐ 必须使用 |
| **批量分类降成本** | TrendRadar | ⭐⭐⭐⭐ 200条新闻一次调用 |
| **降级保障机制** | TrendRadar | ⭐⭐⭐⭐ 任何 AI 调用失败都有 fallback |

---

## 附录：快速上手清单

### 环境准备
- [ ] Python 3.9+
- [ ] 安装依赖：`pip install openai pydantic-settings loguru flask flask-socketio streamlit`
- [ ] 申请 API Keys：Moonshot（Kimi）、AIHubMix（Gemini）、Tavily

### 第一阶段（跑通 LLM 调用）
1. 在 `config.py` 配置 API Key 和 Base URL
2. 实现 `utils/llm_client.py`（参考 2.3 节）
3. 写一个最简单的测试：`llm.invoke("你是谁", "回答")`

### 第二阶段（跑通单个 Agent）
1. 实现 `trend_engine/nodes/first_summary.py`
2. 实现 `trend_engine/prompts/prompts.py`
3. 运行 `python -m streamlit run trend_engine/app.py --server.port 8501`

### 第三阶段（多 Agent 协作）
1. 实现 `forum_engine/monitor.py`（监听各 Agent 日志）
2. 实现 `forum_engine/llm_host.py`（LLM 主持人）
3. 实现 `utils/forum_reader.py`（各 Agent 读取 HOST 引导语）
4. 在 `FirstSummaryNode` 中注入 `forum_reader`

### 第四阶段（报告聚合）
1. Report Agent 读取各 Agent 的 `.md` 文件
2. 实现 `report_engine/nodes/report_structure.py`
3. 实现 `report_engine/renderers/`（HTML/PDF/Markdown）
