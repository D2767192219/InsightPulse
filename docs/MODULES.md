# InsightPulse 模块文档

> 本文件由 AI 自动维护，每次模块更新同步更新。

---

## 已完成模块清单

| 模块 | 文件路径 | 功能说明 |
|------|---------|---------|
| **配置管理** | `core/config.py` | Pydantic Settings 管理环境变量（LLM API、Scheduler 等） |
| **数据库连接** | `core/database.py` | aiosqlite 异步 SQLite 连接，自动建表（feeds/articles/daily_reports/report_tasks） |
| **统一响应** | `core/responses.py` | 标准化 API 返回格式（success/error） |
| **数据模型** | `models/article.py` | Article、Feed、CrawlResult 等 Pydantic 模型 |
| **RSS 爬虫服务** | `services/rss_crawler.py` | 核心爬虫逻辑，支持 8 个默认 AI 源，URL 去重 |
| **Feeds API** | `api/v1/feeds.py` | 增删查、单独爬取、全量爬取、种子数据接口 |
| **Articles API** | `api/v1/articles.py` | 分页列表、条件筛选、详情、删除、统计接口 |
| **Reports API** | `api/v1/reports.py` | 手动触发日报生成、获取指定日期日报、日报列表 |
| **API 路由聚合** | `api/v1/router.py` | v1 版本路由总览（feeds/articles/reports） |
| **调度器** | `scheduler/jobs.py` | APScheduler 自动爬取任务（默认 30 分钟间隔） |
| **FastAPI 入口** | `main.py` | 应用启动/关闭生命周期、CORS、路由注册 |
| **LLM 客户端** | `agents/llms/base.py` | 统一 OpenAI 兼容 Client，支持豆包/DeepSeek/Kimi 等，含指数退避重试 |
| **Orchestrator** | `agents/orchestrator/agent.py` | 日报编排器，Fan-Out/Fan-In 模式，并行调度 3 个分析 Agent |
| **热点发现 Agent** | `agents/hot_topics/agent.py` | 识别 AI 领域最热话题，SortNode→ScoreNode→RankNode 流水线 |
| **深度总结 Agent** | `agents/deep_summary/agent.py` | 重要事件深度摘要，What/Who/Why/Impact 结构化输出 |
| **趋势洞察 Agent** | `agents/trend/agent.py` | 四维度趋势分析（技术/应用/政策/资本），4 个 Sub-Nodes 并行 |
| **信号评分引擎** | `services/scoring_engine.py` | 6 大维度信号评分（Authority/Academic/Community/Recency/Quality/Novelty），综合热度分计算，含 ClusteringEngine 新兴主题检测 |
| **信号计算 API** | `api/v1/signals.py` | 批量计算信号、信号统计、每日趋势、高分排行、来源分布、权重配置接口 |
| **报告聚合 Agent** | `agents/report_composer/agent.py` | 汇总三路输出，生成 JSON + Markdown 双格式日报 |
| **环境变量示例** | `env.example` | 包含豆包 1.8 及主流模型配置说明 |
| **架构设计文档** | `guide/multi-agent-daily-report-architecture.md` | 多智能体日报模块完整架构设计 |
| **AI 信号工程设计** | `docs/v2-ai-signals-engineering.md` | 信号工程完整设计文档（6 维度评分体系、半衰期衰减、TF-ICF 新颖性等） |
| **单元测试** | `tests/test_models.py` | 模型验证测试 |
| **单元测试** | `tests/test_rss_crawler.py` | 爬虫核心逻辑测试 |
| **单元测试** | `tests/test_responses.py` | 响应工具测试 |

---

## 默认 RSS 数据源

| 名称 | URL | 分类 |
|------|-----|------|
| Hugging Face Blog | `huggingface.co/blog/feed.xml` | AI |
| The Gradient | `thegradient.pub/rss/` | AI |
| DeepMind Blog | `deepmind.google/blog/rss.xml` | AI Research |
| OpenAI Blog | `openai.com/blog/rss.xml` | AI |
| MIT News - AI | `news.mit.edu/rss/topic/artificial-intelligence` | AI News |
| arXiv cs.AI | `arxiv.org/rss/cs.AI` | AI Research |
| VentureBeat AI | `venturebeat.com/category/ai/feed/` | AI Industry |
| TechCrunch AI | `techcrunch.com/category/artificial-intelligence/feed/` | AI Industry |

---

## API 接口一览

### Articles & Feeds

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/articles/` | 分页查询文章（支持来源/关键词/时间过滤） |
| `GET` | `/api/v1/articles/{id}` | 获取单篇文章 |
| `DELETE` | `/api/v1/articles/{id}` | 删除单篇文章 |
| `GET` | `/api/v1/articles/stats/overview` | 文章统计概览 |
| `DELETE` | `/api/v1/articles/` | 批量删除（按日期/来源/Feed） |
| `GET` | `/api/v1/feeds/` | 列出所有 RSS 源 |
| `POST` | `/api/v1/feeds/` | 新增 RSS 源 |
| `DELETE` | `/api/v1/feeds/{id}` | 删除 RSS 源 |
| `GET` | `/api/v1/feeds/{id}/crawl` | 手动爬取指定源 |
| `POST` | `/api/v1/feeds/crawl-all` | 全量爬取所有启用的源 |
| `POST` | `/api/v1/feeds/seed-default` | 写入 8 个默认 AI 源 |

### Signals（信号工程）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/signals/compute` | 批量计算信号（最近 N 天文章，6 维度评分 + 综合热度分） |
| `GET` | `/api/v1/signals/stats` | 信号分布统计（均值/p50/p90，各来源类型分布，高分预览） |
| `GET` | `/api/v1/signals/daily` | 每日信号趋势（折线图数据，N 天均值趋势） |
| `GET` | `/api/v1/signals/top` | 高分文章排行（支持按维度排序，含完整信号分项明细） |
| `GET` | `/api/v1/signals/sources` | 来源权威性分布（各来源类型文章数量和平均权威性） |
| `GET` | `/api/v1/signals/weights` | 当前权重配置（DEFAULT_WEIGHTS、维度说明，供前端调参） |

