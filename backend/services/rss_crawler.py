import feedparser
import httpx
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as date_parser
from bs4 import BeautifulSoup

from models.article import FeedCreate, CrawlResult
from core.database import get_database, db as global_db


logger = logging.getLogger(__name__)

# Average adult reading speed (words per minute)
WORDS_PER_MINUTE = 200


class RSSCrawler:
    """
    RSS feed crawler for fetching AI-related news.

    Enriches each article with:
      - author          (from RSS entry)
      - external_id     (original GUID / id from RSS)
      - image_url       (from media:content, enclosure, or og:image in article HTML)
      - language        (detected from character set analysis)
      - reading_time    (word count / 200 wpm)
      - content_hash    (MD5 of normalized content for deduplication)
      - full content    (fetched on-demand from article URL)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # 数据源分类（按用户需求四大类）：
    #   1. 科技媒体    — TechCrunch、The Verge 等行业动态报道
    #   2. 官方渠道    — OpenAI/DeepMind Blog、arXiv 等技术发布信息
    #   3. 社交媒体    — Hacker News 等舆论讨论热点
    #   4. 聚合平台    — Product Hunt、InfoQ 等综合信息源
    #
    # 所有 URL 均已通过实际请求验证（2026-04-02），不可用的源已剔除。
    # ─────────────────────────────────────────────────────────────────────────
    DEFAULT_FEEDS = [
        # ── 1. 科技媒体 ─────────────────────────────────────────────────────
        {
            "name": "TechCrunch AI",
            "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
            "source": "TechCrunch",
            "source_url": "https://techcrunch.com",
            "category": "科技媒体",
            "description": "AI 创业与行业动态报道（每 20 条）",
            "language": "en",
        },
        {
            "name": "The Verge AI",
            "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
            "source": "The Verge",
            "source_url": "https://www.theverge.com",
            "category": "科技媒体",
            "description": "AI 与科技产品交叉报道（每 10 条）",
            "language": "en",
        },
        {
            "name": "VentureBeat AI",
            "url": "https://venturebeat.com/feed/",
            "source": "VentureBeat",
            "source_url": "https://venturebeat.com",
            "category": "科技媒体",
            "description": "AI 行业深度分析（每 7 条）",
            "language": "en",
        },
        {
            "name": "SiliconAngle AI",
            "url": "https://siliconangle.com/feed/",
            "source": "SiliconANGLE",
            "source_url": "https://siliconangle.com",
            "category": "科技媒体",
            "description": "科技市场与 AI 资本动态（每 30 条）",
            "language": "en",
        },
        {
            "name": "Inside AI News",
            "url": "https://insideai.tech/feed",
            "source": "Inside AI News",
            "source_url": "https://insideai.tech",
            "category": "科技媒体",
            "description": "AI 行业快讯（每 9 条）",
            "language": "en",
        },
        {
            "name": "MarkTechPost",
            "url": "https://www.marktechpost.com/feed/",
            "source": "MarkTechPost",
            "source_url": "https://www.marktechpost.com",
            "category": "科技媒体",
            "description": "AI 技术报道与研究解读（每 10 条）",
            "language": "en",
        },
        {
            "name": "AI News",
            "url": "https://artificialintelligence-news.com/feed/",
            "source": "AI News",
            "source_url": "https://artificialintelligence-news.com",
            "category": "科技媒体",
            "description": "AI 综合新闻（每 12 条）",
            "language": "en",
        },
        {
            "name": "MIT Tech Review",
            "url": "https://www.technologyreview.com/feed/",
            "source": "MIT Technology Review",
            "source_url": "https://www.technologyreview.com",
            "category": "科技媒体",
            "description": "MIT 技术评论，AI 深度分析（每 10 条）",
            "language": "en",
        },
        # ── 2. 官方渠道 ─────────────────────────────────────────────────────
        {
            "name": "OpenAI Blog",
            "url": "https://openai.com/blog/rss.xml",
            "source": "OpenAI",
            "source_url": "https://openai.com",
            "category": "官方渠道",
            "description": "OpenAI 官方研究发布与产品更新（每 901 条，最权威）",
            "language": "en",
        },
        {
            "name": "DeepMind Blog",
            "url": "https://deepmind.google/blog/rss.xml",
            "source": "DeepMind",
            "source_url": "https://deepmind.google",
            "category": "官方渠道",
            "description": "Google DeepMind 研究博客（每 100 条）",
            "language": "en",
        },
        {
            "name": "NVIDIA Blog",
            "url": "https://blogs.nvidia.com/feed/",
            "source": "NVIDIA",
            "source_url": "https://blogs.nvidia.com",
            "category": "官方渠道",
            "description": "NVIDIA GPU 与 AI 硬件动态（每 18 条）",
            "language": "en",
        },
        {
            "name": "AWS ML Blog",
            "url": "https://aws.amazon.com/blogs/machine-learning/feed/",
            "source": "AWS",
            "source_url": "https://aws.amazon.com",
            "category": "官方渠道",
            "description": "AWS 机器学习应用与云计算 AI 落地（每 20 条）",
            "language": "en",
        },
        {
            "name": "arXiv cs.AI",
            "url": "https://arxiv.org/rss/cs.AI",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "category": "官方渠道",
            "description": "最新 AI 论文提交（每 260 条，最重要学术源）",
            "language": "en",
        },
        {
            "name": "arXiv cs.CL (NLP)",
            "url": "https://arxiv.org/rss/cs.CL",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "category": "官方渠道",
            "description": "自然语言处理最新论文（含中文 LLM 相关）",
            "language": "en",
        },
        {
            "name": "arXiv cs.LG (ML)",
            "url": "https://arxiv.org/rss/cs.LG",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "category": "官方渠道",
            "description": "机器学习最新论文（最重要学术源）",
            "language": "en",
        },
        {
            "name": "arXiv cs.CV (CV)",
            "url": "https://arxiv.org/rss/cs.CV",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "category": "官方渠道",
            "description": "计算机视觉最新论文",
            "language": "en",
        },
        {
            "name": "Nature AI",
            "url": "https://www.nature.com/nature.rss",
            "source": "Nature",
            "source_url": "https://www.nature.com",
            "category": "官方渠道",
            "description": "Nature 期刊 AI 相关科研（每 75 条）",
            "language": "en",
        },
        {
            "name": "The Gradient",
            "url": "https://thegradient.pub/rss/",
            "source": "The Gradient",
            "source_url": "https://thegradient.pub",
            "category": "官方渠道",
            "description": "AI 学术与行业桥梁媒体（每 15 条）",
            "language": "en",
        },
        {
            "name": "SyncedReview",
            "url": "https://syncedreview.com/feed/",
            "source": "Synced Review",
            "source_url": "https://syncedreview.com",
            "category": "官方渠道",
            "description": "AI 科技评论与研究解读（每 10 条）",
            "language": "en",
        },
        {
            "name": "InfoQ AI",
            "url": "https://feed.infoq.com/",
            "source": "InfoQ",
            "source_url": "https://infoq.com",
            "category": "官方渠道",
            "description": "开发者技术深度报道聚合（每 15 条）",
            "language": "en",
        },
        # ── 3. 社交媒体 / 社区 ─────────────────────────────────────────────
        {
            "name": "Hacker News AI",
            "url": "https://hnrss.org/newest?q=artificial+intelligence",
            "source": "Hacker News",
            "source_url": "https://news.ycombinator.com",
            "category": "社交媒体",
            "description": "工程师社区 AI 相关热点讨论（每 20 条）",
            "language": "en",
        },
        {
            "name": "Hacker News ML",
            "url": "https://hnrss.org/newest?q=machine+learning",
            "source": "Hacker News",
            "source_url": "https://news.ycombinator.com",
            "category": "社交媒体",
            "description": "工程师社区机器学习专项讨论（每 20 条）",
            "language": "en",
        },
        {
            "name": "HN Front Page",
            "url": "https://hnrss.org/frontpage",
            "source": "Hacker News",
            "source_url": "https://news.ycombinator.com",
            "category": "社交媒体",
            "description": "Hacker News 全站热门（交叉参考，每 20 条）",
            "language": "en",
        },
        # ── 4. 聚合平台 ─────────────────────────────────────────────────────
        {
            "name": "Product Hunt",
            "url": "https://www.producthunt.com/feed",
            "source": "Product Hunt",
            "source_url": "https://www.producthunt.com",
            "category": "聚合平台",
            "description": "AI 新产品发布与创投热点（每 50 条）",
            "language": "en",
        },
    ]

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "InsightPulse/1.0 (RSS Crawler; AI News Aggregator)"},
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Helpers ────────────────────────────────────────────────────

    def _generate_article_id(self, url: str) -> str:
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            parsed = date_parser.parse(date_str)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError):
            return None

    def _extract_summary(self, entry: dict) -> Optional[str]:
        for field in ["summary", "description", "subtitle"]:
            if field in entry and entry[field]:
                text = entry[field]
                soup = BeautifulSoup(text, "lxml")
                text = soup.get_text(separator=" ", strip=True)
                if len(text) > 1000:
                    text = text[:997] + "..."
                return text
        return None

    def _extract_tags(self, entry: dict) -> list[str]:
        tags = []
        if "tags" in entry:
            for tag in entry["tags"]:
                if hasattr(tag, "term"):
                    tags.append(tag.term)
                elif isinstance(tag, dict) and "term" in tag:
                    tags.append(tag["term"])
        if "category" in entry:
            cat = entry["category"]
            if isinstance(cat, str):
                tags.append(cat)
            elif isinstance(cat, list):
                tags.extend(cat)
        return list(set(tags))

    def _extract_author(self, entry: dict) -> Optional[str]:
        """Extract author name(s) from RSS entry."""
        # Try author object
        if hasattr(entry, "author") and entry.author:
            return entry.author
        if isinstance(entry.get("author"), str):
            return entry["author"]

        # Try authors list (RSS 2.0 spec)
        if "authors" in entry:
            authors = entry["authors"]
            if isinstance(authors, list) and authors:
                return authors[0].get("name") if isinstance(authors[0], dict) else str(authors[0])

        # Try dc:creator
        if entry.get("dc_creator"):
            return entry["dc_creator"]

        return None

    def _extract_image_from_entry(self, entry: dict) -> Optional[str]:
        """Extract image URL from RSS entry media extensions."""
        # media:content or media:thumbnail
        for media_field in ["media_content", "media_thumbnail"]:
            val = entry.get(media_field)
            if val:
                if isinstance(val, list) and val:
                    item = val[0]
                    url = item.get("url") if isinstance(item, dict) else str(item)
                    if url:
                        return url
                elif isinstance(val, dict):
                    return val.get("url")

        # enclosure (sometimes used for images)
        enclosure = entry.get("enclosure")
        if enclosure and isinstance(enclosure, dict):
            mime = enclosure.get("type", "")
            if "image" in mime:
                return enclosure.get("url")

        return None

    def _detect_language(self, text: str) -> str:
        """Detect language from text character set: en / zh / mixed."""
        if not text:
            return "en"
        chinese_chars = len(json.dumps(text)) - len(
            json.dumps(text.replace("\u4e00-\u9fff", "")))
        # Simpler: count Chinese chars directly
        chinese_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        total_chars = sum(1 for c in text if c.isalpha())
        if total_chars == 0:
            return "en"
        ratio = chinese_count / total_chars
        if ratio >= 0.3:
            return "zh"
        if ratio < 0.05:
            return "en"
        return "mixed"

    def _estimate_reading_time(self, text: Optional[str]) -> int:
        if not text:
            return 0
        word_count = len(text.split())
        return max(1, round(word_count / WORDS_PER_MINUTE))

    def _content_hash(self, text: Optional[str]) -> Optional[str]:
        if not text:
            return None
        normalized = " ".join(text.strip().lower().split())
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()

    async def fetch_feed(self, feed_url: str) -> Optional[dict]:
        try:
            response = await self.client.get(feed_url)
            response.raise_for_status()
            return feedparser.parse(response.text)
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching {feed_url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing feed {feed_url}: {e}")
            return None

    async def _get_existing_urls(self, feed_id: str, conn) -> set[str]:
        existing = set()
        async with conn.execute(
            "SELECT url FROM articles WHERE feed_id = ?", (feed_id,)
        ) as cursor:
            async for row in cursor:
                existing.add(row["url"])
        return existing

    async def _get_existing_hashes(self, conn) -> set[str]:
        """Get all content hashes for deduplication across feeds."""
        hashes = set()
        async with conn.execute(
            "SELECT content_hash FROM articles WHERE content_hash IS NOT NULL"
        ) as cursor:
            async for row in cursor:
                hashes.add(row["content_hash"])
        return hashes

    # ── Fetch full content from article URL ───────────────────────

    async def _fetch_article_content(self, article_url: str) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch and extract article body from URL.
        Returns (content, image_url).
        """
        try:
            resp = await self.client.get(article_url, timeout=15.0)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Failed to fetch article content for {article_url}: {e}")
            return None, None

        soup = BeautifulSoup(resp.text, "lxml")

        # Extract image from og:image
        image_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            image_url = og_img["content"]
        else:
            tw_img = soup.find("meta", attrs={"name": "twitter:image"})
            if tw_img and tw_img.get("content"):
                image_url = tw_img["content"]

        # Extract body text
        content = None

        # Try <article>
        article_el = soup.find("article")
        if article_el:
            text = self._clean_article_text(article_el)
            if len(text) > 200:
                content = text

        # Try common content divs
        if not content:
            for cls_re in [
                re.compile(r"article-content|article-body|post-content|entry-content|story-body", re.I),
                re.compile(r"content.*article|article.*content", re.I),
            ]:
                for el in soup.find_all("div", class_=cls_re):
                    text = self._clean_article_text(el)
                    if 300 < len(text) < 50000:
                        content = text
                        break
                if content:
                    break

        # Fallback to <main>
        if not content:
            main = soup.find("main")
            if main:
                text = self._clean_article_text(main)
                if len(text) > 200:
                    content = text

        return content, image_url

    def _clean_article_text(self, element) -> str:
        import re
        el = BeautifulSoup(str(element), "lxml")
        for tag in el.find_all(["script", "style", "nav", "aside", "footer",
                                 "header", "form", "iframe", "noscript"]):
            tag.decompose()
        for noise in el.find_all(class_=re.compile(
                r"ad[s]?|sidebar|related|recommended|social|share|comment|"
                r"newsletter|subscribe|popup|modal|cookie|consent", re.I)):
            noise.decompose()
        text = el.get_text(separator=" ", strip=True)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Core crawl ───────────────────────────────────────────────

    async def crawl_feed(
        self,
        feed: dict,
        force: bool = False,
        fetch_content: bool = False,
        days: int | None = None,
    ) -> CrawlResult:
        """Crawl a single RSS feed and save articles."""
        import re
        start_time = datetime.now(timezone.utc)
        errors = []
        articles_fetched = 0
        articles_saved = 0

        feed_id = feed.get("id")
        if not feed_id:
            errors.append("Feed has no ID")
            return CrawlResult(
                feed_id="unknown",
                feed_name=feed.get("name", "Unknown"),
                articles_fetched=0, articles_saved=0,
                errors=errors,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )

        parsed = await self.fetch_feed(feed["url"])
        if not parsed:
            errors.append(f"Failed to fetch feed: {feed['url']}")
            return CrawlResult(
                feed_id=str(feed_id),
                feed_name=feed.get("name", "Unknown"),
                articles_fetched=0, articles_saved=0,
                errors=errors,
                duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
            )

        conn = get_database()
        existing_urls = set() if force else await self._get_existing_urls(str(feed_id), conn)
        existing_hashes = await self._get_existing_hashes(conn)

        now = datetime.now(timezone.utc)
        now_str = now.isoformat()

        for entry in parsed.entries:
            articles_fetched += 1
            article_url = entry.get("link") or entry.get("id", "")
            if not article_url or article_url in existing_urls:
                continue

            article_id = self._generate_article_id(article_url)
            summary = self._extract_summary(entry)
            tags_json = json.dumps(self._extract_tags(entry))
            author = self._extract_author(entry)
            external_id = str(entry.get("id", article_url))
            rss_image = self._extract_image_from_entry(entry)

            # Language detection from title + summary
            lang = self._detect_language(summary or "")

            # Estimate reading time from RSS summary (rough)
            reading_time = self._estimate_reading_time(summary)

            # Content fields (populated below)
            content = None
            content_hash = None
            image_url = rss_image
            content_fetched = 0

            # Fetch full article body on demand
            if fetch_content:
                try:
                    content, fetched_image = await self._fetch_article_content(article_url)
                    if content and len(content) > 200:
                        content_fetched = 1
                        content_hash = self._content_hash(content)
                        # Don't overwrite a richer RSS image
                        image_url = image_url or fetched_image
                        # Refine reading time from actual content
                        reading_time = self._estimate_reading_time(content)
                except Exception as e:
                    logger.warning(f"Failed to fetch article body for {article_url}: {e}")

            published = self._parse_date(entry.get("published") or entry.get("updated"))
            published_str = published.isoformat() if published else None

            # Skip articles older than `days` limit
            if days is not None and days > 0 and published is not None:
                cutoff = now - timedelta(days=days)
                if published < cutoff:
                    continue

            article_data = {
                "id": article_id,
                "external_id": external_id,
                "title": entry.get("title", "Untitled"),
                "url": article_url,
                "source": feed.get("source", feed.get("name", "Unknown")),
                "source_url": feed.get("source_url"),
                "author": author,
                "published_at": published_str,
                "summary": summary,
                "content": content,
                "content_hash": content_hash,
                "image_url": image_url,
                "language": lang,
                "reading_time_minutes": reading_time,
                "tags": tags_json,
                "feed_id": str(feed_id),
                "content_fetched": content_fetched,
                "fetched_at": now_str,
                "created_at": now_str,
                "updated_at": now_str,
            }

            try:
                await conn.execute("""
                    INSERT OR IGNORE INTO articles
                    (id, external_id, title, url, source, source_url, author, published_at,
                     summary, content, content_hash, image_url, language, reading_time_minutes,
                     tags, feed_id, content_fetched, fetched_at, created_at, updated_at)
                    VALUES (:id, :external_id, :title, :url, :source, :source_url, :author,
                            :published_at, :summary, :content, :content_hash, :image_url,
                            :language, :reading_time_minutes, :tags, :feed_id, :content_fetched,
                            :fetched_at, :created_at, :updated_at)
                """, article_data)

                # Index into FTS5
                await global_db.fts_index(
                    article_id,
                    article_data["title"],
                    summary or "",
                    content or "",
                )

                articles_saved += 1
            except Exception as e:
                logger.error(f"Error saving article {article_url}: {e}")
                errors.append(f"Error saving: {article_url}")

        # Update feed stats
        await conn.execute("""
            UPDATE feeds
            SET last_fetched_at = ?, article_count = article_count + ?, updated_at = ?
            WHERE id = ?
        """, (now_str, articles_saved, now_str, str(feed_id)))
        await conn.commit()

        return CrawlResult(
            feed_id=str(feed_id),
            feed_name=feed.get("name", "Unknown"),
            articles_fetched=articles_fetched,
            articles_saved=articles_saved,
            errors=errors,
            duration_seconds=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )

    async def crawl_all_feeds(
        self,
        force: bool = False,
        fetch_content: bool = False,
        days: int | None = None,
    ) -> list[CrawlResult]:
        results = []
        conn = get_database()
        async with conn.execute("SELECT * FROM feeds WHERE enabled = 1") as cursor:
            async for row in cursor:
                feed = dict(row)
                result = await self.crawl_feed(
                    feed, force=force, fetch_content=fetch_content, days=days
                )
                results.append(result)
        return results

    async def crawl_specific_feed(
        self,
        feed_id: str,
        force: bool = False,
        fetch_content: bool = False,
        days: int | None = None,
    ) -> Optional[CrawlResult]:
        conn = get_database()
        async with conn.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return await self.crawl_feed(dict(row), force=force, fetch_content=fetch_content, days=days)

    async def add_feed(self, feed_data: FeedCreate, upsert: bool = False) -> str:
        now = datetime.now(timezone.utc)
        feed_id = feed_data.url
        conn = get_database()
        if upsert:
            stmt = """
                INSERT INTO feeds
                (id, name, url, source, source_url, category, enabled, description,
                 favicon_url, language, article_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    url = excluded.url,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    category = excluded.category,
                    enabled = excluded.enabled,
                    description = excluded.description,
                    favicon_url = excluded.favicon_url,
                    language = excluded.language,
                    updated_at = excluded.updated_at
            """
            params = (
                feed_id, feed_data.name, feed_data.url, feed_data.source, feed_data.source_url,
                feed_data.category, 1 if feed_data.enabled else 0, feed_data.description,
                feed_data.favicon_url, feed_data.language, now.isoformat(), now.isoformat(),
            )
        else:
            stmt = """
                INSERT OR IGNORE INTO feeds
                (id, name, url, source, source_url, category, enabled, description,
                 favicon_url, language, article_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """
            params = (
                feed_id, feed_data.name, feed_data.url, feed_data.source, feed_data.source_url,
                feed_data.category, 1 if feed_data.enabled else 0, feed_data.description,
                feed_data.favicon_url, feed_data.language, now.isoformat(), now.isoformat(),
            )
        await conn.execute(stmt, params)
        await conn.commit()
        return feed_id

    async def seed_default_feeds(self, reset: bool = False) -> dict:
        """
        Seed default feeds. If reset=True, replaces all existing feeds;
        otherwise skips feeds that already exist.
        """
        if reset:
            conn = get_database()
            await conn.execute("DELETE FROM feeds")
            await conn.commit()

        added = 0
        skipped = 0
        for feed_data in self.DEFAULT_FEEDS:
            feed_create = FeedCreate(**feed_data)
            await self.add_feed(feed_create, upsert=True)
            added += 1
        return {"added": added, "skipped": skipped}
