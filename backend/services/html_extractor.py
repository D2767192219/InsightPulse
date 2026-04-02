"""
HTML Extractor Service

Fetches article URLs, extracts:
  - Full article body text (cleaned, no ads/nav/sidebar)
  - Cover image URL
  - Author(s)
  - Language detection (zh / en / mixed)
  - Estimated reading time (word count / 200 wpm)

Uses heuristic selectors as primary, falls back to og:meta tags,
finally to generic heuristics — no LLM required.
"""

import re
import hashlib
import httpx
from typing import Optional
from bs4 import BeautifulSoup
from collections import Counter
import logging

logger = logging.getLogger(__name__)

# Average adult reading speed (words per minute)
WORDS_PER_MINUTE = 200

# Chinese characters per word equivalent (1 char ≈ 1 word for timing)
CHARS_PER_WORD = 1.0

# Language detection thresholds
ZH_CHAR_RATIO_THRESHOLD = 0.3  # if ≥30% chars are Chinese → zh


class HTMLExtractor:
    """
    Extract structured data from an article HTML page.

    Strategy:
    1. Fetch HTML (with timeout, User-Agent)
    2. Parse with BeautifulSoup
    3. Try article-body selectors (site-specific heuristics)
    4. Fall back to og:description, <meta name="description">
    5. Extract image from og:image, twitter:image, or first <img> in body
    6. Detect language from character distribution
    7. Estimate reading time from word count
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={"User-Agent": "InsightPulse/1.0 (Article Extractor; bot)"},
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Core extraction ───────────────────────────────────────────

    async def extract(self, url: str) -> "ExtractedArticle":
        """Extract all fields from an article URL. Returns ExtractedArticle."""
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            html = response.text
        except httpx.HTTPError as e:
            logger.error(f"HTMLExtractor: HTTP error fetching {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"HTMLExtractor: error fetching {url}: {e}")
            raise

        soup = BeautifulSoup(html, "lxml")
        return self._parse_soup(soup, url)

    def _parse_soup(self, soup: BeautifulSoup, url: str) -> "ExtractedArticle":
        title = self._extract_title(soup)
        content = self._extract_content(soup)
        image_url = self._extract_image(soup, url)
        author = self._extract_author(soup)
        language = self._detect_language(title, content)
        reading_time = self._estimate_reading_time(content)
        content_hash = self._hash_content(content)

        return ExtractedArticle(
            content=content,
            image_url=image_url,
            author=author,
            language=language,
            reading_time_minutes=reading_time,
            content_hash=content_hash,
        )

    # ── Title ─────────────────────────────────────────────────────

    def _extract_title(self, soup: BeautifulSoup) -> str:
        # og:title (most reliable for articles)
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            return og["content"].strip()

        # <title> tag
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)

        # Twitter title
        tw = soup.find("meta", attrs={"name": "twitter:title"})
        if tw and tw.get("content"):
            return tw["content"].strip()

        return ""

    # ── Content ───────────────────────────────────────────────────

    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract main article body using heuristic selectors."""
        # 1. Try <article> tag
        article = soup.find("article")
        if article:
            text = self._clean_text(article)
            if len(text) > 200:
                return text

        # 2. Common CMS / blog content class/id patterns
        for selector in [
            # Site-specific (high-value targets)
            {"name": "div", "class": re.compile(r"article-content|article-body|post-content|entry-content|story-body", re.I)},
            {"name": "div", "id": re.compile(r"article-content|article-body|post-content|entry-content|story-body", re.I)},
            # Generic
            {"name": "div", "class": re.compile(r"content|article|post|entry|story", re.I)},
        ]:
            candidates = soup.find_all(**selector)
            for el in candidates:
                # Reject too short or too long (likely wrong)
                text = self._clean_text(el)
                length = len(text)
                if 300 < length < 50000:
                    return text

        # 3. <main> tag fallback
        main = soup.find("main")
        if main:
            text = self._clean_text(main)
            if len(text) > 200:
                return text

        # 4. Fall back to description meta (better than nothing)
        for meta_name in ["og:description", "description", "twitter:description"]:
            meta = soup.find("meta", attrs={"name": meta_name}) or \
                   soup.find("meta", property=meta_name)
            if meta and meta.get("content"):
                return meta["content"].strip()

        return None

    def _clean_text(self, element) -> str:
        """Remove ads, nav, scripts, styles from element text."""
        # Clone so we don't modify original soup
        el = element.__copy__() if hasattr(element, "__copy__") else element

        # Remove noise elements
        for tag in el.find_all(["script", "style", "nav", "aside", "footer",
                                 "header", "form", "button", "iframe",
                                 "noscript", "svg"]):
            tag.decompose()

        # Remove elements with ad-related classes
        for noise in el.find_all(class_=re.compile(
                r"ad[s]?|sidebar|related|recommended|social|share|comment|"
                r"newsletter|subscribe|popup|modal|cookie|consent|captcha",
                re.I)):
            noise.decompose()

        text = el.get_text(separator=" ", strip=True)

        # Collapse excessive whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ── Image ──────────────────────────────────────────────────────

    def _extract_image(self, soup: BeautifulSoup, url: str) -> Optional[str]:
        # 1. og:image (most reliable)
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return self._absolutize_url(og["content"], url)

        # 2. Twitter card image
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return self._absolutize_url(tw["content"], url)

        # 3. First meaningful <img> in article body
        article = soup.find("article") or soup.find("main") or soup.find("div")
        if article:
            imgs = article.find_all("img", src=True)
            for img in imgs:
                src = img["src"]
                # Skip icons, 1x1 tracking pixels, data URIs
                if not src.startswith("data:") and "icon" not in src.lower() and "logo" not in src.lower():
                    if self._absolutize_url(src, url):
                        return self._absolutize_url(src, url)

        return None

    def _absolutize_url(self, url: str, base_url: str) -> str:
        """Convert relative URLs to absolute."""
        if not url:
            return ""
        if url.startswith("http://") or url.startswith("https://"):
            return url
        # Resolve relative to base
        try:
            return str(httpx.URL(base_url).join(httpx.URL(url)))
        except Exception:
            return url

    # ── Author ─────────────────────────────────────────────────────

    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        # 1. meta author
        meta_author = soup.find("meta", attrs={"name": "author"})
        if meta_author and meta_author.get("content"):
            return meta_author["content"].strip()

        # 2. og:article:author
        og_author = soup.find("meta", property="og:article:author")
        if og_author and og_author.get("content"):
            return og_author["content"].strip()

        # 3. <address> inside article
        article = soup.find("article")
        if article:
            address = article.find("address")
            if address:
                author_text = address.get_text(strip=True)
                if author_text:
                    return author_text

        # 4. <a> with rel="author" inside article
        if article:
            rel_author = article.find("a", rel="author")
            if rel_author:
                return rel_author.get_text(strip=True)

        # 5. Common class patterns for author name
        for cls in re.compile(r"author|byline|writer", re.I):
            el = soup.find(class_=cls)
            if el:
                text = el.get_text(strip=True)
                if text and len(text) < 100:
                    return text

        return None

    # ── Language detection ────────────────────────────────────────

    def _detect_language(self, title: str, content: Optional[str]) -> str:
        """Detect language: en / zh / mixed, based on character analysis."""
        text = (title or "") + " " + (content or "")
        if not text:
            return "en"

        # Count Chinese characters
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        total_chars = len(re.findall(r"\S", text))

        if total_chars == 0:
            return "en"

        ratio = chinese_chars / total_chars

        if ratio >= ZH_CHAR_RATIO_THRESHOLD:
            return "zh"
        elif ratio < 0.05:
            return "en"
        else:
            return "mixed"

    # ── Reading time ─────────────────────────────────────────────

    def _estimate_reading_time(self, content: Optional[str]) -> int:
        """Estimate reading time in minutes. Returns 0 if content is empty."""
        if not content:
            return 0
        # Count words: split on whitespace, filter noise
        words = re.findall(r"\b[\w']+\b", content)
        word_count = len(words)
        minutes = max(1, round(word_count / WORDS_PER_MINUTE))
        return minutes

    # ── Content hash ──────────────────────────────────────────────

    def _hash_content(self, content: Optional[str]) -> Optional[str]:
        """MD5 hash of normalized content for deduplication."""
        if not content:
            return None
        normalized = re.sub(r"\s+", "", content.strip().lower())
        return hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()


class ExtractedArticle:
    """Result of HTML extraction."""
    def __init__(
        self,
        content: Optional[str],
        image_url: Optional[str],
        author: Optional[str],
        language: str,
        reading_time_minutes: int,
        content_hash: Optional[str],
    ):
        self.content = content
        self.image_url = image_url
        self.author = author
        self.language = language
        self.reading_time_minutes = reading_time_minutes
        self.content_hash = content_hash

    def is_useful(self) -> bool:
        """Return True if we got enough content to be useful."""
        return bool(self.content and len(self.content) > 200)
