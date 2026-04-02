# InsightPulse V2 — AI 领域信号工程层设计

> 本文档为 [V2 事件预测架构](./v2-event-prediction-architecture.md) 的信号工程层补充，专注解决一个核心矛盾：
> **传统社交热度信号（分享/收藏/评论/点赞）在 AI RSS 场景中几乎完全不可用，需要从零构建一套领域适配的信号体系。**

---

## 目录

1. [核心矛盾：为什么社交信号不适用于 AI RSS](#一核心矛盾为什么社交信号不适用于-ai-rss)
2. [信号分层架构总览](#二信号分层架构总览)
3. [信号采集层：AI RSS 场景下可获取的原始数据](#三信号采集层ai-rss-场景下可获取的原始数据)
4. [信号工程层：六大维度设计](#四信号工程层六大维度设计)
5. [综合信号评分公式](#五综合信号评分公式)
6. [信号可观测性与调优](#六信号可观测性与调优)
7. [信号层与现有架构的衔接](#七信号层与现有架构的衔接)

---

## 一、核心矛盾：为什么社交信号不适用于 AI RSS

### 1.1 社交平台热度信号的假设前提

BettaFish 设计的「分享×10 > 评论×5 > 点赞×1」加权体系，建立在以下前提之上：

| 假设 | 前提描述 | AI RSS 场景 |
|---|---|---|
| 存在分享行为 | 用户主动转发到自己的社交网络 | ❌ RSS 是单向拉取，无转发机制 |
| 存在收藏行为 | 用户主动收藏以便后续阅读 | ❌ RSS 无用户收藏体系 |
| 存在评论数据 | 讨论质量可量化 | ❌ arXiv 等源无评论；科技媒体无评论数据 |
| 存在点赞数据 | 群体认可程度可量化 | ❌ RSS 协议本身不支持 |
| 存在阅读量数据 | 曝光基数可追踪 | ❌ 纯 RSS 场景无曝光统计 |

**结论**：如果直接将 BettaFish 的热度公式照搬到 AI RSS 场景，`engagement_score` 将全部为 0 或接近 0，综合分退化为「权威性 × 时效性」，失去热度排序的意义。

### 1.2 AI RSS 场景的独特信号优势

虽然缺少社交互动数据，AI RSS 场景有其他平台不具备的独特信号：

| 信号类型 | 可用性 | 价值 |
|---|---|---|
| **学术引用数据** | 可通过 Semantic Scholar API 获取 | 论文影响力最直接的量化指标 |
| **多源交叉验证** | 同一事件在多个源同时出现 | 比单源阅读量更强的传播信号 |
| **技术关键词密度** | 从摘要/标题直接提取 | 可区分「技术突破」与「行业新闻」 |
| **arXiv 分类体系** | cs.AI/cs.LG/cs.CL/cs.CV 不同权重 | 不同子领域有不同的热度基线 |
| **代码/数据集存在性** | GitHub/Colab 链接存在 | 可判断是否为可复现研究 |
| **HackerNews 分数** | HN 的 upvote+comment 混合指标 | 工程师社区的「点赞+评论」替代指标 |
| **官方首发 vs 转发** | 官方博客直接发布 vs 媒体报道 | 首发源的权威性显著高于转发 |

---

## 二、信号分层架构总览

### 2.1 四层信号体系

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         信号采集层 (Raw Data)                            │
│                                                                         │
│  articles 表基础字段  │  source_metadata 扩展  │  外源 API (可选)        │
│  title/summary/URL   │  arXiv: citations,     │  Semantic Scholar API   │
│  published_at/source │    authors/categories  │  HackerNews API         │
│  tags/read_time      │  HN: score/comments    │  Cross-source crawler   │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓ 特征工程
┌─────────────────────────────────────────────────────────────────────────┐
│                         信号工程层 (Signals)                              │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ 权威性信号    │  │ 学术性信号   │  │ 社区共鸣信号  │  │ 时效性信号  │ │
│  │ Authority    │  │ Academic     │  │ Community    │  │ Recency     │ │
│  │              │  │              │  │              │  │             │ │
│  │ 来源类型权重  │  │ 引用数       │  │ HN 分数/排名  │  │ 指数衰减    │ │
│  │ 子源精细权重  │  │ arXiv子域权重│  │ 跨源扩散速度  │  │ 半衰期模型  │ │
│  │ 首发 vs 转发  │  │ 作者机构权重  │  │ 社区响应速度  │  │             │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │
│                                                                         │
│  ┌──────────────────────┐  ┌────────────────────────────────────────┐  │
│  │ 内容质量信号           │  │ 语义新颖性信号                          │  │
│  │ ContentQuality       │  │ SemanticNovelty                        │  │
│  │                      │  │                                        │  │
│  │ 摘要/正文长度         │  │ TF-ICF (词频-逆簇频)                    │  │
│  │ 技术词汇密度          │  │ 跨簇唯一性                              │  │
│  │ 代码/数据集存在        │  │ 技术术语新鲜度                          │  │
│  │ 突破词/争议词命中     │  │ 新兴子领域检测                          │  │
│  └──────────────────────┘  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         综合评分层 (Scoring)                             │
│                                                                         │
│  composite_score = w1×authority × w2×academic × w3×community           │
│                  × w4×recency × w5×content_quality × w6×semantic_novelty│
│                  + w7×controversy_bonus + w8×breakthrough_bonus        │
│                                                                         │
│  每个权重通过 A/B 测试调优，初期可设为:                                   │
│  w1=2.0, w2=1.5, w3=1.8, w4=1.2, w5=1.0, w6=1.0                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                         预测引擎层 (Prediction)                          │
│  ScoringEngine → ClusteringEngine → SentimentAnalyzer → PredictionEngine  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 信号可用性矩阵（按来源）

| 信号维度 | 官方博客 | arXiv | 科技媒体 | HackerNews | Product Hunt |
|---|---|---|---|---|---|
| **权威性信号** | ✅ 最高 | ✅ 高 | ✅ 中 | ✅ 中 | ✅ 低 |
| **学术性信号** | ❌ 无 | ✅ 引用/分类 | ❌ 无 | ❌ 无 | ❌ 无 |
| **社区共鸣信号** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ HN 分数 | ✅ PH 分数 |
| **时效性信号** | ✅ 发布时 | ✅ 发布时 | ✅ 发布时 | ✅ 提交时 | ✅ 发布时 |
| **内容质量信号** | ✅ 全文 | ⚠️ 仅摘要 | ✅ 全文 | ⚠️ 标题摘要 | ✅ 全文 |
| **语义新颖性信号** | ✅ 可计算 | ✅ 可计算 | ✅ 可计算 | ✅ 可计算 | ✅ 可计算 |
| **跨源扩散信号** | ✅ 可追踪 | ✅ 可追踪 | ✅ 可追踪 | ✅ 可追踪 | ✅ 可追踪 |

---

## 三、信号采集层：AI RSS 场景下可获取的原始数据

### 3.1 articles 表基础字段（已有）

| 字段 | 可提取信号 | 备注 |
|---|---|---|
| `title` | 技术词汇密度、突破词/争议词命中、语义 embedding | 最重要的原始文本 |
| `summary` | 同上，且可计算摘要长度 | arXiv 仅含 Abstract |
| `url` | 可追踪跨源扩散（相同 URL 被多个源报道）| |
| `source` | 映射到权威性权重表 | 第一层来源过滤 |
| `published_at` | 时效性衰减基础 | 精确到分钟更好 |
| `author` | 可关联到作者历史影响力 | 需扩展数据源 |
| `tags` | 预定义标签权重 | 需维护标签权重表 |
| `language` | 中/英内容区分 | 不同语言热度基线不同 |
| `image_url` | 目前未使用 | 未来可用于多模态信号 |
| `reading_time_minutes` | 内容深度代理指标 | |

### 3.2 articles 表扩展字段（建议新增）

| 字段 | 来源 | 用途 |
|---|---|---|
| `external_id` | HN ID / arXiv ID / 产品 ID | 跨平台关联 |
| `external_score` | HN upvotes / PH votes | 社区共识量化 |
| `external_comments` | HN comment count / PH reviews | 讨论深度 |
| `external_rank` | HN rank (当天排名) | 比原始分数更稳定 |
| `has_code` | GitHub / Colab / GitLab 链接检测 | 技术可复现性信号 |
| `has_dataset` | 数据集引用检测 | 研究完整性信号 |
| `has_pdf` | arXiv PDF 链接存在性 | 学术严谨性信号 |
| `title_embedding` | 预计算 title 向量 (384d) | 聚类和相似度计算 |

### 3.3 外源 API 数据（可选，非阻塞）

#### HackerNews API 数据

```
GET https://hacker-news.firebaseio.com/v0/item/{id}.json
返回:
  - score: upvotes 数量
  - descendants: 评论数
  - time: Unix 时间戳（与 published_at 对比可得 HN 上榜速度）
  - url: 原链（可与 articles.url 匹配）
```

**交叉匹配策略**：
1. 爬取 HN 当天所有 AI 相关提交（通过关键词过滤）
2. 从 articles 表查询 url 匹配
3. 匹配成功 → 获取 HN score + descendants
4. 未匹配但 title 相似度 > 0.8 → 同样获取数据（跨源报道判断）

#### Semantic Scholar API 数据

```
GET https://api.semanticscholar.org/graph/v1/paper/{arxiv_id}?fields=citationCount,influentialCitationCount,authors
返回:
  - citationCount: 总引用数
  - influentialCitationCount: 高影响力引用数
  - authors: 作者列表（可构建作者权重）
```

**信号价值**：
- citationCount > 50 → 高影响力论文，热度基准分 +1.0
- influentialCitationCount > 10 → 技术突破信号，breakthrough_bonus +2.0
- 作者历史引用数高 → 作者权威性独立权重

---

## 四、信号工程层：六大维度设计

### 4.1 权威性信号（Authority Signal）

**设计原理**：AI 领域信息来源的权威性差异远大于一般新闻。arXiv 一篇论文和一篇营销博客在技术社区的影响力有本质区别。

#### 4.1.1 一级来源类型权重

| 来源类别 | 权重 | 说明 |
|---|---|---|
| 官方首发（Official First）| **3.0** | OpenAI/DeepMind/Anthropic 官方博客直接发布 |
| 学术顶会/顶刊（Academic Top）| **2.5** | Nature AI、arXiv 重要子域（cs.LG/cs.CL 优先于 cs.AI）|
| 高影响力媒体（Media High）| **2.0** | MIT Tech Review、The Verge、TechCrunch |
| 学术/社区媒体（Media Medium）| **1.5** | The Gradient、Synced Review、InfoQ |
| 社区/聚合（Community）| **1.3** | Hacker News 官方 RSS、Product Hunt |
| 其他来源（Other）| **1.0** | 未分类来源 |

#### 4.1.2 二级子源精细权重

在一级分类内，不同来源的权重也有显著差异：

| 来源 | 一级分类 | 二级权重修正 |
|---|---|---|
| OpenAI Blog | Official | ×1.0 (基准) |
| DeepMind Blog | Official | ×1.0 |
| Anthropic Blog | Official | ×1.0 (新建但权威) |
| NVIDIA Blog | Official | ×0.8 (偏向商业) |
| Nature AI | Academic | ×1.0 |
| arXiv cs.LG | Academic | ×1.0 (ML 核心) |
| arXiv cs.CL | Academic | ×1.0 (NLP 核心) |
| arXiv cs.CV | Academic | ×0.9 (CV 热度基线较高) |
| arXiv cs.AI | Academic | ×0.8 (综述性文章偏多) |
| MIT Tech Review | Media High | ×1.0 |
| VentureBeat AI | Media High | ×0.9 |
| TechCrunch AI | Media High | ×0.8 (商业化报道偏多) |
| The Gradient | Media Medium | ×1.0 |
| Hacker News AI/ML | Community | ×1.0 |
| HN Front Page | Community | ×1.2 (全站顶流) |
| Product Hunt | Community | ×0.8 (偏新产品，非深度) |

#### 4.1.3 首发信号（First Publication）

**核心假设**：同一事件，首发源的权威性 > 转发报道。

检测方法：
1. 对每篇文章，在±6小时时间窗口内搜索其他源是否报道了相同事件
2. 匹配规则：`title similarity > 0.75` OR `url domain 相同 + 时间差 < 12h`
3. 首发文章：`first_publication_bonus = 1.5`（权威首发额外加权）
4. 非首发：`first_publication_bonus = 1.0`

> 注：「首发」的判断是「事件」级别而非「文章」级别——需要通过 clustering 先识别出哪些文章属于同一个事件。

#### 4.1.4 官方认证信号（Official Certification）

部分来源具有「官方认证」属性：

| 信号 | 条件 | bonus |
|---|---|---|
| 官方博客首发 | source ∈ {OpenAI, DeepMind, Anthropic, Google AI} 且为当天首发 | +1.5 |
| 官方 API/SDK 发布 | title 含 "API", "SDK", "release", "launch" | +1.0 |
| 官方论文发布 | source = arXiv 且有官方博客同步发布 | +1.0 |

---

### 4.2 学术性信号（Academic Signal）

**设计原理**：学术论文是 AI 领域最前沿的信息载体，但「学术价值 ≠ 热度」，需要从学术性指标中提取可量化的热度代理信号。

#### 4.2.1 arXiv 子域热度基线修正

不同 arXiv 子域的每日论文产量差异巨大，产量越大的子域，单篇文章的「稀缺性」越低：

| 子域 | 日均论文量 | 基线修正系数 | 说明 |
|---|---|---|---|
| cs.LG (Machine Learning) | ~300 | ×1.0 (基准) | 核心子域 |
| cs.CV (Computer Vision) | ~200 | ×0.9 | CV 领域成熟，论文密度高 |
| cs.CL (Computation and Language) | ~150 | ×1.1 | 大模型热潮，NLP 关注度高 |
| cs.AI (Artificial Intelligence) | ~200 | ×0.8 | 综述性文章多，稀缺性低 |
| cs.RO (Robotics) | ~50 | ×1.2 | 小众子域，单篇稀缺性高 |
| cs.CL + cs.LG 联合 | — | ×1.3 | LLM 相关，特殊加权 |

#### 4.2.2 引用信号（Citation Signal）

通过 Semantic Scholar API 获取（异步爬取，不阻塞主流程）：

| 引用数范围 | 学术影响力权重 | 说明 |
|---|---|---|
| citationCount = 0 (新论文) | ×1.0 + `new_paper_bonus = 1.2` | 新论文稀缺性高 |
| 1 ≤ citationCount < 10 | ×1.0 | 一般 |
| 10 ≤ citationCount < 50 | ×1.3 | 开始受到关注 |
| 50 ≤ citationCount < 200 | ×1.6 | 高影响力 |
| citationCount ≥ 200 | ×2.0 | 里程碑级论文 |
| influentialCitationCount ≥ 10 | `breakthrough_bonus += 2.0` | 被引用催生了后续重要工作 |

**数据获取策略**：
- 在 `seed_default_feeds` 爬取时，异步请求 Semantic Scholar API
- 结果写入 `arxiv_metadata` 表（新增）
- 每日增量更新引用数

#### 4.2.3 作者/机构权威性（Author Authority）

| 机构类型 | 权重修正 |
|---|---|
| 顶级 AI 实验室（OpenAI/DeepMind/Google/Anthropic/Meta AI）| ×1.5 |
| 顶级高校（Stanford ML Group/MIT CSAIL/Berkeley RLAI）| ×1.3 |
| 一般高校 | ×1.0 |
| 未知/个人 | ×0.9 |

> 数据来源：通过 arXiv API 获取作者列表，查询已知机构关键词（Google/Stanford/MIT/Berkeley 等）

#### 4.2.4 代码/数据集可复现性（Reproducibility）

| 条件 | 权重修正 | 说明 |
|---|---|---|
| `has_code = True` | ×1.3 | GitHub/Colab/示例代码存在 |
| `has_dataset = True` | ×1.2 | 数据集/基准存在 |
| `has_code AND has_dataset` | ×1.5 | 完整可复现研究 |
| PDF 链接存在（仅 arXiv）| ×1.05 | 完整论文，学术严谨性 |

---

### 4.3 社区共鸣信号（Community Signal）

**设计原理**：HackerNews 和 Product Hunt 是工程师/创业者社区的信息过滤器， HN 分数和评论数本质上混合了「认可（点赞）」+「讨论深度（评论）」两种信息，可作为 AI 领域的「社区版互动信号」。

#### 4.3.1 HackerNews 评分模型

HN 没有传统意义的「点赞数」公开 API，但 HN 的排序算法本身就是一种社区信号：

```
hn_score_normalized = min(1.0, hn_score / 100)
hn_comments_normalized = min(1.0, hn_comments / 50)
community_score = hn_score_normalized × 0.6 + hn_comments_normalized × 0.4
```

| HN 场景 | 分数/评论数 | community_score | 说明 |
|---|---|---|---|
| HN Front Page 文章 | score > 100 | 0.8-1.0 | 全站顶流，工程师社区共识 |
| HN AI/ML 高分 | 50 ≤ score < 100 | 0.5-0.8 | 专项社区认可 |
| HN 普通 | 10 ≤ score < 50 | 0.1-0.5 | 一般讨论 |
| HN 低分/新提交 | score < 10 | 0.0-0.1 | 早期发现 |
| 0 分（新提交未上榜）| score = 0 | 0.0 | 无信号 |

#### 4.3.2 HN 上榜速度信号（Trending Velocity）

**核心假设**：同一事件，在 HN 上越快被社区发现并投票，说明工程师社区对该话题的即时兴趣越高。

```
time_to HN_score_above_10 = (time_when_score>=10) - published_at

if time_to HN_score_above_10 < 2 hours → trending_velocity_bonus = 1.5 (爆款信号)
elif time_to HN_score_above_10 < 6 hours → trending_velocity_bonus = 1.2
elif time_to HN_score_above_10 < 24 hours → trending_velocity_bonus = 1.0
else → trending_velocity_bonus = 0.9
```

#### 4.3.3 跨源扩散速度（Cross-Source Diffusion）

**核心假设**：同一事件被越多不同类型来源报道，说明该事件的跨圈层影响力越大。

```
same_event_sources = count(distinct source_category WHERE title_similarity > 0.75)

if same_event_sources >= 4 → diffusion_score = 1.5 (跨圈层爆款)
elif same_event_sources == 3 → diffusion_score = 1.3 (多圈层传播)
elif same_event_sources == 2 → diffusion_score = 1.1 (双源确认)
else → diffusion_score = 1.0 (单一来源)
```

> 实现方式：在聚类后，对每个簇内的文章统计来源类型分布。簇内来源类型越多，扩散信号越强。

---

### 4.4 时效性信号（Recency Signal）

**设计原理**：AI 领域信息淘汰速度极快——一篇 72 小时前的论文可能已被新研究「超越」，但一篇 72 小时前的行业分析文章仍可能有价值。因此时效性衰减需区分内容类型。

#### 4.4.1 半衰期模型（按内容类型）

| 内容类型 | 半衰期 | 适用场景 |
|---|---|---|
| 官方新闻/产品发布 | 6 小时 | 新产品发布、API 更新，半衰期最短 |
| 科技媒体报道 | 12 小时 | 行业快讯 |
| HN 社区讨论 | 18 小时 | 社区热点消退较快 |
| 学术论文（arXiv）| 48 小时 | 研究论文生命周期较长 |
| 深度分析/综述 | 72 小时 | 深度分析类价值衰减最慢 |

#### 4.4.2 时效性分计算公式

```python
def recency_score(published_at: datetime, content_type: str) -> float:
    hours_ago = (now_utc() - published_at).total_seconds() / 3600
    half_life = CONTENT_TYPE_HALF_LIFE[content_type]  # 见上表
    score = 0.5 ** (hours_ago / half_life)

    # 最大值钳制：最新文章的 recency_score 上限为 1.0
    return min(1.0, score)

# 边界条件：
# - future articles → 1.0（预热内容，正常）
# - articles > 7 days old → 0.01（下限，防止完全归零影响排序）
```

#### 4.4.3 内容类型自动判断

通过规则从标题/摘要推断内容类型：

| 关键词命中 | 内容类型 |
|---|---|
| "release", "launch", "announce", "launches", "unveils" | official_news |
| "GPT", "Claude", "Gemini", "Llama", "model" + "API" | official_news |
| " HN: ", "Ask HN", "Show HN" | hn_discussion |
| "paper", "arxiv", "study", "research", "proposed" | academic_paper |
| "analysis", "review", "deep dive", "overview", "how to" | deep_analysis |
| 其他 | media_news |

---

### 4.5 内容质量信号（Content Quality Signal）

**设计原理**：AI RSS 场景下，内容质量是区分「技术深度」与「资讯快讯」的核心维度。深度内容通常有更长的摘要、更高的阅读时间、更丰富的技术细节。

#### 4.5.1 摘要/正文长度信号

```python
def content_length_score(summary: str, content: str | None) -> float:
    total_length = len(content or summary)
    # 学术论文：摘要 > 300 字为高质量（Abstract 本身较长）
    # 新闻报道：正文 > 500 字为深度报道
    # 取 min 避免过度加权超长内容
    return min(1.0, total_length / 800)
```

| 内容长度（字符）| 质量得分 | 说明 |
|---|---|---|
| < 100 | 0.1 | 标题党或极短摘要 |
| 100-300 | 0.3 | 短新闻/标题 |
| 300-800 | 0.6 | 标准报道 |
| 800-2000 | 0.9 | 深度报道 |
| > 2000 | 1.0 | 超长深度内容 |

#### 4.5.2 阅读时长信号

```python
def reading_time_score(reading_time_minutes: int | None) -> float:
    if not reading_time_minutes:
        return 0.3  # 无数据，保守估计
    return min(0.5, reading_time_minutes * 0.05)
```

#### 4.5.3 技术词汇密度（Technical Depth）

通过预定义的技术关键词表，计算标题+摘要中的技术词汇密度：

| 关键词类别 | 示例词汇 |
|---|---|
| 模型架构 | transformer, attention, diffusion, LLM, GPT, CNN, RL, GAN |
| 训练技术 | fine-tuning, RLHF, alignment, distillation, pruning, quantization |
| 应用领域 | multimodal, reasoning, code generation, agent, RAG, retrieval |
| 硬件/系统 | GPU, TPU, inference, training, scaling, parallelism |
| 评估方法 | benchmark, SOTA, ablation, evaluation, dataset, human eval |

```
tech_density = matched_keywords_count / total_words × 10
tech_density_score = min(1.0, tech_density)
```

**阈值解释**：
- tech_density > 0.1（每 10 个词有 1 个技术词）→ 强技术内容
- tech_density > 0.2 → 核心技术论文

#### 4.5.4 可复现性信号

| 条件 | 得分 |
|---|---|
| 包含 GitHub 链接 | +0.2 |
| 包含 Colab/ Kaggle 链接 | +0.2 |
| 包含数据集引用（Dataset: xxx）| +0.2 |
| 三项全有 | 上限 1.0 |

---

### 4.6 语义新颖性信号（Semantic Novelty Signal）

**设计原理**：AI 领域「热点事件」往往不是突然出现，而是从学术论文→技术博客→媒体报道→社区讨论逐步扩散。通过语义新颖性检测，可以在热点形成早期（前兆期）识别潜在事件。

#### 4.6.1 TF-ICF（词频-逆簇频）信号

传统 TF-IDF 在大规模语料上偏向高频词。TF-ICF 改用「当前簇的词频」替代「整个语料的词频」，更好地捕捉簇内独特性：

```
TF-ICF(word, article, cluster) = (term_frequency in article) / (inverse_cluster_frequency)

ICF = log(total_articles / articles_containing_word_in_cluster)
TF-ICF 越高 → 该词在此簇中越独特 → 文章越具簇内代表性
```

#### 4.6.2 跨簇唯一性（Cross-Cluster Uniqueness）

**核心假设**：如果一篇文章的内容与现有多个簇都有一定相似性，但又不完全属于任何一个簇，说明它可能是「新兴方向」或「跨领域创新」。

```python
def cross_cluster_uniqueness_score(article_embedding: np.array, cluster_centers: list[np.array]) -> float:
    similarities = [cosine_sim(article_embedding, center) for center in cluster_centers]
    max_sim = max(similarities)
    second_max_sim = sorted(similarities)[-2]

    # 如果与最相似簇的相似度不高（< 0.7），说明可能是全新方向
    # 如果与多个簇都有中等相似度（> 0.5），说明是跨领域文章
    if max_sim < 0.7:
        return 1.5  # 全新方向，高新颖性
    elif second_max_sim > 0.5:
        return 1.2  # 跨领域文章
    else:
        return 1.0  # 典型簇内文章
```

#### 4.6.3 技术术语新鲜度（Term Freshness）

监测「今天首次出现的技术词汇」，这类词往往代表新概念/新模型/新方法：

```python
def term_freshness_score(article_words: list[str], historical_term_frequency: dict) -> float:
    new_terms = sum(1 for w in article_words if historical_term_frequency.get(w, 0) == 0)
    total_terms = len(article_words)

    if total_terms == 0:
        return 1.0  # 无词可分析，保守

    # 首次出现词越多 → 新鲜度越高
    # 但超过 30% 新词的文章可能是噪音（如人名拼写变体）
    freshness_ratio = min(new_terms / total_terms, 0.3)
    return 0.5 + freshness_ratio * 2.0  # [0.5, 1.1]
```

#### 4.6.4 新兴子领域检测（Emerging Subfield）

通过对比昨日和今日的聚类结果，识别「新出现的语义方向」：

| 对比条件 | 判断 | 信号强度 |
|---|---|---|
| 今日新簇（昨日无相似簇，相似度 < 0.5）| 完全新兴子领域 | +2.0 |
| 旧簇规模增长 > 2× | 快速增长子领域 | +1.5 |
| 旧簇平均热度增长 > 1.5× | 快速升温子领域 | +1.2 |
| 跨 2 个以上子域的混合簇 | 交叉创新 | +1.0 |

---

## 五、综合信号评分公式

### 5.1 完整评分公式

```
composite_score = w_authority  × authority_score
                × w_academic   × academic_score
                × w_community  × community_score
                × w_recency    × recency_score
                × w_quality    × content_quality_score
                × w_novelty    × semantic_novelty_score
                + w_controversy × controversy_score
                + w_breakthrough × breakthrough_score
```

### 5.2 各维度得分范围

| 维度 | 得分范围 | 说明 |
|---|---|---|
| `authority_score` | [1.0, 3.0] | 一级分类 × 二级修正 × 首发加成 |
| `academic_score` | [0.8, 2.0] | 子域基线 × 引用修正 × 可复现性 |
| `community_score` | [0.0, 1.0] | HN 分数/评论归一化 |
| `recency_score` | [0.01, 1.0] | 半衰期衰减模型 |
| `content_quality_score` | [0.0, 1.0] | 长度 + 阅读时 + 技术密度 |
| `semantic_novelty_score` | [0.8, 1.5] | TF-ICF + 跨簇唯一性 + 新鲜度 |
| `controversy_score` | [0.0, 1.0] | 争议词命中密度 |
| `breakthrough_score` | [0.0, 1.0] | 突破词命中 + 高引用信号 |

### 5.3 权重配置与调优策略

#### 初期推荐权重（经验值）

```python
WEIGHTS = {
    "authority":    2.0,   # 权威性最重要：官方首发 vs 转载差异巨大
    "academic":    1.5,   # 学术性次之：引用数是强信号
    "community":   1.8,   # 社区共鸣：HN 分数是唯一互动信号
    "recency":     1.2,   # 时效性：权重适中，避免老文章长期霸榜
    "quality":     1.0,   # 内容质量：作为调节阀，不过度加权
    "novelty":     1.0,   # 语义新颖性：新兴方向需要被发现
    "controversy": 0.5,   # 争议加成：谨慎使用，避免噪声
    "breakthrough": 0.5,  # 突破加成：谨慎使用
}
```

#### 调优策略（A/B 测试）

```
阶段1（冷启动）：
  - 使用固定权重，每日报告后人工评估 Top-20 质量
  - 记录「应该更靠前但实际靠后」的案例

阶段2（数据积累）：
  - 建立人工标注数据集（100-200 篇，标注热度等级 1-5）
  - 用梯度下降优化权重，最小化 NDCG@20 损失

阶段3（动态调优）：
  - 按内容类型动态调整权重：
    - 学术日：authority × 1.5, academic × 2.0
    - 产品发布日：authority × 2.5, community × 1.5
    - 争议事件日：controversy × 2.0
```

---

## 六、信号可观测性与调优

### 6.1 信号分项日志

每次评分输出可解释的分项得分，用于人工审计和调优：

```python
@dataclass
class SignalBreakdown:
    article_id: str
    title: str

    # 各维度原始分
    authority_raw: float
    academic_raw: float
    community_raw: float
    recency_raw: float
    quality_raw: float
    novelty_raw: float

    # 各维度加权分
    authority_weighted: float
    academic_weighted: float
    community_weighted: float
    recency_weighted: float
    quality_weighted: float
    novelty_weighted: float

    # 加成项
    controversy_bonus: float
    breakthrough_bonus: float

    # 综合分
    composite_score: float

    # 排名上下文
    rank_in_source: int
    rank_global: int

    # 备注
    warnings: list[str]  # e.g. ["community_score=0 (no HN data)", "new_paper bonus applied"]
```

### 6.2 每日信号分布报告

```python
def generate_daily_signal_report(articles: list[dict], date: str) -> dict:
    """
    每日信号分布统计，用于监控信号异常和调优依据
    """
    scores = {
        "authority":   [a["authority_score"] for a in articles],
        "academic":    [a["academic_score"] for a in articles],
        "community":   [a["community_score"] for a in articles],
        "recency":     [a["recency_score"] for a in articles],
        "quality":     [a["content_quality_score"] for a in articles],
        "novelty":     [a["semantic_novelty_score"] for a in articles],
    }

    return {
        "date": date,
        "total_articles": len(articles),
        "distribution": {
            signal_name: {
                "mean": np.mean(vals),
                "std": np.std(vals),
                "p10": np.percentile(vals, 10),
                "p50": np.percentile(vals, 50),
                "p90": np.percentile(vals, 90),
                "min": min(vals),
                "max": max(vals),
            }
            for signal_name, vals in scores.items()
        },
        "top_sources_by_authority": source_distribution(articles, "authority"),
        "community_coverage_pct": coverage_pct(articles, "community_score > 0"),
        "academic_papers_pct": coverage_pct(articles, "source_type == 'academic'"),
    }
```

---

## 七、信号层与现有架构的衔接

### 7.1 与 ScoringEngine 的衔接

信号工程层的输出直接作为 `ScoringEngine.score_articles()` 的输入：

```
信号工程层输出（per article）:
  - authority_score
  - academic_score
  - community_score
  - recency_score
  - content_quality_score
  - semantic_novelty_score
  - controversy_bonus
  - breakthrough_bonus
  ↓
ScoringEngine:
  composite_score = weighted_product(信号维度, 权重)
  score_and_rank_with_diversity(articles, top_k, max_per_source)
  ↓
输出: 带 composite_score 的排序后文章列表
```

### 7.2 与 ClusteringEngine 的衔接

语义新颖性信号需要 ClusteringEngine 的输出作为输入（循环依赖）：

```
正确顺序（两阶段）：
  阶段1: ClusteringEngine.cluster_articles()
    - 生成 cluster_id, cluster_topic_label
    - 用于跨簇唯一性计算
  阶段2: SignalEngine.compute_semantic_novelty()
    - 输入: articles + cluster_info
    - 输出: semantic_novelty_score
  阶段3: ScoringEngine.score_articles()
    - 综合所有信号维度
```

### 7.3 数据依赖关系图

```
articles 表 (raw)
       │
       ├─────────────────────────────────────────┐
       ↓                                         ↓
  外源 API (可选)                          外源 API (可选)
  Semantic Scholar → academic_score        HackerNews API → community_score
       │                                         │
       └─────────────────┬───────────────────────┘
                         ↓
              信号工程层 (SignalEngine)
              ├─ compute_authority_score()
              ├─ compute_academic_score()
              ├─ compute_community_score()
              ├─ compute_recency_score()
              ├─ compute_content_quality_score()
              ├─ compute_semantic_novelty_score() ←─ 需要 ClusteringEngine 输出
              ├─ compute_controversy_score()
              └─ compute_breakthrough_score()
                         ↓
              ScoringEngine.score_articles()
                         ↓
              HotTopics Agent / DeepSummary Agent / Prediction Agent
```

---

*本文档为 [V2 事件预测架构](./v2-event-prediction-architecture.md) 的信号工程层补充，与 [数据源 Schema](./v2-data-source-schema.md) 共同构成 V2 数据层面的完整设计。*
