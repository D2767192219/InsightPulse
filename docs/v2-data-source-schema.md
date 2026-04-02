# InsightPulse 数据源分析与分源 Schema 设计

> 本文档分析当前所有数据源的特点，并根据每类数据源设计对应的数据库表结构。

---

## 一、数据源全景图

### 1.1 当前 RSS 数据源清单（共 25 个）

| # | 名称 | Source | Category | 语言 | 内容量级 | 特点 |
|---|---|---|---|---|---|---|
| 1 | OpenAI Blog | `OpenAI` | 官方渠道 | EN | 901 篇 | 官方发布，最权威，内容精炼但量少 |
| 2 | arXiv cs.AI | `arXiv` | 官方渠道 | EN | ~200 篇/天 | 学术论文，量最大，摘要式，无评论数据 |
| 3 | arXiv cs.LG (ML) | `arXiv` | 官方渠道 | EN | ~300 篇/天 | 学术论文，同上 |
| 4 | arXiv cs.CL (NLP) | `arXiv` | 官方渠道 | EN | ~150 篇/天 | 学术论文，同上 |
| 5 | arXiv cs.CV (CV) | `arXiv` | 官方渠道 | EN | ~200 篇/天 | 学术论文，同上 |
| 6 | DeepMind Blog | `DeepMind` | 官方渠道 | EN | 100 篇 | 官方博客，权威，内容精炼 |
| 7 | Nature AI | `Nature` | 官方渠道 | EN | 75 篇 | 顶刊，科研重大突破，过滤门槛高 |
| 8 | NVIDIA Blog | `NVIDIA` | 官方渠道 | EN | 18 篇 | 硬件与 AI 应用 |
| 9 | AWS ML Blog | `AWS` | 官方渠道 | EN | 20 篇 | 云端 AI 应用 |
| 10 | The Gradient | `The Gradient` | 官方渠道 | EN | 15 篇 | 学术与行业桥梁，高质量分析 |
| 11 | Synced Review | `Synced Review` | 官方渠道 | EN | 10 篇 | AI 科技评论 |
| 12 | InfoQ AI | `InfoQ` | 官方渠道 | EN | 15 篇 | 开发者技术深度报道 |
| 13 | TechCrunch AI | `TechCrunch` | 科技媒体 | EN | 20 篇 | 创业与行业动态 |
| 14 | MIT Tech Review | `MIT Technology Review` | 科技媒体 | EN | 11 篇 | 深度分析与趋势 |
| 15 | The Verge AI | `The Verge` | 科技媒体 | EN | 10 篇 | 科技产品与 AI 交叉 |
| 16 | VentureBeat AI | `VentureBeat` | 科技媒体 | EN | 7 篇 | 行业深度分析 |
| 17 | SiliconAngle AI | `SiliconANGLE` | 科技媒体 | EN | 30 篇 | 市场与资本动态 |
| 18 | AI News | `AI News` | 科技媒体 | EN | 12 篇 | AI 综合快讯 |
| 19 | MarkTechPost | `MarkTechPost` | 科技媒体 | EN | 10 篇 | 技术报道与研究解读 |
| 20 | Inside AI News | `Inside AI News` | 科技媒体 | EN | 9 篇 | 行业快讯 |
| 21 | Hacker News AI | `Hacker News` | 社交媒体 | EN | 20 篇 | 工程师社区讨论 |
| 22 | Hacker News ML | `Hacker News` | 社交媒体 | EN | 20 篇 | 工程师社区 ML 专项 |
| 23 | HN Front Page | `Hacker News` | 社交媒体 | EN | 20 篇 | 全站热门，交叉参考 |
| 24 | Product Hunt | `Product Hunt` | 聚合平台 | EN | 57 篇 | 新产品发布与创投热点 |

### 1.2 数据源四大分类

