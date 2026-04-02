# InsightPulse — AI 舆情分析日报系统
## 后端架构设计 & 项目计划

> 文档版本：v1.0
> 日期：2026-04-02
> 设计目标：多智能体协同架构，支撑 AI 行业趋势分析 / 舆情监测与风险预警 / 信息快速理解与决策辅助

---

## 一、系统定位与设计目标

### 1.1 核心价值

InsightPulse 是一款面向 AI 从业者、投资人、研究者的**智能舆情日报系统**。用户每天早上能收到一份由 AI 自动生成的、包含热点排名、事件深度解读、趋势研判的个性化分析报告，彻底告别在十几个平台手动刷信息的低效工作方式。

### 1.2 三大应用场景

| 场景 | 用户画像 | 核心诉求 |
|------|---------|---------|
| **AI 行业趋势分析** | 投资人、AI 产品经理、行业研究员 | 快速把握大模型、芯片、应用层的最新动态，不漏关键信号 |
| **舆情监测与风险预警** | 品牌公关、风控、合规部门 | 监测竞争对手、敏感话题，及时预警负面舆情 |
| **信息快速理解与决策辅助** | 企业决策层、高管助理 | 每天 10 分钟了解行业全貌，支持早会决策 |

### 1.3 设计原则

1. **多智能体协同**：每个核心能力封装为独立 Agent，通过消息队列和共享存储协作
2. **可插拔模型层**：统一 AI 接口，支持通义千问及所有 OpenAI 兼容 API
3. **增量流水线**：爬取 → 清洗 → 索引 → 分析 → 报告，全程增量处理，分钟级更新
4. **前端无关 API**：RESTful + WebSocket双通道，前端 Vue3 可任意切换

---

## 二、系统架构总览

```
┌─────────────────────────────────────────────────────────┐
│                      前端 (Vue3)                          │
│   仪表盘 · 热点榜单 · 分析报告 · 舆情预警 · 个人偏好       │
└───────────────────────┬─────────────────────────────────┘
                        │  HTTP / WebSocket
┌───────────────────────▼─────────────────────────────────┐
│                   API 网关层 (FastAPI)                    │
│   /api/v1/news  /api/v1/report  /api/v1/alert  /ws       │
└──────┬─────────────┬──────────────┬─────────────────────┘
       │             │              │
┌──────▼──┐  ┌───────▼───┐  ┌──────▼─────────────────────┐
│  数据层  │  │  调度层   │  │       智能体层 (Agents)       │
│         │  │           │  │                              │
│ MongoDB │  │ APScheduler│  │ ┌──────────────┐           │
│ Redis   │  │ Celery    │  │ │  爬虫智能体   │ ①         │
│         │  │           │  │ └──────┬───────┘           │
│ ┌─────┐ │  │ ┌────────┐│  │ ┌──────▼───────┐           │
│ │原始 │ │  │ │定时任务││  │ │  数据清洗    │ ②         │
│ │数据 │ │  │ │调度器  ││  │ │   智能体     │           │
│ └─────┘ │  │ └────────┘│  │ └──────┬───────┘           │
│ ┌─────┐ │  │ ┌────────┐│  │ ┌──────▼───────┐           │
│ │清洗 │ │  │ │任务队列││  │ │  热点排名    │ ③         │
│ │数据 │ │  │ │(Celery)││  │ │   智能体     │           │
│ └─────┘ │  │ └────────┘│  │ └──────┬───────┘           │
│ ┌─────┐ │  │ ┌────────┐│  │ ┌──────▼───────┐           │
│ │分析 │ │  │ │结果回写││  │ │  事件总结    │ ④         │
│ │报告 │ │  │ │到MongoDB││  │ │   智能体     │           │
│ └─────┘ │  │ └────────┘│  │ └──────┬───────┘           │
│ ┌─────┐ │  │           │  │ ┌──────▼───────┐           │
│ │预警 │ │  │           │  │ │  趋势判断    │ ⑤         │
│ │记录 │ │  │           │  │ │   智能体     │           │
│ └─────┘ │  │           │  │ └──────┬───────┘           │
└─────────┘  └───────────┘  │ ┌──────▼───────┐           │
                            │ │  报告生成    │ ⑥         │
                            │ │   智能体     │           │
                            │ └──────┬───────┘           │
                            │        │                    │
                            │ ┌──────▼───────┐           │
                            │ │  通义千问     │           │
                            │ │  AI Client   │           │
                            │ └──────────────┘           │
                            └─────────────────────────────┘
```

---

## 三、数据流设计

### 3.1 数据生命周期

