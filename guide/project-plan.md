# InsightPulse — 项目实施计划

> 文档版本：v1.0
> 日期：2026-04-02
> 基于架构设计文档：architecture-design.md

---

## 一、实施原则

### 1.1 优先级矩阵

按 **价值 × 难度** 矩阵排序，先做高价值低难度的事：

```
高价值
  │
  │  ★ 阶段三    ★ 阶段四
  │  事件总结    报告生成
  │  Agent       Agent
  │
  ├──────────────────────→ 高价值/低难度
  │  ★ 阶段一    ★ 阶段二
  │  项目骨架    爬虫+
  │  + API层    清洗+
  │              排名
  │
低价值
```

### 1.2 里程碑目标

| 里程碑 | 目标 | 核心价值 |
|-------|------|---------|
| **M1** | MVP — 单数据源日报 | 能跑起来，看到第一份报告 |
| **M2** | 多源聚合 + 热点排名 | 数据丰富度提升 |
| **M3** | 事件聚类 + 摘要 | 从罗列到理解 |
| **M4** | 趋势判断 + 预警 | 从被动到主动 |
| **M5** | 个性化 + 前端完整 UI | 用户体验完整 |
| **M6** | V1.0 发布 | 生产可用 |

---

## 二、阶段一：项目骨架与 API 层（第 1–3 天）

### 目标
搭建完整的项目框架，安装依赖，配置 MongoDB/Redis，实现所有 REST API 端点骨架，跑通前后端联调。

### 交付物

#### 1. 项目初始化（Day 1）

```bash
# 创建项目结构
backend/
frontend/

# backend 环境
cd backend
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic pydantic-settings
pip install motor pymongo redis
pip install celery apscheduler
pip install litellm dashscope
pip install feedparser trafilatura httpx
pip install hdbscan numpy scikit-learn
pip install python-multipart python-dotenv
pip freeze > requirements.txt

# frontend 环境
cd frontend
npm create vite@latest . -- --template vue-ts
npm install axios pinia vue-router @vueuse/core
npm install naive-ui echarts
npm install -D sass
```

#### 2. 配置管理（Day 1）

```python
# backend/core/config.py

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173"]

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "insightpulse"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # AI（通义千问）
    dashscope_api_key: str = ""
    ai_model: str = "qwen-plus"
    ai_embedding_model: str = "text-embedding-v3"
    ai_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ai_timeout: int = 120
    ai_max_tokens: int = 4096
    ai_temperature: float = 0.7

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

#### 3. 数据库连接（Day 1）

```python
# backend/core/database.py

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
from .config import get_settings


class Database:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

    @classmethod
    async def connect(cls):
        settings = get_settings()
        cls.client = AsyncIOMotorClient(settings.mongodb_uri)
        cls.db = cls.client[settings.mongodb_db]

        # 创建索引
        await cls.db.raw_articles.create_index("url", unique=True)
        await cls.db.cleaned_articles.create_index([("published_at", -1)])
        await cls.db.cleaned_articles.create_index("keywords")
        await cls.db.daily_reports.create_index("date", unique=True)
        await cls.db.event_summaries.create_index("date")
        await cls.db.trend_signals.create_index([("created_at", -1)])
        await cls.db.alert_history.create_index([("created_at", -1)])
        await cls.db.user_preferences.create_index("user_id", unique=True)

    @classmethod
    async def disconnect(cls):
        if cls.client:
            cls.client.close()

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        if cls.db is None:
            raise RuntimeError("Database not connected")
        return cls.db
```

#### 4. 统一 AI 客户端（Day 1）

```python
# backend/core/ai_client.py
# 详见 architecture-design.md 第五章
# 完成后输出：已测试调用通义千问 API 返回结果
```

#### 5. API 端点实现（Day 2–3）

按以下顺序实现，每个端点都要有完整的 Pydantic 模型和错误处理：

```
Day 2：
□ GET  /api/v1/news              — 新闻列表（分页/筛选/排序）
□ GET  /api/v1/news/{id}         — 新闻详情
□ GET  /api/v1/news/hot          — 热点榜单
□ GET  /api/v1/reports           — 日报列表
□ GET  /api/v1/reports/{date}    — 日报详情

