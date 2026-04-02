# InsightPulse — 多智能体日报模块架构设计

> 文档版本：v1.0
> 日期：2026-04-02
> 设计目标：Fan-Out / Fan-In 并行多智能体架构，基于 LangChain + BettaFish 模式，生成 AI 行业舆情日报
> 参考：`.cursor/rules/bettafish-multi-agent-architecture.md`

---

## 一、模块定位

日报模块是 InsightPulse **智能体层**的核心组成部分，位于爬虫层和数据持久化层之上。

```
[RSS Crawler] → [SQLite Articles] → [多智能体日报模块] → [Daily Report JSON/Markdown]
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                      HotTopics    DeepSummary    Trend
                        Agent        Agent        Agent
                              └───────────┬───────────┘
                                          ▼
                               [Report Composer]
                                          ▼
                                   [Report 存储]
```

---

## 二、整体架构：Fan-Out / Fan-In

### 2.1 核心理念

采用 **Orchestrator 编排 + 3 个分析 Agent 并行 + 1 个报告聚合** 的 Fan-Out / Fan-In 模式：

```
用户请求（生成日报）
       │
       ▼
  [Orchestrator]
       │  读取最近 N 天文章，构建统一上下文
       │  同时下发 3 个 Agent
       │
  ┌────▼────┐   ┌────▼────────┐   ┌────▼─────────┐
  │ HotTopics│   │ DeepSummary │   │    Trend     │
  │  Agent   │   │    Agent    │   │    Agent     │
  │(并行执行) │   │ (并行执行)  │   │ (并行执行)   │
  └────┬────┘   └────┬────────┘   └────┬─────────┘
       │            │                 │
       └────────────┼─────────────────┘
                    │ 收集 3 路输出
                    ▼
           [Report Composer]
                    │
                    ▼
              日报最终输出
        (JSON + Markdown 双格式)
```

### 2.2 为什么这样设计

| 方案 | 优势 | 劣势 |
|------|------|------|
| 单个 Agent 全流程 | 简单、上下文连贯 | 推理链路长，输出不稳定 |
| 3 个 Agent **串行** | 可逐个调试 | 总响应时间 = 3×Agent，延迟高 |
| **3 个 Agent 并行（采用）** | 响应时间 = 最慢的 1 个，整体效率高 | 需要 Orchestrator 聚合结果 |
| BettaFish ForumEngine | 支持多轮交互、HOST 引导 | 过度设计，当前阶段不需要多轮协作 |

**最终选择：并行 Fan-Out / Fan-In**，结合 BettaFish 的 LLMClient 重试机制和节点流水线思想，但去掉 ForumEngine（日报生成不需要多轮讨论）。

---

## 三、技术栈选型

### 3.1 LangChain 集成策略

不引入 LangGraph（StateGraph 过于复杂，适合需要条件分支的任务）。当前使用 LangChain 核心组件：

| 组件 | 用途 | 说明 |
|------|------|------|
| `langchain-core` | 消息模板、输出解析器 | PromptTemplate + PydanticOutputParser |
| `langchain-community` | OpenAI 兼容 Client | ChatOpenAI 适配任意 base_url |
| `langchain-anthropic` | 模型调用 | 如需 Claude |
| `@langchain/langgraph` | 可选，未来扩展 | 多轮交互时引入 |

### 3.2 各 Agent 模型分配

| Agent | 推荐模型 | 原因 |
|-------|---------|------|
| HotTopics Agent | `kimi-k2-0711-preview` 或 `deepseek-chat` | 批量文章评分，速度快 |
| DeepSummary Agent | `gemini-2.5-pro` 或 `qwen-max` | 长文本理解、深度摘要 |
| Trend Agent | `qwen-plus` 或 `deepseek-chat` | 逻辑推理、趋势归纳 |
| Report Composer | `gemini-2.5-pro` 或 `qwen-plus` | 综合写作、结构化输出 |
| Orchestrator | `qwen-turbo` | 轻量任务，成本低 |

---

## 四、各 Agent 详细设计

### 4.1 Orchestrator（编排器）

**职责**：
1. 从 SQLite 读取最近 N 天文章（默认 7 天）
2. 构建统一上下文（文章摘要列表 + 元数据）
3. 并行下发 3 个分析 Agent
4. 收集结果，处理异常
5. 调用 Report Composer 生成最终日报

**核心逻辑**：