```
爬虫智能体
   ① 抓取 RSS/Html/微博/知乎热榜
   ↓ 原始文本
数据清洗智能体
   ② HTML清洗 / 去重 / 去广告 / 文本标准化
   ↓ 结构化条目
热点排名智能体
   ③ TF-IDF + LLM打分 → 热度分数 → 排序
   ↓ 排名数据
事件总结智能体
   ④ LLM 聚类 + 摘要 → 主题簇 → 单事件摘要
   ↓ 事件摘要
趋势判断智能体
   ⑤ 时序分析 + 信号检测 → 趋势标签 / 风险预警
   ↓ 趋势数据
报告生成智能体
   ⑥ 汇总 ③+④+⑤ → 结构化日报 JSON/Markdown
   ↓ 最终报告
```

### 3.2 存储设计

| 集合/表 | 说明 | 保留策略 |
|---------|------|---------|
| `raw_articles` | 爬虫原始数据 | 7 天 |
| `cleaned_articles` | 清洗后结构化数据 | 30 天 |
| `hot_rankings` | 每日热点排名快照 | 90 天 |
| `event_summaries` | 事件总结结果 | 180 天 |
| `trend_signals` | 趋势信号数据 | 365 天 |
| `daily_reports` | 日报全文 | 永久 |
| `alert_history` | 预警记录 | 永久 |
| `user_preferences` | 用户偏好配置 | 永久 |

---

## 四、智能体详细设计

### 4.1 智能体 ①：爬虫智能体（Crawler Agent）

#### 职责
- 从多个数据源抓取原始内容
- 支持：RSS Feed、网页正文提取、微博热搜、知乎热榜、Hacker News 等
- 按来源分组抓取，支持增量更新

#### 数据源分类

| 类型 | 来源示例 | 抓取频率 | 数据特点 |
|------|---------|---------|---------|
| RSS 订阅源 | 36kr、机器之心、AI科技媒体 | 每30分钟 | 结构化、摘要型 |
| 社交热榜 | 微博热搜、知乎热榜、抖音热榜 | 每15分钟 | 非结构化、标题党 |
| 技术社区 | Hacker News、Reddit AI区 | 每30分钟 | 长文本、高信息密度 |
| 新闻聚合 | 百度热榜、360热榜 | 每15分钟 | 通用性强、噪声大 |

#### 输入
```yaml
sources:
  - type: "rss"
    url: "https://36kr.huati.com/rss/ai.xml"
    id: "36kr_ai"
  - type: "social"
    platform: "weibo"
    api_endpoint: "/api/hot/search"
```

#### 输出
```python
@dataclass
class RawArticle:
    source: str              # "weibo" | "hackernews" | "rss"
    source_id: str           # 源内唯一ID
    title: str               # 原始标题
    url: str                 # 原文链接
    content: str             # 正文/摘要
    author: Optional[str]    # 作者
    published_at: datetime   # 发布时间
    crawled_at: datetime     # 抓取时间
    metadata: dict           # 来源特有字段（如转发数、点赞数）
```

#### 关键实现

```python
class CrawlerAgent:
    """
    爬虫智能体

    使用策略模式支持多种数据源：
    - RSSCrawler: 处理 RSS/Atom/JSON Feed
    - HtmlCrawler: 使用 Trafilatura 提取网页正文
    - ApiCrawler: 调用平台官方 API
    """

    def __init__(self, sources: List[DataSourceConfig], rate_limiter: RateLimiter):
        self.sources = sources
        self.rate_limiter = rate_limiter
        self.strategies: Dict[str, CrawlerStrategy] = {
            "rss": RSSCrawler(),
            "html": HtmlCrawler(),
            "api": ApiCrawler(),
        }

    async def crawl_source(self, source: DataSourceConfig) -> List[RawArticle]:
        """抓取单个数据源，遵守频率限制"""
        await self.rate_limiter.acquire(source.id)
        strategy = self.strategies.get(source.type)
        articles = await strategy.fetch(source)
        return self._deduplicate(articles, source.id)

    async def run_full_crawl(self) -> List[RawArticle]:
        """全量抓取所有数据源"""
        tasks = [self.crawl_source(s) for s in self.sources if s.enabled]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [item for result in results if not isinstance(result, Exception)
                for item in result]
```

---

### 4.2 智能体 ②：数据清洗智能体（Cleaner Agent）

#### 职责
- HTML 标签与实体解码
- 广告、导航栏、侧边栏内容去除
- 文本标准化（中英文标点、空格、换行统一）
- 语义去重（LLM 判断近似重复）
- 来源一致性归一化

#### 清洗规则

| 步骤 | 规则 | 工具 |
|------|------|------|
| HTML 解析 | 移除标签，解码 `&amp;` `&#x4E2D;` 等 | `html.unescape()` + `trafilatura` |
| 广告过滤 | 识别并移除"相关推荐""广告""下载App"等区块 | 正则 + LLM 小模型 |
| 噪声去除 | 去除"登录后可查看""本文已被加密"等占位符 | 规则库 |
| 文本归一化 | 统一中英文引号、破折号、省略号格式 | `ftfy` 库 |
| 语义去重 | 两篇文章标题/正文相似度 > 0.85 → 合并 | LLM embedding 余弦相似度 |