```
┌─────────────────────────────────────────────────────────────────────┐
│                        数据源分类体系                                │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ 官方渠道 (Official)        数量: 5 个源 / ~13%              │  │
│  │ OpenAI / DeepMind / NVIDIA / AWS / Nature                   │  │
│  │ 特点: 权威性最高, 内容精炼, 无评论互动数据                    │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ 学术源 (Academic)          数量: 4 个 RSS / ~87%            │  │
│  │ arXiv cs.AI / cs.LG / cs.CL / cs.CV                        │  │
│  │ 特点: 体量最大, 学术语言, 仅有摘要, 无评论/点赞              │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ 科技媒体 (Media)           数量: 8 个源 / ~15%              │  │
│  │ TechCrunch / The Verge / VentureBeat / MIT / etc.          │  │
│  │ 特点: 行业报道, 有观点立场, 可提炼实体/关系                   │  │
│  └─────────────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │ 社交/聚合 (Social/Aggregate) 数量: 3 个源 / ~10%            │  │
│  │ Hacker News / Product Hunt                                  │  │
│  │ 特点: 有评分/评论, 社区偏好信号强, 信息往往最早出现          │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、数据源特征对比矩阵

| 特征维度 | 官方渠道 | 学术源 (arXiv) | 科技媒体 | 社交/聚合 |
|---|---|---|---|---|
| **内容形式** | 博客文章 | 论文摘要（Abstract only）| 新闻报道 | 社区帖子/产品 |
| **作者身份** | 公司/机构官方 | 研究者团队 | 记者/编辑 | 社区用户 |
| **互动数据** | ❌ 无 | ❌ 无（RSS 协议限制）| ❌ 无 | ✅ 有（HN 分数/评论）|
| **内容深度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐（学术深度）| ⭐⭐⭐ | ⭐⭐ |
| **时效性** | 低频稳定 | 高频日更 | 高频快讯 | 中频热点 |
| **结构化程度** | 高（固定模板）| 高（标准学术格式）| 中 | 中 |
| **可扩展字段** | 发布版本号, 技术栈 | citations, authors, categories, arxiv_id | 人物/公司/产品实体 | score, descendants |
| **核心价值** | 权威认证事实 | 技术前沿信号 | 行业趋势分析 | 社区热点发现 |
| **语言风格** | 官方/营销 | 学术中性 | 新闻客观 | 技术讨论 |
| **标题党风险** | 低 | 极低 | 中 | 低 |

---

## 三、Schema 设计原则

### 3.1 核心理念

```
┌─────────────────────────────────────────────────────────────────────┐
│                    分源 Schema 设计原则                              │
│                                                                     │
│  1. 统一主表（articles）：所有来源的共同字段                         │
│     └── 保持跨源查询的一致性，不需要 UNION                            │
│                                                                     │
│  2. 分源扩展表（source_metadata）：仅存对应来源特有的字段            │
│     └── 不污染主表，减少 NULL 冗余                                   │
│     └── 按需 JOIN，不读无用数据                                      │
│                                                                     │
│  3. 预测信号表（signals）：跨源统一的量化信号                         │
│     └── composite_score / authority_score / recency_score           │
│     └── 所有来源共享，同一信号计算口径                                │
│                                                                     │
│  4. 实体/关系表（entities/relations）：跨源统一的知识抽取             │
│     └── 不按来源拆分，因为同一个实体可能被多源报道                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 表结构概览

```
articles                          ← 统一主表（所有来源）
    │
    ├── arxiv_metadata            ← 学术源扩展（4个 arXiv RSS）
    ├── hn_metadata               ← 社交源扩展（3个 HN RSS）
    ├── media_metadata             ← 科技媒体扩展（8个科技媒体 RSS）
    │
articles_signals                  ← 预测信号表（跨源统一）
    │
articles_entities                ← 实体抽取（跨源统一）
    │
article_relations                ← 关系抽取（跨源统一）
    │
feeds                            ← RSS 源配置表
    │
source_authorities               ← 来源权威性配置表
```

---

## 四、统一主表 — articles

> 存放所有来源的共同字段，是跨源查询的主入口。

```sql
CREATE TABLE articles (
    -- ── 身份标识 ────────────────────────────────────────────────────────
    id              TEXT PRIMARY KEY,        -- UUID
    external_id     TEXT,                    -- 来源原始 ID（如 arXiv ID, HN story ID）
    url             TEXT NOT NULL UNIQUE,    -- 原始 URL
    source          TEXT NOT NULL,            -- 来源名称（OpenAI / arXiv / Hacker News）
    source_url      TEXT,                    -- 来源首页

    -- ── 内容核心 ─────────────────────────────────────────────────────────
    title           TEXT NOT NULL,
    summary         TEXT,                    -- 摘要/abstract（无 full_content 时为主要文本）
    content         TEXT,                    -- 全文（爬取后填充）
    content_hash    TEXT,                    -- MD5(content)，去重用

    -- ── 元数据 ───────────────────────────────────────────────────────────
    author          TEXT,                    -- 作者/团队
    published_at    TEXT,                    -- 发布时间（ISO8601）
    language        TEXT DEFAULT 'en',       -- en / zh / mixed
    tags            TEXT,                    -- JSON 数组，RSS 原始标签

    -- ── 内容特征 ─────────────────────────────────────────────────────────
    reading_time_minutes   INTEGER,         -- 字数 / 200wpm
    image_url              TEXT,            -- 封面图 URL
    has_code               INTEGER DEFAULT 0, -- 摘要含代码标记
    has_dataset            INTEGER DEFAULT 0, -- 摘要提及数据集

    -- ── 来源路由 ─────────────────────────────────────────────────────────
    -- 用于分源扩展表 JOIN，决定去哪张 metadata 表查询
    source_type    TEXT NOT NULL,            -- 'official' / 'academic' / 'media' / 'social'
    feed_id        TEXT NOT NULL REFERENCES feeds(id),

    -- ── 抓取记录 ─────────────────────────────────────────────────────────
    content_fetched        INTEGER DEFAULT 0, -- 是否已拉取全文
    fetched_at             TEXT NOT NULL,

    -- ── 时间戳 ────────────────────────────────────────────────────────────
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX idx_articles_source       ON articles(source);
CREATE INDEX idx_articles_source_type  ON articles(source_type);
CREATE INDEX idx_articles_published    ON articles(published_at);
CREATE INDEX idx_articles_external_id  ON articles(external_id);
CREATE INDEX idx_articles_hash         ON articles(content_hash);
CREATE INDEX idx_articles_language     ON articles(language);
```