```python
# backend/agents/orchestrator.py

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DailyReportContext(BaseModel):
    """统一上下文：所有 Agent 共享的文章数据"""
    date: str
    articles_count: int
    articles: list[dict]        # {id, title, summary, source, published_at, url}
    sources: list[str]          # 来源列表
    language: str               # "zh" | "en" | "mixed"


@dataclass
class AgentResult:
    """单个 Agent 的执行结果"""
    agent_name: str
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


class Orchestrator:
    """
    日报编排器 — Fan-Out / Fan-In 模式

    流程：
    1. build_context()   — 构建统一上下文
    2. fan_out()         — 并行下发 3 个分析 Agent
    3. fan_in()          — 收集结果，异常处理
    4. compose()         — 调用 Report Composer 生成最终日报
    """

    def __init__(
        self,
        hot_topics_agent,      # HotTopicsAgent 实例
        deep_summary_agent,    # DeepSummaryAgent 实例
        trend_agent,           # TrendAgent 实例
        report_composer,       # ReportComposer 实例
    ):
        self.ht_agent = hot_topics_agent
        self.ds_agent = deep_summary_agent
        self.t_agent = trend_agent
        self.composer = report_composer

    async def run(self, days: int = 7, language: str = "mixed") -> dict:
        """
        执行完整日报生成流程

        Returns:
            {
                "report_id": str,
                "date": str,
                "hot_topics": {...},
                "deep_summaries": {...},
                "trend_insights": {...},
                "final_report": {...},
                "duration_seconds": float,
            }
        """
        start = datetime.now(timezone.utc)
        logger.info(f"[Orchestrator] 开始生成日报，days={days}, language={language}")

        # Step 1: 构建上下文
        context = await self.build_context(days, language)
        if context.articles_count == 0:
            return {"error": "No articles found for the specified period"}

        logger.info(f"[Orchestrator] 上下文构建完成，共 {context.articles_count} 篇文章")

        # Step 2: Fan-Out — 并行执行 3 个 Agent
        agent_results = await self.fan_out(context)
        logger.info(f"[Orchestrator] 3 个 Agent 执行完成，耗时 {datetime.now(timezone.utc) - start}s")

        # Step 3: Fan-In — 聚合结果
        aggregated = self.fan_in(agent_results)

        # Step 4: Report Composer — 生成最终日报
        final_report = await self.composer.compose(
            date=context.date,
            hot_topics=aggregated["hot_topics"],
            deep_summaries=aggregated["deep_summaries"],
            trend_insights=aggregated["trend_insights"],
        )

        duration = (datetime.now(timezone.utc) - start).total_seconds()
        logger.info(f"[Orchestrator] 日报生成完成，总耗时 {duration:.2f}s")

        return {
            "report_id": f"report_{context.date}",
            "date": context.date,
            "hot_topics": aggregated["hot_topics"],
            "deep_summaries": aggregated["deep_summaries"],
            "trend_insights": aggregated["trend_insights"],
            "final_report": final_report,
            "articles_count": context.articles_count,
            "duration_seconds": duration,
        }

    async def fan_out(self, context: DailyReportContext) -> list[AgentResult]:
        """
        并行下发 3 个分析 Agent
        使用 asyncio.gather 实现真正的并行执行
        """
        tasks = [
            self._run_agent_safe(self.ht_agent, context, "HotTopics"),
            self._run_agent_safe(self.ds_agent, context, "DeepSummary"),
            self._run_agent_safe(self.t_agent, context, "Trend"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=False)
        return results

    async def _run_agent_safe(
        self,
        agent,
        context: DailyReportContext,
        agent_name: str,
    ) -> AgentResult:
        """安全执行单个 Agent，捕获异常"""
        from datetime import datetime as dt
        start = dt.now(timezone.utc)
        try:
            data = await agent.analyze(context)
            duration = (dt.now(timezone.utc) - start).total_seconds()
            return AgentResult(
                agent_name=agent_name,
                success=True,
                data=data,
                duration_seconds=duration,
            )
        except Exception as e:
            duration = (dt.now(timezone.utc) - start).total_seconds()
            logger.error(f"[Orchestrator] {agent_name} Agent 执行失败: {e}")
            return AgentResult(
                agent_name=agent_name,
                success=False,
                error=str(e),
                duration_seconds=duration,
            )

    def fan_in(self, results: list[AgentResult]) -> dict:
        """
        聚合 3 个 Agent 的输出
        一个 Agent 失败不影响整体，缺失数据用空结构填充
        """
        aggregated = {
            "hot_topics": {},
            "deep_summaries": {},
            "trend_insights": {},
        }
        for result in results:
            if result.success and result.data:
                if result.agent_name == "HotTopics":
                    aggregated["hot_topics"] = result.data
                elif result.agent_name == "DeepSummary":
                    aggregated["deep_summaries"] = result.data
                elif result.agent_name == "Trend":
                    aggregated["trend_insights"] = result.data
            else:
                logger.warning(f"[Fan-In] {result.agent_name} Agent 执行失败，使用空数据: {result.error}")
                # 缺失 Agent 用空结构填充，保证日报仍可生成
                if result.agent_name == "HotTopics":
                    aggregated["hot_topics"] = {"items": [], "error": result.error}
                elif result.agent_name == "DeepSummary":
                    aggregated["deep_summaries"] = {"events": [], "error": result.error}
                elif result.agent_name == "Trend":
                    aggregated["trend_insights"] = {"dimensions": {}, "error": result.error}
        return aggregated

    async def build_context(self, days: int, language: str) -> DailyReportContext:
        """从 SQLite 读取最近 N 天的文章，构建统一上下文"""
        from core.database import get_database
        from datetime import datetime as dt

        conn = get_database()
        since = (dt.now(timezone.utc) - timedelta(days=days)).isoformat()

        query = """
            SELECT id, title, summary, source, source_url, published_at, url,
                   author, tags, language, reading_time_minutes
            FROM articles
            WHERE published_at >= ?
        """
        params = [since]

        if language != "mixed":
            query += " AND language = ?"
            params.append(language)

        query += " ORDER BY published_at DESC"

        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        articles = []
        sources = set()
        for row in rows:
            d = dict(row)
            articles.append({
                "id": d["id"],
                "title": d["title"],
                "summary": d.get("summary") or "",
                "source": d["source"],
                "published_at": d.get("published_at"),
                "url": d["url"],
                "author": d.get("author"),
                "tags": d.get("tags") or [],
                "language": d.get("language"),
                "reading_time_minutes": d.get("reading_time_minutes"),
            })
            sources.add(d["source"])

        return DailyReportContext(
            date=dt.now(timezone.utc).strftime("%Y-%m-%d"),
            articles_count=len(articles),
            articles=articles,
            sources=sorted(list(sources)),
            language=language,
        )
```

---

### 4.2 HotTopics Agent（热点发现）

**职责**：识别今日 AI 领域最热话题，输出排名列表。

**内部节点流水线（参考 BettaFish 5-Node）**：