#### 输出

```python
@dataclass
class CleanedArticle:
    id: str                  # 哈希生成唯一ID
    source: str
    title: str               # 清洗后标题
    content: str             # 清洗后正文（摘要）
    url: str
    author: Optional[str]
    published_at: datetime
    keywords: List[str]      # AI 提取的关键词
    language: str            # "zh" | "en" | "mixed"
    duplicate_of: Optional[str] = None  # 若为重复，指向原始ID
    cleaned_at: datetime
```

---

### 4.3 智能体 ③：热点排名智能体（Ranking Agent）

#### 职责
- 对清洗后的文章计算多维度热度分数
- 支持多平台数据加权融合
- 输出实时热点榜单

#### 热度计算模型

```
热度分数 = w₁×平台权重 + w₂×时间衰减 + w₃×互动信号 + w₄×LLM语义热度
```

| 维度 | 计算方式 | 权重 |
|------|---------|------|
| 平台权重 | 微博=1.0, 知乎=1.0, RSS=0.8, HN=0.9 | w₁=0.25 |
| 时间衰减 | e^(-Δt/6h)，新文章加权 | w₂=0.20 |
| 互动信号 | 转发/评论/点赞归一化 | w₃=0.25 |
| LLM 语义热度 | LLM 判断该话题在当天的重要性（0-1） | w₄=0.30 |

#### LLM 语义热度打分提示词

```text
[system]
你是一个舆情热度评估专家。给定一篇新闻，请评估其在今天 AI 行业中的热度重要性。

评估标准：
1. 技术突破性（重大进展加0.2）
2. 行业影响面（影响多少人/公司）
3. 情感强度（正面/负面/争议性）
4. 稀缺性（是否首次曝光）
5. 时效性（是否有时间敏感窗口）

请给出 0.0-1.0 的热度分数，并简述理由。
```

#### 输出

```python
@dataclass
class HotRankingItem:
    rank: int                # 排名（1=最热）
    article_id: str
    title: str
    url: str
    source: str
    hot_score: float         # 0-100
    score_breakdown: dict    # 各维度得分明细
    trajectory: List[int]    # 近N个时间点的排名轨迹
    first_seen: datetime
    last_seen: datetime
    count: int               # 出现次数（衡量持久度）
```

---

### 4.4 智能体 ④：事件总结智能体（Event Summary Agent）

#### 职责
- 将大量热点条目聚类为若干事件主题
- 每个事件簇生成结构化摘要
- 识别事件参与者（人物、公司、产品）

#### 聚类策略

**两步走**：
1. **粗聚类**：用 embedding 模型（如 text2vec-base-chinese）将所有文章向量化为 768 维向量，用 HDBSCAN 做密度聚类
2. **精调**：对每个粗聚类用 LLM 判断语义一致性，过滤噪声簇

#### 事件摘要提示词

```text
[system]
你是一个事件分析专家。给定一批围绕同一主题的新闻，请生成结构化事件摘要。

输出格式：
{
  "event_id": "uuid",
  "topic": "一句话概括事件主题（20字内）",
  "summary": "200字事件概述，包含背景、经过、现状",
  "sentiment": "positive | negative | neutral | controversial",
  "sentiment_score": 0.0-1.0,  # 负面=0, 正面=1
  "participants": [
    {"name": "DeepSeek", "type": "company", "role": "核心参与者"},
    {"name": "王小川", "type": "person", "role": "关键发声人"}
  ],
  "key_facts": ["关键事实点1", "关键事实点2"],
  "persistence_score": 0.0-1.0,  # 事件是否会持续发酵
  "related_articles": ["标题1", "标题2"]
}
```

#### 输出

```python
@dataclass
class EventSummary:
    event_id: str
    topic: str
    summary: str
    sentiment: str
    sentiment_score: float
    participants: List[Participant]
    key_facts: List[str]
    persistence_score: float
    related_article_ids: List[str]
    generated_at: datetime
```

---

### 4.5 智能体 ⑤：趋势判断智能体（Trend Agent）

#### 职责
- **短期趋势识别**：当天 vs 昨天 vs 上周，关键词频率变化
- **弱信号检测**：低排名但快速上升的内容，暗示趋势萌芽
- **风险预警**：负面情绪聚集、监管动态、竞争威胁自动告警
- **周期规律**：识别每周/每月的周期性规律

#### 趋势信号类型

| 信号类型 | 检测方法 | 预警级别 |
|---------|---------|---------|
| **爆发信号** | 关键词频率日环比 > 200% | 🔴 高 |
| **上升信号** | 排名轨迹持续上升3个时间点 | 🟡 中 |
| **衰退信号** | 热度持续下降超过48h | 🟢 低 |
| **弱信号** | 低排名内容但引用数快速增加 | 🔴 高（预警告警） |
| **风险信号** | 负面情感 + 关键词命中风控词库 | 🔴 高 |
| **监管信号** | 政策/监管关键词出现 | 🔴 高 |

