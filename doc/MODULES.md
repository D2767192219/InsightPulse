# InsightPulse 模块文档

> 本文件由 AI 自动维护，每次模块更新同步更新。

---

## 已完成模块清单

| 模块 | 文件路径 | 功能说明 |
|------|---------|---------|
| **配置管理** | `core/config.py` | Pydantic Settings 管理环境变量（调度间隔等） |
| **数据库连接** | `core/database.py` | aiosqlite 异步 SQLite 连接，自动建表（feeds/articles） |
| **统一响应** | `core/responses.py` | 标准化 API 返回格式（success/error） |
| **数据模型** | `models/article.py` | Article、Feed、CrawlResult 等 Pydantic 模型 |
| **RSS 爬虫服务** | `services/rss_crawler.py` | 核心爬虫逻辑，支持 8 个默认 AI 源，URL 去重 |
| **Feeds API** | `api/v1/feeds.py` | 增删查、单独爬取、全量爬取、种子数据接口 |
| **Articles API** | `api/v1/articles.py` | 分页列表、条件筛选、详情、删除、统计接口 |
| **API 路由聚合** | `api/v1/router.py` | v1 版本路由总览 |
| **调度器** | `scheduler/jobs.py` | APScheduler 自动爬取任务（默认 30 分钟间隔） |
| **FastAPI 入口** | `main.py` | 应用启动/关闭生命周期、CORS、路由注册 |
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
| `GET` | `/` | 健康检查 |
| `GET` | `/health` | 详细健康状态 |

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