Day 3：
□ GET  /api/v1/events           — 事件列表
□ GET  /api/v1/trends           — 趋势分析
□ GET  /api/v1/alerts           — 预警历史
□ GET  /api/v1/alerts/settings  — 预警设置
□ PUT  /api/v1/alerts/settings  — 更新预警设置
□ GET  /api/v1/preferences      — 用户偏好
□ PUT  /api/v1/preferences      — 更新用户偏好
□ GET  /api/v1/feeds            — RSS 源列表
□ POST /api/v1/feeds            — 添加 RSS 源
□ DELETE /api/v1/feeds/{id}     — 删除 RSS 源
□ POST /api/v1/reports/generate — 手动触发日报生成
```

#### 6. 前端骨架（Day 2–3）

```
□ Vite + Vue 3 + TypeScript 项目初始化
□ 路由配置（/, /hot, /report, /events, /trends, /alerts, /settings）
□ Axios 封装（请求拦截器、错误处理、环境变量）
□ Pinia Store 初始化（newsStore, reportStore, trendStore, alertStore, userStore）
□ Dashboard 页面框架（今日概览卡片 + 热点列表 + 近期报告入口）
□ Naive UI 主题配置
□ 基础组件：NewsCard、EventCard、AlertBadge、LoadingSkeleton
```

### 验收标准
- [ ] `curl http://localhost:8000/api/v1/news/hot` 返回正确的 JSON 结构（无数据时返回空数组）
- [ ] `curl http://localhost:8000/api/v1/reports/2026-04-02` 返回正确的 JSON 结构（无数据时返回空结构）
- [ ] 前端 Dashboard 页面能正常打开，数据为空时显示骨架屏
- [ ] 所有 API 端点返回统一格式：`{ code, message, data, timestamp }`
- [ ] API 文档可访问：`http://localhost:8000/docs`

---

## 三、阶段二：数据管道 — 爬虫 + 清洗 + 排名（第 4–8 天）

### 目标
实现全量数据管道：多源爬虫 → 清洗去重 → 热点排名 → 入库

### 交付物

#### 1. RSS 爬虫（Day 4）

```python
# backend/agents/crawler/rss_crawler.py
# 基于 rss-crawler-guide.md 已有设计
# 关键：from_config() 方法从 config.yaml 读取 feeds 配置
```

**Day 4 任务清单：**

```
□ RSSParser（RSS 2.0 / Atom / JSON Feed）— 复用 guide 中代码
□ RSSFetcher（HTTP 请求、限速、错误处理）
□ 初始数据源配置（至少 10 个 RSS 源）：
    - 机器之心 (jiqizhixin.com)
    - 36氪 AI 专题
    - AI 前线
    - 量子位
    - Hacker News
    - Reddit r/MachineLearning
    - The Verge AI
    - VentureBeat AI
□ 配置到 config.yaml 的 feeds 段
□ 手动测试：抓取 10 个 RSS 源，数据入库
□ 数据验证：MongoDB 查看 raw_articles 集合条数
```

#### 2. 社交平台爬虫（Day 5）

```python
# backend/agents/crawler/social_crawler.py
```

**Day 5 任务清单：**

```
□ WeiboHotCrawler — 微博热搜（非官方API，需处理反爬或找可靠数据源）
□ ZhihuHotCrawler — 知乎热榜
□ HackerNewsCrawler — Hacker News API (https://hacker-news.firebaseio.com/v0/)
□ 统一接口：CrawlerStrategy 基类，所有爬虫实现相同 fetch() 签名
□ 频率限制器：每个域名独立的请求间隔
□ 错误日志和告警：某数据源连续失败3次后告警
□ 手动测试：各数据源单独抓取，确认数据格式正确
```

#### 3. 数据清洗（Day 5–6）

```python
# backend/agents/cleaner/agent.py
```

**Day 5–6 任务清单：**

