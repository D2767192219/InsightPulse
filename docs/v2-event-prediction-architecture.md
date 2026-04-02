# InsightPulse V2 事件预测架构方案

> 参考 [BettaFish 事件预测机制](../guide/bettafish-prediction-mechanism.md) 设计
> 针对 AI 行业日报场景，基于现有 Fan-Out/Fan-In 架构重构

---

## 目录

1. [核心结论：BettaFish 的预测本质](#一核心结论bettafish-的预测本质)
2. [热点参考值体系](#二热点参考值体系)
3. [各模块详细设计](#三各模块详细设计)
4. [增强后的 Agent 流水线](#四增强后的-agent-流水线)
5. [增强后的 Orchestrator 流水线](#五增强后的-orchestrator-流水线)
6. [数据模型变更](#六数据模型变更)
7. [需要实现的模块清单](#七需要实现的模块清单)
8. [架构全貌](#八架构全貌)
9. [实现顺序建议](#九实现顺序建议)

---

## 一、核心结论：BettaFish 的预测本质

BettaFish 的预测是**多信号模式识别 + LLM 判断性预测**的混合系统，而非统计时序预测。

| BettaFish 有 | InsightPulse V1 现状 | 差距 |
|---|---|---|
| 加权热度公式（share×10 > comment×5 > like×1） | 无，仅时间排序 | 缺失 |
| IP 地理位置扩散速度 | 无 | 缺失 |
| `relevance_score` 时序排名信号 | 无 | 缺失 |
| 5级情感分类 + 置信度 | 无 | 缺失 |
| KMeans 语义聚类（防止热点掩盖） | 无 | 缺失 |
| ForumHost LLM 研判（趋势预测） | Trend Agent 仅有 4 维度关键词过滤 | 弱 |
| `swotTable` + `pestTable` IR | 无 | 缺失 |

**InsightPulse V2 目标**：在保持现有 Fan-Out/Fan-In 架构优势的基础上，补全缺失的多信号层，使热点选取和事件预测有可验证的算法依据，而非完全依赖单次 LLM 调用。

---

## 二、热点参考值体系

### 2.1 信号分层架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          信号采集层 (当前已有)                            │
│                                                                         │
│  articles 表字段:                                                        │
│  title / summary / source / published_at / url / author / tags         │
│  reading_time_minutes / language / image_url                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓ 特征工程
┌─────────────────────────────────────────────────────────────────────────┐
│                         信号工程层 (待新增)                               │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │ 热度信号      │  │ 权威性信号   │  │ 时效性信号   │  │ 质量信号    │ │
│  │              │  │              │  │              │  │             │ │
│  │ 来源权重表    │  │ arXiv 2.5   │  │ 指数衰减模型  │  │ 摘要长度    │ │
│  │              │  │ 权威媒体 2.0 │  │ 半衰期 24h   │  │ >200字=1.0  │ │
│  │              │  │ 社区 1.3    │  │ 最新=1.0     │  │ 阅读时长    │ │
│  │              │  │ 其他 1.0    │  │ 24h后≈0.5   │  │ 争议词命中  │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          预测引擎层 (待新增)                              │
│                                                                         │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ ScoringEngine     │  │ ClusteringEngine │  │ SentimentAnalyzer     │ │
│  │ 多信号加权热度分   │  │ 语义聚类+新兴检测 │  │ 5级情感+演变轨迹      │ │
│  │ composite_score   │  │ KMeans+DBSCAN   │  │ positive/negative    │ │
│  │ = engagement×    │  │ 防热点掩盖      │  │ controversial        │ │
│  │   authority×     │  │ 每簇固定配额     │  │                      │ │
│  │   recency×       │  │                 │  │                      │ │
│  │   content +bonus │  │                 │  │                      │ │
│  └──────────────────┘  └──────────────────┘  └──────────────────────┘ │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ PredictionEngine — BettaFish ForumHost 思想的事件预测层            │  │
│  │   - PEST 宏观分析（Political/Economic/Social/Technological）     │  │
│  │   - SWOT 分析（Strengths/Weaknesses/Opportunities/Threats）     │  │
│  │   - 3-7天趋势外推（基于信号强度变化，非统计模型）                 │  │
│  │   - 风险点 / 机遇点识别                                         │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          输出层 (待增强)                                 │
│                                                                         │
│  final_report:                                                          │
│    hot_topics[:5]      — Top 5 热点（算法评分）                        │
│    deep_events[:3]     — Top 3 深度事件（聚类+评分）                    │
│    swot_analysis       — SWOT 四象限结构化分析                          │
│    pest_analysis       — PEST 四维度宏观趋势                             │
│    trend_prediction    — 3-7天趋势研判                                  │
│    cross_dimension_signals — 跨维度高置信度信号                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 各信号维度详解

#### 热度信号（参与度加权）

| 行为类型 | 权重 | 说明 |
|---|---|---|
| 分享（share） | ×10 | 认知成本最高，传播意愿最强，最具预测价值 |
| 收藏（favorite） | ×10 | 长期价值信号，用户主动保存 |
| 评论（comment） | ×5 | 互动深度信号，讨论质量高于点赞 |
| 点赞（like） | ×1 | 基础认可信号，认知成本最低 |
| 阅读（view） | ×0.1 | 曝光基数 |

**设计原理**：分享行为的认知成本远高于点赞——用户愿意主动分享，说明话题具有社交货币属性，是传播链延伸的强预测信号。这与传播学中「分享意愿 = 话题生命周期」的结论一致。

#### 权威性信号

| 来源类别 | 代表来源 | 权重 |
|---|---|---|
| 学术 / 官方首发 | arXiv, OpenAI Blog, DeepMind Blog, Anthropic Blog | 2.5 |
| 权威科技媒体 | TechCrunch, The Verge, VentureBeat, Wired | 2.0 |
| 高质量中文媒体 | 机器之心, 量子位, 36kr, 极客公园 | 1.5-1.8 |
| 社区 / 聚合 | HackerNews, Reddit, 知乎, Product Hunt | 1.3 |
| 其他 | — | 1.0 |

#### 时效性信号

指数衰减模型（半衰期 24h）：

```
recency_score = 0.5^(hours_ago / 24)
```

- 最新文章 → 1.0
- 24 小时前 → 0.5
- 48 小时前 → 0.25
- 72 小时前 → 0.125

#### 质量信号

| 指标 | 计算方式 | 说明 |
|---|---|---|
| 摘要长度 | `min(1.0, summary_len / 400)` | 有实质内容 > 标题党 |
| 阅读时长 | `min(0.5, reading_time × 0.05)` | 深度内容的代理信号 |
| 争议词命中 | `min(1.0, controversy_kw_hits / 3)` | 标题/摘要含争议词 |
| 突破词命中 | `min(1.0, breakthrough_kw_hits / 3)` | 标题/摘要含突破性技术词 |

---

## 三、各模块详细设计

### 3.1 ScoringEngine — 多信号热度评分引擎（新增 Service）

**文件路径**: `backend/services/scoring_engine.py`

**定位**: Orchestrator 与各 Agent 之间的事件预筛选层。

#### 综合热度分公式

```
composite_score = engagement_score
                × authority_score_norm    (authority / 2.5)
                × recency_multiplier      (0.5 + recency × 1.2)
                × content_multiplier       (0.5 + content_quality × 0.8)
                + controversy_bonus        (controversy_score × 10)
                + breakthrough_bonus       (breakthrough_score × 10)
```

#### 多样性采样策略

防止同一来源垄断 Top-K：
- 每个来源最多占 `max_per_source=5` 篇
- 不足时补充剩余最高分文章
- 配合 ClusteringEngine 实现簇级多样性

#### API

```python
class ScoringEngine:
    def score_articles(self, articles: list[dict], top_k: int = 50) -> list[dict]:
        """多信号评分，返回带 composite_score 的文章列表，按热度降序"""

    def score_and_rank_with_diversity(
        self,
        articles: list[dict],
        top_k: int = 30,
        max_per_source: int = 5,
    ) -> list[dict]:
        """带多样性保障的评分排序"""

    def explain_score(self, article: dict) -> dict:
        """返回分项解释，用于调试和可解释性报告"""
```

---

### 3.2 ClusteringEngine — 语义聚类引擎（新增 Service）

**文件路径**: `backend/services/clustering_engine.py`

**依赖**: `sentence-transformers`, `scikit-learn`

**定位**: DeepSummary Agent 的前置预处理层，防止热点掩盖效应。

#### BettaFish 聚类逻辑（参考来源）

```
Step 1: 提取文本（前500字符用于 embedding）
Step 2: SentenceTransformer paraphrase-multilingual-MiniLM-L12-v2 → 384维向量
Step 3: KMeans 聚类，簇数 = min(max_results // results_per_cluster, n_articles)
Step 4: 每簇内按热度降序，采样前 results_per_cluster 篇
```

#### 为什么需要聚类

传统 Top-N 只返回最热 N 条会导致：

- **热点掩盖效应**：一个爆款事件（1亿热度）让所有话题都显得「不重要」
- **新兴信号丢失**：刚兴起的话题（热度低但语义相似内容在增加）永远无法进入 Top-N

聚类采样效果：

- 每个语义簇有固定配额（`results_per_cluster=5`）
- 即使簇内总热度低，只要簇内有内容被采样，就说明存在独立讨论方向

#### 新兴主题检测（跨时间窗口）

对比今日聚类结果与昨日聚类结果：

| 条件 | 判断 |
|---|---|
| 完全新出现的簇 | 新兴话题 |
| 规模增长 > 1.2 倍 | 快速增长话题 |
| 平均热度分增长 > 1.2 倍 | 正在升温的话题 |

#### API

```python
class SemanticClusteringEngine:
    def cluster_articles(
        self,
        articles: list[dict],          # 带 composite_score 的文章
        max_results: int = 50,
        results_per_cluster: int = 5,
        score_field: str = "composite_score",
    ) -> tuple[list[dict], list[ClusterResult]]:
        """语义聚类并采样，返回 (采样文章列表, 簇结果列表)"""

    def detect_emerging_clusters(
        self,
        current_clusters: list[ClusterResult],
        previous_clusters: list[ClusterResult],
        growth_threshold: float = 1.2,
    ) -> list[ClusterResult]:
        """跨时间窗口新兴主题检测"""
```

---

### 3.3 SentimentAnalyzer — 情感分析引擎（新增 Service）

**文件路径**: `backend/services/sentiment_analyzer.py`

**依赖**: `transformers`（可选本地模型，也可使用 LLM 模拟）

**定位**: DeepSummary Agent 的后置增强，为每个事件补充情感信号。

#### BettaFish 情感分类（参考来源）

| 级别 | 标签 | 预测含义 |
|---|---|---|
| 0 | 非常负面 | 危机级别舆情信号 |
| 1 | 负面 | 舆情恶化信号 |
| 2 | 中性 | 观察为主 |
| 3 | 正面 | 利好信号 |
| 4 | 非常正面 | 重大利好信号 |

#### 情感预测应用

| 情感轨迹 | 预测含义 |
|---|---|
| 正面 → 负面 | 舆情危机信号 |
| 高置信度负面密集出现 | 快速发酵中的负面事件 |
| 中性主导但正面下降 | 沉默螺旋形成中 |
| 争议性情感分散 | 话题仍在发酵，未定论 |

#### API

```python
class SentimentAnalyzer:
    def analyze_articles(self, articles: list[dict]) -> list[dict]:
        """批量情感分析，返回带 sentiment_label/score/confidence 的文章列表"""

    def analyze_distribution(self, sentiment_results: list[dict]) -> dict:
        """计算情感分布，返回 {label: proportion}"""

    def detect_sentiment_trajectory(
        self,
        today: list[dict],
        yesterday: list[dict],
    ) -> dict:
        """对比今日与昨日情感分布，生成演变轨迹"""
```

---

### 3.4 PredictionEngine — 事件预测引擎（新增 Service）

**文件路径**: `backend/services/prediction_engine.py`

**定位**: Trend Agent → PredictionAgent 的核心增强，参考 BettaFish ForumHost 的预测逻辑。

#### PEST 宏观分析

```python
PEST = {
    Political:   "趋势 ∈ {正面利好/负面影响/中性/不确定/持续观察}",
    Economic:   "趋势 ∈ {正面利好/负面影响/中性/不确定/持续观察}",
    Social:     "趋势 ∈ {正面利好/负面影响/中性/不确定/持续观察}",
    Tech:       "趋势 ∈ {正面利好/负面影响/中性/不确定/持续观察}",
}
```

#### SWOT 四象限分析

```python
SWOT = {
    Strengths:     [  {title, text, impact: 低/中低/中/中高/高/极高}, ... ],
    Weaknesses:    [  {title, text, impact: ...}, ... ],
    Opportunities: [  {title, text, impact: ...}, ... ],
    Threats:       [  {title, text, impact: ...}, ... ],
}
```

#### 趋势预测输出模板

```
舆情发展预判：
预计在未来 3-7 天内，该话题将呈现 [上升/平稳/下降] 趋势，
主要风险点：[具体描述]，
主要机遇点：[具体描述]。
```

**注意**：这里的预测是基于信号强度的 LLM 推演，不是统计外推。BettaFish 的局限性（无 ARIMA/Prophet）同样适用于此。

#### API

```python
class PredictionEngine:
    def analyze_pest(self, context: "PredictionContext") -> dict:
        """PEST 四维度宏观分析"""

    def analyze_swot(self, context: "PredictionContext") -> dict:
        """SWOT 四象限分析"""

    def predict_trend(
        self,
        context: "PredictionContext",
        pest: dict,
        swot: dict,
    ) -> dict:
        """基于 PEST + SWOT + 信号强度，生成 3-7 天趋势研判"""
```

---

### 3.5 EventDeduplicationNode — 跨 Agent 去重节点（新增）

**文件路径**: `backend/agents/orchestrator/dedup_node.py`

**定位**: Orchestrator fan_in() 之后、ReportComposer 之前。

#### 去重策略

1. **HotTopics ↔ DeepSummary 事件匹配**：通过标题/摘要的 embedding 余弦相似度匹配
2. **相似度阈值**：> 0.7 认为是同一事件
3. **合并规则**：保留 HotTopics 的 `hot_score`，融合 DeepSummary 的 `What/Who/Why/Impact`
4. **unified_ranking_score** = `hot_score × 0.6 + persistence_score × 0.4`

---

## 四、增强后的 Agent 流水线

### 4.1 HotTopics Agent 增强

**当前流程**：
```
SortNode → ScoreNode → DedupeNode → RankNode
（二元摘要判断） （单次LLM评分） （LLM隐式去重） （截取Top10）
```

**增强后流程**：
```
┌─────────────────────────────────────────────────────────────┐
│ PreScoringNode — ScoringEngine 多信号评分                   │
│   → composite_score 计算                                    │
│   → 多样性采样（每来源最多5篇）                            │
│   ↓ 取前50篇                                               │
│ SemanticClusteringNode — ClusteringEngine 聚类             │
│   → KMeans 语义聚类（防热点掩盖）                          │
│   → 每簇固定配额采样                                       │
│   ↓                                                        │
│ LLM ScoringNode — LLM 对聚类后文章批量评分                  │
│   → 参考 composite_score 作为 LLM 打分的上下文提示          │
│   ↓                                                        │
│ DedupeNode — 标题/摘要相似度去重（TF-IDF 或 embedding）      │
│   ↓                                                        │
│ RankNode — 综合 LLM分数 + composite_score 双重排序          │
│   ↓ 输出 Top 10                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 DeepSummary Agent 增强

**当前流程**：
```
GroupNode → ExtractNode → StructureNode → ImpactNode
（摘要>50char）  （单次LLM聚类）  （What/Why/Who/Impact） （持续性分数）
```

**增强后流程**：
```
┌─────────────────────────────────────────────────────────────┐
│ PreScoringNode — ScoringEngine（取前30篇）                  │
│   ↓                                                        │
│ SemanticClusteringNode — ClusteringEngine                   │
│   → KMeans 聚类，发现事件簇                                 │
│   → 新兴主题检测（与昨日对比）                              │
│   ↓                                                        │
│ SentimentEnrichmentNode — SentimentAnalyzer                 │
│   → 对每个簇内的文章批量情感分析                            │
│   → 输出: sentiment_distribution per cluster                │
│   ↓                                                        │
│ LLM ExtractNode — LLM 聚类 + 生成事件摘要                   │
│   → 继承 ClusteringEngine 的簇划分                          │
│   → 继承 SentimentAnalyzer 的情感分布                        │
│   ↓                                                        │
│ StructureNode + ImpactNode                                  │
│   → What/Why/Who/Impact + 持续性分数                        │
│   → 新增: sentiment_confidence, emerging_score             │
│   ↓ 输出 Top 10                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 Prediction Agent（Trend 增强）

**当前流程**：
```
4维度并行（Tech/App/Policy/Capital）
  → 关键词过滤（前25篇）
  → 4× LLM Sub-Nodes
  → 跨维度高置信度信号提取
```

**增强后流程**：
```
┌─────────────────────────────────────────────────────────────┐
│ PEST RoutingNode — PEST 四维度 + 关键词双重路由              │
│                                                             │
│   Tech       → tech关键词 + tech_score 加权的文章            │
│   Economic   → capital/app关键词 + 金额相关词                │
│   Social    → opinion/emotion关键词 + high_sentiment        │
│   Political → policy/regulation关键词 + gov相关词           │
│                                                             │
│   动态调整: 高 confidence 维度分配更多 token                  │
│   ↓                                                        │
│ 4维度 LLM Sub-Nodes 并行（加权的文章子集）                  │
│   ↓                                                        │
│ SignalAggregationNode — 跨维度信号聚合                        │
│   → 高置信度 + 高 composite_score 的跨维度信号优先           │
│   → 识别同时出现在多维度的事件（最具影响力）                  │
│   ↓                                                        │
│ PEST SynthesisNode — LLM 生成 PEST 四维度趋势分析            │
│   → 每个维度: trend ∈ {正面利好/负面影响/中性/不确定/持续观察} │
│   → 理由分析（100字以内）                                   │
│   ↓                                                        │
│ SWOTSynthesisNode — LLM 生成 SWOT 四象限分析                 │
│   → 4类各输出 2-3 条                                        │
│   → 每条: title + text + impact ∈ {低/中低/中/中高/高/极高}  │
│   ↓                                                        │
│ TrendPredictionNode — BettaFish ForumHost 风格的趋势研判   │
│   → 基于 PEST + SWOT + 信号强度，预测 3-7 天趋势            │
│   → 风险点 + 机遇点识别                                     │
│   → 时间线预测                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 五、增强后的 Orchestrator 流水线

**当前流程**：
```
build_context() → fan_out(3×Agent并行) → fan_in() → compose()
                 （3个Agent共享相同文章，无预评分）
```

**增强后流程**：
```
┌──────────────────────────────────────────────────────────────┐
│ Step 1: build_context()                                       │
│   → 从 SQLite 读取最近 N 天文章                                │
│   → 新增: 加载昨日聚类结果（用于新兴主题检测）                 │
│   → 新增: 加载昨日情感分布（用于情感演变轨迹）                 │
│   → 新增: DailyReportContext 增加 prediction_context 字段      │
│                                                              │
│ Step 2: scoring_prepass() [NEW]                               │
│   → ScoringEngine 对全部文章计算 composite_score             │
│   → ClusteringEngine 聚类，识别新兴主题                       │
│   → SentimentAnalyzer 批量情感分析                            │
│   → 生成 PredictionContext                                    │
│                                                              │
│ Step 3: fan_out() — 3个Agent并行                            │
│   → HotTopicsAgent     接收: 聚类+评分后的 Top-50 文章        │
│   → DeepSummaryAgent   接收: 聚类+情感后的文章子集            │
│   → PredictionAgent    接收: 全量信号 + PEST维度路由文章      │
│   （注：Trend Agent 改名为 PredictionAgent，承担 PEST/SWOT）   │
│                                                              │
│ Step 4: fan_in() + EventDeduplicationNode() [NEW]           │
│   → 3个Agent结果聚合                                         │
│   → 跨Agent去重：HotTopics ↔ DeepSummary 事件相似度匹配      │
│   → 合并为 unified_event_list                               │
│   → 新增: unified_ranking_score（综合 HotTopics + DeepSummary）│
│                                                              │
│ Step 5: compose()                                            │
│   → 最终报告:                                                 │
│     hot_topics[:5]         — Top 5 热点                       │
│     deep_events[:3]       — Top 3 深度事件                   │
│     emerging_themes[]     — 新兴主题列表                     │
│     swot_analysis         — SWOT 四象限                       │
│     pest_analysis         — PEST 四维度                       │
│     trend_prediction      — 3-7天 趋势研判                    │
│     cross_dimension_signals — 跨维度高置信度信号              │
│     sentiment_trajectory  — 情感演变轨迹                      │
└──────────────────────────────────────────────────────────────┘
```

---

## 六、数据模型变更

### 6.1 articles 表新增字段

```sql
ALTER TABLE articles ADD COLUMN composite_score REAL;
ALTER TABLE articles ADD COLUMN authority_score REAL;
ALTER TABLE articles ADD COLUMN cluster_id INTEGER;
ALTER TABLE articles ADD COLUMN sentiment_label TEXT;
ALTER TABLE articles ADD COLUMN sentiment_score REAL;
ALTER TABLE articles ADD COLUMN sentiment_confidence REAL;
```

### 6.2 新增 articles_signals 表（中间信号表）

```sql
CREATE TABLE articles_signals (
    id TEXT PRIMARY KEY,
    article_id TEXT REFERENCES articles(id),
    date TEXT,
    engagement_score REAL,
    authority_score REAL,
    recency_score REAL,
    content_quality_score REAL,
    controversy_score REAL,
    breakthrough_score REAL,
    composite_score REAL,
    sentiment_label TEXT,
    sentiment_score REAL,
    sentiment_confidence REAL,
    cluster_id INTEGER,
    cluster_topic_label TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_id, date)
);
```

### 6.3 新增 daily_clusters 表（用于跨时间窗口对比）

```sql
CREATE TABLE daily_clusters (
    id TEXT PRIMARY KEY,
    date TEXT,
    cluster_id INTEGER,
    avg_composite_score REAL,
    size INTEGER,
    topic_label TEXT,
    is_emerging BOOLEAN DEFAULT FALSE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date, cluster_id)
);
```

---

## 七、需要实现的模块清单

| # | 模块名 | 类型 | 依赖 | 输入 | 输出 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | `ScoringEngine` | 新增 Service | 无 | `List[Article]` | `List[Article]` + `composite_score` | P0 |
| 2 | `ClusteringEngine` | 新增 Service | `sentence-transformers`, `scikit-learn` | `List[Article]` | `ClusterResult[]` + 采样文章 | P0 |
| 3 | `SentimentAnalyzer` | 新增 Service | `transformers`（可选本地模型） | `List[Article]` | `sentiment_label/score/confidence` | P1 |
| 4 | `PredictionEngine` | 新增 Service | LLM Client | `PredictionContext` | `PEST` + `SWOT` + `TrendPrediction` | P0 |
| 5 | `EventDeduplicationNode` | 新增跨Agent节点 | `ClusteringEngine` | `HotTopics` + `DeepSummary` 结果 | `UnifiedEventList` | P1 |
| 6 | `HotTopics Agent` 增强 | 增强 | `ScoringEngine` | `DailyReportContext` | 预评分后的文章子集 | P0 |
| 7 | `DeepSummary Agent` 增强 | 增强 | `ScoringEngine`, `ClusteringEngine`, `SentimentAnalyzer` | `DailyReportContext` | 带情感的深度事件 | P0 |
| 8 | `Prediction Agent`（原Trend）增强 | 增强 | `ScoringEngine`, `PredictionEngine` | `DailyReportContext` | PEST + SWOT + 趋势预测 | P0 |
| 9 | `Orchestrator` 增强 | 增强 | 上述全部 | — | 新增 `scoring_prepass` + `EventDeduplication` | P0 |
| 10 | `ReportComposer` 增强 | 增强 | 无 | 增强后的 Agent 结果 | 新增 swot/pest/trend_prediction 章节 | P0 |
| 11 | 依赖安装 | 基础设施 | — | — | `pip install sentence-transformers scikit-learn` | P0 |
| 12 | DB Migration | 数据 | — | — | 新增字段 + 新表 | P0 |

---

## 八、架构全貌

```
                                    ┌────────────────────────────────────────────┐
                                    │         数据采集层 (RSS Crawler)           │
                                    │                                            │
                                    │  TechCrunch / The Verge / 机器之心 / arXiv  │
                                    │  GitHub Releases / HackerNews / Product Hunt│
                                    └────────────────────────┬───────────────────┘
                                                             ↓
                         ┌────────────────────────────────────────────────────┐
                         │                  articles 表                       │
                         │  title / summary / source / published_at / tags    │
                         │  reading_time_minutes / language                   │
                         └────────────────────────┬───────────────────────────┘
                                                  ↓
                         ┌────────────────────────────────────────────────────┐
                         │              Orchestrator                          │
                         │  build_context() → scoring_prepass() [NEW]         │
                         │                     ↓                              │
                         │  ┌──────────────────────────────────────────┐      │
                         │  │  ScoringEngine — 多信号热度评分         │      │
                         │  │  ClusteringEngine — 语义聚类             │      │
                         │  │  SentimentAnalyzer — 情感分析            │      │
                         │  └──────────────────────────────────────────┘      │
                         └────────────────────────┬───────────────────────────┘
                                                  ↓
                    ┌────────────────────────────┤
                    ↓                            ↓                            ↓
        ┌───────────────────────┐  ┌───────────────────────┐  ┌──────────────────────────────┐
        │   HotTopicsAgent        │  │  DeepSummaryAgent     │  │  PredictionAgent (原Trend)    │
        │   (增强)                │  │  (增强)                │  │  (增强)                        │
        │                         │  │                       │  │                               │
        │  PreScoringNode         │  │  PreScoringNode       │  │  PEST RoutingNode              │
        │  SemanticClustering     │  │  ClusteringNode       │  │  SignalAggregation             │
        │  LLM ScoringNode        │  │  SentimentEnrichment  │  │  PEST SynthesisNode            │
        │  DedupeNode             │  │  LLM ExtractNode      │  │  SWOTSynthesisNode             │
        │  RankNode               │  │  StructureNode+Impact │  │  TrendPredictionNode            │
        └───────────┬─────────────┘  └───────────┬───────────┘  └──────────────┬───────────────┘
                    ↓                            ↓                            ↓
                    └────────────────────────────┤
                                                  ↓
                              ┌─────────────────────────────────────────────┐
                              │  EventDeduplicationNode [NEW]                  │
                              │  跨Agent去重：HotTopics ↔ DeepSummary          │
                              │  unified_ranking_score 双重排序                 │
                              └────────────────────────┬────────────────────────┘
                                                       ↓
                              ┌─────────────────────────────────────────────┐
                              │           ReportComposer (增强)               │
                              │                                              │
                              │  hot_topics[:5]     ← Top 5 热点              │
                              │  deep_events[:3]    ← Top 3 深度事件          │
                              │  emerging_themes[]  ← 新兴主题                 │
                              │  swot_analysis      ← SWOT 四象限             │
                              │  pest_analysis      ← PEST 四维度             │
                              │  trend_prediction   ← 3-7天趋势研判            │
                              │  sentiment_trajectory ← 情感演变               │
                              └─────────────────────────────────────────────┘
```

---

## 九、实现顺序建议

### Phase 1: 基础设施（P0，不改变现有 Agent 逻辑）

1. 安装依赖：`pip install sentence-transformers scikit-learn`
2. 实现 `ScoringEngine`（最简单，立即可用，不影响现有流程）
3. DB Migration：新增字段

### Phase 2: 聚类层（P0，增强 HotTopics + DeepSummary）

4. 实现 `ClusteringEngine`
5. 增强 `HotTopics Agent`：PreScoringNode + SemanticClusteringNode
6. 增强 `DeepSummary Agent`：接入聚类结果

### Phase 3: 情感+预测层（P0，增强 Trend → PredictionAgent）

7. 实现 `SentimentAnalyzer`
8. 实现 `PredictionEngine`（PEST + SWOT + TrendPrediction）
9. 增强 `Trend Agent` → `PredictionAgent`

### Phase 4: 编排增强（P0）

10. 增强 `Orchestrator`：scoring_prepass + EventDeduplicationNode
11. 增强 `ReportComposer`：新增章节模板

### Phase 5: 优化（P1）

12. 新兴主题检测（跨时间窗口对比）
13. 情感演变轨迹追踪
14. 来源权威性权重调优
15. 参与度字段扩展（RSS → 爬虫 → 社交数据）

---

*文档参考: [BettaFish 事件预测机制深度解析](../guide/bettafish-prediction-mechanism.md)*