```
SortNode      → 按热度排序文章（简单规则：时间 + 来源权重）
     ↓
ScoreNode     → LLM 批量打分（文章 vs 话题重要性）
     ↓
DedupeNode    → 合并相似话题（LLM 判断近似）
     ↓
RankNode      → 输出最终 Top 10 热点
```

**LangChain 实现**：

```python
# backend/agents/hot_topics/agent.py

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import Optional


class HotTopicItem(BaseModel):
    rank: int = Field(description="热点排名，1=最热")
    topic: str = Field(description="话题名称（一句话，30字以内）")
    summary: str = Field(description="话题摘要（100字以内）")
    key_article_title: str = Field(description="代表性文章标题")
    key_article_url: str = Field(description="代表性文章链接")
    source: str = Field(description="主要来源")
    hot_score: float = Field(description="热度分数 0-100")
    direction: str = Field(description="趋势方向：rising / stable / declining")
    trajectory: list[int] = Field(description="近期排名轨迹")


class HotTopicsOutput(BaseModel):
    date: str = Field(description="日报日期")
    total_analyzed: int = Field(description="分析的文章数量")
    items: list[HotTopicItem] = Field(description="Top 10 热点列表")


class HotTopicsAgent:

    SYSTEM_PROMPT = """你是一名 AI 行业舆情分析师，擅长从海量新闻中识别最热话题。

你的任务是：
1. 阅读所有输入文章，识别出最具影响力的 AI 行业话题
2. 合并相似话题（避免重复）
3. 按热度从高到低排序
4. 输出结构化的热点榜单

评分标准（0-100分）：
- 技术突破性：重大进展 +15分
- 行业影响面：影响广泛 +15分
- 情感强度：争议性/突发性 +10分
- 来源权威性：权威媒体 +10分
- 时效性：当天首发 +10分

输出格式：严格 JSON，不要添加任何解释性文字。
"""

    USER_PROMPT_TEMPLATE = PromptTemplate.from_template("""\
## 今日待分析文章（共 {count} 篇）

{articles}

## 输出要求
分析以上文章，输出 JSON 格式的热点榜单（Top 10）：
""")

    def __init__(self, llm):
        self.llm = llm
        self.parser = JsonOutputParser(pydantic_object=HotTopicsOutput)

    async def analyze(self, context) -> dict:
        """
        分析入口：构建 prompt → 调用 LLM → 解析结果

        参考 BettaFish 的节点流水线：
        1. 上下文构建（SortNode → 前50篇高质量文章筛选）
        2. LLM 批量打分（ScoreNode）
        3. 去重合并（DedupeNode → 合并标题相似的话题）
        4. 排序输出（RankNode）
        """
        # SortNode: 筛选高质量文章（前50篇，优先有 summary 的）
        articles = sorted(
            context.articles,
            key=lambda a: (len(a.get("summary") or "") > 0, a.get("published_at") or ""),
            reverse=True,
        )[:50]

        # 构建文章摘要文本
        articles_text = "\n\n".join(
            f"[{i+1}] 来源：{a['source']} | 时间：{a.get('published_at', '未知')} | "
            f"标题：{a['title']} | 摘要：{a.get('summary', '无')[:300]}"
            for i, a in enumerate(articles)
        )

        # ScoreNode + RankNode: LLM 批量分析
        prompt = self.USER_PROMPT_TEMPLATE.format(
            count=len(articles),
            articles=articles_text,
        )

        response = await self.llm.ainvoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        # 解析结果
        raw_content = response.content if hasattr(response, "content") else str(response)
        parsed = self.parser.parse(raw_content)

        # 补充元数据
        parsed["date"] = context.date
        parsed["total_analyzed"] = context.articles_count

        return parsed
```

---

### 4.3 DeepSummary Agent（深度总结）

**职责**：对重要事件做深度摘要，输出结构化的 3W1H（What/Why/Who/Impact）分析。

**内部节点流水线**：

```
GroupNode     → LLM 将文章按事件分组
     ↓
ExtractNode   → 每个事件簇提取关键事实
     ↓
StructureNode → 输出 3W1H 结构化摘要
     ↓
ImpactNode    → 评估事件影响范围和持续性
```