### 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `source_type` | TEXT | **关键路由字段**，决定 JOIN 哪张扩展表 |
| `external_id` | TEXT | **学术源**：arXiv ID（如 `2404.12345`）；**HN**：story ID；其他来源可能为空 |
| `has_code` | INTEGER | 摘要含 `code`、`GitHub`、`Colab` 等关键词 → 1 |
| `has_dataset` | INTEGER | 摘要含 `dataset`、`benchmark`、`Dataloader` 等 → 1 |

---

## 五、分源扩展表

### 5.1 arxiv_metadata — 学术源扩展表

**适用来源**：`arXiv cs.AI / cs.LG / cs.CL / cs.CV`

**为什么需要单独表**：
- arXiv 是当前数据量最大的来源（预计 870+ 篇/天，占全站 ~87%）
- arXiv 有标准化的元数据体系（arXiv ID、分类、作者机构、DOI），其他来源完全不需要
- 学术源没有评论/点赞数据，但有 citation、author h-index 等替代信号

```sql
CREATE TABLE arxiv_metadata (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,

    -- ── arXiv 标准字段 ─────────────────────────────────────────────────
    arxiv_id           TEXT NOT NULL UNIQUE,   -- 无版本号: "2404.12345"
    arxiv_id_versioned TEXT,                   -- 带版本号: "2404.12345v1"
    categories         TEXT NOT NULL,          -- JSON 数组: ["cs.CL", "cs.AI"]
    primary_category   TEXT NOT NULL,          -- 主分类: "cs.CL"
    sub_categories      TEXT,                   -- JSON 数组，次级分类

    -- ── 作者信息 ──────────────────────────────────────────────────────
    authors            TEXT NOT NULL,          -- JSON 数组: [{"name": "...", "affiliation": "..."}]
    first_author       TEXT,                    -- 第一作者姓名（用于快速查询）
    author_count       INTEGER DEFAULT 0,      -- 作者总数

    -- ── 学术关联 ──────────────────────────────────────────────────────
    doi                TEXT,                    -- 正式期刊引用（部分论文有）
    journal_ref        TEXT,                    -- 期刊引用信息
    comments           TEXT,                    -- 作者注释（部分论文含重要信息）

    -- ── 扩展信息（通过 arXiv API 补充，非 RSS 可得）──────────────────
    -- 以下字段需要定期调用 export.arxiv.org/api/query 增量更新
    citation_count     INTEGER DEFAULT 0,       -- 被引用次数（API 补充）
    reference_count    INTEGER DEFAULT 0,        -- 参考文献数
    author_hindex_avg  REAL DEFAULT 0,           -- 作者平均 h-index

    -- ── 技术声明提取 ──────────────────────────────────────────────────
    -- LLM 从摘要中提取的关键技术声明（语义情感等价信号）
    claims             TEXT,                    -- JSON 数组: ["surpasses GPT-4", "first to achieve..."]
    limitations        TEXT,                    -- JSON 数组: ["cannot scale", "limited to..."]
    is_novelty         INTEGER DEFAULT 0,        -- 是否声明 novelty（1=yes）
    is_sota             INTEGER DEFAULT 0,       -- 是否声明 SOTA（1=yes）

    -- ── 内容分类标签 ──────────────────────────────────────────────────
    content_label      TEXT,                    -- LLM 分类: 'breakthrough' / 'improvement' / 'benchmark' / 'survey' / 'application'
    impact_score       REAL DEFAULT 0.5,        -- 影响力预估 0.0-1.0（LLM 评估）

    -- ── 时间戳 ─────────────────────────────────────────────────────────
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_arxiv_id           ON arxiv_metadata(arxiv_id);
CREATE INDEX idx_arxiv_primary_cat ON arxiv_metadata(primary_category);
CREATE INDEX idx_arxiv_citations   ON arxiv_metadata(citation_count DESC);
CREATE INDEX idx_arxiv_article     ON arxiv_metadata(article_id);
```

**arXiv 的「情感」等价信号设计**：

| 传统情感字段 | arXiv 等价设计 | 说明 |
|---|---|---|
| 情感分类 | `is_novelty` / `is_sota` | 论文标题/摘要含「first」「novel」「surpasses」→ 正面声明 |
| 争议性 | 多篇同主题同时提交（竞争激烈）| 需要跨时间窗口检测 |
| 负面/局限 | `limitations` 字段 | 论文承认的局限性 |
| 传播力 | `citation_count`（通过 API 获取）| 被引用越多，影响力越大 |

---

### 5.2 hn_metadata — Hacker News 扩展表

**适用来源**：`Hacker News AI / Hacker News ML / HN Front Page`

**为什么需要单独表**：
- HN 是目前唯一有真实社区互动数据（score / descendants / comments）的来源
- HN 有独特的用户体系（author / karma），可以评估内容来源质量
- HN 的三个 RSS 源共享同一套 metadata（同一 story 会被多个 HN RSS 收录）