### Reports（多智能体日报）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/reports/generate` | 手动触发日报生成（Fan-Out 并行 3 Agent） |
| `GET` | `/api/v1/reports/{date}` | 获取指定日期日报（YYYY-MM-DD） |
| `GET` | `/api/v1/reports/` | 日报列表（分页） |

### Health

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 健康检查 |
| `GET` | `/health` | 详细健康状态 |

---

## 多智能体日报模块

### 架构概览

```
[Orchestrator]
     │  build_context() → 从 SQLite 读文章
     │
  ┌──▼──┐    ┌──▼──┐    ┌──▼──┐
  │Hot   │ ✕  │Deep │ ✕  │Trend│
  │Topics│    │Sum  │    │Agent│
  │Agent │    │Agent│    │     │
  └──┬──┘    └──┬──┘    └──┬──┘
     │          │          │
     └──────────┼──────────┘
                │ fan_in()
                ▼
      [Report Composer]
                │
                ▼
         日报 JSON + Markdown
```

### Agent 流水线

| Agent | 内部节点 | 输出 |
|-------|---------|------|
| **HotTopics** | SortNode→ScoreNode→DedupeNode→RankNode | Top 10 热点榜单 |
| **DeepSummary** | GroupNode→ExtractNode→StructureNode→ImpactNode | What/Who/Why/Impact 事件摘要 |
| **Trend** | 4 Sub-Nodes 并行：Tech/App/Policy/Capital | 四维度趋势洞察 + 跨维度信号 |
| **Report Composer** | 汇总三路→JSON摘要→Markdown正文 | 完整日报 |

### LLM 模型支持

默认使用豆包 1.8（`doubao-1-5-latest`），通过 `env.example` 可快速切换：

- **豆包 1.8** — `ark.cn-beijing.volces.com`（推荐，延迟低）
- **DeepSeek** — `api.deepseek.com`
- **Kimi / Moonshot** — `api.moonshot.cn`
- **通义千问** — `dashscope.aliyuncs.com`
- **AIHubMix（Gemini）** — `aihubmix.com`

切换模型只需修改 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 三个环境变量。

---

## 信号工程模块

### 六大信号维度

| 维度 | 名称 | 评分逻辑 |
|------|------|---------|
| **Authority** | 来源权威性 | 官方首发最高 3.0，学术顶刊 2.5，媒体 1.8，社区聚合 1.0 |
| **Academic** | 学术性 | arXiv 引用数 + 子域权重 + 代码/数据集存在标志 |
| **Community** | 社区共鸣 | HackerNews 分数/评论归一化，无 HN 数据则为 0 |
| **Recency** | 时效性 | 内容类型半衰期衰减：官方快讯 6h，论文 48h，深度分析 72h |
| **Quality** | 内容质量 | 摘要长度 + 阅读时长 + 技术词汇密度综合得分 0-1 |
| **Novelty** | 语义新颖性 | TF-ICF + 跨簇唯一性，由 ClusteringEngine 更新，默认 1.0 |

### 综合评分公式

```
composite = authority×w1 + recency×w2 + quality×w3 + community×w4
          + novelty×w5 + academic×w6 + controversy_boost + breakthrough_boost
```

默认权重：`w1=0.25, w2=0.20, w3=0.20, w4=0.15, w5=0.10, w6=0.10`

### ClusteringEngine（新兴主题检测）

- 基于 TF-ICF 关键词聚类，自动识别新兴主题
- 被标记为 `is_emerging=1` 的文章获得新颖性加成
- 语义新颖性分由聚类引擎实时更新

---

## 启动方式

```bash
# 1. 进入后端目录
cd backend

# 2. 激活虚拟环境（必须先激活，依赖安装在此环境下）
source .venv/bin/activate

# 3. 确认依赖已安装（如尚未安装）
pip install -r requirements.txt

# 4. 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

> ⚠️ **注意**：激活虚拟环境后终端前缀会显示 `(venv)`，此时 `uvicorn` 等依赖命令才可用。未激活直接运行会报 `command not found: uvicorn`。

---

## 更新日志

| 日期 | 更新内容 |
|------|---------|
| 2026-04-02 | 初始模块文档，涵盖 RSS 自动爬取 AI 资讯功能全部模块 |
| 2026-04-02 | 存储层从 MongoDB (Docker) 迁移至 SQLite（aiosqlite），移除 Docker 依赖，MVP 更轻量 |
| 2026-04-02 | 新增多智能体日报模块：Orchestrator + HotTopics + DeepSummary + Trend + Report Composer Agent，Fan-Out/Fan-In 并行架构，支持豆包 1.8 及主流模型 |
| 2026-04-02 | 新增信号工程模块（`scoring_engine.py`）：6 大维度评分（Authority/Academic/Community/Recency/Quality/Novelty），综合热度分，半衰期衰减，ClusteringEngine 新兴主题检测；配套 `signals.py` API：批量计算、统计趋势、高分排行、来源分布、权重配置 |
