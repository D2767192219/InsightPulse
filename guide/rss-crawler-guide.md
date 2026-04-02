# RSS 爬取与数据清洗指南

> 基于 TrendRadar 项目解析，从零实现 RSS 数据抓取、清洗、结构化输出的完整方案。
> 以下所有代码均为 Python 实现。

---

## 一、数据流总览

```
RSS Feed URL（网站主动提供）
       ↓
  HTTP 请求获取 XML/JSON
       ↓
  Feed 解析（RSS 2.0 / Atom / JSON Feed）
       ↓
  文本清洗（HTML 实体、标签、多余空白）
       ↓
  字段提取（标题、链接、时间、摘要、作者）
       ↓
  结构化数据（RSSItem dataclass）
       ↓
  过滤与分组（关键词匹配 / 数量限制 / 新鲜度过滤）
       ↓
  排序输出（按时间 / 热度）
```

---

## 二、RSS 解析器实现

### 2.1 依赖安装

```bash
pip install feedparser requests
```

### 2.2 数据结构定义

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class RSSItem:
    """单条 RSS 条目的结构化数据"""
    title: str                      # 文章标题
    feed_id: str                     # RSS 源 ID
    feed_name: str                   # RSS 源显示名称
    url: str                         # 文章链接
    published_at: Optional[str] = None  # 发布时间（ISO 格式）
    summary: Optional[str] = None       # 文章摘要
    author: Optional[str] = None         # 作者
    crawl_time: str = ""             # 抓取时间
    first_time: str = ""             # 首次出现时间
    last_time: str = ""              # 最后出现时间
    count: int = 1                   # 出现次数
```

### 2.3 三种 Feed 格式的支持

RSS 世界里有三种主流格式，解析器需要全部支持：

#### 格式一：RSS 2.0（最常见）

```xml
<rss version="2.0">
  <channel>
    <item>
      <title>文章标题</title>
      <link>https://example.com/article</link>
      <pubDate>Thu, 02 Apr 2026 10:30:00 +0000</pubDate>
      <description>文章摘要...</description>
    </item>
  </channel>
</rss>
```

#### 格式二：Atom

```xml
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>文章标题</title>
    <link href="https://example.com/article"/>
    <updated>2026-04-02T10:30:00Z</updated>
    <summary>文章摘要...</summary>
    <author><name>作者名</name></author>
  </entry>
</feed>
```

#### 格式三：JSON Feed 1.1

```json
{
  "version": "https://jsonfeed.org/version/1.1",
  "title": "Site Name",
  "items": [
    {
      "title": "文章标题",
      "url": "https://example.com/article",
      "date_published": "2026-04-02T10:30:00Z",
      "summary": "文章摘要..."
    }
  ]
}
```

### 2.4 完整解析器代码

```python
import re
import html
import json
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False


@dataclass
class ParsedRSSItem:
    """解析后的单条 RSS 条目（内部中间格式）"""
    title: str
    url: str
    published_at: Optional[str] = None
    summary: Optional[str] = None
    author: Optional[str] = None
    guid: Optional[str] = None