```sql
CREATE TABLE hn_metadata (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,

    -- ── HN 标准字段 ────────────────────────────────────────────────────
    hn_id              INTEGER NOT NULL UNIQUE,   -- HN story ID（如 12345678）
    hn_url             TEXT NOT NULL,            -- HN 讨论页: https://news.ycombinator.com/item?id=xxx
    hn_author          TEXT NOT NULL,            -- HN 用户名
    hn_author_karma     INTEGER DEFAULT 0,         -- HN 用户 karma（权威性参考）
    hn_score           INTEGER DEFAULT 0,         -- HN 点赞数
    hn_descendants      INTEGER DEFAULT 0,        -- HN 评论数（含子评论）
    hn_comments         INTEGER DEFAULT 0,         -- 顶级评论数（不含子评论）
    hn_rank             INTEGER,                   -- 在 HN Top-30 中的排名（当日）

    -- ── 内容分类 ────────────────────────────────────────────────────────
    -- HN 上常见的帖子类型（通过 LLM 或规则识别）
    content_type        TEXT DEFAULT 'link',       -- 'link' / 'ask_hn' / 'show_hn' / 'poll'
    is_ask_hn           INTEGER DEFAULT 0,         -- 是否为 Ask HN 帖
    is_show_hn          INTEGER DEFAULT 0,         -- 是否为 Show HN 帖
    is_poll             INTEGER DEFAULT 0,         -- 是否为 Poll 帖

    -- ── 关联外部资源 ───────────────────────────────────────────────────
    -- HN 帖往往会链接到 GitHub / arXiv / 新闻页面
    linked_github_repo  TEXT,                      -- 如果链接到 GitHub，存 "owner/repo"
    linked_arxiv_id     TEXT,                      -- 如果链接到 arXiv，存 arXiv ID
    linked_domain       TEXT,                      -- 外部链接的主域名

    -- ── 社区信号 ───────────────────────────────────────────────────────
    -- 通过 HN API 实时补充（每日更新一次）
    sentiment_proxy     TEXT,                      -- LLM 根据 HN 评论提取: 'positive' / 'negative' / 'controversial' / 'neutral'
    top_comment_preview TEXT,                      -- 最高赞评论摘要（取前200字）

    -- ── 热度追踪（跨时间窗口）───────────────────────────────────────────
    score_peak          INTEGER DEFAULT 0,         -- 历史最高分
    score_peak_at       TEXT,                     -- 达到峰值的时间
    velocity_score      REAL DEFAULT 0,            -- 热度上升速度: (current - yesterday) / yesterday

    -- ── 时间戳 ─────────────────────────────────────────────────────────
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_hn_id              ON hn_metadata(hn_id);
CREATE INDEX idx_hn_score           ON hn_metadata(hn_score DESC);
CREATE INDEX idx_hn_author          ON hn_metadata(hn_author);
CREATE INDEX idx_hn_linked_github   ON hn_metadata(linked_github_repo);
CREATE INDEX idx_hn_linked_arxiv   ON hn_metadata(linked_arxiv_id);
CREATE INDEX idx_hn_article         ON hn_metadata(article_id);
```

**HN 的信号价值**：
- `hn_score` × 10 + `hn_descendants` × 5 可以作为类似「传播力」的代理指标
- HN 上出现的内容往往比传统媒体早 12-48 小时
- `velocity_score` 可以捕捉正在爆发的热点

---

### 5.3 media_metadata — 科技媒体扩展表

**适用来源**：`TechCrunch / The Verge / VentureBeat / MIT Tech Review / SiliconANGLE / AI News / MarkTechPost / Inside AI News`

**为什么需要单独表**：
- 科技媒体是观点和立场的来源，可以提取实体（公司/产品/人名）
- 科技媒体有记者署名，可以关联记者历史报道质量
- 科技媒体报道往往会引用官方源（HN 讨论 + arXiv 论文）