#### 风险预警提示词

```text
[system]
你是一个风险预警专家。分析以下信息，判断是否存在需要立即预警的风险。

风控维度：
1. 品牌风险：是否有针对我方品牌的负面舆情？
2. 竞争风险：竞争对手是否有重大突破？
3. 监管风险：是否有即将出台的政策法规影响业务？
4. 技术风险：是否有技术路线颠覆我方核心产品？
5. 市场风险：是否有宏观经济变化影响行业？

每个维度返回：是/否 + 风险描述 + 建议动作。
```

#### 输出

```python
@dataclass
class TrendSignal:
    signal_id: str
    signal_type: str         # "burst" | "rise" | "decline" | "weak" | "risk" | "regulatory"
    severity: str            # "high" | "medium" | "low"
    topic: str
    description: str
    evidence: List[str]      # 支持该判断的具体证据
    recommendation: str      # 建议动作
    created_at: datetime
    acknowledged: bool = False


@dataclass
class TrendReport:
    """趋势报告"""
    date: date
    emerging_topics: List[str]    # 新兴话题
    declining_topics: List[str]  # 衰退话题
    signals: List[TrendSignal]
    weekly_outlook: str           # 本周展望
    monthly_comparison: dict       # 与上月对比
    generated_at: datetime
```

---

### 4.6 智能体 ⑥：报告生成智能体（Report Agent）

#### 职责
- 汇总Ranking + EventSummary + Trend 三者结果
- 生成结构化日报（JSON + Markdown 双格式）
- 支持用户自定义模板和关键词过滤

#### 日报结构

```json
{
  "report_id": "uuid",
  "date": "2026-04-02",
  "generated_at": "2026-04-02T08:00:00+08:00",
  "language": "中文",

  "executive_summary": {
    "headline": "一句话概括今日最重要事件",
    "key_number": 3,
    "overall_sentiment": "偏正面",
    "risk_level": "中"
  },

  "hot_topics": [
    {
      "rank": 1,
      "topic": "DeepSeek R2 发布",
      "hot_score": 95,
      "key_article": "标题...",
      "trend_direction": "rising"
    }
  ],

  "event_summaries": [
    {
      "event_id": "...",
      "topic": "...",
      "summary": "...",
      "sentiment": "positive",
      "participants": [...]
    }
  ],

  "trend_analysis": {
    "emerging": ["话题A", "话题B"],
    "declining": ["话题C"],
    "signals": [TrendSignal, ...]
  },

  "risk_alerts": [AlertRecord, ...],

  "recommended_actions": [
    {"actor": "投资者", "action": "关注..."},
    {"actor": "产品经理", "action": "跟进..."}
  ],

  "raw_markdown": "..."
}
```

#### 报告生成提示词模板

```text
[system]
你是 InsightPulse 的首席情报分析师。你需要基于今日抓取的全量数据，
生成一份专业的 AI 舆情日报。

## 数据构成
- 热点榜单（Top 20）：{hot_rankings}
- 事件摘要（{event_count} 个事件簇）：{event_summaries}
- 趋势信号（{signal_count} 个）：{trend_signals}
- 预警记录（{alert_count} 个）：{risk_alerts}

## 输出要求
1. 语言：中文，专业简洁
2. 核心趋势不超过200字，要见微知著
3. 每个事件摘要不超过150字
4. 推荐动作要具体，禁止"建议持续关注"等废话
5. 风险预警要明确级别和处置建议
6. 使用「」引用话题名，使用序号列举
7. 禁止使用 Markdown 语法（**加粗**、## 标题等）
8. 严格输出 JSON，不要添加任何解释性文字
```

---

## 五、AI 接口层（通义千问 + LiteLLM）

### 5.1 统一 AI 客户端