```python
# backend/agents/deep_summary/agent.py

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import Optional


class EventParticipant(BaseModel):
    name: str = Field(description="参与者名称（人名/公司名/产品名）")
    role: str = Field(description="角色：核心参与者 / 关键发声人 / 受影响方")
    type: str = Field(description="类型：person / company / product / organization")


class EventSummaryItem(BaseModel):
    event_id: str = Field(description="事件唯一ID")
    topic: str = Field(description="事件主题（一句话，25字以内）")
    what: str = Field(description="发生了什么（What）：50字以内")
    who: str = Field(description="涉及谁（Who）：涉及的主要参与者和角色")
    why: str = Field(description="为什么重要（Why）：事件背景和重要性，50字以内")
    impact: str = Field(description="影响是什么（Impact）：事件的影响范围和程度，80字以内")
    sentiment: str = Field(description="情感倾向：positive / negative / neutral / controversial")
    sentiment_score: float = Field(description="情感分数：0.0（极度负面）~ 1.0（极度正面）")
    participants: list[EventParticipant] = Field(description="主要参与者列表")
    key_facts: list[str] = Field(description="关键事实点（3-5条）")
    persistence_score: float = Field(description="持续性分数：0.0=短暂 1.0=持续发酵")
    source_count: int = Field(description="相关文章数量")
    generated_at: str = Field(description="生成时间")


class DeepSummaryOutput(BaseModel):
    date: str
    total_events: int = Field(description="识别出的事件数量")
    events: list[EventSummaryItem] = Field(description="事件摘要列表（按重要性排序）")


class DeepSummaryAgent:

    SYSTEM_PROMPT = """你是一名 AI 行业深度分析师，擅长从碎片化新闻中提炼核心事件。

你的任务是：
1. 将大量新闻按主题聚类，识别出独立的事件
2. 每个事件生成结构化摘要（What/Why/Who/Impact）
3. 评估事件的重要性和持续性

结构化摘要规范：
- What：事件核心事实（客观描述，不添加评价）
- Who：主要参与方及角色（人名/公司/产品）
- Why：事件背景和重要性（为什么值得关注）
- Impact：影响范围和程度（短期/长期影响）

注意：
- 合并同一事件的多个报道，不要重复
- 优先识别有实质内容的事件，忽略标题党
- 输出严格 JSON，不要 Markdown
"""

    USER_PROMPT_TEMPLATE = PromptTemplate.from_template("""\
## 今日待分析文章（共 {count} 篇）

{articles}

## 输出要求
将以上文章聚类为独立事件，每个事件输出 JSON：
""")

    def __init__(self, llm):
        self.llm = llm
        self.parser = JsonOutputParser(pydantic_object=DeepSummaryOutput)

    async def analyze(self, context) -> dict:
        """
        分析入口

        流水线：
        1. GroupNode：筛选有实质内容的文章（前30篇，优先有摘要的）
        2. ExtractNode + StructureNode：LLM 批量生成事件摘要
        3. ImpactNode：评估每个事件的影响持续性
        """
        # GroupNode: 筛选高质量文章
        articles = [
            a for a in context.articles
            if len(a.get("summary") or "") > 50  # 过滤无实质内容的文章
        ][:30]

        articles_text = "\n\n".join(
            f"[{i+1}] 来源：{a['source']} | "
            f"标题：{a['title']} | 摘要：{a.get('summary', '')[:400]}"
            for i, a in enumerate(articles)
        )

        prompt = self.USER_PROMPT_TEMPLATE.format(
            count=len(articles),
            articles=articles_text,
        )

        response = await self.llm.ainvoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        raw_content = response.content if hasattr(response, "content") else str(response)
        parsed = self.parser.parse(raw_content)

        return {
            "date": context.date,
            "total_events": len(parsed.get("events", [])),
            "events": parsed.get("events", []),
        }
```

---

### 4.4 Trend Agent（趋势洞察）

**职责**：从技术/应用/政策/资本四个维度输出趋势洞察。

**内部结构**：4 个 Sub-Node 并行，汇总后输出。

```
Trend Agent
    ├── TechTrendNode   ─▶ 技术突破与路线竞争
    ├── AppTrendNode   ─▶ 商业落地与应用扩散
    ├── PolicyNode      ─▶ 监管动态与政策利好
    └── CapitalNode     ─▶ 融资并购与资本流向
              │
              ▼ 汇总
        TrendInsightOutput
```