```
□ HTML 正文提取（Trafilatura）
□ 文本清洗（标签去除、HTML实体解码、空白归一化）
□ 语义去重：
    - 用 embedding 模型向量化标题
    - 余弦相似度 > 0.85 的文章标记为重复
    - 保留发布时间最新的一条
□ 关键词提取（LLM 辅助提取 top-10 关键词）
□ 语言检测（zh / en / mixed）
□ 入库 cleaned_articles 集合
□ 手动测试：raw_articles → cleaned_articles 全流程
□ 验证：去重前后条数对比，清洗质量抽检
```

#### 4. 热点排名（Day 7）

```python
# backend/agents/ranking/agent.py
```

**Day 7 任务清单：**

```
□ 多维度热度分数计算：
    - 平台权重配置
    - 时间衰减（e^{-t/6h}）
    - 互动信号归一化（转发/评论/点赞）
□ LLM 语义热度打分（每条新闻调用一次，批量处理）
□ 排名轨迹记录（每小时快照，支持查看升降趋势）
□ 热点榜单写入 hot_rankings 集合
□ API 对接：GET /api/v1/news/hot 返回实时排名
□ 手动测试：确认排名结果符合预期（头部效应明显）
□ 性能优化：embedding 批量请求，LLM 调用批量
□ 缓存：热点榜单写入 Redis，TTL=15分钟
```

#### 5. 定时调度集成（Day 8）

```python
# backend/scheduler/jobs.py
```

**Day 8 任务清单：**

```
□ APScheduler 初始化，与 FastAPI lifespan 集成
□ 定时任务注册：
    - crawl_all_sources (每15分钟)
    - clean_raw_articles (每15分钟)
    - update_hot_rankings (每30分钟)
□ 任务执行日志
□ Celery 任务包装：
    - 所有爬虫/清洗/排名任务注册 Celery Beat
□ Docker Compose 配置：
    - FastAPI 服务
    - MongoDB 服务
    - Redis 服务
    - Celery Worker
    - Celery Beat
□ docker-compose up 本地全量运行测试
```

### 验收标准
- [ ] 每日 8:00 自动生成日报（调用 Report Agent）
- [ ] 每 15 分钟更新热点榜单
- [ ] MongoDB 各集合数据正常增长
- [ ] 热点榜单包含至少 20 个条目
- [ ] 爬虫无单次运行超过 30s 的情况
- [ ] 各数据源抓取失败有日志记录，不影响整体

---

## 四、阶段三：事件总结 Agent（第 9–12 天）

### 目标
将热点条目聚类为事件簇，每个簇生成结构化摘要

### 交付物

#### 1. Embedding 聚类（Day 9）

```python
# backend/agents/event_summary/clustering.py
```

**Day 9 任务清单：**

```
□ 用 text-embedding-v3 对当天 cleaned_articles 批量向量化
□ HDBSCAN 聚类（min_cluster_size=3, min_samples=2）
□ 聚类结果质量评估（轮廓系数）
□ 噪声点（未聚类文章）处理策略：归入最近邻簇或单独处理
□ 聚类结果写入 event_clusters 集合（临时中间表）
□ 手动测试：聚类结果人工校验，修正参数
□ 性能：1000条文章embedding+聚类 < 30s
```

#### 2. 事件摘要生成（Day 10–11）

```python
# backend/agents/event_summary/agent.py
```

**Day 10–11 任务清单：**

```
□ LLM 事件摘要提示词（参考 architecture-design.md 4.4 节）
□ 参与者识别（人名/公司名/产品名提取）
□ 情感分析（正面/负面/中性/争议）
□ 关键事实点提取（最多5个）
□ 持久度评分（该事件是否会持续发酵）
□ 结果写入 event_summaries 集合
□ API 对接：GET /api/v1/events 返回事件列表
□ API 对接：GET /api/v1/events/{id} 返回事件详情+相关文章
□ 手动测试：生成当日事件摘要，人工审核质量
□ 迭代优化：根据测试结果调整提示词和参数
```

#### 3. 定时任务集成（Day 12）

```
□ generate_event_summaries 每小时执行
□ 与 Ranking Agent 并行执行（不依赖排名结果）
□ 事件摘要更新策略：
    - 新文章到达后，动态更新相关簇
    - 每日 23:59 生成最终快照，标记为 finalized
□ 前端事件卡片组件：EventCard（标题+摘要+参与者+情感标签）
```