```python
# backend/core/ai_client.py

from typing import List, Dict, Optional
import os


class QwenAIClient:
    """
    通义千问 AI 客户端

    基于 LiteLLM 实现，支持以下模型：
    - qwen/qwen-max（主模型，分析/总结）
    - qwen-plus（备选，分析）
    - qwen-turbo（快速任务，分类/标签提取）
    """

    def __init__(self, config: dict):
        self.api_key = config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY")
        self.base_url = config.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self.model = config.get("model", "qwen-plus")
        self.fallback_models = config.get("fallback_models", ["qwen-turbo"])
        self.timeout = config.get("timeout", 120)
        self.max_tokens = config.get("max_tokens", 4096)
        self.temperature = config.get("temperature", 0.7)

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """
        发送对话请求

        Args:
            messages: [{"role": "system"/"user"/"assistant", "content": "..."}]
            model: 覆盖默认模型
            json_mode: 是否启用 JSON 模式（qwen-plus 支持）
        """
        import litellm

        litellm.drop_params = True

        # 通义千问 API 格式
        provider = "openai-compatible"
        model_name = f"{provider}/{model or self.model}"

        kwargs = {
            "model": model_name,
            "messages": messages,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        return litellm.completion(**kwargs)["choices"][0]["message"]["content"]

    def embed(self, texts: List[str], model: str = "text-embedding-v3") -> List[List[float]]:
        """
        获取文本 embedding 向量（用于聚类和相似度计算）

        使用 DashScope Embedding API
        """
        import litellm

        model_name = f"openai-compatible/{model}"
        response = litellm.embedding(
            model=model_name,
            input=texts,
            api_key=self.api_key,
            base_url=self.base_url,
        )
        return [item["embedding"] for item in response["data"]]

    # ── 封装高频任务方法 ──────────────────────────────────

    def classify_relevance(
        self,
        title: str,
        tags: List[Dict[str, str]],
        user_interests: str = "",
    ) -> List[Dict]:
        """AI 筛选：判断新闻标题与用户标签的相关度"""
        prompt = f"""用户偏好：{user_interests}\n\n标签：{tags}\n\n标题：{title}\n\n返回JSON："""
        response = self.chat([{"role": "user", "content": prompt}])
        return self._extract_json(response)

    def extract_keywords(self, text: str, top_k: int = 10) -> List[str]:
        """关键词提取"""
        prompt = f"从以下文本中提取{top_k}个最重要的关键词，返回JSON数组：\n\n{text}"
        response = self.chat([{"role": "user", "content": prompt}])
        return self._extract_json(response) or []

    def summarize_event(self, articles: List[Dict]) -> Dict:
        """事件摘要：汇总一批相关新闻为核心事件"""
        content = "\n".join(f"- {a['title']}: {a.get('content', '')[:200]}" for a in articles)
        prompt = f"分析以下文章，生成事件摘要：\n\n{content}"
        response = self.chat([{"role": "user", "content": prompt}], json_mode=True)
        return self._extract_json(response)

    def judge_hot_score(self, title: str, content: str = "") -> float:
        """热度评分：判断新闻的热度重要性（0.0-1.0）"""
        prompt = f"评估以下新闻的热度重要性（0.0=无热度，1.0=极高热度）：\n标题：{title}\n摘要：{content}"
        response = self.chat([{"role": "user", "content": prompt}])
        try:
            return float(self._extract_json(response) or 0.5)
        except (ValueError, TypeError):
            return 0.5

    def _extract_json(self, response: str) -> Optional[dict]:
        """健壮的 JSON 提取"""
        import json, re

        if not response:
            return None

        # 尝试提取代码块
        patterns = ["```json", "```", ""]
        for pattern in patterns:
            if pattern in response:
                parts = response.split(pattern, 1)
                if len(parts) > 1:
                    code = parts[1]
                    end = code.rfind("```")
                    json_str = code[:end] if end != -1 else code
                    try:
                        return json.loads(json_str.strip())
                    except json.JSONDecodeError:
                        continue

        # 尝试整段解析
        try:
            return json.loads(response.strip())
        except json.JSONDecodeError:
            # 尝试找 JSON 对象
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return None
```

### 5.2 模型选择策略

| 任务类型 | 推荐模型 | 说明 |
|---------|---------|------|
| 事件摘要生成 | `qwen-max` | 质量最高，生成深度分析 |
| 日报综合撰写 | `qwen-plus` | 平衡质量与成本 |
| 标签提取/分类 | `qwen-turbo` | 快速，适合高频轻量任务 |
| 关键词抽取 | `qwen-turbo` | 快速 |
| 语义去重 | `text-embedding-v3` | 向量化后余弦相似度 |
| 聚类 | `text-embedding-v3` | HDBSCAN 聚类 |
| 风险预警分析 | `qwen-max` | 涉及决策，高质量优先 |

---

## 六、API 层设计（FastAPI）

### 6.1 路由结构

```
/api/v1/
├── /news
│   ├── GET  /news              # 获取新闻列表（支持分页、筛选、排序）
│   ├── GET  /news/{id}         # 获取单条新闻详情
│   └── GET  /news/hot          # 获取当前热点榜单
│
├── /reports
│   ├── GET  /reports           # 获取日报列表
│   ├── GET  /reports/{date}    # 获取指定日期日报
│   └── POST /reports/generate   # 手动触发日报生成
│
├── /events
│   ├── GET  /events            # 获取事件列表
│   └── GET  /events/{id}       # 获取事件详情
│
├── /trends
│   ├── GET  /trends            # 获取趋势分析
│   └── GET  /trends/signals    # 获取实时预警信号
│
├── /alerts
│   ├── GET  /alerts            # 获取预警历史
│   ├── POST /alerts/ack/{id}   # 确认预警
│   └── GET  /alerts/settings    # 获取预警设置
│   └── PUT  /alerts/settings   # 更新预警设置
│
├── /preferences
│   ├── GET  /preferences        # 获取用户偏好
│   └── PUT  /preferences         # 更新用户偏好
│
└── /feeds
    ├── GET  /feeds              # 获取 RSS 源列表
    ├── POST /feeds              # 添加 RSS 源
    └── DELETE /feeds/{id}       # 删除 RSS 源