```sql
CREATE TABLE media_metadata (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,

    -- ── 媒体特有字段 ────────────────────────────────────────────────────
    publisher           TEXT,                      -- 发布机构全称（如 "Vox Media"）
    section             TEXT,                      -- 版块（如 "AI" / "Enterprise" / "Startups"）
    article_type        TEXT DEFAULT 'news',      -- 'news' / 'opinion' / 'analysis' / 'interview' / 'review'

    -- ── 人物实体（提取）────────────────────────────────────────────────
    mentioned_companies TEXT,                      -- JSON 数组: ["OpenAI", "Google", "Microsoft"]
    mentioned_products  TEXT,                      -- JSON 数组: ["GPT-4o", "Gemini", "Claude"]
    mentioned_persons   TEXT,                      -- JSON 数组: ["Sam Altman", "Demis Hassabis"]
    mentioned_models    TEXT,                      -- JSON 数组: ["GPT-4", "Llama-3"]（产品名独立标记）

    -- ── 事件信号 ────────────────────────────────────────────────────────
    is_funding_news     INTEGER DEFAULT 0,         -- 融资/投资新闻
    is_acquisition_news INTEGER DEFAULT 0,          -- 收购新闻
    is_regulation_news  INTEGER DEFAULT 0,          -- 监管/政策新闻
    is_product_launch   INTEGER DEFAULT 0,          -- 产品发布
    funding_amount      TEXT,                       -- 融资金额（如 "$1.3B"）
    funding_round       TEXT,                       -- 轮次（如 "Series C"）
    acquiring_company   TEXT,                      -- 收购方（如被收购）
    regulation_region   TEXT,                       -- 涉及监管地区（如 "EU", "US", "China"）

    -- ── 争议/情感 ────────────────────────────────────────────────────────
    sentiment_label     TEXT,                      -- LLM 情感: 'positive' / 'negative' / 'neutral' / 'controversial'
    sentiment_confidence REAL DEFAULT 0,            -- 置信度 0.0-1.0
    has_controversy      INTEGER DEFAULT 0,         -- 是否涉及争议

    -- ── 引用关系 ────────────────────────────────────────────────────────
    -- 本报道引用了哪些其他来源
    cites_arxiv_ids     TEXT,                      -- JSON 数组: ["2404.12345", "2404.67890"]
    cites_hn_ids        TEXT,                      -- JSON 数组: [12345678, 87654321]
    cites_press_releases TEXT,                     -- JSON 数组: 官方新闻稿标题

    -- ── 原创性 ───────────────────────────────────────────────────────────
    is_original_report  INTEGER DEFAULT 0,         -- 是否为原创报道（站方记者）
    is_syndicated       INTEGER DEFAULT 0,         -- 是否为转载

    -- ── 时间戳 ──────────────────────────────────────────────────────────
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_media_publisher     ON media_metadata(publisher);
CREATE INDEX idx_media_companies    ON media_metadata(mentioned_companies);
CREATE INDEX idx_media_products     ON media_metadata(mentioned_products);
CREATE INDEX idx_media_funding      ON media_metadata(is_funding_news);
CREATE INDEX idx_media_article      ON media_metadata(article_id);
```

---

### 5.4 official_metadata — 官方渠道扩展表

**适用来源**：`OpenAI / DeepMind / NVIDIA / AWS / The Gradient / Synced Review / InfoQ`

```sql
CREATE TABLE official_metadata (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,

    -- ── 官方发布特有 ────────────────────────────────────────────────────
    release_version     TEXT,                      -- 发布版本号（如 "v2.0" / "4.0"）
    product_name        TEXT,                       -- 相关产品名（官方不一定在标题写明）
    product_url         TEXT,                       -- 产品页/下载页链接

    -- ── 官方声明分类 ─────────────────────────────────────────────────────
    announcement_type   TEXT,                       -- 'research' / 'product' / 'partnership' / 'policy' / 'milestone'
    is_partnership      INTEGER DEFAULT 0,          -- 是否涉及合作
    partner_name        TEXT,                       -- 合作方名称
    is_pricing_update   INTEGER DEFAULT 0,          -- 价格更新
    pricing_change      TEXT,                       -- 价格变化描述

    -- ── 技术细节 ─────────────────────────────────────────────────────────
    tech_stack          TEXT,                       -- JSON 数组: ["PyTorch", "TPU", "RLHF"]
    model_name          TEXT,                       -- 涉及的模型名称
    benchmark_results   TEXT,                       -- JSON 对象: {"MMLU": "89%", "GSM8K": "95%"}

    -- ── 影响力评估 ───────────────────────────────────────────────────────
    audience_scope      TEXT DEFAULT 'industry',    -- 'global' / 'industry' / 'niche' / 'internal'
    is_major_announcement INTEGER DEFAULT 0,       -- 是否为重大发布（LLM 评估）

    -- ── 时间戳 ───────────────────────────────────────────────────────────
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_official_announce_type ON official_metadata(announcement_type);
CREATE INDEX idx_official_product      ON official_metadata(product_name);
CREATE INDEX idx_official_article      ON official_metadata(article_id);
```

---

## 六、预测信号表 — articles_signals

> 跨所有来源统一的量化信号表，是 ScoringEngine 计算 composite_score 的数据基础。

**设计原则**：
- 所有来源共享同一套信号口径，保证跨源可比性
- 按日期分区（每篇文章每天一条信号记录，支持时间序列分析）
- 信号值由 ScoringEngine 在每日 `scoring_prepass` 阶段计算并写入

