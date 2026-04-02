import aiosqlite
import logging
from pathlib import Path

from core.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()
DATABASE_PATH = _settings.DB_DIR / _settings.DB_NAME


def _ensure_db_dir():
    _settings.DB_DIR.mkdir(parents=True, exist_ok=True)


class Database:
    conn: aiosqlite.Connection | None = None

    async def connect(self):
        _ensure_db_dir()
        self.conn = await aiosqlite.connect(DATABASE_PATH)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")
        await self.conn.execute("PRAGMA journal_mode = WAL")
        await self._init_tables()
        logger.info(f"SQLite connected: {DATABASE_PATH}")

    async def close(self):
        if self.conn:
            await self.conn.close()
            self.conn = None
            logger.info("SQLite connection closed.")

    async def _init_tables(self):
        # ── Feeds ─────────────────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS feeds (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                url             TEXT NOT NULL UNIQUE,
                source          TEXT NOT NULL,
                source_url      TEXT,
                source_type     TEXT NOT NULL DEFAULT 'media',
                    -- 'official' / 'academic' / 'media' / 'social' / 'aggregate'
                category        TEXT NOT NULL DEFAULT 'AI',
                enabled         INTEGER NOT NULL DEFAULT 1,
                description     TEXT,
                favicon_url     TEXT,
                language        TEXT,
                last_fetched_at TEXT,
                article_count   INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feeds_source      ON feeds(source)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feeds_source_type ON feeds(source_type)"
        )

        # ── Articles (统一主表) ────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                -- 身份标识
                id                  TEXT PRIMARY KEY,
                external_id         TEXT,
                url                 TEXT NOT NULL UNIQUE,
                source              TEXT NOT NULL,
                source_url          TEXT,

                -- 内容核心
                title               TEXT NOT NULL,
                summary             TEXT,
                content             TEXT,
                content_hash        TEXT,

                -- 元数据
                author              TEXT,
                published_at        TEXT,
                language            TEXT DEFAULT 'en',
                tags                TEXT,

                -- 内容特征
                reading_time_minutes INTEGER,
                image_url            TEXT,
                has_code             INTEGER DEFAULT 0,
                has_dataset          INTEGER DEFAULT 0,

                -- 来源路由
                source_type          TEXT NOT NULL,
                feed_id             TEXT NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,

                -- 抓取记录
                content_fetched     INTEGER DEFAULT 0,
                fetched_at          TEXT NOT NULL,

                -- 时间戳
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_source       ON articles(source)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_source_type  ON articles(source_type)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_published     ON articles(published_at)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_external_id  ON articles(external_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_hash          ON articles(content_hash)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_language      ON articles(language)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_feed_id        ON articles(feed_id)"
        )

        # ── FTS5 全文搜索 ─────────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(
                article_id,
                title,
                summary,
                content,
                tokenize='unicode61 remove_diacritics 1'
            )
        """)

        # ── arxiv_metadata ──────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_metadata (
                id                   TEXT PRIMARY KEY,
                article_id           TEXT NOT NULL UNIQUE
                                            REFERENCES articles(id) ON DELETE CASCADE,

                -- arXiv 标准字段
                arxiv_id             TEXT NOT NULL UNIQUE,
                arxiv_id_versioned   TEXT,
                categories           TEXT NOT NULL,
                primary_category     TEXT NOT NULL,
                sub_categories       TEXT,

                -- 作者信息
                authors              TEXT NOT NULL,
                first_author         TEXT,
                author_count         INTEGER DEFAULT 0,

                -- 学术关联
                doi                  TEXT,
                journal_ref          TEXT,
                comments             TEXT,

                -- 扩展信息（API 补充）
                citation_count       INTEGER DEFAULT 0,
                reference_count      INTEGER DEFAULT 0,
                author_hindex_avg    REAL DEFAULT 0,

                -- 技术声明提取
                claims               TEXT,
                limitations          TEXT,
                is_novelty           INTEGER DEFAULT 0,
                is_sota              INTEGER DEFAULT 0,

                -- 内容分类标签
                content_label        TEXT,
                impact_score         REAL DEFAULT 0.5,

                -- 时间戳
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arxiv_id          ON arxiv_metadata(arxiv_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arxiv_primary_cat  ON arxiv_metadata(primary_category)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arxiv_citations    ON arxiv_metadata(citation_count DESC)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_arxiv_article      ON arxiv_metadata(article_id)"
        )

        # ── hn_metadata ─────────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS hn_metadata (
                id                   TEXT PRIMARY KEY,
                article_id           TEXT NOT NULL UNIQUE
                                            REFERENCES articles(id) ON DELETE CASCADE,

                -- HN 标准字段
                hn_id               INTEGER NOT NULL UNIQUE,
                hn_url              TEXT NOT NULL,
                hn_author           TEXT NOT NULL,
                hn_author_karma     INTEGER DEFAULT 0,
                hn_score            INTEGER DEFAULT 0,
                hn_descendants      INTEGER DEFAULT 0,
                hn_comments         INTEGER DEFAULT 0,
                hn_rank             INTEGER,

                -- 内容分类
                content_type        TEXT DEFAULT 'link',
                is_ask_hn           INTEGER DEFAULT 0,
                is_show_hn          INTEGER DEFAULT 0,
                is_poll             INTEGER DEFAULT 0,

                -- 关联外部资源
                linked_github_repo  TEXT,
                linked_arxiv_id     TEXT,
                linked_domain       TEXT,

                -- 社区信号
                sentiment_proxy     TEXT,
                top_comment_preview TEXT,

                -- 热度追踪
                score_peak          INTEGER DEFAULT 0,
                score_peak_at       TEXT,
                velocity_score      REAL DEFAULT 0,

                -- 时间戳
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hn_id             ON hn_metadata(hn_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hn_score           ON hn_metadata(hn_score DESC)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hn_author          ON hn_metadata(hn_author)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hn_linked_github   ON hn_metadata(linked_github_repo)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hn_linked_arxiv   ON hn_metadata(linked_arxiv_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_hn_article         ON hn_metadata(article_id)"
        )

        # ── media_metadata ──────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS media_metadata (
                id                   TEXT PRIMARY KEY,
                article_id           TEXT NOT NULL UNIQUE
                                            REFERENCES articles(id) ON DELETE CASCADE,

                -- 媒体特有字段
                publisher            TEXT,
                section              TEXT,
                article_type         TEXT DEFAULT 'news',

                -- 人物实体（提取）
                mentioned_companies  TEXT,
                mentioned_products   TEXT,
                mentioned_persons    TEXT,
                mentioned_models     TEXT,

                -- 事件信号
                is_funding_news      INTEGER DEFAULT 0,
                is_acquisition_news  INTEGER DEFAULT 0,
                is_regulation_news   INTEGER DEFAULT 0,
                is_product_launch    INTEGER DEFAULT 0,
                funding_amount       TEXT,
                funding_round        TEXT,
                acquiring_company    TEXT,
                regulation_region    TEXT,

                -- 争议/情感
                sentiment_label      TEXT,
                sentiment_confidence REAL DEFAULT 0,
                has_controversy       INTEGER DEFAULT 0,

                -- 引用关系
                cites_arxiv_ids      TEXT,
                cites_hn_ids         TEXT,
                cites_press_releases  TEXT,

                -- 原创性
                is_original_report   INTEGER DEFAULT 0,
                is_syndicated        INTEGER DEFAULT 0,

                -- 时间戳
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_publisher    ON media_metadata(publisher)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_companies   ON media_metadata(mentioned_companies)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_products    ON media_metadata(mentioned_products)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_funding     ON media_metadata(is_funding_news)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_article     ON media_metadata(article_id)"
        )

        # ── official_metadata ──────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS official_metadata (
                id                   TEXT PRIMARY KEY,
                article_id           TEXT NOT NULL UNIQUE
                                            REFERENCES articles(id) ON DELETE CASCADE,

                -- 官方发布特有
                release_version      TEXT,
                product_name         TEXT,
                product_url          TEXT,

                -- 官方声明分类
                announcement_type    TEXT,
                is_partnership       INTEGER DEFAULT 0,
                partner_name         TEXT,
                is_pricing_update    INTEGER DEFAULT 0,
                pricing_change       TEXT,

                -- 技术细节
                tech_stack           TEXT,
                model_name           TEXT,
                benchmark_results    TEXT,

                -- 影响力评估
                audience_scope       TEXT DEFAULT 'industry',
                is_major_announcement INTEGER DEFAULT 0,

                -- 时间戳
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_official_announce_type ON official_metadata(announcement_type)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_official_product     ON official_metadata(product_name)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_official_article     ON official_metadata(article_id)"
        )

        # ── articles_signals ─────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS articles_signals (
                id                   TEXT PRIMARY KEY,
                article_id           TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                date                 TEXT NOT NULL,

                -- 原始参与度信号
                engagement_score     REAL DEFAULT 0,

                -- 来源权威性信号
                authority_score      REAL DEFAULT 1.0,
                authority_source     TEXT,

                -- 时效性信号
                recency_score        REAL DEFAULT 1.0,
                hours_ago             REAL DEFAULT 0,

                -- 内容质量信号
                content_quality_score REAL DEFAULT 0.5,
                reading_depth_score   REAL DEFAULT 0,
                has_controversy_kw   INTEGER DEFAULT 0,
                has_breakthrough_kw  INTEGER DEFAULT 0,

                -- 语义情感信号
                sentiment_label      TEXT,
                sentiment_score       REAL DEFAULT 0,
                sentiment_confidence  REAL DEFAULT 0,

                -- 跨源影响力信号
                citation_count       INTEGER DEFAULT 0,
                github_stars         INTEGER DEFAULT 0,
                cross_source_mentions INTEGER DEFAULT 0,

                -- 综合热度分
                composite_score      REAL DEFAULT 0,
                score_breakdown      TEXT,

                -- 聚类信息
                cluster_id           INTEGER,
                cluster_topic_label   TEXT,
                is_emerging          INTEGER DEFAULT 0,

                -- 多样性采样标记
                selected_for_top_k   INTEGER DEFAULT 0,
                selection_round      INTEGER DEFAULT 0,

                -- 时间戳
                created_at           TEXT NOT NULL,

                UNIQUE(article_id, date)
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_date        ON articles_signals(date)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_composite   ON articles_signals(composite_score DESC)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_article     ON articles_signals(article_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_cluster     ON articles_signals(cluster_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_sentiment   ON articles_signals(sentiment_label)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_emerging   ON articles_signals(is_emerging) "
            "WHERE is_emerging = 1"
        )

        # ── articles_entities ────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS articles_entities (
                id                  TEXT PRIMARY KEY,
                article_id          TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                entity_type         TEXT NOT NULL,

                -- 实体身份
                entity_name         TEXT NOT NULL,
                entity_aliases      TEXT,
                raw_mentions        TEXT,

                -- 上下文信号
                first_mentioned_at   TEXT,
                mentions_count      INTEGER DEFAULT 1,
                context_sentiment   TEXT,

                -- 实体级别统计（每日汇总更新）
                total_mentions_7d   INTEGER DEFAULT 0,
                total_sources_7d    INTEGER DEFAULT 0,
                avg_sentiment_7d    REAL DEFAULT 0,
                is_trending_up      INTEGER DEFAULT 0,

                -- 来源追踪
                source_types        TEXT,

                UNIQUE(article_id, entity_type, entity_name)
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_type      ON articles_entities(entity_type)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_name      ON articles_entities(entity_name)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_article    ON articles_entities(article_id)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_entities_trending   ON articles_entities(is_trending_up) "
            "WHERE is_trending_up = 1"
        )

        # ── article_relations ───────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS article_relations (
                id                TEXT PRIMARY KEY,
                article_id        TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,

                -- 关系三元组
                relation_type     TEXT NOT NULL,
                subject_entity    TEXT NOT NULL,
                subject_type      TEXT NOT NULL,
                object_entity     TEXT NOT NULL,
                object_type       TEXT NOT NULL,

                -- 关系上下文
                description       TEXT,
                confidence        REAL DEFAULT 0.5,
                source_sentiment  TEXT,

                -- 关系属性
                amount            TEXT,
                timeline          TEXT,
                is_rumor          INTEGER DEFAULT 0,

                UNIQUE(article_id, subject_entity, object_entity, relation_type)
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_type    ON article_relations(relation_type)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_subject ON article_relations(subject_entity)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_object  ON article_relations(object_entity)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_relations_conf    ON article_relations(confidence DESC)"
        )

        # ── source_authorities ──────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS source_authorities (
                id                  TEXT PRIMARY KEY,
                source              TEXT NOT NULL UNIQUE,
                source_type         TEXT NOT NULL,

                -- 权威性权重
                authority_base      REAL NOT NULL DEFAULT 1.0,
                authority_tier      TEXT NOT NULL DEFAULT 'C',

                -- 内容质量
                avg_content_length  INTEGER DEFAULT 0,
                avg_reading_time    INTEGER DEFAULT 0,
                novelty_rate        REAL DEFAULT 0,

                -- 覆盖范围
                coverage_scope      TEXT DEFAULT 'industry',
                primary_language    TEXT DEFAULT 'en',

                -- 活跃度
                is_active           INTEGER DEFAULT 1,
                articles_per_day    REAL DEFAULT 0,
                last_article_at     TEXT,

                -- 备注
                notes               TEXT,
                updated_at          TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_authorities_source     ON source_authorities(source)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_authorities_source_type ON source_authorities(source_type)"
        )

        # Seed source authority config
        await self._seed_source_authorities()

        # ── Daily Reports ────────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id              TEXT PRIMARY KEY,
                date            TEXT NOT NULL UNIQUE,
                report_json     TEXT NOT NULL,
                markdown_report TEXT,
                articles_count  INTEGER NOT NULL DEFAULT 0,
                hot_topics      TEXT,
                deep_summaries  TEXT,
                trend_insights  TEXT,
                generated_at    TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(date)"
        )

        # ── Report Tasks ─────────────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS report_tasks (
                id               TEXT PRIMARY KEY,
                report_date      TEXT NOT NULL,
                agent_name       TEXT NOT NULL,
                status           TEXT NOT NULL DEFAULT 'pending',
                started_at       TEXT,
                completed_at     TEXT,
                duration_seconds REAL,
                error_message    TEXT,
                output_data      TEXT,
                created_at       TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_report_date ON report_tasks(report_date)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status      ON report_tasks(status)"
        )

        await self.conn.commit()
        logger.info("Database schema initialised.")

    async def _seed_source_authorities(self):
        """Seed source authority configuration if not already present."""
        now = '"2026-01-01T00:00:00+00:00"'
        authorities = [
            # 官方渠道 A 级
            ("auth_openai",    "OpenAI",               "official",  2.5, "A", "global",   "官方首发，最权威"),
            ("auth_deepmind",  "DeepMind",              "official",  2.5, "A", "global",   "Google 官方，科研权威"),
            ("auth_nature",    "Nature",                "official",  2.5, "A", "global",   "顶刊，过滤门槛最高"),
            ("auth_nvidia",    "NVIDIA",                "official",  2.0, "A", "industry", "硬件与基础设施"),
            ("auth_aws",       "AWS",                   "official",  1.8, "B", "industry", "云端 AI 应用"),
            # 学术源 A-B 级
            ("auth_arxiv",     "arXiv",                 "academic",  2.0, "A", "global",   "学术预印本，量最大"),
            ("auth_gradient",  "The Gradient",          "official",  2.0, "A", "global",   "学术与行业桥梁"),
            ("auth_synced",    "Synced Review",         "official",  1.5, "B", "industry", "AI 科技评论"),
            ("auth_infoq",     "InfoQ",                 "official",  1.5, "B", "industry", "开发者技术深度"),
            # 科技媒体 B-C 级
            ("auth_mit",       "MIT Technology Review", "media",     2.0, "A", "global",   "MIT 背书，深度分析"),
            ("auth_tc",        "TechCrunch",            "media",     1.8, "B", "industry", "创业与资本动态"),
            ("auth_verge",     "The Verge",             "media",     1.5, "B", "industry", "科技产品与 AI"),
            ("auth_vb",        "VentureBeat",           "media",     1.5, "B", "industry", "AI 行业深度"),
            ("auth_silicon",   "SiliconANGLE",          "media",     1.3, "C", "industry", "资本与市场"),
            ("auth_marktech",  "MarkTechPost",          "media",     1.3, "C", "industry", "技术报道与研究解读"),
            ("auth_ainews",    "AI News",                "media",     1.0, "C", "industry", "AI 综合快讯"),
            ("auth_insideai",  "Inside AI News",        "media",     1.0, "C", "industry", "行业快讯"),
            # 社交/聚合 D-C 级
            ("auth_hn",        "Hacker News",           "social",    1.3, "B", "industry", "工程师社区，热点发现"),
            ("auth_ph",        "Product Hunt",          "aggregate", 1.0, "C", "niche",    "新产品发布，创投热点"),
        ]
        for auth in authorities:
            (auth_id, source, source_type, authority_base,
             tier, scope, notes) = auth
            await self.conn.execute(f"""
                INSERT OR IGNORE INTO source_authorities
                (id, source, source_type, authority_base, authority_tier,
                 coverage_scope, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (auth_id, source, source_type, authority_base, tier, scope, notes))
        await self.conn.commit()

    # ── FTS helpers ─────────────────────────────────────────────────────────────

    async def fts_index(self, article_id: str, title: str, summary: str, content: str):
        await self.conn.execute("""
            INSERT OR REPLACE INTO article_fts (article_id, title, summary, content)
            VALUES (?, ?, ?, ?)
        """, (article_id, title, summary, content))
        await self.conn.commit()

    async def fts_search(self, query: str, limit: int = 20) -> list[str]:
        results = []
        async with self.conn.execute(
            "SELECT article_id FROM article_fts WHERE article_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ) as cursor:
            async for row in cursor:
                results.append(row["article_id"])
        return results


db = Database()


async def connect_db():
    await db.connect()


async def close_db_connection():
    await db.close()


def get_database():
    return db.conn
