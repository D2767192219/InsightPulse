# ─────────────────────────────────────────────────────────────────────────────
# services/scoring_engine.py
#
# 信号工程引擎 — AI 领域多维度热度评分
#
# 参考 docs/v2-ai-signals-engineering.md 设计文档
# 将原始文章数据转换为 6 大维度信号，并计算综合热度分。
#
# 六大信号维度：
#   1. Authority  — 来源权威性（官方首发 > 学术顶刊 > 媒体 > 社区）
#   2. Academic   — 学术性信号（arXiv 引用数、子域权重、代码/数据集）
#   3. Community — 社区共鸣信号（HackerNews 分数/评论、上榜速度）
#   4. Recency   — 时效性信号（内容类型半衰期衰减）
#   5. Quality   — 内容质量信号（摘要长度、阅读时长、技术词汇密度）
#   6. Novelty   — 语义新颖性信号（跨簇唯一性、新兴主题检测）
# ─────────────────────────────────────────────────────────────────────────────

import logging
import json
import math
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 配置常量
# ─────────────────────────────────────────────────────────────────────────────

# 一级来源类型权重
AUTHORITY_BY_TYPE = {
    "official":   3.0,
    "academic":   2.5,
    "media":      1.8,
    "social":     1.3,
    "aggregate":  1.0,
    "other":      1.0,
}

# 二级子源精细权重修正（乘以一级权重）
AUTHORITY_SUB_SOURCE = {
    # 官方渠道
    "OpenAI":         1.0,
    "DeepMind":       1.0,
    "Anthropic":      1.0,
    "Google AI":      1.0,
    "NVIDIA":          0.8,
    "AWS":            0.7,
    "Nature":         1.0,
    # 学术源（arXiv 各子域）
    "arXiv cs.LG":    1.0,
    "arXiv cs.CL":    1.0,
    "arXiv cs.CV":    0.9,
    "arXiv cs.AI":    0.8,
    "arXiv cs.RO":    1.2,
    # 科技媒体
    "MIT Technology Review": 1.0,
    "VentureBeat":           0.9,
    "TechCrunch":            0.8,
    "The Verge":             0.8,
    "SiliconANGLE":          0.7,
    "MarkTechPost":          0.7,
    "The Gradient":          1.0,
    "Synced Review":         0.8,
    "InfoQ":                 0.8,
    "AI News":               0.6,
    "Inside AI News":        0.6,
    # 社区/聚合
    "Hacker News":           1.0,
    "Hacker News ML":        1.0,
    "Hacker News AI":        1.2,
    "HN Front Page":         1.3,
    "Product Hunt":          0.8,
}

# arXiv 子域热度基线修正
ARXIV_SUBDOMAIN_HALFLIFE = {
    "cs.LG": 48,   # Machine Learning — 核心子域，半衰期最长
    "cs.CL": 48,   # NLP — 大模型热潮，关注度高
    "cs.CV": 36,   # Computer Vision — 成熟子域，论文量大
    "cs.AI": 36,   # AI — 综述性文章多，稀缺性低
    "cs.RO": 72,   # Robotics — 小众子域，单篇稀缺性高
}

# 内容类型半衰期（小时）
CONTENT_HALFLIFE = {
    "official_news":    6,
    "academic_paper":  48,
    "hn_discussion":   18,
    "deep_analysis":    72,
    "media_news":      12,
}

# 技术关键词类别（用于技术词汇密度计算）
TECH_KEYWORDS = {
    # 模型架构
    "transformer", "attention", "diffusion", "llm", "gpt", "cnn", "rl",
    "gan", "vae", "moe", "mixture", "scaling", "embedding", "token",
    # 训练技术
    "fine-tuning", "rlhf", "alignment", "distillation", "pruning",
    "quantization", "training", "pre-training", "sft", "dpo", "ppo",
    # 应用领域
    "multimodal", "reasoning", "code generation", "agent", "rag",
    "retrieval", "tool use", "planning", "world model",
    # 硬件/系统
    "gpu", "tpu", "inference", "parallelism", "distributed", "cluster",
    # 评估方法
    "benchmark", "sota", "ablation", "evaluation", "dataset", "human eval",
}