```sql
CREATE TABLE articles_signals (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    date                TEXT NOT NULL,                    -- 信号计算日期（YYYY-MM-DD）

    -- ── 原始参与度信号（按来源获取）──────────────────────────────────────
    -- HN 场景: hn_score × 10 + hn_descendants × 5
    -- 其他场景: 0（RSS 协议无参与度数据）
    engagement_score    REAL DEFAULT 0,

    -- ── 来源权威性信号 ───────────────────────────────────────────────────
    authority_score     REAL DEFAULT 1.0,        -- 来源基础权重（0.5 ~ 2.5）
    authority_source    TEXT,                   -- 'academic' / 'official' / 'media' / 'social'

    -- ── 时效性信号 ───────────────────────────────────────────────────────
    recency_score       REAL DEFAULT 1.0,        -- 指数衰减: 0.5^(hours_ago/24)
    hours_ago            REAL DEFAULT 0,         -- 距今小时数（精确）

    -- ── 内容质量信号 ─────────────────────────────────────────────────────
    content_quality_score REAL DEFAULT 0.5,     -- min(1.0, summary_len / 400)
    reading_depth_score  REAL DEFAULT 0,         -- min(0.5, reading_time × 0.05)
    has_controversy_kw   INTEGER DEFAULT 0,       -- 争议词命中数（/3 归一化）
    has_breakthrough_kw  INTEGER DEFAULT 0,       -- 突破词命中数（/3 归一化）

    -- ── 语义情感信号（arXiv/媒体专用）─────────────────────────────────────
    sentiment_label      TEXT,                  -- 'positive' / 'negative' / 'neutral' / 'controversial'
    sentiment_score       REAL DEFAULT 0,         -- -1.0（负面）~ +1.0（正面）
    sentiment_confidence  REAL DEFAULT 0,         -- 置信度 0.0 ~ 1.0

    -- ── 跨源影响力信号 ───────────────────────────────────────────────────
    citation_count       INTEGER DEFAULT 0,        -- arXiv 引用数（API 补充）
    github_stars         INTEGER DEFAULT 0,        -- GitHub Star 数（API 补充）
    cross_source_mentions INTEGER DEFAULT 0,        -- 被多少个其他来源提及

    -- ── 综合热度分（最终输出）─────────────────────────────────────────────
    composite_score      REAL DEFAULT 0,           -- 多信号加权总分
    score_breakdown      TEXT,                     -- JSON: 各分项权重贡献 {recency: 0.3, authority: 0.2, ...}

    -- ── 聚类信息 ─────────────────────────────────────────────────────────
    cluster_id          INTEGER,                   -- SemanticClusteringEngine 分配的簇 ID
    cluster_topic_label  TEXT,                     -- 簇的主题标签（如 "LLM Training"）
    is_emerging          INTEGER DEFAULT 0,        -- 是否为新兴主题（对比昨日）

    -- ── 多样性采样标记 ───────────────────────────────────────────────────
    selected_for_top_k   INTEGER DEFAULT 0,        -- 是否被选入当日 Top-K
    selection_round      INTEGER DEFAULT 0,        -- 被选入的轮次（用于多样性采样调试）

    -- ── 时间戳 ───────────────────────────────────────────────────────────
    created_at          TEXT NOT NULL,

    -- ── 唯一约束：同一篇文章同一日期只有一条信号记录 ─────────────────────
    UNIQUE(article_id, date)
);

CREATE INDEX idx_signals_date         ON articles_signals(date);
CREATE INDEX idx_signals_composite    ON articles_signals(composite_score DESC);
CREATE INDEX idx_signals_article      ON articles_signals(article_id);
CREATE INDEX idx_signals_cluster      ON articles_signals(cluster_id);
CREATE INDEX idx_signals_sentiment    ON articles_signals(sentiment_label);
CREATE INDEX idx_signals_emerging     ON articles_signals(is_emerging) WHERE is_emerging = 1;
```

---

## 七、实体表 — articles_entities

> 从所有来源统一抽取的实体，不按来源拆分（同一实体可被多源报道）。

```sql
CREATE TABLE articles_entities (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    entity_type         TEXT NOT NULL,         -- 'company' / 'product' / 'model' / 'person' / 'dataset' / 'framework' / 'event'

    -- ── 实体身份 ─────────────────────────────────────────────────────────
    entity_name        TEXT NOT NULL,           -- 规范化名称（去大小写/空格差异）
    entity_aliases     TEXT,                    -- JSON 数组: ["GPT-4", "GPT4"] → 统一为 "GPT-4"
    raw_mentions       TEXT,                    -- JSON 数组: 文中出现的原始写法

    -- ── 上下文信号 ───────────────────────────────────────────────────────
    first_mentioned_at  TEXT,                   -- 首次在本文中出现的位置（字符偏移）
    mentions_count     INTEGER DEFAULT 1,        -- 在本文中出现的次数
    context_sentiment   TEXT,                   -- 该实体在本文中的情感: 'positive' / 'negative' / 'neutral'

    -- ── 实体级别统计（每日汇总更新）─────────────────────────────────────
    -- 以下字段由定时任务汇总更新，非实时
    total_mentions_7d   INTEGER DEFAULT 0,      -- 过去7天被提及次数
    total_sources_7d    INTEGER DEFAULT 0,      -- 过去7天被多少来源提及
    avg_sentiment_7d    REAL DEFAULT 0,         -- 过去7天平均情感分
    is_trending_up      INTEGER DEFAULT 0,     -- 是否趋势上升（相比上周）

    -- ── 来源追踪 ─────────────────────────────────────────────────────────
    source_types        TEXT,                   -- JSON 数组: ["media", "official"] 覆盖了哪些类型

    -- ── 唯一约束 ─────────────────────────────────────────────────────────
    UNIQUE(article_id, entity_type, entity_name)
);

CREATE INDEX idx_entities_type       ON articles_entities(entity_type);
CREATE INDEX idx_entities_name       ON articles_entities(entity_name);
CREATE INDEX idx_entities_article     ON articles_entities(article_id);
CREATE INDEX idx_entities_trending   ON articles_entities(is_trending_up) WHERE is_trending_up = 1;
```

