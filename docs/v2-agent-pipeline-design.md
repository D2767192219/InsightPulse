# InsightPulse V2 — Agent 流水线串行化设计

> 本文档为 [V2 事件预测架构](./v2-event-prediction-architecture.md) 的 Agent 层补充，核心设计决策：
> **四个分析 Agent（HotTopics / DeepSummary / Trend / OpportunityScanner）从并行改为串行流水线，信号层作为各 Agent 的决策依据而非数据传递载体。**

---

## 目录

1. [核心设计决策：为什么串行优于并行](#一核心设计决策为什么串行优于并行)
2. [串行流水线总览](#二串行流水线总览)
3. [Orchestrator 重构：prepass 阶段前置](#三orchestrator-重构prepass-阶段前置)
4. [Agent 1：HotTopics — Top 3-5 热点发现（串行第一步）](#四agent-1hottopics--top-3-5-热点发现串行第一步)
5. [Agent 2：DeepSummary — 重要事件深度总结（串行第二步）](#五agent-2deepsummary--重要事件深度总结串行第二步)
6. [Agent 3：Trend — 趋势研判（串行第三步）](#六agent-3trend--趋势研判串行第三步)
7. [Agent 4：OpportunityScanner — 风险与机会识别（串行第四步）](#七agent-4opportunitionscanner--风险与机会识别串行第四步)
8. [信息流向与上下文继承](#八信息流向与上下文继承)
9. [串行流水线的错误处理与降级策略](#九串行流水线的错误处理与降级策略)
10. [改进前后对比](#十改进前后对比)

---

## 一、核心设计决策：为什么串行优于并行

### 1.1 并行模式的问题

当前三个 Agent 并行执行，存在三个根本性问题：

**问题 1：信息孤岛，重复计算**

```
并行模式：
  context (原始文章列表)
       ↓
  ┌────────┐  ┌────────┐  ┌────────┐
  │HotTopics│  │DeepSum │  │ Trend  │
  │ 每个都看 │  │ 每个都看│  │ 每个都看│
  │ 全部文章 │  │ 全部文章│  │ 全部文章│
  └────────┘  └────────┘  └────────┘
       ↓         ↓         ↓
  hot_topics   events   trends   (三路输出互相独立)
```

三个 Agent 完全独立处理同样的原始文章列表，没有任何信息共享。HotTopics 发现的最热话题、DeepSummary 识别的重要事件，Trend 完全不知道，不会针对这些重点事件做更深入的分析。

**问题 2：热点与深度总结脱节**

- HotTopics 输出的 Top-10 话题，与 DeepSummary 输出的 Top-10 事件，可能完全不在同一个语义空间
- 今日最重要的事件（DeepSummary 认为是 #1）可能在 HotTopics 的热度排名中只是 #7
- Report Composer 拼接时，两路输出的重点不一致，日报缺乏核心主线

**问题 3：信号层只能做预筛选，无法指导各 Agent 的深度分析**

信号工程层输出的 `composite_score` 等维度得分，在并行模式下只能用于排序和预筛选，无法告诉每个 Agent「应该重点分析哪些文章、应该关注哪些信号」。三个 Agent 各自用自己的逻辑筛选文章，信号层的价值被浪费。

### 1.2 串行模式的优势

```
串行模式：
  context (原始文章列表)
       ↓
  ScoringEngine ← 信号层输出（composite_score 等）
       ↓
  ┌─────────────────────────────────────────────────────────┐
  │  Agent 1: HotTopics                                     │
  │  输入: Top-50 高分文章 + 信号上下文                      │
  │  输出: Top 3-5 热点话题（作为下游锚点）                  │
  │  → 同时输出: "hot_topic_articles"（这些话题的核心文章）   │
  └─────────────────────────────────────────────────────────┘
       ↓ 继承 hot_topic_articles + 信号上下文
  ┌─────────────────────────────────────────────────────────┐
  │  Agent 2: DeepSummary                                    │
  │  输入: Top-30 高分文章 + Agent1 的 Top 热点锚点          │
  │  任务: 优先围绕 Agent1 的 Top 热点做深度分析            │
  │  输出: Top 3 重要事件（与 Agent1 锚点对齐）             │
  │  → 同时输出: "key_events_with_context"                   │
  └─────────────────────────────────────────────────────────┘
       ↓ 继承 Top 热点 + Top 事件 + 信号上下文
  ┌─────────────────────────────────────────────────────────┐
  │  Agent 3: Trend                                         │
  │  输入: 全量文章 + Agent1 的 Top 热点 + Agent2 的 Top 事件 │
  │  任务: 针对 Top 热点 + Top 事件做趋势外推                │
  │  输出: PEST/SWOT + 3-7天 趋势研判                       │
  └─────────────────────────────────────────────────────────┘
       ↓ 继承热点 + 事件 + PEST/SWOT + 信号上下文
  ┌─────────────────────────────────────────────────────────┐
  │  Agent 4: OpportunityScanner [NEW]                      │
  │  输入: Agent1 热点 + Agent2 事件 + Agent3 PEST/SWOT     │
  │  任务: 基于趋势研判，识别风险点与投资机会               │
  │  输出: RiskSignals[] + OpportunitySignals[]             │
  └─────────────────────────────────────────────────────────┘
       ↓
  ReportComposer（串行输出，无需二次聚合）
```

**核心优势**：
1. **信息逐层浓缩**：每一步 Agent 的输出都在缩小下游的关注范围
2. **锚点继承**：后面的 Agent 知道前面的 Agent 发现了什么，针对性分析
3. **信号引导**：信号层为每一步提供决策上下文，而不是仅做预筛选
4. **报告一致性**：最终输出的热点、重要事件、趋势研判天然对齐，有核心主线

### 1.3 串行的代价与应对

串行的主要代价是**总耗时 = 四个 Agent 耗时之和**（而并行是最慢 Agent 的耗时）。

应对策略：
- HotTopics、DeepSummary 是轻量任务（主要是 LLM 单次调用），各耗时约 5-15s
- Trend 的 4 个 Sub-Nodes 仍然可以并行（内并行，外串行），耗时约 10-20s
- OpportunityScanner 是轻量任务（基于上游输出的结构化推理），耗时约 5-10s
- 四个 Agent 串行总耗时约 30-60s，在可接受范围内（日报生成非实时任务）
- 与并行模式相比，增加的耗时换来的是报告质量的显著提升

---

## 二、串行流水线总览

### 2.1 完整流水线架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                      Orchestrator.run()                               │
│                                                                      │
│  Step 1: build_context()                                             │
│    → 从 SQLite 读取最近 N 天文章                                      │
│    → 构建原始 DailyReportContext                                      │
│                                                                      │
│  Step 2: scoring_prepass() [NEW]                                    │
│    → ScoringEngine.score_articles() — 计算 composite_score           │
│    → ClusteringEngine.cluster_articles() — 语义聚类                  │
│    → 写入 articles_signals 表（持久化分项得分）                      │
│    → 生成 SignalContext（信号上下文，供后续 Agent 使用）              │
│                                                                      │
│  Step 3: Agent 1 — HotTopics.analyze() [串行第一步]                  │
│    输入: context + signal_context                                    │
│    输出: Top 3-5 热点 + hot_topic_articles（核心文章列表）          │
│                                                                      │
│  Step 4: Agent 2 — DeepSummary.analyze() [串行第二步]                │
│    输入: context + signal_context + hot_topics + hot_topic_articles   │
│    输出: Top 3 重要事件 + events_with_context                        │
│    策略: 优先围绕 Agent1 的 Top 热点做深度分析                        │
│                                                                      │
│  Step 5: Agent 3 — Trend.analyze() [串行第三步]                     │
│    输入: context + signal_context + hot_topics + key_events          │
│    输出: PEST + SWOT + 趋势研判 + cross_dimension_signals            │
│    策略: 针对 Top 热点 + Top 事件做趋势外推                           │
│                                                                      │
│  Step 6: Agent 4 — OpportunityScanner.analyze() [串行第四步]         │
│    输入: Agent1 热点 + Agent2 事件 + Agent3 PEST/SWOT/趋势          │
│    输出: RiskSignals[] + OpportunitySignals[]                        │
│    策略: 基于趋势研判，从风险和机会两个维度输出结构化判断             │
│                                                                      │
│  Step 7: ReportComposer.compose() [最终聚合]                         │
│    输入: Agent1 + Agent2 + Agent3 + Agent4 的串行输出                │
│    输出: 最终日报（Markdown + JSON）                                  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 数据上下文演进

每一步 Agent 执行的输入上下文逐步丰富，但保持同一份 article 列表（仅在数量上递减）：

```
初始上下文:
  DailyReportContext:
    date: "2026-04-02"
    articles_count: 847
    articles: [全部847篇文章]
    sources: [24个来源]
    language: "mixed"

↓ scoring_prepass 后，增加:

  DailyReportContext + SignalContext:
    (以上全部)
    + scored_articles: [带 composite_score 的文章，按分排序]
    + cluster_info: [{cluster_id, topic_label, size, avg_score}]
    + signal_summary: {authority_mean, community_coverage_pct, ...}
    + top_articles_by_source: {source: [top-5 articles]}

↓ Agent1 (HotTopics) 输出，增加:

  + hot_topics: [Top 3-5 热点话题]
  + hot_topic_articles: [每个热点话题的核心文章，约 10-15 篇]
  + hot_topics_concern_trends: [Agent1 识别的趋势方向]

↓ Agent2 (DeepSummary) 输出，增加:

  + key_events: [Top 3 重要事件，W/W/I 结构]
  + events_with_context: [每个事件+围绕该事件的全部相关文章]
  + event_sentiment: [每个事件的情感标签和置信度]

↓ Agent3 (Trend) 输出:

  + pest_analysis: {P/E/S/T 四个维度}
  + swot_analysis: {S/W/O/T 四个象限}
  + trend_prediction: {direction, risk_points, opportunity_points, timeline}
  + cross_dimension_signals: [高置信度跨维度信号]
```

---

## 三、Orchestrator 重构：prepass 阶段前置

### 3.1 新增 SignalContext 数据类

```python
@dataclass
class SignalContext:
    """信号工程层的输出，供所有 Agent 共用"""
    date: str

    # 评分结果
    scored_articles: list[dict]          # 带 composite_score，按分降序
    top_articles: list[dict]             # Top-50（用于 HotTopics）
    top_events_articles: list[dict]      # Top-30（用于 DeepSummary）

    # 聚类结果
    clusters: list[ClusterResult]        # 所有语义簇
    emerging_clusters: list[ClusterResult] # 新兴主题簇

    # 信号分布摘要（用于 Agent 的上下文提示）
    signal_summary: dict
    # e.g. {
    #   "authority_mean": 1.45,
    #   "community_coverage_pct": 0.23,
    #   "academic_papers_pct": 0.61,
    #   "top_source": "arXiv",
    #   "emerging_topic_hints": ["多模态", "Agent", "RL"],
    # }

    # 每个来源的最高分文章（用于多样性保障）
    top_articles_by_source: dict[str, list[dict]]

    # 情感分布摘要
    sentiment_summary: dict  # e.g. {"positive": 0.35, "neutral": 0.45, "negative": 0.15, "controversial": 0.05}
```

### 3.2 scoring_prepass 阶段

```python
async def scoring_prepass(
    self,
    context: DailyReportContext,
) -> tuple[DailyReportContext, SignalContext]:
    """
    在 Agent 执行前，对全量文章进行信号评分和聚类。

    输出：
      - enriched_context: 在原上下文中增加 scored_articles
      - signal_context: 独立的信号上下文，供 Agent 使用
    """
    # 1. ScoringEngine — 计算 composite_score
    scored = await self.scoring_engine.score_articles(
        context.articles,
        with_diversity=True,
        max_per_source=5,
    )
    # 2. ClusteringEngine — 语义聚类 + 新兴主题检测
    clusters, emerging = await self.clustering_engine.cluster_with_emerging(
        scored,
        max_results=50,
        previous_clusters=await self._load_previous_clusters(context.date),
    )
    # 3. (可选) SentimentAnalyzer — 批量情感分析
    sentiments = await self.sentiment_analyzer.analyze_distribution(scored)

    # 4. 构建 SignalContext
    signal_ctx = SignalContext(
        date=context.date,
        scored_articles=scored,
        top_articles=scored[:50],
        top_events_articles=scored[:30],
        clusters=clusters,
        emerging_clusters=emerging,
        signal_summary=self._build_signal_summary(scored, clusters, sentiments),
        top_articles_by_source=self._group_by_source_top(scored),
        sentiment_summary=sentiments,
    )

    return context, signal_ctx
```

---

## 四、Agent 1：HotTopics — Top 3-5 热点发现（串行第一步）

### 4.1 定位与目标

**定位**：串行流水线的第一棒，热点发现与锚点生成。

**核心目标**：
- 从 Top-50 高分文章中识别 Top 3-5 最热话题
- 输出「热点锚点」供下游 Agent 使用
- 为整个日报定下主线基调

### 4.2 内部流水线改进

当前问题：
- `_sort_and_filter` 只看摘要长度，不看信号得分
- LLM 评分标准模糊，无信号上下文

**改进后的内部节点**：

```
┌──────────────────────────────────────────────────────────────────────┐
│  Input: context.articles + signal_context                            │
│                                                                      │
│  Node 1: SignalPreFilter                                             │
│    → 取 signal_context.top_articles（Top-50，已按 composite_score） │
│    → 展示 composite_score 分项维度（authority/community/recency）   │
│    → 按来源多样性约束（每来源最多3篇）                               │
│                                                                      │
│  Node 2: LLMHotspotScoring                                           │
│    → 系统提示增加信号上下文提示（"今日有 X 篇高权威性文章，         │
│       Y 篇高社区共鸣文章，Z 个新兴主题"）                           │
│    → LLM 批量评分时，同时输出：                                      │
│      1. 热点话题排名                                                 │
│      2. 每个话题的核心文章（2-3篇代表性文章）                       │
│      3. 每个话题的 composite_score 分布（为什么这个话题热）          │
│                                                                      │
│  Node 3: TopicAnchorGenerator                                        │
│    → 选取 Top 3-5 热点                                               │
│    → 为每个热点生成锚点对象:                                          │
│      {                                                               │
│        "topic_id": "ht_001",                                         │
│        "topic_name": "一句话话题名",                                  │
│        "composite_score": 8.5,                                       │
│        "signal_breakdown": {                                         │
│          "authority_score": 2.4,                                     │
│          "community_score": 0.82,                                    │
│          "recency_score": 0.91,                                     │
│        },                                                            │
│        "key_articles": [article_id, ...],  # 2-3篇                  │
│        "direction": "rising",                                        │
│        "related_clusters": [cluster_id, ...],                       │
│        "trend_note": "技术圈关注度高，但大众媒体尚未跟进",            │
│      }                                                               │
│                                                                      │
│  Output: {                                                           │
│    "hot_topics": [Top 3-5 热点锚点],                                │
│    "hot_topic_articles": [所有锚点涉及的核心文章，约 10-15 篇],      │
│    "hot_topics_concern_trends": [Agent1 识别的初步趋势方向],        │
│    "total_analyzed": 50,                                            │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.3 关键改进点

**改进 1：信号上下文注入 System Prompt**

```python
SIGNAL_CONTEXT_HINT = """\
【今日信号背景】（以下信息来自信号工程层，仅供参考）

今日共分析 {articles_count} 篇文章，
- 高权威性文章（authority_score > 2.0）：{high_authority_count} 篇
- 有社区共鸣信号的文章（community_score > 0.5）：{community_count} 篇
- 新兴主题（今日首次出现）：{emerging_count} 个
- 学术论文占比：{academic_pct:.0%}
- 情感分布：{sentiment_dist}

【评分权重参考】
请结合以上信号背景，重点关注：
1. 高权威性 + 高社区共鸣 的交叉文章（最具影响力）
2. 高信号得分 + 新兴主题 的交叉文章（可能是明日热点）
3. 高时效性（recency > 0.8）+ 高质量内容的文章（今日首发重要事件）
"""
```

**改进 2：每个热点同时输出核心文章**

当前 HotTopics 只输出话题名和摘要，DeepSummary 需要重新分析文章。改进后，每个热点直接携带 2-3 篇代表性文章，大幅减少 DeepSummary 的分析负担。

**改进 3：TopicAnchorGenerator 生成结构化锚点**

锚点包含 composite_score 分项维度，下游 Agent 可以快速判断该热点的热度来源（是权威性高？还是社区共鸣强？还是时效性好？）。

---

## 五、Agent 2：DeepSummary — 重要事件深度总结（串行第二步）

### 5.1 定位与目标

**定位**：串行流水线的第二棒，在 HotTopics 的锚点上做深度分析。

**核心目标**：
- 围绕 Agent1 识别的 Top 热点，深入挖掘背后的重要事件
- 区分「热」和「重要」：热的文章不一定重要，重要的文章可能还没被广泛传播
- 输出结构化的 What/Why/Who/Impact 事件摘要

### 5.2 串行 vs 并行的本质差异

```
并行模式（现有）：
  DeepSummary 输入: 全部文章，盲目聚类
  问题: 识别出的 Top 事件可能与 HotTopics 的 Top 热点不重合
  后果: 日报主线混乱，热点和深度事件各说各话

串行模式（改进后）：
  DeepSummary 输入: Top-30 高分文章 + Agent1 的 Top 3-5 热点锚点
  策略: 优先围绕 Agent1 的 Top 热点找深度事件
        但仍保留独立识别「被低估的重要事件」的能力
  后果: 日报主线清晰，热点和深度事件相互印证
```

### 5.3 内部流水线改进

```
┌──────────────────────────────────────────────────────────────────────┐
│  Input: context.articles + signal_context + Agent1 输出             │
│                                                                      │
│  Node 1: HotTopics-GuidedFilter                                      │
│    → 识别 Agent1 的 Top 3-5 热点锚点                                  │
│    → 从 signal_context.scored_articles 中，                         │
│      找出与每个热点锚点最相关的文章（embedding 相似度 top-5）         │
│    → 同时补充：未被 Agent1 锚点覆盖的高质量文章（防止遗漏）            │
│    → 总输入约 25-35 篇文章                                            │
│                                                                      │
│  Node 2: EventExtractionNode                                         │
│    → LLM 对聚类后文章进行事件提取                                    │
│    → 系统提示中注入 Agent1 的热点上下文：                            │
│      "今日 HotTopics 识别的前3热点为：                               │
│       [1] {topic_name}（composite_score={score}）                  │
│       [2] {topic_name}（...）                                        │
│       请优先围绕以上热点识别重要事件"                                 │
│                                                                      │
│  Node 3: ImportanceRankingNode                                       │
│    → 区分「热」和「重要」：                                          │
│      - hot_score 高 → 传播广度大                                     │
│      - importance_score（新增）→ 信息增量/认知价值                   │
│      - composite_score → 综合热度                                   │
│    → 重要性评分标准（新增）：                                        │
│      - 首次公开信息 +10（独家/首发）                                 │
│      - 涉及多方关键参与方 +8                                         │
│      - 有具体数据/案例支撑 +7                                        │
│      - 对行业有结构性影响 +10                                        │
│      - 持续发酵中（跨多天报道）+5                                     │
│                                                                      │
│  Node 4: EventContextBuilder                                         │
│    → 为每个 Top 事件，收集围绕该事件的所有相关文章                    │
│    → 生成 events_with_context（供 Agent3 Trend 使用）               │
│      {                                                               │
│        "event_id": "evt_001",                                        │
│        "event_topic": "...",                                         │
│        "importance_score": 9.2,                                      │
│        "related_articles": [article_ids],                            │
│        "cross_source_count": 4,  # 多少个不同来源报道了此事         │
│        "sentiment": "controversial",                                │
│        "sentiment_confidence": 0.78,                                 │
│        "persistence_score": 0.85,                                    │
│        "signal_context": {  # 来自信号工程层                         │
│          "authority": 2.1,                                          │
│          "recency": 0.95,                                           │
│          "community": 0.45,                                         │
│        },                                                            │
│        "impact_horizon": "short|medium|long",                        │
│      }                                                               │
│                                                                      │
│  Output: {                                                           │
│    "key_events": [Top 3 重要事件],                                  │
│    "events_with_context": [所有重要事件 + 上下文],                  │
│    "underestimated_events": [被低估的重要事件（optional）],         │
│    "total_events": N,                                               │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.4 关键改进点

**改进 1：HotTopics 引导的过滤策略**

不再从全量文章中盲目聚类，而是先识别与 Agent1 热点锚点最相关的文章，再聚类。保证输出的事件与日报主线一致。

**改进 2：「热」与「重要」的双轨评分**

引入 `importance_score`（重要度），与 Agent1 的 `hot_score`（热度）形成双轨：
- `hot_score` 高的 → 传播广度大
- `importance_score` 高的 → 信息增量大，可能是被低估的事件

Agent2 的输出同时包含双轨评分，Agent3 Trend 可以据此判断「哪些事件需要重点做趋势外推」。

**改进 3：事件上下文打包**

每个事件携带 `events_with_context`，包含相关文章列表、跨源数量、信号维度得分。Agent3 直接使用，无需重新分析文章。

---

## 六、Agent 3：Trend — 趋势研判（串行第三步）

### 6.1 定位与目标

**定位**：串行流水线的最后一棒，在 HotTopics 和 DeepSummary 的基础上做趋势研判。

**核心目标**：
- 针对 Top 热点 + Top 事件，做 PEST + SWOT + 3-7 天趋势外推
- 输出结构性分析（相比 Agent1/2 的叙事性分析）
- 为 Report Composer 提供研判性结论

### 6.2 串行 vs 并行的本质差异

```
并行模式（现有）：
  Trend 输入: 全量文章，各自为政
  问题: 趋势分析与今日热点/重要事件脱节
  后果: 趋势研判可能是"通用 AI 趋势"，而非"今日特定事件驱动的趋势"

串行模式（改进后）：
  Trend 输入: 全量文章 + Agent1 的 Top 热点 + Agent2 的 Top 事件
  策略: 趋势分析必须锚定到具体事件
        PEST/SWOT 的每一条结论都要有具体文章支撑
  后果: 趋势研判与日报主线强关联，有具体事实依据
```

### 6.3 内部流水线改进

```
┌──────────────────────────────────────────────────────────────────────┐
│  Input: context.articles + signal_context + Agent1 输出 + Agent2 输出 │
│                                                                      │
│  Node 1: TrendRoutingNode (PEST 四维度路由)                          │
│    → 分析 Agent1 的 Top 热点 + Agent2 的 Top 事件                     │
│    → 判断哪些事件/热点落入哪个 PEST 维度                              │
│    → 策略: 每个维度至少锚定 1 个具体事件/热点                         │
│    → 如果某维度无锚点，使用 signal_context 的信号分布推断            │
│                                                                      │
│  Node 2: AnchorDrivenExtraction                                      │
│    → 对每个 PEST 维度，提取与锚定事件相关的文章子集                  │
│    → 同时使用 signal_context 中的信号得分加权                        │
│    → 重点引用 Agent2 的 events_with_context（已有上下文）            │
│                                                                      │
│  Node 3: PESTSynthesisNode (PEST 四维度分析)                         │
│    → Tech: 基于 Agent2 的技术突破事件 + signal_context 的学术信号   │
│    → Economic: 基于 Agent2 的商业化事件 + 社区讨论中的市场信号       │
│    → Social: 基于 Agent2 的舆情事件 + sentiment_summary              │
│    → Political: 基于 Agent2 的监管事件                              │
│                                                                      │
│  Node 4: SWOTAnalysisNode (SWOT 四象限分析)                          │
│    → Strengths: 今日哪些事件/动作展示了正面能力                      │
│    → Weaknesses: 今日哪些事件/问题暴露了短板                         │
│    → Opportunities: 基于 Top 热点/事件，识别未来机会点               │
│    → Threats: 基于 Top 热点/事件，识别未来风险点                     │
│    → 每条 SWOT 论断必须引用具体事件（来源: Agent1 或 Agent2）       │
│                                                                      │
│  Node 5: TrendPredictionNode (3-7天趋势外推)                        │
│    → 基于 PEST + SWOT + signal_context 的信号强度                   │
│    → 预测格式:                                                       │
│      {                                                               │
│        "direction": "rising|stable|declining|uncertain",           │
│        "confidence": "high|medium|low",                             │
│        "time_horizon": "3-7 days",                                   │
│        "key_drivers": [驱动因素1, ...],                              │
│        "risk_points": [风险点1, ...],                                │
│        "opportunity_points": [机遇点1, ...],                         │
│        "anchor_events": [引用的事件/热点锚点],                       │
│      }                                                               │
│                                                                      │
│  Node 6: CrossDimensionSignalNode (跨维度信号)                       │
│    → 识别同时出现在多个维度的事件（最具影响力）                      │
│    → 基于 signal_context 的跨源扩散信号判断                          │
│                                                                      │
│  Output: {                                                           │
│    "pest_analysis": {P/E/S/T 四维度},                               │
│    "swot_analysis": {S/W/O/T 四象限},                               │
│    "trend_prediction": {...},                                        │
│    "cross_dimension_signals": [...],                                │
│    "anchor_references": [引用了 Agent1 的哪些热点, Agent2 的哪些事件],│
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.4 关键改进点

**改进 1：PEST 路由基于锚点而非关键词**

现有 Trend 用关键词过滤文章，导致维度划分机械（一篇文章只能属于一个维度）。改进后，先识别 Agent1/2 输出中有哪些事件落入哪个维度，再提取相关文章。一个事件可以同时影响多个维度（如一项新法规既影响 Policy 又影响 Tech）。

**改进 2：每条趋势结论必须锚定具体事件**

现有 Trend 输出的 `signals` 列表是抽象描述。改进后，每个信号的 `source` 字段必须引用具体事件/热点（格式：`evt_001`、`ht_001`），Report Composer 可以追溯到原始内容。

**改进 3：Agent3 的 4 个 Sub-Nodes 仍内并行**

PEST 四个维度的分析是独立的，可以在 Agent3 内部并行执行（保持现有优势），但 Agent3 的整体输入依赖 Agent1+2 的串行输出。

---

## 七、Agent 4：OpportunityScanner — 风险与机会识别（串行第四步）

### 7.1 定位与目标

**定位**：串行流水线的最后一棒（ReportComposer 之前），将趋势研判转化为可操作的风险/机会信号。

**核心目标**：
- 基于 Agent3 的 PEST/SWOT + 趋势预测，输出结构化的风险信号和投资/布局机会
- 填补现有架构缺失的「研判到行动」环节——Trend 输出的是分析结论，OpportunityScanner 输出的是行动参考
- 从 AI 行业视角，区分「值得关注的信号」和「需要警惕的信号」

### 7.2 与 Trend Agent 的关系

```
Trend Agent（分析层）→ OpportunityScanner（决策层）

Trend 输出：                    OpportunityScanner 输入：
  pest_analysis: {...}    →    pest = {...}（直接继承）
  swot_analysis: {...}    →    swot = {...}（直接继承）
  trend_prediction: {      →    trend = {...}（直接继承）
    direction, confidence,
    risk_points, ...       →    (已有风险点，作为初始候选)
  }
  cross_dimension_signals   →    cross_signals = [...]（直接继承）

OpportunityScanner 额外输入：
  → Agent1 的 Top 热点（判断热点背后是否有未被充分定价的风险/机会）
  → Agent2 的重要事件（判断事件的持续性是否足够支撑投资/布局决策）
  → signal_context（信号强度验证：社区共鸣、学术引用等）
```

Trend 回答「趋势是什么」，OpportunityScanner 回答「我们应该怎么做」。两者不是重复，而是分析到决策的递进。

### 7.3 内部流水线设计

```
┌──────────────────────────────────────────────────────────────────────┐
│  Input: Agent1 输出 + Agent2 输出 + Agent3 输出 + signal_context     │
│                                                                      │
│  Node 1: RiskCandidateCollector                                      │
│    → 收集 Agent3.trend_prediction.risk_points 作为候选               │
│    → 收集 Agent3.swot_analysis.Threats 作为候选                      │
│    → 收集 Agent3.pest_analysis 中趋势为"负面影响"的维度              │
│    → 补充：从 Agent1/2 中识别未被 Agent3 覆盖的风险信号               │
│                                                                      │
│  Node 2: OpportunityCandidateCollector                               │
│    → 收集 Agent3.trend_prediction.opportunity_points 作为候选        │
│    → 收集 Agent3.swot_analysis.Opportunities 作为候选                │
│    → 收集 Agent3.pest_analysis 中趋势为"正面利好"的维度              │
│    → 补充：从 signal_context.emerging_clusters 中识别新兴机会         │
│                                                                      │
│  Node 3: RiskEvaluator                                               │
│    → 对每个风险候选评估：                                            │
│      1. 紧迫性（urgency）：1-5 天内是否可能发生                      │
│      2. 影响程度（severity）：对 AI 行业/特定公司影响范围            │
│      3. 置信度（confidence）：当前信号强度是否充分                   │
│      4. 可监控性（monitorability）：是否有指标可以追踪变化            │
│    → 筛选输出: RiskSignals[]                                         │
│                                                                      │
│  Node 4: OpportunityEvaluator                                         │
│    → 对每个机会候选评估：                                            │
│      1. 时间窗口（time_window）：3-30 天内值得关注                   │
│      2. 受益方（beneficiaries）：谁将从这个机会中受益                │
│      3. 信号强度（signal_strength）：是否有多源交叉验证               │
│      4. 风险收益比（risk_reward）：机会的潜在收益 vs 失败风险         │
│    → 筛选输出: OpportunitySignals[]                                  │
│                                                                      │
│  Node 5: CrossValidationNode                                         │
│    → 验证风险/机会 信号是否与 Agent1/2 的热点/事件有交叉             │
│    → 高度关联的风险/机会 → confidence_bonus +0.2                    │
│    → 无关联的孤立信号 → confidence_penalty -0.1（可能是假信号）      │
│                                                                      │
│  Output: {                                                           │
│    "risk_signals": [RiskSignal, ...],  // 按 urgency×severity 排序  │
│    "opportunity_signals": [OpportunitySignal, ...], // 按 time_window 排序│
│    "high_confidence_pairs": [  // 高置信度风险-机会对              │
│      {risk: "...", opportunity: "...", relationship: "互斥|共生效"}  │
│    ],                                                               │
│  }                                                                   │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.4 输出数据结构

#### RiskSignal

```python
@dataclass
class RiskSignal:
    signal_id: str           # "risk_001"
    title: str               # 一句话风险描述（20字以内）
    description: str          # 详细说明（100字以内）
    urgency: int             # 紧迫性 1-5（1=观察，5=紧急行动）
    severity: int            # 影响程度 1-5
    confidence: float        # 置信度 0.0-1.0

    # 信号来源
    source_type: str         # "trend_prediction" | "swot_threats" | "pest_negative" | "signal_context"
    source_references: list[str]  # ["ht_001", "evt_002", "swot_T_001"]

    # 信号分类
    category: str            # "技术风险" | "监管风险" | "市场风险" | "竞争风险" | "资本风险"
    affected_actors: list[str]  # 受影响的主体 ["OpenAI", "整个行业", "AI芯片"]

    # 监控指标
    monitor_indicators: list[str]  # ["相关股票指数", "GitHub star 趋势", "媒体报道频率"]

    # 关联机会（可选）
    paired_opportunity: str | None  # 对应的反向机会（如果有）
```

#### OpportunitySignal

```python
@dataclass
class OpportunitySignal:
    signal_id: str           # "opp_001"
    title: str               # 一句话机会描述（20字以内）
    description: str          # 详细说明（100字以内）
    time_window: str          # "3-7天" | "1-4周" | "1-3月"
    confidence: float        # 置信度 0.0-1.0
    signal_strength: float   # 信号强度 0.0-1.0（多源交叉验证程度）

    # 信号来源
    source_type: str         # "trend_prediction" | "swot_opportunities" | "emerging_clusters"
    source_references: list[str]  # ["ht_001", "evt_002", "cluster_emerging_003"]

    # 信号分类
    category: str            # "技术布局机会" | "投资机会" | "产品机会" | "人才机会"
    beneficiaries: list[str]  # 受益方 ["开源社区", "AI应用层公司", "算力供应商"]

    # 行动建议
    action_horizon: str      # "立即关注" | "1-2周内布局" | "季度规划"
    key_indicators_to_watch: list[str]  # 需持续跟踪的关键指标

    # 风险提示（反向思考）
    associated_risks: list[str]  # 伴随此机会的风险 ["技术成熟度不确定", "监管政策变化"]
```

### 7.5 关键设计决策

**决策 1：OpportunityScanner 为什么放在 Trend 之后**

Trend 输出的 PEST/SWOT/趋势预测，是 OpportunityScanner 的输入原料。如果放在 Trend 之前，OpportunityScanner 就只能基于热点和事件做浅层判断，缺乏趋势外推的支撑。

但 HotTopics 和 DeepSummary 的输出同样重要——它们提供了「哪些事件是真实的、值得信赖的」，避免 OpportunityScanner 基于虚假或夸大的信号做出错误判断。

**决策 2：风险和机会为什么要双轨输出**

AI 行业的每一个变化都有两面性。单纯输出风险容易让人忽视机会，单纯输出机会容易让人忽视风险。双轨输出要求 OpportunityScanner 对每个机会都要思考「伴随的风险」，对每个风险都要思考「反向的机会」。

**决策 3：为什么需要 CrossValidationNode**

避免「假信号」——只出现在单一来源的高置信度信号（比如 HN 上的一个帖子），可能在多源验证后被降权。通过 Agent1/2/3 的交叉引用，判断信号是否有足够的事实支撑。

---

## 八、信息流向与上下文继承

### 7.1 完整的上下文继承链

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          DailyReportContext                              │
│   date / articles / sources / language                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          SignalContext                                   │
│   scored_articles / clusters / emerging / signal_summary                │
│   全部 6 个维度的分项得分                                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Agent 1: HotTopics 输出                                                │
│                                                                         │
│  hot_topics: [                                                         │
│    {topic_id, topic_name, composite_score, signal_breakdown,          │
│     key_articles, direction, related_clusters, trend_note},            │
│  ]                                                                     │
│                                                                         │
│  hot_topic_articles: [article_ids of key articles, ~10-15篇]          │
│  hot_topics_concern_trends: [初步趋势方向，用于引导 Agent3]            │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Agent 2: DeepSummary 输出                                              │
│                                                                         │
│  key_events: [                                                         │
│    {event_id, event_topic, importance_score, what/why/who/impact,     │
│     related_articles, cross_source_count, sentiment,                   │
│     signal_context, impact_horizon},                                   │
│  ]                                                                     │
│                                                                         │
│  events_with_context: [每个事件 + 围绕该事件的全部上下文]               │
│  underestimated_events: [可选，被低估的重要事件]                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Agent 3: Trend 输出                                                    │
│                                                                         │
│  pest_analysis: {Tech/Economic/Social/Political}                      │
│  swot_analysis: {Strengths/Weaknesses/Opportunities/Threats}          │
│  trend_prediction: {direction, confidence, key_drivers, ...}           │
│  cross_dimension_signals: [...]                                        │
│  anchor_references: [引用了哪些 Agent1 热点和 Agent2 事件]             │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  ReportComposer: 最终日报                                               │
│                                                                         │
│  → hot_topics[:5]: 直接继承 Agent1 输出                                │
│  → deep_events[:3]: 直接继承 Agent2 输出                               │
│  → pest/swot/trend: 直接继承 Agent3 输出                               │
│  → 日报主线天然一致，无信息断裂                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 信号层在各 Agent 中的角色

| Agent | 信号层的用途 | 使用方式 |
|---|---|---|
| **HotTopics** | 预筛选 + 上下文注入 | 取 Top-50 高分文章；System Prompt 注入信号分布背景 |
| **DeepSummary** | 重要性校准 | importance_score 与 hot_score 双轨；跨源扩散信号 |
| **Trend** | 方向判断 + 论据支撑 | PEST 路由参考；每条结论引用信号来源 |

### 7.3 串行流水线的 token 消耗分析

```
并行模式（现有）：
  HotTopics: ~50 篇 × 300 字 = 15K tokens（输入）
  DeepSummary: ~30 篇 × 500 字 = 15K tokens（输入）
  Trend: ~25 篇 × 4 维度 = 30K tokens（输入）
  总计: ~60K tokens（输入）

串行模式（改进后）：
  HotTopics: 50 篇 + signal_summary = ~15K tokens（输入）
  DeepSummary: 30 篇 + Agent1 热点锚点 = ~18K tokens（输入）
  Trend: 25 篇 + Agent1 热点 + Agent2 事件 = ~22K tokens（输入）
  总计: ~55K tokens（输入）

结论：串行模式的 token 消耗与并行模式基本持平，
     甚至略有节省（Agent 不用重复分析相同上下文）。
```

---

## 八、串行流水线的错误处理与降级策略

### 8.1 各 Agent 的降级策略

| Agent 失败 | 影响范围 | 降级策略 |
|---|---|---|
| **Agent1 HotTopics 失败** | Agent2、Agent3、Agent4 失去锚点 | 使用 signal_context.top_articles 直接作为输入；Agent2 改为全量聚类；Agent3/4 改为基于高分文章分析 |
| **Agent2 DeepSummary 失败** | Agent3 和 Agent4 失去事件上下文 | 使用 Agent1 的 hot_topic_articles 直接作为 Agent3 输入；Agent4 降级为仅基于 Agent1+3 分析 |
| **Agent3 Trend 失败** | Agent4 失去 PEST/SWOT 上下文 | Agent4 降级为仅基于 Agent1+2 的原始信号分析 |
| **Agent4 OpportunityScanner 失败** | 仅机会/风险部分为空 | 输出 risk_signals/opportunity_signals 为空列表；保留 Agent1/2/3 输出 |

### 8.2 错误传播与日志

```python
async def run(...):
    context = await self.build_context(...)

    try:
        context, signal_ctx = await self.scoring_prepass(context)
    except Exception as e:
        logger.warning(f"[Orchestrator] scoring_prepass 失败，降级: {e}")
        signal_ctx = None

    # Agent 1
    try:
        ht_result = await self.ht_agent.analyze(context, signal_ctx)
    except Exception as e:
        logger.error(f"[Orchestrator] HotTopics 失败: {e}")
        ht_result = self._empty_hot_topics()

    # Agent 2
    try:
        ds_result = await self.ds_agent.analyze(context, signal_ctx, ht_result)
    except Exception as e:
        logger.error(f"[Orchestrator] DeepSummary 失败: {e}")
        ds_result = self._empty_deep_summary()
        # 降级: Agent3 仍可继续，使用 Agent1 的 hot_topic_articles
        t_input = {"hot_topic_articles": ht_result.get("hot_topic_articles", [])}
    else:
        t_input = ds_result

    # Agent 3
    try:
        t_result = await self.t_agent.analyze(context, signal_ctx, ht_result, ds_result)
    except Exception as e:
        logger.error(f"[Orchestrator] Trend 失败: {e}")
        t_result = self._empty_trend()

    # Agent 4
    try:
        opp_result = await self.opp_agent.analyze(
            ht_result=ht_result,
            ds_result=ds_result,
            t_result=t_result,
            signal_ctx=signal_ctx,
        )
    except Exception as e:
        logger.error(f"[Orchestrator] OpportunityScanner 失败: {e}")
        opp_result = self._empty_opportunity()

    final = await self.composer.compose(
        date=...,
        hot_topics=ht_result,
        deep_summaries=ds_result,
        trend_insights=t_result,
        opportunity_signals=opp_result,
    )
```

---

## 十、改进前后对比

### 10.1 流水线结构对比

| 维度 | 并行模式（现有）| 串行模式（改进后）|
|---|---|---|
| Agent 执行顺序 | HotTopics ∥ DeepSummary ∥ Trend | HotTopics → DeepSummary → Trend → OpportunityScanner |
| 输入数据 | 各自独立处理全量文章 | 逐步浓缩，上游输出作为下游输入 |
| 锚点继承 | 无 | Agent1 → Agent2 → Agent3 → Agent4 层层继承 |
| 报告主线 | 三路输出可能不相关 | 天然对齐，围绕同一主线 |
| 耗时 | ~max(T_HT, T_DS, T_T) | ~T_HT + T_DS + T_T + T_Opp（约增加 60-100%）|
| token 消耗 | 较高（有重复分析）| 基本持平（Agent4 基于结构化输出，几无额外消耗）|
| 风险/机会识别 | 无 | 有（Agent4 独立输出）|
| 信号层参与度 | 仅做预筛选 | 全程参与每个 Agent 的决策 |

### 10.2 输出质量对比

| 指标 | 并行模式（现有）| 串行模式（改进后）|
|---|---|---|
| 热点与事件的关联性 | 低（三路独立）| 高（Agent2 围绕 Agent1 的热点分析）|
| 趋势研判的事实支撑 | 弱（抽象结论多）| 强（每条结论锚定具体事件/热点）|
| 日报主线清晰度 | 中（依赖 Report Composer 拼接）| 高（四步分析天然围绕同一主线）|
| 新兴主题发现能力 | 中 | 高（signal_context.emerging_clusters 引导）|
| 被低估事件识别 | 无 | 有（Agent2 的 underestimated_events）|
| 风险/机会信号 | 无 | 有（Agent4 结构化输出）|

### 10.3 实现优先级

| 优先级 | 改动 | 工作量 | 风险 |
|---|---|---|---|
| **P0** | Orchestrator 重构：串行调用 + scoring_prepass | 中 | 低 |
| **P0** | Agent1 改进：信号上下文注入 + TopicAnchorGenerator | 中 | 低 |
| **P0** | Agent2 改进：HotTopics 引导过滤 + 双轨评分 | 中 | 中（改变输出结构）|
| **P1** | Agent3 改进：锚点驱动 PEST/SWOT | 中 | 低 |
| **P1** | Agent4 新增：OpportunityScanner | 中 | 低（独立 Agent，无历史包袱）|
| **P1** | ReportComposer 适配新串行输出 | 低 | 低 |
| **P2** | underestimated_events 机制 | 低 | 低 |

---

*本文档为 [V2 事件预测架构](./v2-event-prediction-architecture.md) 的 Agent 层补充，与 [信号工程层](./v2-ai-signals-engineering.md) 共同构成 V2 分析层面的完整设计。*