/ws
└── /ws/stream                   # WebSocket 实时推送
                                    # - 实时新闻推送
                                    # - 预警实时通知
                                    # - 报告生成进度
```

### 6.2 核心 API 响应格式

```python
# backend/core/responses.py

from typing import Any, Generic, TypeVar
from pydantic import BaseModel


T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    code: int = 200
    message: str = "success"
    data: T | None = None
    timestamp: str = ""


class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    code: int = 200
    message: str = "success"
    data: List[T] = []
    pagination: dict = {
        "page": 1,
        "page_size": 20,
        "total": 0,
        "total_pages": 0,
    }
```

### 6.3 关键接口示例

#### 获取热点榜单

```
GET /api/v1/news/hot?date=2026-04-02&top=20
```

```json
{
  "code": 200,
  "data": {
    "date": "2026-04-02",
    "hot_topics": [
      {
        "rank": 1,
        "article_id": "abc123",
        "title": "DeepSeek R2 发布：性能超越 GPT-4",
        "url": "https://...",
        "source": "微博",
        "hot_score": 96.5,
        "trend_direction": "rising",
        "trajectory": [5, 3, 1, 1, 1]
      }
    ],
    "generated_at": "2026-04-02T08:00:00+08:00"
  }
}
```

#### 获取日报

```
GET /api/v1/reports/2026-04-02
```

```json
{
  "code": 200,
  "data": {
    "report_id": "...",
    "date": "2026-04-02",
    "executive_summary": {
      "headline": "大模型竞争白热化，DeepSeek R2 引发全行业讨论",
      "key_number": 3,
      "overall_sentiment": "偏正面",
      "risk_level": "低"
    },
    "hot_topics": [...],
    "event_summaries": [...],
    "trend_analysis": {...},
    "risk_alerts": [...],
    "recommended_actions": [...]
  }
}
```

---

## 七、调度系统设计

### 7.1 定时任务编排

使用 **APScheduler** 做进程内调度，**Celery** 做异步任务队列。

| 任务名 | 执行频率 | 调用的智能体 | 说明 |
|--------|---------|------------|------|
| `crawl_all_sources` | 每15分钟 | Crawler Agent | 全量抓取所有数据源 |
| `clean_raw_articles` | 每15分钟 | Cleaner Agent | 清洗新抓取的原始数据 |
| `update_hot_rankings` | 每30分钟 | Ranking Agent | 更新热点排名 |
| `generate_event_summaries` | 每小时 | Event Summary Agent | 生成/更新事件簇 |
| `detect_trend_signals` | 每小时 | Trend Agent | 检测趋势信号和预警 |
| `generate_daily_report` | 每天 08:00 | Report Agent | 生成当日日报 |
| `cleanup_old_data` | 每天 03:00 | — | 清理过期数据 |

### 7.2 任务依赖关系

```
crawl_all_sources (每15分钟)
       ↓
clean_raw_articles (立即触发，等待爬虫完成)
       ↓
update_hot_rankings (立即触发，等待清洗完成)
       ↓
generate_event_summaries (每小时，可独立运行)
       ↓
detect_trend_signals (每小时，依赖排名+事件)
       ↓
generate_daily_report (每天08:00，依赖以上全部)
```

### 7.3 Celery 任务定义

```python
# backend/tasks/__init__.py

from celery import Celery
from backend.core.config import settings

celery_app = Celery(
    "insightpulse",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)


@celery_app.task(bind=True, max_retries=3)
def crawl_task(self, source_ids: List[str] = None):
    """爬虫任务"""
    from backend.agents.crawler import CrawlerAgent
    agent = CrawlerAgent.from_config(settings.CRAWLER_CONFIG)
    return agent.crawl_sources(source_ids)


@celery_app.task(bind=True, max_retries=2)
def clean_task(self, raw_article_ids: List[str]):
    """清洗任务"""
    from backend.agents.cleaner import CleanerAgent
    agent = CleanerAgent(ai_client=settings.ai_client)
    return agent.clean(raw_article_ids)


@celery_app.task(bind=True, max_retries=2)
def ranking_task(self, article_ids: List[str]):
    """排名任务"""
    from backend.agents.ranking import RankingAgent
    agent = RankingAgent(ai_client=settings.ai_client)
    return agent.rank(article_ids)


@celery_app.task(bind=True)
def event_summary_task(self, date: str):
    """事件总结任务"""
    from backend.agents.event_summary import EventSummaryAgent
    agent = EventSummaryAgent(ai_client=settings.ai_client)
    return agent.run(date)


@celery_app.task(bind=True)
def trend_task(self, date: str):
    """趋势判断任务"""
    from backend.agents.trend import TrendAgent
    agent = TrendAgent(ai_client=settings.ai_client)
    return agent.analyze(date)