# 争议词（用于 controversy_score）
CONTROVERSY_KEYWORDS = {
    "risk", "danger", "threat", "harm", "bias", "misinformation",
    "disinformation", "fake", "scam", "fraud", "abuse", "exploit",
    "regulation", "ban", "restrict", "crackdown", "warn", "dangerous",
}

# 突破词（用于 breakthrough_score）
BREAKTHROUGH_KEYWORDS = {
    "breakthrough", "revolution", "discover", "novel", "first", "new state",
    "outperform", "exceed", "surpass", "record-breaking", "significant",
    "milestone", "game-changer", "paradigm", "unprecedented", "prove",
}

# 综合评分权重配置（初期经验值）
DEFAULT_WEIGHTS = {
    "authority":    2.0,
    "academic":     1.5,
    "community":    1.8,
    "recency":      1.2,
    "quality":      1.0,
    "novelty":      1.0,
    "platform":     1.1,
    "controversy":  0.5,
    "breakthrough": 0.25,
}

# 平台类型权重：用于将“平台内热度”映射到全局热度
PLATFORM_TYPE_WEIGHTS = {
    "official": 1.15,
    "academic": 1.2,
    "media": 1.0,
    "social": 0.95,
    "aggregate": 0.9,
    "other": 0.9,
}


# ─────────────────────────────────────────────────────────────────────────────
# 数据类
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ArticleSignals:
    """单篇文章的多维度信号"""
    article_id: str

    # 权威性信号
    authority_score: float = 1.0
    authority_source: str = ""
    is_first_publication: bool = False
    is_official_certified: bool = False

    # 学术性信号
    academic_score: float = 1.0
    citation_count: int = 0
    has_code: bool = False
    has_dataset: bool = False
    arxiv_subdomain: str = ""

    # 社区共鸣信号
    community_score: float = 0.0
    hn_score: int = 0
    hn_comments: int = 0
    hn_rank: int = 0
    trending_velocity: float = 1.0
    cross_source_mentions: int = 0

    # 时效性信号
    recency_score: float = 1.0
    hours_ago: float = 0.0
    content_type: str = "media_news"

    # 内容质量信号
    content_quality_score: float = 0.5
    reading_depth_score: float = 0.0
    tech_density_score: float = 0.0
    has_controversy_kw: bool = False
    has_breakthrough_kw: bool = False

    # 语义新颖性信号
    novelty_score: float = 1.0
    is_emerging: bool = False

    # 平台信号（V2：平台特定热度）
    platform_signal_score: float = 0.5
    platform_weight: float = 1.0

    # 综合评分
    composite_score: float = 0.0

    # 分项得分（用于可解释性报告）
    signal_breakdown: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class SignalSummary:
    """信号分布摘要（用于 API 返回和 Agent 上下文）"""
    date: str
    total_articles: int = 0

    # 各维度分布统计
    authority_mean: float = 0.0
    community_coverage_pct: float = 0.0
    academic_papers_pct: float = 0.0
    emerging_pct: float = 0.0

    # 来源分布
    top_sources: list[dict] = field(default_factory=list)
    source_type_distribution: dict = field(default_factory=dict)

    # 情感分布（如果有）
    sentiment_distribution: dict = field(default_factory=dict)

    # 新兴主题提示
    emerging_topic_hints: list[str] = field(default_factory=list)

    # 高分文章预览
    top_articles_preview: list[dict] = field(default_factory=list)

    # 信号维度分布（用于前端可视化）
    signal_dimension_stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# ScoringEngine
# ─────────────────────────────────────────────────────────────────────────────