### 验收标准
- [ ] 每日事件簇数量在 10–30 个（合理范围）
- [ ] 每个事件簇有 2+ 条相关文章
- [ ] 事件摘要可读性达标（无明显逻辑错误）
- [ ] API 返回时间 < 500ms（有缓存）
- [ ] 参与者识别准确率 > 80%（抽检）

---

## 五、阶段四：趋势判断 + 预警 Agent（第 13–16 天）

### 目标
时序趋势分析、弱信号检测、自动化预警

### 交付物

#### 1. 趋势信号检测（Day 13–14）

```python
# backend/agents/trend/agent.py
```

**Day 13–14 任务清单：**

```
□ 关键词频率时序分析：
    - 提取每日 top-100 关键词
    - 计算日环比变化率
    - 变化率 > 200% → 爆发信号
□ 排名轨迹分析：
    - 读取 hot_rankings.trajectory
    - 连续上升 → 上升信号
    - 持续下降 → 衰退信号
□ 弱信号检测：
    - 低排名（>20）但轨迹急升（3个时间点内进前10）
    - 小众社区（Hacker News）出现高赞技术帖
□ 信号写入 trend_signals 集合
□ API 对接：GET /api/v1/trends 获取趋势分析
□ API 对接：GET /api/v1/trends/signals 获取实时信号列表
```

#### 2. 风险预警（Day 15）

```python
# backend/agents/trend/alert_engine.py
```

**Day 15 任务清单：**

```
□ 风控词库初始化（50+ 个高风险关键词）
□ 情感-风险交叉分析：
    - 负面情感文章 + 风控词命中 → 高风险
    - 监管/政策关键词出现 → 监管风险
□ 预警级别：high / medium / low
□ 预警去重：相同话题24h内不重复告警
□ 预警写入 alert_history 集合
□ 预警通知：
    - WebSocket 实时推送（前端 AlertCenter）
    - 可扩展：邮件/飞书 webhook（V2）
□ API 对接：
    - GET /api/v1/alerts 获取预警历史
    - POST /api/v1/alerts/ack/{id} 确认预警
    - PUT /api/v1/alerts/settings 更新预警设置
```

#### 3. 定时任务集成（Day 16）

```
□ detect_trend_signals 每小时执行
□ 预警规则引擎：每30分钟扫描新文章
□ 定时任务编排：
    crawl → clean → rank → event → trend → report
    (每小时)    (每小时) (每小时) (每小时)
□ 前端预警中心页面：AlertCenter.vue
    - 实时 WebSocket 接收新预警
    - 预警列表（按级别筛选）
    - 预警确认/忽略操作
    - 预警历史（最近7天）
□ 预警趋势图表：AlertTrendChart.vue（每日预警数量折线图）
```

### 验收标准
- [ ] 每日至少检测到 1 个 trending up 信号
- [ ] 风险预警误报率 < 10%（抽检100条）
- [ ] WebSocket 预警推送延迟 < 5s
- [ ] 预警确认后，历史记录保留但标记为已处理

---

## 六、阶段五：报告生成 Agent（第 17–20 天）

### 目标
生成结构化日报，串联前面所有 Agent 的输出

### 交付物

#### 1. 报告生成逻辑（Day 17–18）

```python
# backend/agents/report/agent.py
```

**Day 17–18 任务清单：**

```
□ 日报模板引擎：
    - 结构化 JSON 输出
    - Markdown 备份输出
    - 存储到 daily_reports 集合
□ 日报内容生成：
    - Executive Summary（AI 生成）
    - Hot Topics（取排名 Top 10）
    - Event Summaries（取当天所有事件）
    - Trend Analysis（取趋势信号）
    - Risk Alerts（取未处理的预警）
    - Recommended Actions（AI 生成，针对投资者/产品经理/公众）
□ 手动触发日报：POST /api/v1/reports/generate
□ 日报版本管理：同一日期可生成多个版本，保留历史版本
□ 验收：生成一份完整日报，人工审核
□ 迭代优化：根据审核结果优化提示词
```

#### 2. 日报 API + 前端页面（Day 19）

