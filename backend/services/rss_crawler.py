import feedparser
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from dateutil import parser as date_parser
from bs4 import BeautifulSoup

from models.article import FeedCreate, CrawlResult, SourceType
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
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "AI 创业与行业动态报道（每 20 条）",
            "language": "en",
        },
        {
            "name": "The Verge AI",
            "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
            "source": "The Verge",
            "source_url": "https://www.theverge.com",
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "AI 与科技产品交叉报道（每 10 条）",
            "language": "en",
        },
        {
            "name": "VentureBeat AI",
            "url": "https://venturebeat.com/feed/",
            "source": "VentureBeat",
            "source_url": "https://venturebeat.com",
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "AI 行业深度分析（每 7 条）",
            "language": "en",
        },
        {
            "name": "SiliconAngle AI",
            "url": "https://siliconangle.com/feed/",
            "source": "SiliconANGLE",
            "source_url": "https://siliconangle.com",
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "科技市场与 AI 资本动态（每 30 条）",
            "language": "en",
        },
        {
            "name": "Inside AI News",
            "url": "https://insideai.tech/feed",
            "source": "Inside AI News",
            "source_url": "https://insideai.tech",
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "AI 行业快讯（每 9 条）",
            "language": "en",
        },
        {
            "name": "MarkTechPost",
            "url": "https://www.marktechpost.com/feed/",
            "source": "MarkTechPost",
            "source_url": "https://www.marktechpost.com",
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "AI 技术报道与研究解读（每 10 条）",
            "language": "en",
        },
        {
            "name": "AI News",
            "url": "https://artificialintelligence-news.com/feed/",
            "source": "AI News",
            "source_url": "https://artificialintelligence-news.com",
            "source_type": SourceType.MEDIA.value,
            "category": "科技媒体",
            "description": "AI 综合新闻（每 12 条）",
            "language": "en",
        },
        {
            "name": "MIT Tech Review",
            "url": "https://www.technologyreview.com/feed/",
            "source": "MIT Technology Review",
            "source_url": "https://www.technologyreview.com",
            "source_type": SourceType.MEDIA.value,
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
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "OpenAI 官方研究发布与产品更新（每 901 条，最权威）",
            "language": "en",
        },
        {
            "name": "DeepMind Blog",
            "url": "https://deepmind.google/blog/rss.xml",
            "source": "DeepMind",
            "source_url": "https://deepmind.google",
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "Google DeepMind 研究博客（每 100 条）",
            "language": "en",
        },
        {
            "name": "NVIDIA Blog",
            "url": "https://blogs.nvidia.com/feed/",
            "source": "NVIDIA",
            "source_url": "https://blogs.nvidia.com",
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "NVIDIA GPU 与 AI 硬件动态（每 18 条）",
            "language": "en",
        },
        {
            "name": "AWS ML Blog",
            "url": "https://aws.amazon.com/blogs/machine-learning/feed/",
            "source": "AWS",
            "source_url": "https://aws.amazon.com",
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "AWS 机器学习应用与云计算 AI 落地（每 20 条）",
            "language": "en",
        },
        {
            "name": "arXiv cs.AI",
            "url": "https://arxiv.org/rss/cs.AI",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "source_type": SourceType.ACADEMIC.value,
            "category": "官方渠道",
            "description": "最新 AI 论文提交（每 260 条，最重要学术源）",
            "language": "en",
        },
        {
            "name": "arXiv cs.CL (NLP)",
            "url": "https://arxiv.org/rss/cs.CL",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "source_type": SourceType.ACADEMIC.value,
            "category": "官方渠道",
            "description": "自然语言处理最新论文（含中文 LLM 相关）",
            "language": "en",
        },
        {
            "name": "arXiv cs.LG (ML)",
            "url": "https://arxiv.org/rss/cs.LG",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "source_type": SourceType.ACADEMIC.value,
            "category": "官方渠道",
            "description": "机器学习最新论文（最重要学术源）",
            "language": "en",
        },
        {
            "name": "arXiv cs.CV (CV)",
            "url": "https://arxiv.org/rss/cs.CV",
            "source": "arXiv",
            "source_url": "https://arxiv.org",
            "source_type": SourceType.ACADEMIC.value,
            "category": "官方渠道",
            "description": "计算机视觉最新论文",
            "language": "en",
        },
        {
            "name": "Nature AI",
            "url": "https://www.nature.com/nature.rss",
            "source": "Nature",
            "source_url": "https://www.nature.com",
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "Nature 期刊 AI 相关科研（每 75 条）",
            "language": "en",
        },
        {
            "name": "The Gradient",
            "url": "https://thegradient.pub/rss/",
            "source": "The Gradient",
            "source_url": "https://thegradient.pub",
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "AI 学术与行业桥梁媒体（每 15 条）",
            "language": "en",
        },
        {
            "name": "SyncedReview",
            "url": "https://syncedreview.com/feed/",
            "source": "Synced Review",
            "source_url": "https://syncedreview.com",
            "source_type": SourceType.OFFICIAL.value,
            "category": "官方渠道",
            "description": "AI 科技评论与研究解读（每 10 条）",
            "language": "en",
        },
        {
            "name": "InfoQ AI",
            "url": "https://feed.infoq.com/",
            "source": "InfoQ",
            "source_url": "https://infoq.com",
            "source_type": SourceType.OFFICIAL.value,
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
            "source_type": SourceType.SOCIAL.value,
            "category": "社交媒体",
            "description": "工程师社区 AI 相关热点讨论（每 20 条）",
            "language": "en",
        },
        {
            "name": "Hacker News ML",
            "url": "https://hnrss.org/newest?q=machine+learning",
            "source": "Hacker News",
            "source_url": "https://news.ycombinator.com",
            "source_type": SourceType.SOCIAL.value,
            "category": "社交媒体",
            "description": "工程师社区机器学习专项讨论（每 20 条）",
            "language": "en",
        },
        {
            "name": "HN Front Page",
            "url": "https://hnrss.org/frontpage",
            "source": "Hacker News",
            "source_url": "https://news.ycombinator.com",
            "source_type": SourceType.SOCIAL.value,
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
            "source_type": SourceType.AGGREGATE.value,
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

    # ── Source-specific field extraction ───────────────────────────────────────

    def _extract_code_signal(self, text: str) -> bool:
        """Detect code / repository keywords in text."""
        if not text:
            return False
        code_keywords = [
            r'\bcode\b', r'\bgithub\b', r'\bcolab\b', r'\bsource\s*code\b',
            r'\brepository\b', r'\bjupyter\b', r'\bnotebook\b',
            r'\bopen\s*source\b', r'\bpypi\b', r'\bnpm\b',
        ]
        return any(re.search(kw, text, re.I) for kw in code_keywords)

    def _extract_dataset_signal(self, text: str) -> bool:
        """Detect dataset / benchmark keywords in text."""
        if not text:
            return False
        dataset_keywords = [
            r'\bdataset\b', r'\bbenchmark\b', r'\btraining\s*data\b',
            r'\bdata\s*loader\b', r'\bdata\s*augmentation\b',
            r'\bdata\s*collection\b', r'\bpreprocessing\b',
        ]
        return any(re.search(kw, text, re.I) for kw in dataset_keywords)

    def _extract_arxiv_id(self, url: str) -> Optional[str]:
        """Extract arXiv ID from URL or entry title."""
        patterns = [
            r'arxiv\.org/abs/(\d+\.\d+)',
            r'arxiv\.org/pdf/(\d+\.\d+)',
            r'arxiv\.org/html/(\d+\.\d+)',
            r'(\d{4}\.\d{4,})',  # fallback: 4-digit year + 4+ digit number
        ]
        for pattern in patterns:
            m = re.search(pattern, url, re.I)
            if m:
                return m.group(1)
        return None

    def _extract_arxiv_categories(self, entry: dict) -> tuple[list[str], str]:
        """Return (categories list, primary_category) from RSS entry tags."""
        tags = self._extract_tags(entry)
        # arXiv RSS tags follow the format "cs.XX" e.g. "cs.CL"
        arxiv_cats = [t for t in tags if re.match(r'^cs\.[A-Z]{1,2}$', t)]
        if not arxiv_cats:
            # Try to infer from feed URL
            url = entry.get("link", "")
            m = re.search(r'arxiv\.org/rss/(cs\.[A-Z]{1,2})', url, re.I)
            if m:
                arxiv_cats = [m.group(1)]
        return arxiv_cats, arxiv_cats[0] if arxiv_cats else "cs.AI"

    def _extract_hn_metadata(self, entry: dict) -> dict:
        """Extract Hacker News-specific fields from RSS entry."""
        url = entry.get("link", "")
        hn_id = None
        hn_url = ""

        # HN RSS feeds put the story ID in the entry link as an anchor
        m = re.search(r'id=(\d+)', url)
        if m:
            hn_id = int(m.group(1))
        elif entry.get("id"):
            m2 = re.search(r'(\d+)', str(entry.get("id")))
            if m2:
                hn_id = int(m2.group(1))

        if hn_id:
            hn_url = f"https://news.ycombinator.com/item?id={hn_id}"

        # Detect content type from title
        title = entry.get("title", "")
        is_ask = bool(re.search(r'\bAsk\s*HN\b', title, re.I))
        is_show = bool(re.search(r'\bShow\s*HN\b', title, re.I))
        is_poll = bool(re.search(r'\bPoll\b', title, re.I))

        # Detect linked domain
        if entry.get("links"):
            for link in entry.get("links", []):
                if isinstance(link, dict) and link.get("rel") == "alternate":
                    linked_url = link.get("href", "")
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(linked_url)
                        linked_domain = parsed.netloc.replace("www.", "")
                    except Exception:
                        linked_domain = None
                    break
            else:
                linked_domain = None
        else:
            linked_domain = None

        # Detect linked GitHub repo
        github_match = re.search(r'github\.com/([^/]+/[^/\s]+)', url, re.I)
        linked_github = github_match.group(1) if github_match else None

        # Detect linked arXiv
        linked_arxiv = self._extract_arxiv_id(url)

        return {
            "hn_id": hn_id,
            "hn_url": hn_url,
            "hn_author": entry.get("author") or entry.get("dc_creator") or "unknown",
            "hn_author_karma": 0,
            "hn_score": 0,
            "hn_descendants": 0,
            "hn_comments": 0,
            "hn_rank": None,
            "content_type": "ask_hn" if is_ask else ("show_hn" if is_show else ("poll" if is_poll else "link")),
            "is_ask_hn": 1 if is_ask else 0,
            "is_show_hn": 1 if is_show else 0,
            "is_poll": 1 if is_poll else 0,
            "linked_github_repo": linked_github,
            "linked_arxiv_id": linked_arxiv,
            "linked_domain": linked_domain,
            "sentiment_proxy": None,
            "top_comment_preview": None,
            "score_peak": 0,
            "score_peak_at": None,
            "velocity_score": 0.0,
        }

    def _extract_media_metadata(self, entry: dict, article_url: str) -> dict:
        """Extract tech-media-specific fields (currently only linked_domain)."""
        linked_domain = None
        if article_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(article_url)
                linked_domain = parsed.netloc.replace("www.", "")
            except Exception:
                pass
        return {
            "publisher": None,
            "section": None,
            "article_type": "news",
            "mentioned_companies": "[]",
            "mentioned_products": "[]",
            "mentioned_persons": "[]",
            "mentioned_models": "[]",
            "is_funding_news": 0,
            "is_acquisition_news": 0,
            "is_regulation_news": 0,
            "is_product_launch": 0,
            "funding_amount": None,
            "funding_round": None,
            "acquiring_company": None,
            "regulation_region": None,
            "sentiment_label": None,
            "sentiment_confidence": 0.0,
            "has_controversy": 0,
            "cites_arxiv_ids": "[]",
            "cites_hn_ids": "[]",
            "cites_press_releases": "[]",
            "is_original_report": 0,
            "is_syndicated": 0,
        }

    def _extract_official_metadata(self, entry: dict) -> dict:
        """Extract official-channel-specific fields (currently minimal)."""
        return {
            "release_version": None,
            "product_name": None,
            "product_url": None,
            "announcement_type": None,
            "is_partnership": 0,
            "partner_name": None,
            "is_pricing_update": 0,
            "pricing_change": None,
            "tech_stack": "[]",
            "model_name": None,
            "benchmark_results": "{}",
            "audience_scope": "industry",
            "is_major_announcement": 0,
        }

    async def _save_arxiv_metadata(self, conn, article_id: str, entry: dict, now_str: str):
        """Parse arXiv entry and write to arxiv_metadata."""
        import uuid
        url = entry.get("link", "")

        # Parse arXiv ID
        arxiv_id = self._extract_arxiv_id(url)
        if not arxiv_id:
            arxiv_id = self._extract_arxiv_id(entry.get("title", ""))

        if not arxiv_id:
            return

        categories, primary_cat = self._extract_arxiv_categories(entry)

        # Parse authors
        authors_raw = entry.get("authors", [])
        authors_list = []
        first_author = None
        if isinstance(authors_raw, list):
            for i, a in enumerate(authors_raw):
                name = (a.get("name") if isinstance(a, dict) else str(a))
                if name:
                    if i == 0:
                        first_author = name
                    authors_list.append({"name": name, "affiliation": None})
        author_count = len(authors_list)

        # Content signals
        text_for_signal = entry.get("title", "") + " " + (entry.get("summary") or "")
        is_novelty = 1 if re.search(
            r'\b(first|introduce|propose|present|new\s+(method|approach|model|architecture))\b',
            text_for_signal, re.I
        ) else 0
        is_sota = 1 if re.search(
            r'\b(state-of-the-art|sota|surpass|outperform|exceed|beat|best)\b',
            text_for_signal, re.I
        ) else 0

        try:
            await conn.execute("""
                INSERT OR IGNORE INTO arxiv_metadata
                (id, article_id, arxiv_id, arxiv_id_versioned, categories, primary_category,
                 sub_categories, authors, first_author, author_count, doi, journal_ref,
                 comments, citation_count, reference_count, author_hindex_avg,
                 claims, limitations, is_novelty, is_sota, content_label, impact_score,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                article_id,
                arxiv_id,
                None,
                json.dumps(categories),
                primary_cat,
                json.dumps(categories[1:]) if len(categories) > 1 else None,
                json.dumps(authors_list),
                first_author,
                author_count,
                None, None, None,
                0, 0, 0.0,
                "[]", "[]",
                is_novelty, is_sota,
                None, 0.5,
                now_str, now_str,
            ))
        except Exception as e:
            logger.warning(f"Failed to save arxiv_metadata for {article_id}: {e}")

    async def _save_hn_metadata(self, conn, article_id: str, entry: dict, now_str: str):
        """Parse HN entry and write to hn_metadata."""
        import uuid
        meta = self._extract_hn_metadata(entry)
        if not meta["hn_id"]:
            return
        try:
            await conn.execute("""
                INSERT OR IGNORE INTO hn_metadata
                (id, article_id, hn_id, hn_url, hn_author, hn_author_karma,
                 hn_score, hn_descendants, hn_comments, hn_rank, content_type,
                 is_ask_hn, is_show_hn, is_poll, linked_github_repo, linked_arxiv_id,
                 linked_domain, sentiment_proxy, top_comment_preview,
                 score_peak, score_peak_at, velocity_score, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                article_id,
                meta["hn_id"],
                meta["hn_url"],
                meta["hn_author"],
                meta["hn_author_karma"],
                meta["hn_score"],
                meta["hn_descendants"],
                meta["hn_comments"],
                meta["hn_rank"],
                meta["content_type"],
                meta["is_ask_hn"],
                meta["is_show_hn"],
                meta["is_poll"],
                meta["linked_github_repo"],
                meta["linked_arxiv_id"],
                meta["linked_domain"],
                meta["sentiment_proxy"],
                meta["top_comment_preview"],
                meta["score_peak"],
                meta["score_peak_at"],
                meta["velocity_score"],
                now_str,
                now_str,
            ))
        except Exception as e:
            logger.warning(f"Failed to save hn_metadata for {article_id}: {e}")

    async def _save_media_metadata(self, conn, article_id: str, entry: dict, now_str: str):
        """Parse entry and write to media_metadata."""
        import uuid
        article_url = entry.get("link", "")
        meta = self._extract_media_metadata(entry, article_url)
        try:
            await conn.execute("""
                INSERT OR IGNORE INTO media_metadata
                (id, article_id, publisher, section, article_type,
                 mentioned_companies, mentioned_products, mentioned_persons, mentioned_models,
                 is_funding_news, is_acquisition_news, is_regulation_news, is_product_launch,
                 funding_amount, funding_round, acquiring_company, regulation_region,
                 sentiment_label, sentiment_confidence, has_controversy,
                 cites_arxiv_ids, cites_hn_ids, cites_press_releases,
                 is_original_report, is_syndicated, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                article_id,
                meta["publisher"],
                meta["section"],
                meta["article_type"],
                meta["mentioned_companies"],
                meta["mentioned_products"],
                meta["mentioned_persons"],
                meta["mentioned_models"],
                meta["is_funding_news"],
                meta["is_acquisition_news"],
                meta["is_regulation_news"],
                meta["is_product_launch"],
                meta["funding_amount"],
                meta["funding_round"],
                meta["acquiring_company"],
                meta["regulation_region"],
                meta["sentiment_label"],
                meta["sentiment_confidence"],
                meta["has_controversy"],
                meta["cites_arxiv_ids"],
                meta["cites_hn_ids"],
                meta["cites_press_releases"],
                meta["is_original_report"],
                meta["is_syndicated"],
                now_str,
                now_str,
            ))
        except Exception as e:
            logger.warning(f"Failed to save media_metadata for {article_id}: {e}")

    async def _save_official_metadata(self, conn, article_id: str, entry: dict, now_str: str):
        """Parse entry and write to official_metadata."""
        import uuid
        meta = self._extract_official_metadata(entry)
        try:
            await conn.execute("""
                INSERT OR IGNORE INTO official_metadata
                (id, article_id, release_version, product_name, product_url,
                 announcement_type, is_partnership, partner_name, is_pricing_update, pricing_change,
                 tech_stack, model_name, benchmark_results,
                 audience_scope, is_major_announcement, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                article_id,
                meta["release_version"],
                meta["product_name"],
                meta["product_url"],
                meta["announcement_type"],
                meta["is_partnership"],
                meta["partner_name"],
                meta["is_pricing_update"],
                meta["pricing_change"],
                meta["tech_stack"],
                meta["model_name"],
                meta["benchmark_results"],
                meta["audience_scope"],
                meta["is_major_announcement"],
                now_str,
                now_str,
            ))
        except Exception as e:
            logger.warning(f"Failed to save official_metadata for {article_id}: {e}")

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
        skipped_no_date = 0
        skipped_older = 0

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

        logger.info(f"[{feed.get('name')}] Fetching feed: {feed['url']}")

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
        cutoff = (now - timedelta(days=days)) if (days is not None and days > 0) else None

        for entry in parsed.entries:
            articles_fetched += 1
            article_url = entry.get("link") or entry.get("id", "")
            if not article_url:
                continue
            if article_url in existing_urls:
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

            # Source-specific content signals
            text_for_signal = entry.get("title", "") + " " + (summary or "")
            has_code = 1 if self._extract_code_signal(text_for_signal) else 0
            has_dataset = 1 if self._extract_dataset_signal(text_for_signal) else 0

            # Source type from feed config
            source_type = feed.get("source_type", "media")

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
                        image_url = image_url or fetched_image
                        reading_time = self._estimate_reading_time(content)
                except Exception as e:
                    logger.warning(f"Failed to fetch article body for {article_url}: {e}")

            published = self._parse_date(entry.get("published") or entry.get("updated"))
            published_str = published.isoformat() if published else None

            # Only skip articles that have a published date AND are older than cutoff.
            # Entries with no published date are NOT skipped — they may still be recent.
            if cutoff is not None and published is not None and published < cutoff:
                skipped_older += 1
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
                "source_type": source_type,
                "feed_id": str(feed_id),
                "content_fetched": content_fetched,
                "fetched_at": now_str,
                "created_at": now_str,
                "updated_at": now_str,
                "has_code": has_code,
                "has_dataset": has_dataset,
            }

            try:
                await conn.execute("""
                    INSERT OR IGNORE INTO articles
                    (id, external_id, title, url, source, source_url, author, published_at,
                     summary, content, content_hash, image_url, language, reading_time_minutes,
                     tags, source_type, feed_id, content_fetched, fetched_at, created_at,
                     updated_at, has_code, has_dataset)
                    VALUES (:id, :external_id, :title, :url, :source, :source_url, :author,
                            :published_at, :summary, :content, :content_hash, :image_url,
                            :language, :reading_time_minutes, :tags, :source_type, :feed_id,
                            :content_fetched, :fetched_at, :created_at, :updated_at,
                            :has_code, :has_dataset)
                """, article_data)

                # Index into FTS5
                await global_db.fts_index(
                    article_id,
                    article_data["title"],
                    summary or "",
                    content or "",
                )

                # ── Route to source-specific metadata table ───────────────────
                if source_type == SourceType.ACADEMIC.value:
                    await self._save_arxiv_metadata(conn, article_id, entry, now_str)
                elif source_type == SourceType.SOCIAL.value:
                    await self._save_hn_metadata(conn, article_id, entry, now_str)
                elif source_type == SourceType.MEDIA.value:
                    await self._save_media_metadata(conn, article_id, entry, now_str)
                elif source_type == SourceType.OFFICIAL.value:
                    await self._save_official_metadata(conn, article_id, entry, now_str)
                # aggregate (Product Hunt) — no specific metadata table needed yet

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

        if skipped_older > 0 or skipped_no_date > 0:
            logger.info(
                f"[{feed.get('name')}] Skipped {skipped_older} older entries "
                f"(cutoff={cutoff}), {skipped_no_date} undated."
            )

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
        conn = get_database()
        async with conn.execute("SELECT * FROM feeds WHERE enabled = 1") as cursor:
            feed_rows = await cursor.fetchall()
        logger.info(f"Found {len(feed_rows)} enabled feeds to crawl.")

        results = []
        for row in feed_rows:
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
                (id, name, url, source, source_url, source_type, category, enabled, description,
                 favicon_url, language, last_fetched_at, article_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    url = excluded.url,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    source_type = excluded.source_type,
                    category = excluded.category,
                    enabled = excluded.enabled,
                    description = excluded.description,
                    favicon_url = excluded.favicon_url,
                    language = excluded.language,
                    updated_at = excluded.updated_at
            """
            params = (
                feed_id, feed_data.name, feed_data.url, feed_data.source, feed_data.source_url,
                feed_data.source_type.value, feed_data.category, 1 if feed_data.enabled else 0,
                feed_data.description, feed_data.favicon_url, feed_data.language,
                now.isoformat(), now.isoformat(),
            )
        else:
            stmt = """
                INSERT OR IGNORE INTO feeds
                (id, name, url, source, source_url, source_type, category, enabled, description,
                 favicon_url, language, last_fetched_at, article_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?)
            """
            params = (
                feed_id, feed_data.name, feed_data.url, feed_data.source, feed_data.source_url,
                feed_data.source_type.value, feed_data.category, 1 if feed_data.enabled else 0,
                feed_data.description, feed_data.favicon_url, feed_data.language,
                now.isoformat(), now.isoformat(),
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