class ScoringEngine:
    """
    多维度信号评分引擎

    流水线：
    1. score_articles()      — 对文章列表批量计算信号和综合评分
    2. compute_authority()   — 权威性信号
    3. compute_academic()    — 学术性信号
    4. compute_community()    — 社区共鸣信号
    5. compute_recency()      — 时效性信号
    6. compute_quality()     — 内容质量信号
    7. compute_composite()    — 综合评分
    8. get_signal_summary()  — 信号分布摘要
    9. compute_signals_for_articles() — 批量计算所有信号（主要 API）
    """

    def __init__(
        self,
        weights: Optional[dict] = None,
        now: Optional[datetime] = None,
    ):
        """
        Args:
            weights: 各维度权重配置，默认使用 DEFAULT_WEIGHTS
            now: 当前时间（用于测试注入）
        """
        self.weights = weights or DEFAULT_WEIGHTS.copy()
        self._now = now or datetime.now(timezone.utc)

    # ── Public API ────────────────────────────────────────────────────────────

    def score_articles(
        self,
        articles: list[dict],
        date: Optional[str] = None,
        top_k: int = 50,
    ) -> list[dict]:
        """
        对文章列表计算信号和综合评分。

        Args:
            articles: 原始文章列表（dict，每个包含 title/summary/source/...）
            date: 计算日期（YYYY-MM-DD），用于 signals 表写入
            top_k: 返回前 N 篇（按 composite_score 降序）

        Returns:
            带信号和评分的文章列表，按 composite_score 降序
        """
        if not articles:
            return []

        date = date or self._now.strftime("%Y-%m-%d")

        scored = []
        for article in articles:
            signals = self._compute_signals(article, date)
            article_copy = article.copy()
            article_copy["signals"] = signals
            article_copy["composite_score"] = signals.composite_score
            article_copy["authority_score"] = signals.authority_score
            article_copy["recency_score"] = signals.recency_score
            article_copy["content_quality_score"] = signals.content_quality_score
            scored.append(article_copy)

        # 按综合分降序
        scored.sort(key=lambda a: a["composite_score"], reverse=True)

        logger.info(
            f"[ScoringEngine] 评分完成，共 {len(scored)} 篇，"
            f"Top-1 score={scored[0]['composite_score']:.2f} "
            f"({scored[0].get('title', '')[:40]})"
        )

        return scored[:top_k]

    def compute_signals_for_articles(
        self,
        articles: list[dict],
        date: Optional[str] = None,
    ) -> list[ArticleSignals]:
        """
        对文章列表批量计算信号对象（不修改原始文章）。

        Args:
            articles: 原始文章列表
            date: 计算日期

        Returns:
            ArticleSignals 列表
        """
        date = date or self._now.strftime("%Y-%m-%d")
        return [self._compute_signals(a, date) for a in articles]

    def get_signal_summary(
        self,
        articles: list[dict],
        date: Optional[str] = None,
    ) -> SignalSummary:
        """
        生成信号分布摘要（供 Agent 和前端使用）。
        """
        date = date or self._now.strftime("%Y-%m-%d")

        if not articles:
            return SignalSummary(date=date, total_articles=0)

        signals_list = [
            a.get("signals") or self._compute_signals(a, date)
            for a in articles
        ]

        authority_scores = [s.authority_score for s in signals_list]
        community_scores = [s.community_score for s in signals_list]
        academic_scores = [s.academic_score for s in signals_list]
        recency_scores = [s.recency_score for s in signals_list]
        quality_scores = [s.content_quality_score for s in signals_list]
        novelty_scores = [s.novelty_score for s in signals_list]

        # 来源分布
        source_counts: dict = {}
        source_type_counts: dict = {}
        for a in articles:
            src = a.get("source", "unknown")
            src_type = a.get("source_type", "other")
            source_counts[src] = source_counts.get(src, 0) + 1
            source_type_counts[src_type] = source_type_counts.get(src_type, 0) + 1

        top_sources = sorted(
            [{"source": k, "count": v} for k, v in source_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        total = len(articles)

        summary = SignalSummary(
            date=date,
            total_articles=total,
            authority_mean=_mean(authority_scores) if authority_scores else 0,
            community_coverage_pct=len([s for s in community_scores if s > 0]) / total if total else 0,
            academic_papers_pct=len([s for s in academic_scores if s > 1.0]) / total if total else 0,
            emerging_pct=len([s for s in signals_list if s.is_emerging]) / total if total else 0,
            top_sources=top_sources,
            source_type_distribution={
                k: {"count": v, "pct": round(v / total, 3)}
                for k, v in source_type_counts.items()
            },
            signal_dimension_stats={
                "authority": _distribution_stats(authority_scores),
                "community": _distribution_stats(community_scores),
                "academic": _distribution_stats(academic_scores),
                "recency": _distribution_stats(recency_scores),
                "quality": _distribution_stats(quality_scores),
                "novelty": _distribution_stats(novelty_scores),
            },
            top_articles_preview=[
                {
                    "id": a.get("id", ""),
                    "title": a.get("title", "")[:60],
                    "source": a.get("source", ""),
                    "composite_score": a.get("composite_score", 0),
                }
                for a in sorted(
                    articles,
                    key=lambda x: x.get("composite_score", 0),
                    reverse=True,
                )[:5]
            ],
        )

        return summary

    # ── 信号计算 ──────────────────────────────────────────────────────────────

    def _compute_signals(self, article: dict, date: str) -> ArticleSignals:
        """计算单篇文章的所有信号"""
        article_id = article.get("id", "")
        signals = ArticleSignals(article_id=article_id)

        # 1. 权威性
        signals.authority_score, signals.authority_source = self._compute_authority(article)
        signals.is_first_publication = self._detect_first_publication(article)
        signals.is_official_certified = self._detect_official_certified(article)

        # 2. 学术性
        signals.academic_score, signals.citation_count, signals.has_code, signals.has_dataset, signals.arxiv_subdomain = \
            self._compute_academic(article)

        # 3. 社区共鸣
        signals.community_score, signals.hn_score, signals.hn_comments, signals.hn_rank, signals.trending_velocity = \
            self._compute_community(article)

        # 4. 时效性
        signals.recency_score, signals.hours_ago, signals.content_type = \
            self._compute_recency(article)

        # 5. 内容质量
        (
            signals.content_quality_score,
            signals.reading_depth_score,
            signals.tech_density_score,
            signals.has_controversy_kw,
            signals.has_breakthrough_kw,
        ) = self._compute_quality(article)

        # 6. 语义新颖性（默认 1.0，由 ClusteringEngine 更新）
        signals.novelty_score = 1.0
        signals.is_emerging = False

        # 7. 综合评分
        (
            signals.platform_signal_score,
            signals.platform_weight,
        ) = self._compute_platform_signal(article, signals)

        signals.composite_score = self._compute_composite(signals)

        # 8. 分项得分（用于可解释性）
        signals.signal_breakdown = {
            "authority_score": signals.authority_score,
            "academic_score": signals.academic_score,
            "community_score": signals.community_score,
            "recency_score": signals.recency_score,
            "content_quality_score": signals.content_quality_score,
            "novelty_score": signals.novelty_score,
            "platform_signal_score": signals.platform_signal_score,
            "platform_weight": signals.platform_weight,
            "is_first_publication": signals.is_first_publication,
            "is_official_certified": signals.is_official_certified,
        }

        return signals

    def _compute_authority(self, article: dict) -> tuple[float, str]:
        """权威性信号：来源类型 × 子源修正 × 首发加成"""
        source_type = article.get("source_type", "other")
        source = article.get("source", "")
        url = article.get("url", "")

        # 一级权重
        base_score = AUTHORITY_BY_TYPE.get(source_type, 1.0)

        # 二级子源修正
        sub_key = source
        if source in AUTHORITY_SUB_SOURCE:
            base_score *= AUTHORITY_SUB_SOURCE[source]

        # HN 特殊处理
        if "HN" in source or "Hacker News" in source:
            if "ML" in source or "AI" in source:
                base_score *= AUTHORITY_SUB_SOURCE.get("Hacker News AI", 1.2)
            elif "Front Page" in source:
                base_score *= AUTHORITY_SUB_SOURCE.get("HN Front Page", 1.3)

        # 首发加成（URL 中含官方域名则为首发概率高）
        official_domains = ["openai.com", "deepmind.com", "anthropic.com",
                            "nature.com", "arxiv.org", "github.com"]
        for domain in official_domains:
            if domain in url:
                base_score *= 1.2
                break

        return round(min(base_score, 3.0), 2), source_type

    def _compute_academic(self, article: dict) -> tuple[float, int, bool, bool, str]:
        """学术性信号：子域权重 × 引用数修正 × 可复现性"""
        source_type = article.get("source_type", "")
        source = article.get("source", "")
        url = article.get("url", "")

        # 默认值
        academic_score = 1.0
        citation_count = 0
        has_code = False
        has_dataset = False
        subdomain = ""

        if source_type != "academic":
            # 非学术源：如果提及 arXiv ID，也有一定学术性
            if "arxiv.org" in url or article.get("external_id", "").startswith("arxiv:"):
                academic_score = 1.3
            return academic_score, citation_count, has_code, has_dataset, subdomain

        # arXiv 子域判断
        if source == "arXiv":
            tags = article.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            tags_str = " ".join(tags).upper()

            if "CS.LG" in tags_str or "CS.ML" in tags_str:
                subdomain = "cs.LG"
                academic_score = 2.0 * 1.0
            elif "CS.CL" in tags_str or "CS.LT" in tags_str:
                subdomain = "cs.CL"
                academic_score = 2.0 * 1.0
            elif "CS.CV" in tags_str:
                subdomain = "cs.CV"
                academic_score = 2.0 * 0.9
            elif "CS.AI" in tags_str or "CS.NE" in tags_str:
                subdomain = "cs.AI"
                academic_score = 2.0 * 0.8
            else:
                subdomain = "cs.OTHER"
                academic_score = 2.0 * 0.7

        # 引用数修正（从 metadata 中获取）
        citation_count = article.get("citation_count", 0) or 0
        if citation_count > 0:
            if citation_count >= 200:
                academic_score *= 2.0
            elif citation_count >= 50:
                academic_score *= 1.6
            elif citation_count >= 10:
                academic_score *= 1.3

            # 连续型引用增益，避免分档导致大量同分
            citation_gain = 1.0 + min(math.log1p(citation_count) / 8.0, 0.8)
            academic_score *= citation_gain

        # 代码/数据集存在性
        url_lower = url.lower()
        has_code = any(kw in url_lower for kw in ["github.com", "colab.google", "kaggle.com", "modelscope"])
        has_dataset = any(kw in url_lower for kw in ["dataset", "data.huggingface", "paperswithcode"])

        if has_code and has_dataset:
            academic_score *= 1.5
        elif has_code:
            academic_score *= 1.3
        elif has_dataset:
            academic_score *= 1.2

        return round(min(academic_score, 3.2), 2), citation_count, has_code, has_dataset, subdomain

    def _compute_community(self, article: dict) -> tuple[float, int, int, int, float]:
        """社区共鸣信号：HN 分数归一化 + 上榜速度"""
        source_type = article.get("source_type", "")
        source = article.get("source", "")

        # 只有社交/聚合源有社区信号
        if source_type not in ("social", "aggregate") and "HN" not in source and "Hacker" not in source:
            return 0.0, 0, 0, 0, 1.0

        # 从 metadata 或直接字段获取 HN 数据
        hn_score = 0
        hn_comments = 0
        hn_rank = 0

        # 直接字段
        hn_score = article.get("hn_score", 0) or 0
        hn_comments = article.get("hn_comments", 0) or 0
        hn_rank = article.get("hn_rank", 0) or 0

        # metadata 嵌套
        metadata = article.get("hn_metadata", {}) or {}
        if metadata:
            hn_score = hn_score or metadata.get("hn_score", 0) or 0
            hn_comments = hn_comments or metadata.get("hn_comments", 0) or 0
            hn_rank = hn_rank or metadata.get("hn_rank", 0) or 0

        # 归一化
        hn_score_norm = min(1.0, (hn_score or 0) / 100)
        hn_comments_norm = min(1.0, (hn_comments or 0) / 50)
        community_score = hn_score_norm * 0.6 + hn_comments_norm * 0.4

        # HN 排名加成（排名越高得分越高）
        if hn_rank > 0 and hn_rank <= 10:
            community_score = min(1.0, community_score * 1.5)
        elif hn_rank > 10 and hn_rank <= 30:
            community_score = min(1.0, community_score * 1.2)

        # 上榜速度加成（估算）
        trending_velocity = 1.0
        if hn_rank > 0 and hn_rank <= 5:
            trending_velocity = 1.5
        elif hn_rank > 5 and hn_rank <= 20:
            trending_velocity = 1.2

        return round(community_score, 3), hn_score, hn_comments, hn_rank, trending_velocity

    def _compute_recency(self, article: dict) -> tuple[float, float, str]:
        """时效性信号：内容类型半衰期衰减"""
        published_at = article.get("published_at", "")
        content_type = self._detect_content_type(article)

        if not published_at:
            return 1.0, 0.0, content_type

        try:
            if isinstance(published_at, str):
                pub_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            else:
                pub_time = published_at
        except Exception:
            return 1.0, 0.0, content_type

        hours_ago = (self._now - pub_time).total_seconds() / 3600
        if hours_ago < 0:
            hours_ago = 0.0

        half_life = CONTENT_HALFLIFE.get(content_type, 24)
        recency_score = 0.5 ** (hours_ago / half_life)
        recency_score = min(1.0, recency_score)

        # 下限：超过 7 天的文章不至于完全归零
        if hours_ago > 168:  # 7 days
            recency_score = max(recency_score, 0.01)

        return round(recency_score, 4), round(hours_ago, 1), content_type

    def _compute_quality(self, article: dict) -> tuple[float, float, float, bool, bool]:
        """内容质量信号：摘要长度 + 阅读时长 + 技术词汇密度"""
        summary = article.get("summary", "") or ""
        content = article.get("content", "") or ""
        title = article.get("title", "") or ""
        reading_time = article.get("reading_time_minutes", 0) or 0

        total_text = f"{title} {summary} {content}"

        # 1. 摘要长度信号
        text_len = len(summary)
        length_score = min(1.0, text_len / 800)

        # 2. 阅读时长信号
        depth_score = min(0.5, reading_time * 0.05) if reading_time else 0.0

        # 3. 技术词汇密度
        words = re.findall(r"\b\w+\b", total_text.lower())
        matched = sum(1 for w in words if w in TECH_KEYWORDS)
        tech_density = (matched / len(words) * 10) if words else 0
        tech_density_score = min(1.0, tech_density)

        # 4. 争议词和突破词
        has_controversy = any(kw in total_text.lower() for kw in CONTROVERSY_KEYWORDS)
        has_breakthrough = any(kw in total_text.lower() for kw in BREAKTHROUGH_KEYWORDS)

        # 综合内容质量分
        content_quality = length_score * 0.4 + depth_score * 0.2 + tech_density_score * 0.4

        return (
            round(content_quality, 3),
            round(depth_score, 3),
            round(tech_density_score, 3),
            has_controversy,
            has_breakthrough,
        )

    def _compute_composite(self, signals: ArticleSignals) -> float:
        """综合评分公式（平台特定热度 + 平台权重）"""
        score = (
            (signals.authority_score ** self.weights["authority"])
            * (signals.academic_score ** self.weights["academic"])
            * (max(signals.community_score, 0.01) ** self.weights["community"])
            * (signals.recency_score ** self.weights["recency"])
            * (signals.content_quality_score ** self.weights["quality"])
            * (signals.novelty_score ** self.weights["novelty"])
            * (max(signals.platform_signal_score, 0.05) ** self.weights["platform"])
            * signals.platform_weight
        )

        # 线性加成项
        controversy_bonus = 0.0
        if signals.has_controversy_kw:
            controversy_bonus = self.weights["controversy"] * signals.community_score * 10

        breakthrough_bonus = 0.0
        if signals.has_breakthrough_kw:
            # 避免固定大额加分导致大量文章同分
            breakthrough_bonus = (
                self.weights["breakthrough"]
                * signals.authority_score
                * max(0.2, signals.content_quality_score)
                * 2.0
            )

        # 首发加成
        if signals.is_first_publication:
            score *= 1.3

        # 官方认证加成
        if signals.is_official_certified:
            score *= 1.2

        final_score = score + controversy_bonus + breakthrough_bonus

        return round(final_score, 4)

    def _compute_platform_signal(
        self,
        article: dict,
        signals: ArticleSignals,
    ) -> tuple[float, float]:
        """
        平台特定热度：
        - arXiv: 引用 + 学术质量 + 时效
        - HN/社区: 分数 + 评论 + 排名
        - 官方: 权威 + 时效 + 内容质量
        - 媒体/其他: 权威 + 质量 + 时效
        """
        source_type = article.get("source_type", "other")
        source = article.get("source", "")
        url = (article.get("url", "") or "").lower()

        platform_weight = PLATFORM_TYPE_WEIGHTS.get(source_type, 0.9)

        # arXiv / 学术源：热度与引用强相关
        if source_type == "academic" or "arxiv.org" in url or source.lower() == "arxiv":
            citation = max(0, signals.citation_count)
            citation_norm = min(1.0, math.log1p(citation) / math.log1p(500))
            platform_signal = (
                citation_norm * 0.55
                + signals.academic_score / 3.2 * 0.25
                + signals.recency_score * 0.2
            )
            return round(max(platform_signal, 0.02), 4), platform_weight

        # 社区源（HN/PH 等）：热度与互动强相关
        if source_type in ("social", "aggregate") or "hacker news" in source.lower() or "hn" in source.lower():
            rank_bonus = 0.0
            if signals.hn_rank and signals.hn_rank > 0:
                rank_bonus = max(0.0, (40 - min(signals.hn_rank, 40)) / 40) * 0.2
            platform_signal = (
                signals.community_score * 0.7
                + min(1.0, signals.trending_velocity / 1.5) * 0.2
                + rank_bonus
            )
            return round(max(platform_signal, 0.02), 4), platform_weight

        # 官方源：强调权威与时效
        if source_type == "official":
            platform_signal = (
                min(1.0, signals.authority_score / 3.0) * 0.45
                + signals.recency_score * 0.35
                + signals.content_quality_score * 0.2
            )
            return round(max(platform_signal, 0.02), 4), platform_weight

        # 媒体/其他：综合质量导向
        platform_signal = (
            min(1.0, signals.authority_score / 3.0) * 0.4
            + signals.content_quality_score * 0.35
            + signals.recency_score * 0.25
        )
        return round(max(platform_signal, 0.02), 4), platform_weight

    # ── 辅助方法 ─────────────────────────────────────────────────────────────

    def _detect_content_type(self, article: dict) -> str:
        """从标题/摘要推断内容类型，决定半衰期"""
        text = (
            article.get("title", "") + " " + (article.get("summary", "") or "")
        ).lower()

        official_keywords = ["release", "launch", "announce", "launches", "unveils",
                            "gpt", "claude", "gemini", "llama", "model"]
        if any(kw in text for kw in official_keywords):
            return "official_news"

        academic_keywords = ["paper", "arxiv", "study", "research", "proposed",
                            "submit", "preprint", "findings"]
        if any(kw in text for kw in academic_keywords):
            return "academic_paper"

        hn_markers = ["hn:", "ask hn", "show hn"]
        if any(m in text for m in hn_markers):
            return "hn_discussion"

        analysis_keywords = ["analysis", "review", "deep dive", "overview",
                           "how to", "guide", "tutorial"]
        if any(kw in text for kw in analysis_keywords):
            return "deep_analysis"

        return "media_news"

    def _detect_first_publication(self, article: dict) -> bool:
        """检测是否为首发（简单规则：URL 含官方域名）"""
        url = article.get("url", "").lower()
        official_domains = [
            "openai.com/blog", "deepmind.com/blog", "anthropic.com/news",
            "blog.google/research", "ai.meta.com/blog", "nature.com/articles",
        ]
        return any(domain in url for domain in official_domains)

    def _detect_official_certified(self, article: dict) -> bool:
        """检测是否为官方认证发布"""
        source = article.get("source", "")
        url = article.get("url", "").lower()
        official_sources = {"OpenAI", "DeepMind", "Anthropic", "Nature", "Google AI"}
        official_domains = ["openai.com", "deepmind.com", "anthropic.com", "nature.com"]
        return source in official_sources or any(d in url for d in official_domains)


# ─────────────────────────────────────────────────────────────────────────────
# 统计辅助
# ─────────────────────────────────────────────────────────────────────────────

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _distribution_stats(values: list[float]) -> dict:
    if not values:
        return {"mean": 0, "min": 0, "max": 0, "p50": 0, "p90": 0}
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "mean": round(_mean(values), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
        "p50": round(sorted_vals[n // 2], 3),
        "p90": round(sorted_vals[int(n * 0.9)], 3),
    }