```python
# backend/agents/trend/agent.py

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import Optional
import asyncio


class TrendDimension(BaseModel):
    dimension: str = Field(description="维度名称")
    summary: str = Field(description="该维度的趋势总结（150字以内）")
    signals: list[str] = Field(description="具体信号（2-4条）")
    confidence: str = Field(description="判断置信度：high / medium / low")


class TrendInsightOutput(BaseModel):
    date: str
    tech_trend: TrendDimension = Field(description="技术趋势")
    app_trend: TrendDimension = Field(description="应用趋势")
    policy_trend: TrendDimension = Field(description="政策趋势")
    capital_trend: TrendDimension = Field(description="资本趋势")
    cross_dimension_signals: list[str] = Field(
        description="跨维度信号（横跨多个维度的重要趋势）"
    )


TECH_SYSTEM_PROMPTS = {
    "tech": """\
你是一名 AI 技术趋势分析师。你的任务是从今日新闻中识别：
1. 技术突破：大模型、新算法、硬件进展
2. 路线竞争：OpenAI vs Google vs 开源社区的竞争动态
3. 技术风险：某技术路线被证伪或遇到瓶颈

评分标准：只输出有明确技术信号的内容。
""",
    "app": """\
你是一名 AI 应用落地分析师。你的任务是从今日新闻中识别：
1. 商业落地：哪些产品/服务开始实际应用
2. 用户增长：爆款应用的传播路径
3. 商业模式：盈利模式的创新或验证

只关注有实际应用案例的内容，不关注纯概念。
""",
    "policy": """\
你是一名 AI 政策与监管分析师。你的任务是从今日新闻中识别：
1. 监管动态：各国/地区的 AI 监管政策
2. 政策利好：政府支持 AI 发展的政策
3. 标准制定：行业标准、安全规范的新进展

关注政策的具体内容和影响，不关注泛泛的"政策支持"描述。
""",
    "capital": """\
你是一名 AI 资本市场分析师。你的任务是从今日新闻中识别：
1. 融资并购：重大投融资事件
2. 资本流向：资金从哪些领域撤出/进入
3. 估值变化：独角兽估值调整、IPO 动态

只关注有具体金额或明确资金流向的信息。
""",
}

TREND_USER_TEMPLATE = PromptTemplate.from_template("""\
## 今日文章（共 {count} 篇）

{articles}

## 输出要求
按 {dimension} 维度分析，输出 JSON：
""")


class TrendAgent:

    def __init__(self, llm):
        self.llm = llm
        self.parser = JsonOutputParser(pydantic_object=TrendDimension)

    async def analyze(self, context) -> dict:
        """
        4 个 Sub-Node 并行执行，最后汇总

        参考 BettaFish 5-Node 流水线：
        - TechTrendNode / AppTrendNode / PolicyNode / CapitalNode 并行
        - 每个 Node 内部：SearchNode → AnalysisNode → ReportNode
        """
        # 并行执行 4 个维度分析
        tasks = [
            self._analyze_dimension(context, "tech", "技术趋势", TECH_SYSTEM_PROMPTS["tech"]),
            self._analyze_dimension(context, "app", "应用趋势", TECH_SYSTEM_PROMPTS["app"]),
            self._analyze_dimension(context, "policy", "政策趋势", TECH_SYSTEM_PROMPTS["policy"]),
            self._analyze_dimension(context, "capital", "资本趋势", TECH_SYSTEM_PROMPTS["capital"]),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 组装结果
        dimensions = {}
        for dim, result in zip(["tech_trend", "app_trend", "policy_trend", "capital_trend"], results):
            if isinstance(result, Exception):
                dimensions[dim] = {
                    "dimension": dim,
                    "summary": "分析失败",
                    "signals": [],
                    "confidence": "low",
                    "error": str(result),
                }
            else:
                dimensions[dim] = result

        # 跨维度信号（简单策略：引用置信度高的信号）
        cross_signals = self._extract_cross_signals(dimensions)

        return {
            "date": context.date,
            "tech_trend": dimensions.get("tech_trend", {}),
            "app_trend": dimensions.get("app_trend", {}),
            "policy_trend": dimensions.get("policy_trend", {}),
            "capital_trend": dimensions.get("capital_trend", {}),
            "cross_dimension_signals": cross_signals,
        }

    async def _analyze_dimension(
        self,
        context,
        dim_key: str,
        dim_name: str,
        system_prompt: str,
    ) -> dict:
        """分析单个维度"""
        # 为每个维度准备相关文章（关键词筛选，减少 token）
        keywords = {
            "tech": ["模型", "算法", "训练", "参数", "架构", "GPT", "LLM", "benchmark", "论文"],
            "app": ["产品", "发布", "用户", "落地", "应用", "APP", "上线", "商业化"],
            "policy": ["监管", "政策", "法规", "政府", "禁止", "审查", "合规", "安全"],
            "capital": ["融资", "投资", "并购", "估值", "IPO", "上市", "资金", "亿美元"],
        }

        relevant = [
            a for a in context.articles
            if any(kw.lower() in (a.get("title", "") + a.get("summary", "")).lower()
                   for kw in keywords.get(dim_key, []))
        ] or context.articles[:20]  # 无匹配则用前20篇

        articles_text = "\n\n".join(
            f"[{i+1}] 来源：{a['source']} | "
            f"标题：{a['title']} | 摘要：{a.get('summary', '')[:300]}"
            for i, a in enumerate(relevant[:25])
        )

        prompt = TREND_USER_TEMPLATE.format(
            count=len(relevant),
            articles=articles_text,
            dimension=dim_name,
        )

        response = await self.llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ])

        raw_content = response.content if hasattr(response, "content") else str(response)
        parsed = self.parser.parse(raw_content)
        parsed["dimension"] = dim_name
        return parsed

    def _extract_cross_signals(self, dimensions: dict) -> list[str]:
        """提取跨维度信号（置信度高的信号优先）"""
        cross_signals = []
        for dim_data in dimensions.values():
            if isinstance(dim_data, dict) and dim_data.get("confidence") == "high":
                for signal in dim_data.get("signals", []):
                    cross_signals.append(f"[{dim_data.get('dimension', '未知')}] {signal}")
        return cross_signals[:5]  # 最多5条
```

---

### 4.5 Report Composer（报告聚合）

**职责**：汇总 3 个 Agent 的输出，生成结构化日报（JSON + Markdown）。