---

## 八、关系表 — article_relations

> 实体间关系的抽取结果，构建 AI 行业知识图谱的基础。

```sql
CREATE TABLE article_relations (
    id                  TEXT PRIMARY KEY,
    article_id          TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,

    -- ── 关系三元组 ───────────────────────────────────────────────────────
    relation_type       TEXT NOT NULL,          -- 'acquires' / 'partner_with' / 'releases' / 'surpasses' / 'competes_with' / 'invests_in' / 'integrates'
    subject_entity      TEXT NOT NULL,          -- 主语实体
    subject_type        TEXT NOT NULL,          -- 主语类型
    object_entity       TEXT NOT NULL,          -- 宾语实体
    object_type         TEXT NOT NULL,          -- 宾语类型

    -- ── 关系上下文 ───────────────────────────────────────────────────────
    description         TEXT,                    -- LLM 提取的关系描述（如 "announced a $2B Series D"）
    confidence          REAL DEFAULT 0.5,        -- 关系置信度 0.0 ~ 1.0
    source_sentiment    TEXT,                   -- 关系的情感色彩

    -- ── 关系属性 ─────────────────────────────────────────────────────────
    amount              TEXT,                    -- 金额相关: "$2B" / "100M users"
    timeline            TEXT,                    -- 时间线: "2024-Q2" / "next month"
    is_rumor            INTEGER DEFAULT 0,       -- 是否为传言（未经官方确认）

    -- ── 唯一约束 ─────────────────────────────────────────────────────────
    UNIQUE(article_id, subject_entity, object_entity, relation_type)
);

CREATE INDEX idx_relations_type       ON article_relations(relation_type);
CREATE INDEX idx_relations_subject    ON article_relations(subject_entity);
CREATE INDEX idx_relations_object     ON article_relations(object_entity);
CREATE INDEX idx_relations_conf      ON article_relations(confidence DESC);
```

---

## 九、来源权威性配置表 — source_authorities

> 预配置的权威性权重，供 ScoringEngine 读取，不硬编码在代码中。

```sql
CREATE TABLE source_authorities (
    id                  TEXT PRIMARY KEY,
    source              TEXT NOT NULL UNIQUE,   -- 来源名称
    source_type         TEXT NOT NULL,          -- 'official' / 'academic' / 'media' / 'social' / 'aggregate'

    -- ── 权威性权重 ───────────────────────────────────────────────────────
    authority_base      REAL NOT NULL DEFAULT 1.0,   -- 基础权威性分（0.5 ~ 2.5）
    authority_tier      TEXT NOT NULL DEFAULT 'C',  -- A/B/C/D 四个等级

    -- ── 内容质量 ─────────────────────────────────────────────────────────
    avg_content_length  INTEGER DEFAULT 0,       -- 平均内容长度（摘要字数）
    avg_reading_time    INTEGER DEFAULT 0,      -- 平均阅读时长（分钟）
    novelty_rate        REAL DEFAULT 0,          -- 原创/首发的比例

    -- ── 覆盖范围 ──────────────────────────────────────────────────────────
    coverage_scope      TEXT DEFAULT 'industry', -- 'global' / 'industry' / 'niche'
    primary_language    TEXT DEFAULT 'en',

    -- ── 活跃度 ────────────────────────────────────────────────────────────
    is_active           INTEGER DEFAULT 1,
    articles_per_day    REAL DEFAULT 0,          -- 日均产出文章数
    last_article_at     TEXT,                    -- 最近一次抓取时间

    -- ── 备注 ─────────────────────────────────────────────────────────────
    notes               TEXT,
    updated_at          TEXT NOT NULL
);

-- 预置数据
INSERT INTO source_authorities (id, source, source_type, authority_base, authority_tier, coverage_scope, notes) VALUES
-- ── 官方渠道（A 级）───────────────────────────────────────────────────────
('auth_openai',     'OpenAI',      'official',  2.5, 'A', 'global',   '官方首发，最权威，无中间层'),
('auth_deepmind',   'DeepMind',    'official',  2.5, 'A', 'global',   'Google 官方，科研权威'),
('auth_nature',     'Nature',      'official',  2.5, 'A', 'global',   '顶刊，过滤门槛最高'),
('auth_nvidia',     'NVIDIA',      'official',  2.0, 'A', 'industry', '硬件与基础设施'),
('auth_aws',        'AWS',         'official',  1.8, 'B', 'industry', '云端 AI 应用'),

-- ── 学术源（B 级）─────────────────────────────────────────────────────────
('auth_arxiv',      'arXiv',       'academic',  2.0, 'A', 'global',   '学术预印本，量最大，前沿信号强'),
('auth_gradient',   'The Gradient','official',  2.0, 'A', 'global',   '学术与行业桥梁'),
('auth_synced',     'Synced Review','official', 1.5, 'B', 'industry', 'AI 科技评论'),
('auth_infoq',      'InfoQ',       'official',  1.5, 'B', 'industry', '开发者技术深度'),

-- ── 科技媒体（B-C 级）──────────────────────────────────────────────────────
('auth_mit',        'MIT Technology Review', 'media', 2.0, 'A', 'global',  'MIT 背书，深度分析'),
('auth_tc',         'TechCrunch',   'media',  1.8, 'B', 'industry', '创业与资本动态'),
('auth_verge',      'The Verge',    'media',  1.5, 'B', 'industry', '科技产品与 AI 交叉'),
('auth_vb',         'VentureBeat',  'media',  1.5, 'B', 'industry', 'AI 行业深度'),
('auth_silicon',    'SiliconANGLE', 'media',  1.3, 'C', 'industry', '资本与市场'),
('auth_marktech',   'MarkTechPost', 'media',  1.3, 'C', 'industry', '技术报道与研究解读'),
('auth_ainews',     'AI News',      'media',  1.0, 'C', 'industry', 'AI 综合快讯'),
('auth_insideai',   'Inside AI News','media',  1.0, 'C', 'industry', '行业快讯'),

-- ── 社交/聚合（D-C 级）────────────────────────────────────────────────────
('auth_hn',         'Hacker News',  'social',  1.3, 'B', 'industry', '工程师社区，热点发现价值高'),
('auth_ph',         'Product Hunt', 'aggregate',1.0, 'C', 'niche',    '新产品发布，创投热点');
```