@celery_app.task(bind=True)
def daily_report_task(self, date: str):
    """日报生成任务"""
    from backend.agents.report import ReportAgent
    agent = ReportAgent(ai_client=settings.ai_client)
    return agent.generate(date)
```

---

## 八、项目目录结构

```
InsightPulse/
├── backend/
│   ├── main.py                      # FastAPI 应用入口
│   ├── requirements.txt
│   ├── pyproject.toml
│   │
│   ├── core/                        # 核心模块
│   │   ├── config.py                # 配置管理（支持 .env）
│   │   ├── database.py              # MongoDB 连接
│   │   ├── cache.py                 # Redis 缓存
│   │   ├── ai_client.py             # 统一 AI 调用（通义千问）
│   │   ├── responses.py             # 统一 API 响应格式
│   │   └── exceptions.py            # 自定义异常
│   │
│   ├── api/                         # API 路由
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── router.py            # v1 路由汇总
│   │   │   ├── news.py              # /news 端点
│   │   │   ├── reports.py           # /reports 端点
│   │   │   ├── events.py            # /events 端点
│   │   │   ├── trends.py            # /trends 端点
│   │   │   ├── alerts.py            # /alerts 端点
│   │   │   ├── preferences.py       # /preferences 端点
│   │   │   └── feeds.py             # /feeds 端点
│   │   └── ws.py                    # WebSocket 端点
│   │
│   ├── agents/                      # 智能体层
│   │   ├── __init__.py
│   │   ├── base.py                  # Agent 基类（公共方法）
│   │   ├── prompts/                 # 提示词模板
│   │   │   ├── ranking_prompt.txt
│   │   │   ├── event_summary_prompt.txt
│   │   │   ├── trend_prompt.txt
│   │   │   └── report_prompt.txt
│   │   ├── crawler/
│   │   │   ├── __init__.py
│   │   │   ├── agent.py             # CrawlerAgent
│   │   │   ├── rss_crawler.py        # RSS 爬虫
│   │   │   ├── html_crawler.py      # 网页正文提取
│   │   │   └── social_crawler.py    # 社交平台爬虫
│   │   ├── cleaner/
│   │   │   ├── __init__.py
│   │   │   └── agent.py             # CleanerAgent
│   │   ├── ranking/
│   │   │   ├── __init__.py
│   │   │   └── agent.py             # RankingAgent
│   │   ├── event_summary/
│   │   │   ├── __init__.py
│   │   │   └── agent.py             # EventSummaryAgent
│   │   ├── trend/
│   │   │   ├── __init__.py
│   │   │   └── agent.py             # TrendAgent
│   │   └── report/
│   │       ├── __init__.py
│   │       └── agent.py            # ReportAgent
│   │
│   ├── models/                      # 数据模型（Pydantic）
│   │   ├── __init__.py
│   │   ├── article.py               # Article 相关模型
│   │   ├── report.py                # Report 相关模型
│   │   ├── event.py                 # Event 相关模型
│   │   ├── trend.py                 # Trend 相关模型
│   │   ├── alert.py                 # Alert 相关模型
│   │   └── user.py                  # User 相关模型
│   │
│   ├── services/                    # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── news_service.py
│   │   ├── report_service.py
│   │   ├── event_service.py
│   │   ├── trend_service.py
│   │   ├── alert_service.py
│   │   └── notification_service.py  # WebSocket 推送
│   │
│   ├── tasks/                      # Celery 异步任务
│   │   ├── __init__.py
│   │   ├── celery_app.py
│   │   ├── crawl_tasks.py
│   │   ├── clean_tasks.py
│   │   ├── ranking_tasks.py
│   │   ├── event_tasks.py
│   │   ├── trend_tasks.py
│   │   └── report_tasks.py
│   │
│   ├── scheduler/                  # APScheduler 定时调度
│   │   ├── __init__.py
│   │   └── jobs.py                 # 定时任务定义
│   │
│   └── utils/                      # 工具函数
│       ├── __init__.py
│       ├── text_utils.py           # 文本处理
│       ├── date_utils.py           # 时间处理
│       └── rate_limiter.py         # 频率限制器
│
├── frontend/
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── api/                    # 前端 API 调用层
│   │   │   ├── axios.ts           # Axios 封装
│   │   │   ├── news.ts
│   │   │   ├── reports.ts
│   │   │   └── websocket.ts
│   │   │
│   │   ├── stores/                 # Pinia 状态管理
│   │   │   ├── news.ts
│   │   │   ├── report.ts
│   │   │   ├── trend.ts
│   │   │   └── user.ts
│   │   │
│   │   ├── views/                  # 页面视图
│   │   │   ├── Dashboard.vue      # 总仪表盘
│   │   │   ├── HotList.vue        # 热点榜单
│   │   │   ├── DailyReport.vue    # 日报阅读
│   │   │   ├── EventDetail.vue    # 事件详情
│   │   │   ├── TrendAnalysis.vue  # 趋势分析
│   │   │   ├── AlertCenter.vue    # 预警中心
│   │   │   └── Settings.vue       # 设置页
│   │   │
│   │   ├── components/             # 公共组件
│   │   │   ├── NewsCard.vue
│   │   │   ├── EventCard.vue
│   │   │   ├── TrendChart.vue
│   │   │   ├── AlertBadge.vue
│   │   │   └── ...
│   │   │
│   │   ├── router/                # Vue Router
│   │   │   └── index.ts
│   │   │
│   │   └── styles/                # 全局样式
│   │       ├── variables.scss
│   │       └── global.scss
│   │
│   ├── package.json
│   └── vite.config.ts
│
├── guide/                          # 项目文档
│   ├── architecture-design.md      # 本文档
│   ├── project-plan.md             # 项目实施计划
│   ├── ai-prompts-guide.md         # AI 提示词设计指南（已存在）
│   └── rss-crawler-guide.md        # RSS 爬取指南（已存在）
│
├── docker-compose.yml
└── README.md
```

---

## 九、技术选型总结

| 层次 | 技术选型 | 理由 |
|------|---------|------|
| **后端框架** | FastAPI | 异步、高性能、自动 OpenAPI 文档、类型安全 |
| **AI 调用** | LiteLLM + 通义千问 DashScope API | 统一接口、支持 100+ 模型、自动重试与降级 |
| **Embedding** | text-embedding-v3（DashScope） | 向量聚类、语义去重 |
| **数据库** | MongoDB | 灵活 schema、JSON 原生存储、时序集合支持 |
| **缓存** | Redis | 热点数据缓存、WebSocket 集群广播、Celery broker |
| **任务队列** | Celery + Redis | 分布式异步任务、可视化监控（Flower） |
| **定时调度** | APScheduler | 轻量、无额外依赖、与 FastAPI 集成好 |
| **爬虫** | feedparser + Trafilatura + httpx | RSS + 网页正文 + 异步请求 |
| **聚类** | HDBSCAN + text-embedding-v3 | 密度聚类、无需预设 K 值 |
| **前端** | Vue 3 + Vite + TypeScript | 组合式 API、Pinia、Vue Router |
| **UI 组件** | Naive UI / Element Plus | Vue 3 兼容、主题定制 |
| **图表** | ECharts | 趋势可视化、热点轨迹图 |
| **容器化** | Docker + Docker Compose | 一键部署 |

---

## 十、配置管理

```yaml
# backend/config.yaml