```python
# backend/agents/report_composer/agent.py

from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone


class ExecutiveSummary(BaseModel):
    headline: str = Field(description="一句话概括今日最重要事件")
    key_count: int = Field(description="核心事件数量")
    overall_sentiment: str = Field(description="整体情感：极度正面 / 偏正面 / 中性 / 偏负面 / 极度负面")
    risk_level: str = Field(description="风险等级：低 / 中 / 高")


class DailyReport(BaseModel):
    report_id: str
    date: str
    generated_at: str
    executive_summary: ExecutiveSummary
    hot_topics: list[dict]     # 直接引用 HotTopics Agent 输出
    deep_summaries: list[dict]  # 直接引用 DeepSummary Agent 输出
    trend_insights: dict        # 直接引用 Trend Agent 输出
    markdown_report: str         # Markdown 格式完整日报


class ReportComposer:

    SYSTEM_PROMPT = """\
你是一名高级情报报告撰写专家。你的任务是：
1. 综合 HotTopics（热点）、DeepSummary（事件深度）、Trend（趋势洞察）三个模块的输出
2. 生成一份专业的 AI 行业舆情日报
3. 输出两部分内容：JSON 结构化数据 + Markdown 全文

日报结构要求：
一、执行摘要（Executive Summary）：一句话概括 + 情感定性 + 风险等级
二、今日热点 Top 5：最热门的 5 个话题
三、重要事件深度总结：2-3 个最重要的事件（What/Why/Who/Impact）
四、趋势洞察：技术 / 应用 / 政策 / 资本 四个维度的核心信号
五、综合研判：明日值得关注的事件

写作风格：
- 中文，专业简洁，有见地
- 核心判断要具体，禁止"建议持续关注"等废话
- 引用话题用「」，引用公司/人名用【】
- 禁止 Markdown 语法（## 标题、**加粗** 等）
- 日报面向 AI 从业者、投资人、行业研究员
"""

    USER_PROMPT_TEMPLATE = PromptTemplate.from_template("""\
## 数据输入

### 热点榜单（HotTopics）
{hot_topics}

### 重要事件（DeepSummary）
{deep_summaries}

### 趋势洞察（Trend）
{trend_insights}

## 输出要求
综合以上三部分数据，生成：
1. JSON 格式的执行摘要
2. Markdown 格式的完整日报全文（300-500字）
""")

    def __init__(self, llm):
        self.llm = llm
        self.parser = JsonOutputParser(pydantic_object=DailyReport)

    async def compose(
        self,
        date: str,
        hot_topics: dict,
        deep_summaries: dict,
        trend_insights: dict,
    ) -> dict:
        """聚合三个 Agent 的输出，生成最终日报"""

        # 构建摘要上下文（控制 token 长度）
        hot_topics_text = self._summarize_hot(hot_topics)
        deep_summaries_text = self._summarize_events(deep_summaries)
        trend_insights_text = self._summarize_trends(trend_insights)

        prompt = self.USER_PROMPT_TEMPLATE.format(
            hot_topics=hot_topics_text,
            deep_summaries=deep_summaries_text,
            trend_insights=trend_insights_text,
        )

        response = await self.llm.ainvoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        raw_content = response.content if hasattr(response, "content") else str(response)
        parsed = self.parser.parse(raw_content)

        return {
            "report_id": f"report_{date}",
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "executive_summary": parsed.get("executive_summary", {}),
            "hot_topics": parsed.get("hot_topics", []),
            "deep_summaries": parsed.get("deep_summaries", []),
            "trend_insights": parsed.get("trend_insights", {}),
            "markdown_report": parsed.get("markdown_report", ""),
        }

    def _summarize_hot(self, hot_topics: dict) -> str:
        items = hot_topics.get("items", [])
        if not items:
            return "暂无热点数据"
        return "\n".join(
            f"{i+1}. 【{item.get('topic', '')}】{item.get('summary', '')}"
            for i, item in enumerate(items[:5])
        )

    def _summarize_events(self, deep_summaries: dict) -> str:
        events = deep_summaries.get("events", [])
        if not events:
            return "暂无事件数据"
        return "\n\n".join(
            f"事件{i+1}：{e.get('topic', '')}\n"
            f"  What：{e.get('what', '')}\n"
            f"  Who：{e.get('who', '')}\n"
            f"  Impact：{e.get('impact', '')}"
            for i, e in enumerate(events[:3])
        )

    def _summarize_trends(self, trend_insights: dict) -> str:
        lines = []
        for key, label in [
            ("tech_trend", "技术趋势"),
            ("app_trend", "应用趋势"),
            ("policy_trend", "政策趋势"),
            ("capital_trend", "资本趋势"),
        ]:
            dim = trend_insights.get(key, {})
            if dim:
                lines.append(
                    f"【{label}】{dim.get('summary', '')}\n"
                    f"  信号：{'；'.join(dim.get('signals', [])[:3])}"
                )
        return "\n\n".join(lines) if lines else "暂无趋势数据"
```

---

## 五、统一 LLM 客户端（参考 BettaFish）

```python
# backend/agents/llms/base.py

from openai import OpenAI
import os
import time
import logging
from functools import wraps
from typing import Optional

logger = logging.getLogger(__name__)

LLM_RETRY_CONFIG = {
    "max_attempts": 6,
    "initial_delay": 30,
    "max_delay": 300,
    "exponential_base": 2,
}


def with_retry(config: dict):
    """指数退避重试装饰器（参考 BettaFish）"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = config["initial_delay"]
            for attempt in range(config["max_attempts"]):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == config["max_attempts"] - 1:
                        logger.error(f"[LLMClient] 最终失败 after {attempt+1} attempts: {e}")
                        raise
                    logger.warning(f"[LLMClient] Attempt {attempt+1} failed: {e}, retrying in {delay}s")
                    time.sleep(delay)
                    delay = min(delay * config["exponential_base"], config["max_delay"])
        return wrapper
    return decorator


class LLMClient:
    """
    统一 OpenAI 兼容 LLM 客户端

    支持任意兼容 API 的提供商：
    - Moonshot (Kimi): api.moonshot.cn
    - DeepSeek: api.deepseek.com
    - AIHubMix (Gemini): aihubmix.com
    - 通义千问 (DashScope): dashscope.aliyuncs.com
    - SiliconFlow: cloud.siliconflow.com
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "kimi-k2-0711-preview",
        base_url: str = "https://api.moonshot.cn/v1",
        timeout: int = 180,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ):
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model_name
        self.base_url = base_url
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    @with_retry(LLM_RETRY_CONFIG)
    async def ainvoke(self, messages: list, **kwargs) -> any:
        """
        异步调用 LLM

        Args:
            messages: [{"role": "system"/"user"/"assistant", "content": "..."}]
        """
        from datetime import datetime, timezone
        # 注入当前时间（参考 BettaFish）
        if messages and messages[0].get("role") == "system":
            time_context = f"\n[当前时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC]\n"
            messages = [type(messages[0])(content=time_context + messages[0].content, **dict(messages[0]))] + list(messages[1:])

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": m["role"], "content": m["content"]} for m in messages],
            max_tokens=kwargs.pop("max_tokens", self.max_tokens),
            temperature=kwargs.pop("temperature", self.temperature),
            **kwargs,
        )
        return response.choices[0].message

    def get_client(self) -> OpenAI:
        """获取底层 OpenAI 客户端（用于 LangChain 集成）"""
        return self.client


# 工厂函数：按 Agent 类型获取配置好的 LLMClient
def create_llm_client(agent_type: str) -> LLMClient:
    """
    agent_type: hot_topics | deep_summary | trend | report_composer | orchestrator
    """
    configs = {
        "hot_topics": {
            "model_name": os.environ.get("HOT_TOPICS_MODEL", "kimi-k2-0711-preview"),
            "base_url": os.environ.get("HOT_TOPICS_BASE_URL", "https://api.moonshot.cn/v1"),
        },
        "deep_summary": {
            "model_name": os.environ.get("DEEP_SUMMARY_MODEL", "gemini-2.5-pro"),
            "base_url": os.environ.get("DEEP_SUMMARY_BASE_URL", "https://aihubmix.com/v1"),
        },
        "trend": {
            "model_name": os.environ.get("TREND_MODEL", "qwen-plus"),
            "base_url": os.environ.get("TREND_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        },
        "report_composer": {
            "model_name": os.environ.get("REPORT_MODEL", "qwen-plus"),
            "base_url": os.environ.get("REPORT_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        },
        "orchestrator": {
            "model_name": os.environ.get("ORCHESTRATOR_MODEL", "qwen-turbo"),
            "base_url": os.environ.get("ORCHESTRATOR_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        },
    }
    config = configs.get(agent_type, {})
    return LLMClient(
        api_key=os.environ.get("LLM_API_KEY"),
        model_name=config.get("model_name", "kimi-k2-0711-preview"),
        base_url=config.get("base_url", "https://api.moonshot.cn/v1"),
    )
```