class RSSParser:
    """RSS 解析器，支持 RSS 2.0、Atom 和 JSON Feed"""

    def __init__(self, max_summary_length: int = 500):
        if not HAS_FEEDPARSER:
            raise ImportError("需要安装 feedparser: pip install feedparser")
        self.max_summary_length = max_summary_length

    def parse(self, content: str, feed_url: str = "") -> List[ParsedRSSItem]:
        """
        解析 RSS/Atom/JSON Feed 内容

        Args:
            content: Feed 的原始文本（XML 或 JSON）
            feed_url: Feed URL（用于错误提示）

        Returns:
            解析后的条目列表
        """
        # 优先检测 JSON Feed
        if self._is_json_feed(content):
            return self._parse_json_feed(content, feed_url)

        # 使用 feedparser 解析 RSS/Atom
        feed = feedparser.parse(content)

        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS 解析失败: {feed.bozo_exception}")

        items = []
        for entry in feed.entries:
            item = self._parse_entry(entry)
            if item:
                items.append(item)
        return items

    # ── 内部方法 ─────────────────────────────────────────────

    def _is_json_feed(self, content: str) -> bool:
        """检测是否为 JSON Feed 格式"""
        content = content.strip()
        if not content.startswith("{"):
            return False
        try:
            data = json.loads(content)
            version = data.get("version", "")
            return "jsonfeed.org" in version
        except (json.JSONDecodeError, TypeError):
            return False

    def _parse_json_feed(self, content: str, feed_url: str = "") -> List[ParsedRSSItem]:
        """解析 JSON Feed 1.1 格式"""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON Feed 解析失败: {e}")

        items = []
        for item_data in data.get("items", []):
            item = self._parse_json_feed_item(item_data)
            if item:
                items.append(item)
        return items

    def _parse_json_feed_item(self, item_data: Dict[str, Any]) -> Optional[ParsedRSSItem]:
        """解析单个 JSON Feed 条目"""
        # 标题
        title = item_data.get("title", "")
        if not title:
            content_text = item_data.get("content_text", "")
            if content_text:
                title = content_text[:100] + ("..." if len(content_text) > 100 else "")
        title = self._clean_text(title)
        if not title:
            return None

        # 链接
        url = item_data.get("url", "") or item_data.get("external_url", "")

        # 发布时间
        published_at = None
        date_str = item_data.get("date_published") or item_data.get("date_modified")
        if date_str:
            published_at = self._parse_iso_date(date_str)

        # 摘要
        summary = item_data.get("summary", "")
        if not summary:
            content_text = item_data.get("content_text", "")
            content_html = item_data.get("content_html", "")
            summary = content_text or self._clean_text(content_html)
        if summary:
            summary = self._clean_text(summary)
            if len(summary) > self.max_summary_length:
                summary = summary[:self.max_summary_length] + "..."

        # 作者
        author = None
        authors = item_data.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if isinstance(a, dict) and a.get("name")]
            if names:
                author = ", ".join(names)

        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary or None,
            author=author,
            guid=item_data.get("id", "") or url,
        )

    def _parse_iso_date(self, date_str: str) -> Optional[str]:
        """解析 ISO 8601 日期格式"""
        if not date_str:
            return None
        try:
            date_str = date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(date_str)
            return dt.isoformat()
        except (ValueError, TypeError):
            return None

    def _parse_entry(self, entry) -> Optional[ParsedRSSItem]:
        """解析 feedparser 返回的单条 entry（RSS/Atom）"""
        title = self._clean_text(entry.get("title", ""))
        if not title:
            return None

        # 链接
        url = entry.get("link", "")
        if not url:
            links = entry.get("links", [])
            for link in links:
                if link.get("rel") == "alternate" or link.get("type", "").startswith("text/html"):
                    url = link.get("href", "")
                    break
            if not url and links:
                url = links[0].get("href", "")

        # 发布时间
        published_at = self._parse_date(entry)

        # 摘要
        summary = self._parse_summary(entry)

        # 作者
        author = self._parse_author(entry)

        # GUID
        guid = entry.get("id") or entry.get("guid", {}).get("value") or url

        return ParsedRSSItem(
            title=title,
            url=url,
            published_at=published_at,
            summary=summary,
            author=author,
            guid=guid,
        )

    def _clean_text(self, text: str) -> str:
        """
        文本清洗——这是数据清洗的核心步骤

        步骤：
        1. 解码 HTML 实体（&amp; → &, &lt; → <, &#x4E2D; → 中）
        2. 移除 HTML 标签（<b>加粗</b> → 加粗）
        3. 合并多余空白（多个空格 → 单个空格）
        4. 去除首尾空白
        """
        if not text:
            return ""

        # 1. 解码 HTML 实体
        text = html.unescape(text)

        # 2. 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)

        # 3. 合并多余空白
        text = re.sub(r'\s+', ' ', text)

        # 4. 去除首尾空白
        return text.strip()

    def _parse_date(self, entry) -> Optional[str]:
        """解析发布日期，支持多种格式"""
        # feedparser 自动解析到 published_parsed
        date_struct = entry.get("published_parsed") or entry.get("updated_parsed")
        if date_struct:
            try:
                dt = datetime(*date_struct[:6])
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

        # 手动解析 RFC 2822 格式
        date_str = entry.get("published") or entry.get("updated")
        if date_str:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

            # 尝试 ISO 格式
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return dt.isoformat()
            except (ValueError, TypeError):
                pass

        return None

    def _parse_summary(self, entry) -> Optional[str]:
        """解析摘要/描述字段"""
        summary = entry.get("summary") or entry.get("description", "")
        if not summary:
            content = entry.get("content", [])
            if content and isinstance(content, list):
                summary = content[0].get("value", "")
        if not summary:
            return None
        summary = self._clean_text(summary)
        if len(summary) > self.max_summary_length:
            summary = summary[:self.max_summary_length] + "..."
        return summary

    def _parse_author(self, entry) -> Optional[str]:
        """解析作者字段"""
        author = entry.get("author")
        if author:
            return self._clean_text(author)
        author = entry.get("dc_creator")
        if author:
            return self._clean_text(author)
        authors = entry.get("authors", [])
        if authors:
            names = [a.get("name", "") for a in authors if a.get("name")]
            if names:
                return ", ".join(names)
        return None