---

## 十、Schema 完整 ER 图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              feeds                                          │
│  id / name / url / source / category / language / article_count / ...      │
│                               1                                              │
│                               │ N                                             │
│                               ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                          articles                                      │   │
│  │  id / external_id / title / url / source / source_type / feed_id     │   │
│  │  summary / content / author / published_at / language / tags        │   │
│  │  reading_time_minutes / has_code / has_dataset / composite_score    │   │
│  │  cluster_id / created_at / updated_at                                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                               │                                              │
│          ┌────────────────────┼────────────────────┐                       │
│          │                    │                    │                       │
│          ▼                    ▼                    ▼                       │
│  ┌───────────────┐  ┌───────────────┐  ┌────────────────────┐            │
│  │ arxiv_metadata│  │  hn_metadata  │  │  media_metadata    │            │
│  │               │  │               │  │                    │            │
│  │ arxiv_id      │  │ hn_id         │  │ publisher          │            │
│  │ categories    │  │ hn_score      │  │ mentioned_companies│            │
│  │ authors       │  │ hn_descendants│  │ mentioned_products │            │
│  │ citation_count│  │ hn_author_karma│ │ is_funding_news   │            │
│  │ claims        │  │ linked_github  │  │ cites_arxiv_ids    │            │
│  │ limitations   │  │ velocity_score│  │ sentiment_label    │            │
│  │ is_novelty    │  │               │  │                    │            │
│  │ is_sota       │  │               │  │                    │            │
│  └───────────────┘  └───────────────┘  └────────────────────┘            │
│          │                    │                    │                       │
│          └────────────────────┼────────────────────┘                       │
│                               │ articles_signals（通过 article_id）        │
│                               ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                      articles_signals                                  │   │
│  │  article_id / date / engagement_score / authority_score / recency   │   │
│  │  content_quality / sentiment_label / citation_count / github_stars  │   │
│  │  composite_score / cluster_id / cluster_topic_label / is_emerging    │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                               │                                              │
│                               ▼                                              │
│  ┌─────────────────────┐          ┌────────────────────────────┐           │
│  │  articles_entities  │          │   article_relations        │           │
│  │                     │          │                            │           │
│  │  entity_type        │          │  relation_type              │           │
│  │  entity_name        │          │  subject_entity / object    │           │
│  │  entity_aliases     │          │  description / confidence   │           │
│  │  context_sentiment  │          │  amount / is_rumor           │           │
│  │  is_trending_up     │          │                            │           │
│  └─────────────────────┘          └────────────────────────────┘           │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                       source_authorities                              │   │
│  │  source / source_type / authority_base / authority_tier              │   │
│  │  avg_content_length / novelty_rate / articles_per_day                │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 十一、扩展数据源路线图

当前仅通过 RSS 抓取，以下扩展数据源可在未来逐步接入：

| 数据源 | 接入方式 | 补充的关键字段 | 价值评级 |
|---|---|---|---|
| **arXiv API** | `export.arxiv.org/api/query` | citation_count / author_hindex / categories | ⭐⭐⭐⭐⭐ |
| **Hacker News API** | Firebase Realtime DB | hn_score / descendants / author_karma | ⭐⭐⭐⭐⭐ |
| **GitHub API** | `api.github.com/search/repositories` | stars / forks / commit_activity | ⭐⭐⭐ |
| **Reddit API** | `reddit.com/r/{subreddit}/hot.json` | upvotes / comment_count | ⭐⭐⭐ |
| **Google Scholar Alerts** | 邮件 + RSS | citations | ⭐⭐ |
| **LinkedIn API** | 企业博客/职位变化 | company momentum | ⭐ |