---

## 六、数据库扩展

在现有 `backend/insightpulse.db`（SQLite）基础上新增两张表：

```sql
-- 日报表
CREATE TABLE IF NOT EXISTS daily_reports (
    id              TEXT PRIMARY KEY,
    date            TEXT NOT NULL UNIQUE,           -- 日期 YYYY-MM-DD
    report_json     TEXT NOT NULL,                  -- JSON 格式完整报告
    markdown_report TEXT,                            -- Markdown 格式报告
    articles_count  INTEGER NOT NULL DEFAULT 0,     -- 分析的文章数量
    hot_topics      TEXT,                           -- 热点数据（JSON）
    deep_summaries  TEXT,                           -- 事件摘要（JSON）
    trend_insights  TEXT,                           -- 趋势洞察（JSON）
    generated_at    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(date);

-- 报告生成任务记录（用于追踪每个 Agent 的执行状态）
CREATE TABLE IF NOT EXISTS report_tasks (
    id              TEXT PRIMARY KEY,
    report_date     TEXT NOT NULL,
    agent_name      TEXT NOT NULL,                   -- hot_topics | deep_summary | trend
    status          TEXT NOT NULL DEFAULT 'pending', -- pending | running | success | failed
    started_at      TEXT,
    completed_at    TEXT,
    duration_seconds REAL,
    error_message   TEXT,
    output_data     TEXT,                            -- Agent 输出（JSON）
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_report_date ON report_tasks(report_date);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON report_tasks(status);
```

---

## 七、API 层设计

### 7.1 新增路由

```
/api/v1/
├── ...
├── /reports
│   ├── GET  /reports                    # 获取日报列表
│   ├── GET  /reports/{date}             # 获取指定日期日报
│   ├── POST /reports/generate            # 手动触发日报生成
│   └── GET  /reports/{date}/status      # 查询生成状态
│
└── /analysis
    ├── POST /analysis/hot-topics         # 单独触发热点分析
    ├── POST /analysis/deep-summary      # 单独触发深度总结
    ├── POST /analysis/trend             # 单独触发趋势分析
    └── GET  /analysis/history           # 查看历史分析记录
```

### 7.2 核心 API 实现

```python
# backend/api/v1/reports.py

from fastapi import APIRouter, Query
from datetime import datetime, timezone
import json
import logging

from core.database import get_database
from core.responses import success_response, error_response
from agents.orchestrator import Orchestrator
from agents.hot_topics.agent import HotTopicsAgent
from agents.deep_summary.agent import DeepSummaryAgent
from agents.trend.agent import TrendAgent
from agents.report_composer.agent import ReportComposer
from agents.llms.base import create_llm_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post("/generate", response_model=dict)
async def generate_daily_report(
    days: int = Query(7, ge=1, le=30, description="分析最近 N 天的文章"),
    language: str = Query("mixed", description="语言：zh / en / mixed"),
):
    """
    手动触发日报生成

    执行流程：
    1. Orchestrator 从 SQLite 读取文章
    2. Fan-Out：并行执行 HotTopics + DeepSummary + Trend Agent
    3. Fan-In：聚合三路结果
    4. Report Composer：生成最终日报
    5. 存储到数据库
    """
    try:
        # 创建 Agent 实例（使用工厂函数获取配置好的 LLMClient）
        orchestrator = Orchestrator(
            hot_topics_agent=HotTopicsAgent(create_llm_client("hot_topics")),
            deep_summary_agent=DeepSummaryAgent(create_llm_client("deep_summary")),
            trend_agent=TrendAgent(create_llm_client("trend")),
            report_composer=ReportComposer(create_llm_client("report_composer")),
        )

        result = await orchestrator.run(days=days, language=language)

        # 存储到数据库
        conn = get_database()
        report_id = result["report_id"]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        await conn.execute("""
            INSERT OR REPLACE INTO daily_reports
            (id, date, report_json, markdown_report, articles_count,
             hot_topics, deep_summaries, trend_insights, generated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            today,
            json.dumps(result, ensure_ascii=False),
            result.get("final_report", {}).get("markdown_report", ""),
            result["articles_count"],
            json.dumps(result["hot_topics"], ensure_ascii=False),
            json.dumps(result["deep_summaries"], ensure_ascii=False),
            json.dumps(result["trend_insights"], ensure_ascii=False),
            result.get("final_report", {}).get("generated_at", ""),
            datetime.now(timezone.utc).isoformat(),
        ))
        await conn.commit()

        return success_response(data={
            "report_id": report_id,
            "date": today,
            "status": "completed",
            "duration_seconds": result["duration_seconds"],
            "articles_analyzed": result["articles_count"],
            "final_report": result.get("final_report", {}),
        })

    except Exception as e:
        logger.error(f"[Reports] 日报生成失败: {e}")
        return error_response(message=f"日报生成失败: {e}", code=500)


@router.get("/{date}", response_model=dict)
async def get_report(date: str):
    """获取指定日期的日报"""
    conn = get_database()
    async with conn.execute(
        "SELECT * FROM daily_reports WHERE date = ?", (date,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        return error_response(message=f"日报不存在: {date}", code=404)

    d = dict(row)
    return success_response(data={
        "report_id": d["id"],
        "date": d["date"],
        "articles_count": d["articles_count"],
        "markdown_report": d["markdown_report"],
        "hot_topics": json.loads(d["hot_topics"] or "{}"),
        "deep_summaries": json.loads(d["deep_summaries"] or "{}"),
        "trend_insights": json.loads(d["trend_insights"] or "{}"),
        "generated_at": d["generated_at"],
    })


@router.get("/", response_model=dict)
async def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=30),
):
    """获取日报列表（分页）"""
    conn = get_database()
    offset = (page - 1) * page_size

    async with conn.execute(
        "SELECT id, date, articles_count, generated_at FROM daily_reports "
        "ORDER BY date DESC LIMIT ? OFFSET ?",
        (page_size, offset)
    ) as cursor:
        rows = await cursor.fetchall()

    async with conn.execute("SELECT COUNT(*) as cnt FROM daily_reports") as cursor:
        total = (await cursor.fetchone())["cnt"]

    items = [
        {"report_id": r["id"], "date": r["date"],
         "articles_count": r["articles_count"], "generated_at": r["generated_at"]}
        for r in rows
    ]

    return success_response(data={
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    })
```