```

---

## 三、抓取器实现

### 3.1 RSS 源配置

```python
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RSSFeedConfig:
    """RSS 源配置"""
    id: str                     # 源 ID（唯一标识）
    name: str                   # 显示名称
    url: str                    # RSS Feed URL
    max_items: int = 0          # 最大条目数（0=不限制）
    enabled: bool = True        # 是否启用
    max_age_days: Optional[int] = None  # 文章最大保留天数（None=继承全局设置）
```

### 3.2 完整抓取器代码

```python
import time
import random
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import requests

from .parser import RSSParser, ParsedRSSItem


class RSSFetcher:
    """RSS 抓取器"""

    def __init__(
        self,
        feeds: List[RSSFeedConfig],
        request_interval: int = 2000,   # 请求间隔（毫秒）
        timeout: int = 15,              # 请求超时（秒）
        use_proxy: bool = False,
        proxy_url: str = "",
        timezone: str = "Asia/Shanghai",
        freshness_enabled: bool = True,  # 是否启用新鲜度过滤
        default_max_age_days: int = 3,   # 默认文章最大天数
    ):
        self.feeds = [f for f in feeds if f.enabled]
        self.request_interval = request_interval
        self.timeout = timeout
        self.parser = RSSParser()
        self.session = self._create_session(use_proxy, proxy_url)
        self.timezone = timezone
        self.freshness_enabled = freshness_enabled
        self.default_max_age_days = default_max_age_days

    def _create_session(self, use_proxy: bool, proxy_url: str) -> requests.Session:
        """创建 HTTP 会话"""
        session = requests.Session()
        session.headers.update({
            "User-Agent": "YourAppName/1.0 RSS Reader",
            "Accept": (
                "application/feed+json, application/json, "
                "application/rss+xml, application/atom+xml, "
                "application/xml, text/xml, */*"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        if use_proxy and proxy_url:
            session.proxies = {"http": proxy_url, "https": proxy_url}
        return session

    def fetch_all(self) -> List[RSSItem]:
        """
        抓取所有配置的 RSS 源

        Returns:
            所有源合并后的 RSSItem 列表
        """
        all_items = []
        for i, feed in enumerate(self.feeds):
            # 请求间隔（避免对目标服务器造成压力）
            if i > 0:
                interval = self.request_interval / 1000
                jitter = random.uniform(-0.2, 0.2) * interval
                time.sleep(interval + jitter)

            items, error = self._fetch_feed(feed)
            if error:
                print(f"[RSS] {feed.name}: {error}")
            else:
                all_items.extend(items)

        return all_items

    def _fetch_feed(self, feed: RSSFeedConfig) -> Tuple[List[RSSItem], Optional[str]]:
        """抓取单个 RSS 源"""
        try:
            response = self.session.get(feed.url, timeout=self.timeout)
            response.raise_for_status()

            # 解析 Feed
            parsed_items = self.parser.parse(response.text, feed.url)

            # 限制条目数量
            if feed.max_items > 0:
                parsed_items = parsed_items[:feed.max_items]

            # 转换为 RSSItem
            from datetime import datetime
            crawl_time = datetime.now().strftime("%H:%M")

            items = []
            for parsed in parsed_items:
                item = RSSItem(
                    title=parsed.title,
                    feed_id=feed.id,
                    feed_name=feed.name,
                    url=parsed.url,
                    published_at=parsed.published_at or "",
                    summary=parsed.summary or "",
                    author=parsed.author or "",
                    crawl_time=crawl_time,
                    first_time=crawl_time,
                    last_time=crawl_time,
                    count=1,
                )
                items.append(item)

            print(f"[RSS] {feed.name}: 获取 {len(items)} 条")
            return items, None

        except requests.Timeout:
            return [], f"请求超时 ({self.timeout}s)"
        except requests.RequestException as e:
            return [], f"请求失败: {e}"
        except ValueError as e:
            return [], f"解析失败: {e}"
        except Exception as e:
            return [], f"未知错误: {e}"

    @classmethod
    def from_config(cls, config: dict) -> "RSSFetcher":
        """
        从配置字典创建抓取器

        config 格式示例：
        {
            "enabled": True,
            "request_interval": 2000,
            "freshness_filter": {
                "enabled": True,
                "max_age_days": 3
            },
            "feeds": [
                {
                    "id": "hacker-news",
                    "name": "Hacker News",
                    "url": "https://news.ycombinator.com/rss",
                    "max_items": 30,
                    "enabled": True
                }
            ]
        }
        """
        freshness_config = config.get("freshness_filter", {})
        freshness_enabled = freshness_config.get("enabled", True)
        default_max_age_days = freshness_config.get("max_age_days", 3)

        feeds = []
        for feed_config in config.get("feeds", []):
            feed = RSSFeedConfig(
                id=feed_config.get("id", ""),
                name=feed_config.get("name", ""),
                url=feed_config.get("url", ""),
                max_items=feed_config.get("max_items", 0),
                enabled=feed_config.get("enabled", True),
                max_age_days=feed_config.get("max_age_days"),
            )
            if feed.id and feed.url:
                feeds.append(feed)

        return cls(
            feeds=feeds,
            request_interval=config.get("request_interval", 2000),
            timeout=config.get("timeout", 15),
            use_proxy=config.get("use_proxy", False),
            proxy_url=config.get("proxy_url", ""),
            timezone=config.get("timezone", "Asia/Shanghai"),
            freshness_enabled=freshness_enabled,
            default_max_age_days=default_max_age_days,
        )
```

---

## 四、数据清洗详解

### 4.1 清洗步骤拆解

每条原始数据从 Feed 出来到进入最终列表，要经过以下清洗环节：

#### Step 1：过滤无效标题

```python
title = self._clean_text(entry.get("title", ""))
if not title:
    return None  # 空标题直接跳过
```

**目的**：有些 Feed 会返回空标题或纯空白，不应该进入后续处理。

#### Step 2：HTML 清洗

```python
def _clean_text(self, text: str) -> str:
    # 1. 解码 HTML 实体
    text = html.unescape(text)
    # "DeepSeek &amp; OpenAI" → "DeepSeek & OpenAI"
    # "&#x4E2D;&#x6587;" → "中文"

    # 2. 移除 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # "<b>加粗</b>和<i>斜体</i>" → "加粗和斜体"
    # "<a href='...'>链接</a>" → "链接"

    # 3. 合并多余空白
    text = re.sub(r'\s+', ' ', text)
    # "标题   多个   空格" → "标题 多个 空格"

    return text.strip()
```

**效果示例**：

| 原始数据 | 清洗后 |
|---------|--------|
| `&lt;b&gt;ChatGPT&lt;/b&gt;发布新版本` | `ChatGPT发布新版本` |
| `DeepSeek &amp; OpenAI 合作` | `DeepSeek & OpenAI 合作` |
| `文章标题&nbsp;&nbsp;&nbsp;摘要` | `文章标题 摘要` |

#### Step 3：时间解析标准化

不同 Feed 的时间格式各不相同，统一转为 ISO 8601 格式：

```python
def _parse_date(self, date_str: str) -> Optional[str]:
    # 支持的格式：
    # "Thu, 02 Apr 2026 10:30:00 +0000"  → RFC 2822
    # "2026-04-02T10:30:00Z"             → ISO 8601
    # "2026-04-02 10:30:00"              → 常见变体
    # 自动检测格式并统一转为 ISO 格式存储
```

**目的**：后续做时间排序、新鲜度过滤时，统一格式更方便比较。

#### Step 4：URL 去重

```python
processed_urls = set()
for item in items:
    if item.url in processed_urls:
        continue
    processed_urls.add(item.url)
```

**目的**：同一个 Feed 可能通过不同字段（`url`、`guid`、`id`）重复返回同一篇文章，去重避免推送重复内容。

#### Step 5：摘要截断

```python
if summary and len(summary) > max_summary_length:
    summary = summary[:max_summary_length] + "..."
```

**目的**：RSS 的 `<description>` 可能是一篇完整文章正文（如 WordPress 博客）。只保留前 N 个字符，控制存储和后续处理的资源消耗。

---

## 五、新鲜度过滤

### 5.1 什么是新鲜度过滤？

RSS 源有时会返回几天甚至几个月前的旧文章（如博客归档页面的 Feed）。新鲜度过滤的作用是：**只保留最近 N 天内发布的文章**。

### 5.2 实现

```python
from datetime import datetime, timezone


def is_within_days(
    published_at: str,
    max_days: int,
    timezone_str: str = "Asia/Shanghai"
) -> bool:
    """判断发布时间是否在指定天数内"""
    if not published_at:
        return True  # 无时间信息，保留

    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(timezone_str)
    except Exception:
        tz = timezone.utc

    try:
        # 解析 ISO 格式时间
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)

        now = datetime.now(tz)
        age_days = (now - dt).total_seconds() / 86400
        return age_days <= max_days
    except (ValueError, TypeError):
        return True  # 解析失败，保守保留


def filter_by_freshness(
    items: List[RSSItem],
    max_age_days: int,
    timezone_str: str = "Asia/Shanghai"
) -> Tuple[List[RSSItem], int]:
    """
    根据新鲜度过滤文章

    Returns:
        (过滤后的列表, 被过滤掉的数量)
    """
    filtered = []
    removed_count = 0

    for item in items:
        if not item.published_at:
            # 无发布时间，保留
            filtered.append(item)
        elif is_within_days(item.published_at, max_age_days, timezone_str):
            # 在指定天数内，保留
            filtered.append(item)
        else:
            removed_count += 1

    return filtered, removed_count
```

### 5.3 配置方式

```python
# 全局默认：超过 3 天的文章不保留
default_max_age_days = 3

# 单个 Feed 可覆盖全局设置
# max_age_days = 1   → Hacker News 只需1天内
# max_age_days = 7    → 周更博客可保留7天
# max_age_days = 0    → 禁用此源的新鲜度过滤
```

---

## 六、关键词过滤与分组

### 6.1 过滤语法设计

支持 5 种语法：

| 语法 | 符号 | 含义 | 示例 |
|------|------|------|------|
| 普通词 | 无 | 包含即匹配 | `DeepSeek` |
| 必须词 | `+` | 必须同时包含 | `+发布`（和普通词组合用） |
| 过滤词 | `!` | 包含则排除 | `!广告` |
| 全局过滤 | `[GLOBAL_FILTER]` | 任何情况都排除 | `[GLOBAL_FILTER]\n广告\n推广` |
| 数量限制 | `@` | 每组最多显示N条 | `@10` |

### 6.2 配置解析

```python
import re
from typing import List, Tuple, Dict, Optional, Union


@dataclass
class WordItem:
    word: str
    is_regex: bool = False
    pattern: Optional[re.Pattern] = None
    display_name: Optional[str] = None


@dataclass
class WordGroup:
    required: List[WordItem]         # 必须词列表（+前缀）
    normal: List[WordItem]            # 普通词列表
    group_key: str                    # 组标识（用于统计）
    display_name: Optional[str] = None  # 显示名称（可选）
    max_count: int = 0                # 最大显示数量（0=不限制）


def parse_regex_word(word: str) -> WordItem:
    """解析单个词，识别正则表达式"""
    display_name = None

    # 处理显示名称：/pattern/ => 显示名称
    if "=>" in word:
        parts = re.split(r'\s*=>\s*', word, 1)
        word_config = parts[0].strip()
        if len(parts) > 1 and parts[1].strip():
            display_name = parts[1].strip()
    else:
        word_config = word.strip()

    # 解析正则：/pattern/ 格式
    regex_match = re.match(r'^/(.+)/[a-z]*$', word_config)
    if regex_match:
        pattern_str = regex_match.group(1)
        try:
            pattern = re.compile(pattern_str, re.IGNORECASE)
            return WordItem(word=pattern_str, is_regex=True,
                           pattern=pattern, display_name=display_name)
        except re.error:
            pass

    return WordItem(word=word_config, display_name=display_name)


def matches_word_groups(
    title: str,
    word_groups: List[WordGroup],
    filter_words: List[WordItem],
    global_filters: Optional[List[str]] = None
) -> bool:
    """
    检查标题是否匹配词组规则

    匹配顺序：全局过滤 → 过滤词(!) → 必须词(+) → 普通词 → 匹配
    """
    # 防御性检查
    if not isinstance(title, str):
        title = str(title) if title is not None else ""
    if not title.strip():
        return False

    title_lower = title.lower()

    # 1. 全局过滤（最高优先级）
    if global_filters:
        if any(f.lower() in title_lower for f in global_filters):
            return False

    # 2. 无词组配置 → 全部匹配
    if not word_groups:
        return True

    # 3. 过滤词检查
    for filter_item in filter_words:
        if _word_matches(filter_item, title_lower):
            return False

    # 4. 词组匹配
    for group in word_groups:
        required_ok = all(_word_matches(w, title_lower) for w in group.required) \
                      if group.required else True
        normal_ok = any(_word_matches(w, title_lower) for w in group.normal) \
                     if group.normal else True

        if required_ok and normal_ok:
            return True

    return False


def _word_matches(item: Union[str, WordItem], title_lower: str) -> bool:
    """检查单个词是否匹配"""
    if isinstance(item, str):
        return item.lower() in title_lower
    if item.is_regex and item.pattern:
        return bool(item.pattern.search(title_lower))
    return item.word.lower() in title_lower
```

### 6.3 配置加载

```python
def load_frequency_words(frequency_file: str) -> Tuple[List[WordGroup], List[WordItem], List[str]]:
    """
    从配置文件加载频率词规则

    文件格式：
        普通词1
        普通词2

        DeepSeek
        OpenAI
        +发布        # 必须词：DeepSeek/OpenAI + 发布

        [GLOBAL_FILTER]
        广告         # 全局过滤词
        推广
    """
    with open(frequency_file, "r", encoding="utf-8") as f:
        content = f.read()

    groups_raw = [g.strip() for g in content.split("\n\n") if g.strip()]

    processed_groups: List[WordGroup] = []
    filter_words: List[WordItem] = []
    global_filters: List[str] = []

    current_section = "WORD_GROUPS"

    for group in groups_raw:
        lines = [l.strip() for l in group.split("\n")
                 if l.strip() and not l.strip().startswith("#")]

        if not lines:
            continue

        # 检查是否为区域标记
        if lines[0].startswith("[") and lines[0].endswith("]"):
            section = lines[0][1:-1].upper()
            if section in ("GLOBAL_FILTER", "WORD_GROUPS"):
                current_section = section
                lines = lines[1:]

        if current_section == "GLOBAL_FILTER":
            global_filters.extend([l for l in lines if l])
            continue

        # 解析词组
        required_words: List[WordItem] = []
        normal_words: List[WordItem] = []
        max_count = 0

        for word in lines:
            if word.startswith("@"):
                try:
                    count = int(word[1:])
                    if count > 0:
                        max_count = count
                except (ValueError, IndexError):
                    pass
            elif word.startswith("!"):
                parsed = parse_regex_word(word[1:])
                filter_words.append(parsed)
            elif word.startswith("+"):
                required_words.append(parse_regex_word(word[1:]))
            else:
                normal_words.append(parse_regex_word(word))

        if required_words or normal_words:
            if normal_words:
                group_key = " ".join(w.word for w in normal_words)
            else:
                group_key = " ".join(w.word for w in required_words)

            processed_groups.append(WordGroup(
                required=required_words,
                normal=normal_words,
                group_key=group_key,
                max_count=max_count,
            ))

    return processed_groups, filter_words, global_filters
```

---

## 七、结构化输出

### 7.1 最终输出格式

经过爬取 → 清洗 → 过滤 → 分组后，每条新闻的结构化输出：

```python
@dataclass
class FilteredNewsItem:
    """最终输出给下游的条目"""
    title: str                    # 标题
    feed_name: str                # 来源名称
    url: str                      # 文章链接
    time_display: str             # 格式化后的时间（如 "04-02 10:30"）
    count: int = 1               # 出现次数
    ranks: List[int] = None      # 排名（RSS 用发布时间顺序）
    is_new: bool = False         # 是否为新增
```

### 7.2 分组统计结果

```python
@dataclass
class GroupedStats:
    """按关键词分组的统计结果"""
    word: str                     # 关键词/组名
    count: int                    # 匹配的新闻总数
    position: int                 # 配置顺序
    display_word: str             # 显示用名称
    titles: List[FilteredNewsItem]  # 该组下的新闻列表
    percentage: float             # 占比
```

### 7.3 完整分组统计函数

```python
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import zoneinfo


def count_rss_frequency(
    rss_items: List[RSSItem],
    word_groups: List[WordGroup],
    filter_words: List[WordItem],
    global_filters: Optional[List[str]] = None,
    max_news_per_keyword: int = 0,
    sort_by_position_first: bool = False,
    timezone_str: str = "Asia/Shanghai",
    quiet: bool = False,
) -> Tuple[List[Dict], int]:
    """
    按关键词分组统计 RSS 条目

    Returns:
        (分组统计结果列表, 总条目数)
    """
    if not rss_items:
        return [], 0

    # 无配置 → 显示全部
    if not word_groups:
        word_groups = [WordGroup(required=[], normal=[], group_key="全部")]

    # 初始化词组统计
    word_stats: Dict[str, Dict] = {}
    for group in word_groups:
        word_stats[group.group_key] = {"count": 0, "titles": []}

    total_items = len(rss_items)
    processed_urls = set()

    # 按发布时间排序，作为"排名"
    sorted_items = sorted(
        rss_items,
        key=lambda x: x.published_at or "",
        reverse=True
    )
    url_to_rank = {item.url: idx + 1 for idx, item in enumerate(sorted_items)}

    for item in rss_items:
        title = item.title
        url = item.url

        # URL 去重
        if url and url in processed_urls:
            continue
        if url:
            processed_urls.add(url)

        # 关键词过滤
        if not matches_word_groups(title, word_groups, filter_words, global_filters):
            continue

        # 找到匹配的词组（每个条目只匹配第一个词组）
        title_lower = title.lower()
        matched_group_key = None

        for group in word_groups:
            required_ok = all(_word_matches(w, title_lower) for w in group.required) \
                          if group.required else True
            normal_ok = any(_word_matches(w, title_lower) for w in group.normal) \
                        if group.normal else True

            if required_ok and normal_ok:
                matched_group_key = group.group_key
                break

        if not matched_group_key:
            continue

        # 格式化时间
        if item.published_at:
            try:
                dt = datetime.fromisoformat(
                    item.published_at.replace("Z", "+00:00")
                )
                try:
                    tz = zoneinfo.ZoneInfo(timezone_str)
                except Exception:
                    from datetime import timezone
                    tz = timezone.utc
                dt_local = dt.astimezone(tz)
                time_display = dt_local.strftime("%m-%d %H:%M")
            except Exception:
                time_display = ""
        else:
            time_display = ""

        # 排名
        rank = url_to_rank.get(url, 99)

        word_stats[matched_group_key]["count"] += 1
        word_stats[matched_group_key]["titles"].append({
            "title": title,
            "feed_name": item.feed_name,
            "url": url,
            "time_display": time_display,
            "count": 1,
            "ranks": [rank],
            "is_new": False,
        })

    # 构建最终结果
    stats = []
    for group in word_groups:
        group_key = group.group_key
        data = word_stats.get(group_key, {"count": 0, "titles": []})
        if data["count"] == 0:
            continue

        # 按发布时间排序（最新在前）
        sorted_titles = sorted(
            data["titles"],
            key=lambda x: x["ranks"][0] if x["ranks"] else 999
        )

        # 应用数量限制
        max_count = group.max_count or max_news_per_keyword
        if max_count > 0:
            sorted_titles = sorted_titles[:max_count]

        # 显示名称
        display_word = group.display_name or group_key

        stats.append({
            "word": display_word,
            "count": data["count"],
            "position": word_groups.index(group),
            "titles": sorted_titles,
            "percentage": round(data["count"] / total_items * 100, 2),
        })

    # 排序
    if sort_by_position_first:
        stats.sort(key=lambda x: (x["position"], -x["count"]))
    else:
        stats.sort(key=lambda x: (-x["count"], x["position"]))

    return stats, total_items
```

---

## 八、配置示例

### 8.1 RSS 源配置（config.yaml 格式）

```yaml
rss:
  enabled: true
  request_interval: 2000      # 每个源间隔 2 秒
  timeout: 15                  # 请求超时 15 秒
  freshness_filter:
    enabled: true              # 启用新鲜度过滤
    max_age_days: 3             # 默认保留 3 天内
  feeds:
    # 技术/开发者社区
    - id: "hacker-news"
      name: "Hacker News"
      url: "https://news.ycombinator.com/rss"
      max_items: 30
      max_age_days: 1           # HN 文章生命周期短，1天足够

    - id: "devto"
      name: "Dev.to"
      url: "https://dev.to/feed"
      max_items: 20

    - id: "github-trending"
      name: "GitHub Trending"
      url: "https://github.com/github/g trending.rss"
      max_items: 20

    - id: "product-hunt"
      name: "Product Hunt"
      url: "https://www.producthunt.com/feed"
      max_items: 15
      enabled: false            # 需要认证，可暂时禁用

    # 科技媒体
    - id: "ars-technica"
      name: "Ars Technica"
      url: "https://feeds.arstechnica.com/arstechnica/index"
      max_items: 15

    - id: "techcrunch"
      name: "TechCrunch"
      url: "https://techcrunch.com/feed/"
      max_items: 15

    # AI/机器学习
    - id: "arxiv-ai"
      name: "arXiv CS.AI"
      url: "http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&max_results=20"
      max_items: 20
      max_age_days: 7           # 论文生命周期长，保留 7 天
```

### 8.2 关键词配置（frequency_words.txt 格式）

```txt
# ═══════════════════════════════════
# 全局过滤词（优先级最高）
# ═══════════════════════════════════
[GLOBAL_FILTER]
广告
推广
震惊
标题党
揭秘
#

# ═══════════════════════════════════
# 词组配置（空行分隔）
# ═══════════════════════════════════

# 第1组：AI 与大模型
AI
大模型
LLM
ChatGPT
DeepSeek
OpenAI
Claude
+发布
+发布
@10

# 第2组：机器人与具身智能
人形机器人
具身智能
宇树
特斯拉机器人
+发布
@5

# 第3组：芯片与半导体
芯片
半导体
英伟达
光刻机
@8

# 第4组：智能汽车
自动驾驶
FSD
比亚迪
特斯拉
+发布
@5

# 第5组：投资与金融市场
美联储
加征关税
美股
A股
```

---

## 九、快速开始代码模板

```python
"""
RSS 爬取最小可运行示例
"""

import feedparser
import requests
from dataclasses import dataclass
from typing import List
import html
import re


@dataclass
class RSSItem:
    title: str
    url: str
    feed_name: str
    published_at: str = ""
    summary: str = ""


class SimpleRSSFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "MyApp/1.0"

    def fetch(self, url: str, feed_name: str = "Unknown") -> List[RSSItem]:
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        feed = feedparser.parse(resp.text)

        items = []
        for entry in feed.entries:
            title = self._clean(entry.get("title", ""))
            if not title:
                continue
            items.append(RSSItem(
                title=title,
                url=entry.get("link", ""),
                feed_name=feed_name,
                published_at=str(entry.get("published", "")),
                summary=self._clean(entry.get("summary", "")),
            ))
        return items

    def _clean(self, text: str) -> str:
        if not text:
            return ""
        text = html.unescape(text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()


# 使用
fetcher = SimpleRSSFetcher()

# Hacker News
hn_items = fetcher.fetch("https://news.ycombinator.com/rss", "Hacker News")
for item in hn_items[:5]:
    print(f"[{item.feed_name}] {item.title}")
    print(f"  URL: {item.url}")
    print(f"  Time: {item.published_at}")
    print()
```

运行效果：

```
[Hacker News] Show HN: I built a new programming language
  URL: https://example.com/new-lang
  Time: Thu, 02 Apr 2026 10:30:00 +0000

[Hacker News] Ask HN: What's your favorite dev tool?
  URL: https://example.com/ask-hn
  Time: Thu, 02 Apr 2026 09:15:00 +0000
```