server:
  host: "0.0.0.0"
  port: 8000
  cors_origins: ["http://localhost:5173"]

mongodb:
  uri: "mongodb://localhost:27017"
  database: "insightpulse"

redis:
  host: "localhost"
  port: 6379
  db: 0

ai:
  api_key: "${DASHSCOPE_API_KEY}"
  model: "qwen-plus"
  embedding_model: "text-embedding-v3"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  timeout: 120
  max_tokens: 4096
  temperature: 0.7
  fallback_models:
    - "qwen-turbo"

crawler:
  request_interval_ms: 2000
  timeout_s: 15
  max_items_per_source: 50
  freshness_filter:
    enabled: true
    max_age_days: 3
  feeds: []

scheduler:
  timezone: "Asia/Shanghai"
  tasks:
    crawl_interval_minutes: 15
    ranking_interval_minutes: 30
    report_hour: 8
    report_minute: 0

celery:
  broker_url: "redis://localhost:6379/1"
  result_backend: "redis://localhost:6379/2"

websocket:
  heartbeat_interval_s: 30
```

---

## 十一、安全与运维

### 11.1 安全措施
- AI API Key 存储在环境变量，不进代码库
- 用户输入通过 Pydantic 严格校验，防止 prompt injection
- RSS 源 URL 白名单校验，禁止内网地址
- 请求频率限制（API + 爬虫双层）

### 11.2 监控指标
- 每个智能体的执行时长和成功率
- AI API 的 token 消耗和费用
- 数据管道延迟（爬取→清洗→分析的时间差）
- 热点榜单更新频率

### 11.3 降级策略
- AI API 不可用时：使用规则引擎兜底（关键词匹配）
- 单个数据源失败时：不影响其他源和整体报告
- 模型降级：qwen-max → qwen-plus → qwen-turbo

---

## 十二、扩展方向（V2）

1. **多语言支持**：英文日报、翻译引擎（已有 AI 翻译设计，见 ai-prompts-guide.md）
2. **个性化推送**：邮件/飞书/微信订阅，支持推送时间偏好
3. **对比报告**：周报/月报自动生成，趋势环比分析
4. **知识图谱**：事件参与者关系可视化
5. **LLM Agents 化**：每个智能体接入 MCP 协议，支持外部工具调用