---

## 八、项目目录结构（新增部分）

```
backend/
├── agents/                          # 智能体层（新增）
│   ├── __init__.py
│   ├── llms/
│   │   ├── __init__.py
│   │   └── base.py                 # LLMClient（参考 BettaFish，支持重试）
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── agent.py                # Orchestrator（Fan-Out/Fan-In）
│   │
│   ├── hot_topics/
│   │   ├── __init__.py
│   │   └── agent.py                # HotTopicsAgent
│   │
│   ├── deep_summary/
│   │   ├── __init__.py
│   │   └── agent.py                # DeepSummaryAgent
│   │
│   ├── trend/
│   │   ├── __init__.py
│   │   └── agent.py                # TrendAgent（4 Sub-Nodes 并行）
│   │
│   └── report_composer/
│       ├── __init__.py
│       └── agent.py                # ReportComposer
│
├── api/v1/
│   ├── reports.py                  # 日报 API（新增）
│   └── analysis.py                 # 单独分析 API（新增）
│
└── core/
    ├── config.py                   # 扩展 LLM 配置
    └── database.py                 # 扩展日报表
```

---

## 九、配置扩展

```python
# backend/core/config.py 新增字段

class Settings(BaseSettings):
    # ... 现有字段 ...

    # ── LLM API Keys & 模型配置（按 Agent 分组）────────────
    LLM_API_KEY: Optional[str] = Field(None, description="统一 LLM API Key")

    HOT_TOPICS_MODEL: str = Field("kimi-k2-0711-preview")
    HOT_TOPICS_BASE_URL: str = Field("https://api.moonshot.cn/v1")

    DEEP_SUMMARY_MODEL: str = Field("gemini-2.5-pro")
    DEEP_SUMMARY_BASE_URL: str = Field("https://aihubmix.com/v1")

    TREND_MODEL: str = Field("qwen-plus")
    TREND_BASE_URL: str = Field("https://dashscope.aliyuncs.com/compatible-mode/v1")

    REPORT_MODEL: str = Field("qwen-plus")
    REPORT_BASE_URL: str = Field("https://dashscope.aliyuncs.com/compatible-mode/v1")

    ORCHESTRATOR_MODEL: str = Field("qwen-turbo")
    ORCHESTRATOR_BASE_URL: str = Field("https://dashscope.aliyuncs.com/compatible-mode/v1")

    # ── 日报生成配置 ──────────────────────────────────────
    REPORT_DAYS: int = Field(7, description="分析最近 N 天的文章")
    REPORT_LANGUAGE: str = Field("mixed", description="zh / en / mixed")

    class Config:
        env_file = ".env"
```

---

## 十、与 BettaFish 架构对比

| 维度 | BettaFish | InsightPulse 日报模块 |
|------|-----------|----------------------|
| **通信模式** | ForumEngine（文件日志 + LLM Host） | Fan-Out/Fan-In（asyncio.gather） |
| **节点流水线** | 5-Node：Search→Summary→Reflection→RefSummary→Format | 3 Agent × 内部节点流水线 |
| **LLM 调用** | OpenAI 兼容 Client + 重试装饰器 | 同上（直接复用 BettaFish 实现） |
| **输出格式** | Markdown 报告文件 | JSON + Markdown 双格式，存入 SQLite |
| **协作深度** | 多轮讨论（HOST 引导语循环） | 单次并行 → 一次性聚合 |
| **数据源** | Tavily / Bocha / Anspire 搜索 API | SQLite RSS 文章数据（已有） |
| **框架** | 纯 Python + Streamlit | LangChain + BettaFish LLMClient + FastAPI |

---

## 十一、关键设计原则总结

1. **并行优先**：`asyncio.gather` 确保总响应时间等于最慢 Agent，而非三者之和
2. **容错聚合**：Fan-In 使用 `return_exceptions=True`，单个 Agent 失败不影响整体日报
3. **BettaFish LLMClient 复用**：指数退避重试机制直接移植，保证生产稳定性
4. **LangChain 核心组件**：PromptTemplate + JsonOutputParser 负责结构化输出，不引入复杂状态机
5. **Token 优化**：每个 Agent 只接收必要的文章子集（前 20-50 篇），避免超长上下文
6. **数据库扩展最小化**：只在现有 SQLite 上加 2 张表，不引入 MongoDB 等新存储