**Day 19 任务清单：**

```
□ GET /api/v1/reports 返回日报列表（分页）
□ GET /api/v1/reports/{date} 返回日报详情
□ 前端 DailyReport.vue：
    - 报告头部（日期、生成时间、整体情感）
    - Executive Summary 展示
    - Hot Topics 列表（带排名和热度分）
    - Event Summaries 折叠面板
    - Trend Analysis 图表
    - Risk Alerts 警告卡片
    - Recommended Actions
□ 报告分享功能：生成分享链接（后端 Markdown → HTML）
□ 报告导出：PDF 导出（V2 可扩展）
```

#### 3. 定时任务 + 全流程联调（Day 20）

```
□ 日报定时生成：每天 08:00 (Asia/Shanghai)
□ 全流程联调测试：
    - 清空数据库
    - 触发一次完整 pipeline
    - 验证各环节数据
    - 审核最终日报质量
□ Docker Compose 全量测试
□ 编写 README.md（安装、运行、API 文档）
□ 编写 .env.example
□ Git 提交，Tag v0.1.0
```

### 验收标准
- [ ] 每天 08:00 自动生成并存储日报
- [ ] 日报内容包含所有 6 个板块（Executive Summary / Hot Topics / Events / Trends / Alerts / Actions）
- [ ] 日报可读性强（无乱码、无明显 AI 幻觉）
- [ ] API 响应时间 < 1s（有缓存）
- [ ] 前端日报页面完整呈现所有内容

---

## 七、阶段六：个性化与前端完整 UI（第 21–26 天）

### 目标
用户偏好配置、AI 个性化筛选、完整前端体验

### 交付物

#### 1. 用户偏好系统（Day 21）

```
□ 用户模型：user_id / 关注领域 / 关键词 / 排除关键词 / 推送时间
□ 偏好 API：
    - GET /api/v1/preferences
    - PUT /api/v1/preferences
□ AI 个性化筛选（基于 ai-prompts-guide.md）：
    - 用户兴趣 → AI 标签提取（阶段A）
    - 新闻标题 → AI 相关度打分（阶段B）
    - 过滤阈值可配置（默认 score > 0.6）
□ 个性化榜单：GET /api/v1/news/hot?personalized=true
□ 前端 Settings.vue：偏好配置表单
```

#### 2. 前端完整 UI 优化（Day 22–24）

```
□ 全局样式统一（Naive UI 主题定制，符合舆情产品风格）
□ 响应式布局（桌面端为主，移动端可查看）
□ Loading / Error / Empty 状态设计
□ 骨架屏（提升感知性能）
□ ECharts 趋势图表：
    - 热点排名轨迹折线图
    - 情感分布饼图
    - 预警趋势面积图
□ 深色模式切换（可选，V2）
□ 数据可视化：TrendChart.vue / SentimentChart.vue
```

#### 3. WebSocket 实时推送（Day 25）

```
□ /ws/stream 端点实现：
    - 新文章到达通知
    - 实时预警推送
    - 报告生成进度
□ 前端 WebSocket 客户端封装
□ 前端实时通知组件：NotificationToast.vue
□ AlertCenter 实时刷新
```

#### 4. RSS 源管理 UI（Day 26）

```
□ 前端 Feeds.vue：RSS 源管理页面
□ 添加/删除/启用/禁用 RSS 源
□ 源健康度监控（抓取成功率、更新时间）
□ 源分类（AI/科技/商业/政策）
```

### 验收标准
- [ ] 用户可以配置关注领域，个性化榜单有差异
- [ ] 所有页面加载时间 < 2s（有缓存）
- [ ] WebSocket 连接稳定，断线自动重连
- [ ] RSS 源添加后 15 分钟内出现在热点榜单

---

## 八、V1.0 发布准备（第 27–30 天）

### 目标
生产环境部署、监控告警、性能优化、文档完善

### 交付物

#### 1. 生产部署（Day 27–28）

