import aiosqlite
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATABASE_PATH = Path(__file__).parent.parent / "insightpulse.db"


class Database:
    conn: aiosqlite.Connection | None = None

    async def connect(self):
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
        # Feeds table
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS feeds (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                url             TEXT NOT NULL UNIQUE,
                source          TEXT NOT NULL,
                source_url      TEXT,
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
            "CREATE INDEX IF NOT EXISTS idx_feeds_source ON feeds(source)"
        )

        # Articles table — full enriched schema
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id                    TEXT PRIMARY KEY,
                external_id           TEXT,
                title                 TEXT NOT NULL,
                url                   TEXT NOT NULL UNIQUE,
                source                TEXT NOT NULL,
                source_url            TEXT,
                author                TEXT,
                published_at          TEXT,
                summary               TEXT,
                content               TEXT,
                content_hash          TEXT,
                image_url             TEXT,
                language              TEXT,
                reading_time_minutes   INTEGER,
                tags                  TEXT,
                feed_id               TEXT NOT NULL,
                content_fetched       INTEGER NOT NULL DEFAULT 0,
                fetched_at            TEXT NOT NULL,
                created_at            TEXT NOT NULL,
                updated_at            TEXT NOT NULL,
                FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE
            )
        """)
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_feed_id    ON articles(feed_id)")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_source    ON articles(source)")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at)")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_hash      ON articles(content_hash)")
        await self.conn.execute("CREATE INDEX IF NOT EXISTS idx_articles_language  ON articles(language)")

        # FTS5 virtual table for full-text search on title + summary + content
        await self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5(
                article_id,
                title,
                summary,
                content,
                tokenize='unicode61 remove_diacritics 1'
            )
        """)

        # ── Daily Reports ────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id              TEXT PRIMARY KEY,
                date            TEXT NOT NULL UNIQUE,
                report_json     TEXT NOT NULL,
                markdown_report TEXT,
                articles_count  INTEGER NOT NULL DEFAULT 0,
                hot_topics      TEXT,
                deep_summaries TEXT,
                trend_insights  TEXT,
                generated_at    TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(date)"
        )

        # ── Report Tasks ──────────────────────────────────────────────────
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS report_tasks (
                id              TEXT PRIMARY KEY,
                report_date     TEXT NOT NULL,
                agent_name      TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                started_at      TEXT,
                completed_at    TEXT,
                duration_seconds REAL,
                error_message   TEXT,
                output_data     TEXT,
                created_at      TEXT NOT NULL
            )
        """)
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_report_date ON report_tasks(report_date)"
        )
        await self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status ON report_tasks(status)"
        )

        await self.conn.commit()
        logger.info("Database schema initialised.")

    # ── FTS helpers ────────────────────────────────────────────────

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