```
□ Docker Compose 生产配置（分离 dev/prod）
□ Nginx 反向代理配置
□ MongoDB 副本集配置（生产）
□ Redis 持久化配置
□ 环境变量文档（.env.example）
□ CI/CD 脚本（GitHub Actions）：
    - 代码检查（ruff/black）
    - 单元测试
    - Docker 镜像构建
    - 自动部署到服务器（可选）
```

#### 2. 监控与告警（Day 28）

```
□ API 响应时间监控（Prometheus metrics）
□ AI API 费用监控（token 计数）
□ 爬虫成功率监控
□ Celery 任务失败告警
□ 日志收集（structlog + Loki/Grafana 可选）
□ 健康检查端点：GET /health
```

#### 3. 单元测试（Day 29）

```
□ 测试覆盖率目标：核心逻辑 > 60%
□ 测试用例：
    - AI Client mock 测试
    - RSS 解析测试（多种格式）
    - 清洗逻辑测试
    - 排名计算测试
    - API 端点测试（FastAPI TestClient）
□ 测试报告生成
```

#### 4. 文档与发布（Day 30）

```
□ README.md 更新（完整安装/使用说明）
□ API 文档完善（http://localhost:8000/docs）
□ 数据源清单文档
□ 提示词设计文档（architecture-design.md 已有）
□ Git Tag v1.0.0
□ CHANGELOG.md
□ 性能基准测试报告（1000条文章全流程 < 5分钟）
```

---

## 九、总览甘特图

```
阶段        | 第1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30
------------|---------------------------------------------------------------------------------------------------
阶段一：骨架 | ████
            |      API端点
            |          前端骨架
阶段二：管道 |           ████████████████████████
            |                                      定时调度集成
阶段三：事件 |                                           ████████████████
            |                                                               定时任务集成
阶段四：趋势 |                                                                   ████████████████
            |                                                                                          定时任务
阶段五：报告 |                                                                                                 ████████████████
            |                                                                                                                                        全流程联调
阶段六：个性 |                                                                                                                                                      ██████████████████
V1.0发布    |                                                                                                                                                                              ████
```

---

## 十、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 通义千问 API 不稳定 | 分析任务失败 | 配置 fallback 模型（qwen-plus → qwen-turbo → 本地模型） |
| 爬虫被反爬 | 数据中断 | 降低请求频率、使用代理池、备选数据源 |
| LLM 输出不稳定 | 报告质量波动 | 提示词迭代 + 多次采样 + 规则兜底 |
| MongoDB 性能瓶颈 | 查询延迟 | 定期创建索引、Redis 缓存热点数据 |
| 全流程耗时过长 | 无法在8:00前完成日报 | 流水线并行化、缓存中间结果、分阶段生成 |
| 个性化筛选误杀 | 重要文章被过滤 | 阈值可配置 + 低阈值时提醒用户确认 |

---

## 十一、关键依赖

| 依赖项 | 优先级 | 获取方式 |
|--------|-------|---------|
| 通义千问 API Key | P0 | https://dashscope.console.aliyun.com/ |
| MongoDB | P0 | Docker 或本地安装 |
| Redis | P0 | Docker 或本地安装 |
| text-embedding-v3 | P0 | 通过 DashScope API |
| Docker & Docker Compose | P1 | 官网安装 |
| Hacker News API | P0 | 免费，无需 Key |
| 微博/知乎数据源 | P1 | 需处理反爬或寻找第三方接口 |

---

## 十二、核心指标（OKR）

| Objective | Key Result | 目标值 |
|-----------|-----------|--------|
| **O1: 数据管道稳定运行** | KR1: 每日数据覆盖 ≥ 5 个数据源 | ≥ 5 |
| | KR2: 日报生成成功率 | ≥ 95% |
| | KR3: 全流程耗时 | ≤ 5 分钟 |
| **O2: AI 分析质量达标** | KR1: 事件摘要可读性评分 | ≥ 4/5 |
| | KR2: 趋势判断准确率（人工抽检） | ≥ 80% |
| | KR3: 风险预警召回率 | ≥ 85% |
| **O3: 用户体验完整** | KR1: 核心页面加载时间 | ≤ 2s |
| | KR2: API 响应时间（热点榜单） | ≤ 500ms |
| | KR3: 前端功能覆盖度 | 100%（核心功能） |
