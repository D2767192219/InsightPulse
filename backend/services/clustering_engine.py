# ─────────────────────────────────────────────────────────────────────────────
# services/clustering_engine.py
#
# 语义聚类引擎
# 参考 BettaFish _cluster_and_sample_results 设计
#
# 核心能力：
#   1. SentenceTransformer embedding — 将文章文本转为语义向量
#   2. KMeans 聚类 — 发现语义相似的主题簇
#   3. 多样性采样 — 每簇按热度采样，防止热点掩盖新兴主题
#   4. 新兴主题检测 — 识别规模在增长的新簇
#
# 为什么需要聚类：
#   传统 Top-N 只返回「最热的 N 条」，会导致热点掩盖效应。
#   聚类后每个语义簇都有固定配额，新兴话题（热度低但语义相似内容在增加）
#   也能进入 Top-K，不会被爆款事件淹没。
# ─────────────────────────────────────────────────────────────────────────────

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── 模型配置 ──────────────────────────────────────────────────────────────────

# paraphrase-multilingual-MiniLM-L12-v2 — 12层 multilingual BERT，384维输出
# 支持 50+ 语言，适合中英文混合的 AI 新闻场景
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_BATCH_SIZE = 32


@dataclass
class ClusterResult:
    """聚类结果"""
    cluster_id: int
    articles: list[dict]           # 该簇内的文章
    representative_article: dict     # 代表性文章（热度最高的）
    avg_composite_score: float     # 簇内平均热度分
    size: int                      # 簇内文章数量
    topic_label: str = ""           # LLM 生成的主题标签


class SemanticClusteringEngine:
    """
    语义聚类引擎

    流水线：
    1. embed()             — SentenceTransformer 生成语义向量
    2. cluster()           — KMeans 聚类
    3. sample_per_cluster()— 每簇按热度采样（多样性保障）
    4. detect_emerging()    — 识别新兴主题（跨时间窗口对比）

    注意：embedding 模型首次调用时需要联网下载（约 500MB），
          之后会被 sentence-transformers 缓存到本地。
    """

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None

    # ── Public API ────────────────────────────────────────────────────────────

    def cluster_articles(
        self,
        articles: list[dict],
        max_results: int = 50,
        results_per_cluster: int = 5,
        score_field: str = "composite_score",
    ) -> tuple[list[dict], list[ClusterResult]]:
        """
        对文章进行语义聚类并采样。

        Args:
            articles: 带 composite_score 的文章列表（ScoringEngine 输出）
            max_results: 总返回上限
            results_per_cluster: 每个簇最多采样的文章数
            score_field: 用于簇内排序的分数字段

        Returns:
            (sampled_articles, cluster_results)
            sampled_articles: 聚类采样后的文章列表（供 Agent 使用）
            cluster_results: 每个簇的详细信息
        """
        if not articles:
            return [], []

        # Step 1: 生成 embedding
        texts = [self._get_text_for_embedding(a) for a in articles]
        embeddings = self._embed(texts)
        if embeddings is None:
            logger.warning(
                "[SemanticClustering] Embedding 失败，回退到纯热度排序"
            )
            return articles[:max_results], []

        # Step 2: KMeans 聚类
        n_clusters = self._compute_n_clusters(len(articles), max_results, results_per_cluster)
        cluster_labels = self._kmeans_predict(embeddings, n_clusters)

        # Step 3: 按簇分组
        clusters = self._group_by_cluster(articles, cluster_labels, embeddings)

        # Step 4: 每簇内按热度降序采样
        sampled = []
        cluster_results = []

        for cluster_id, (cluster_articles, cluster_embeddings) in clusters.items():
            # 簇内按 composite_score 降序
            sorted_cluster = sorted(
                cluster_articles,
                key=lambda a: a.get(score_field, 0.0),
                reverse=True,
            )

            # 取前 results_per_cluster 篇
            sampled_cluster = sorted_cluster[:results_per_cluster]
            sampled.extend(sampled_cluster)

            # 簇统计信息
            scores = [a.get(score_field, 0.0) for a in sorted_cluster]
            cluster_results.append(ClusterResult(
                cluster_id=cluster_id,
                articles=sorted_cluster,
                representative_article=sorted_cluster[0] if sorted_cluster else {},
                avg_composite_score=sum(scores) / len(scores) if scores else 0.0,
                size=len(sorted_cluster),
            ))

            if len(sampled) >= max_results:
                break

        # 如果还没到 max_results，继续补充剩余高分文章
        if len(sampled) < max_results:
            sampled_ids = {a.get("id") for a in sampled}
            for article in articles:
                if article.get("id") not in sampled_ids:
                    sampled.append(article)
                    if len(sampled) >= max_results:
                        break

        # 按 composite_score 降序最终排序
        sampled.sort(key=lambda a: a.get(score_field, 0.0), reverse=True)
        sampled = sampled[:max_results]

        logger.info(
            f"[SemanticClustering] 聚类完成：{len(cluster_results)} 个簇，"
            f"采样 {len(sampled)} 篇文章"
        )

        return sampled, cluster_results

    def embed_for_dedup(
        self,
        articles: list[dict],
    ) -> list[list[float]]:
        """
        为去重/相似度计算生成 embedding 向量。
        """
        if not articles:
            return []
        texts = [self._get_text_for_embedding(a) for a in articles]
        return self._embed(texts) or []

    def compute_similarity(
        self,
        vec1: list[float],
        vec2: list[float],
    ) -> float:
        """
        计算两个向量的余弦相似度。
        """
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)

    def detect_emerging_clusters(
        self,
        current_clusters: list[ClusterResult],
        previous_clusters: list[ClusterResult],
        growth_threshold: float = 1.2,
    ) -> list[ClusterResult]:
        """
        跨时间窗口新兴主题检测。

        对比 current_clusters 和 previous_clusters，
        识别规模增长 > growth_threshold 倍的新簇。
        这些新簇代表正在兴起的新话题。
        """
        emerging = []
        for curr in current_clusters:
            # 匹配语义最接近的历史簇
            best_match = None
            best_sim = 0.0

            for prev in previous_clusters:
                sim = self._cluster_embedding_similarity(
                    curr.articles, prev.articles
                )
                if sim > best_sim:
                    best_sim = sim
                    best_match = prev

            if best_match is None or best_sim < 0.7:
                # 完全新出现的簇
                emerging.append(curr)
            else:
                growth = curr.size / max(1, best_match.size)
                avg_score_growth = (
                    curr.avg_composite_score / max(0.01, best_match.avg_composite_score)
                )
                if growth >= growth_threshold or avg_score_growth >= growth_threshold:
                    emerging.append(curr)

        if emerging:
            logger.info(
                f"[SemanticClustering] 检测到 {len(emerging)} 个新兴主题簇"
            )

        return emerging

    # ── Internal Methods ───────────────────────────────────────────────────────

    @property
    def model(self):
        """延迟加载 SentenceTransformer 模型"""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                logger.info(
                    f"[SemanticClustering] 模型加载完成: {self.model_name}"
                )
            except ImportError:
                logger.error(
                    "[SemanticClustering] sentence-transformers 未安装。"
                    "请运行: pip install sentence-transformers"
                )
                raise
        return self._model

    def _embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """生成文本的语义向量"""
        try:
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"[SemanticClustering] Embedding 生成失败: {e}")
            return None

    def _compute_n_clusters(
        self,
        n_articles: int,
        max_results: int,
        results_per_cluster: int,
    ) -> int:
        """
        计算最优簇数。
        策略：保证每个簇至少能贡献 results_per_cluster 篇文章，
        同时簇数不宜过多（每簇至少 2 篇文章）。
        """
        max_clusters = max_results // results_per_cluster
        min_clusters = max(2, n_articles // (results_per_cluster * 2))
        return min(max_clusters, max(min_clusters, 2))

    def _kmeans_predict(
        self,
        embeddings: list[list[float]],
        n_clusters: int,
    ) -> list[int]:
        """执行 KMeans 聚类"""
        try:
            import numpy as np
            from sklearn.cluster import KMeans

            arr = np.array(embeddings)
            kmeans = KMeans(
                n_clusters=n_clusters,
                random_state=42,
                n_init=10,
            )
            labels = kmeans.fit_predict(arr)
            return labels.tolist()
        except ImportError:
            logger.error(
                "[SemanticClustering] sklearn 未安装。"
                "请运行: pip install scikit-learn"
            )
            return [0] * len(embeddings)
        except Exception as e:
            logger.error(f"[SemanticClustering] KMeans 聚类失败: {e}")
            return [0] * len(embeddings)

    def _group_by_cluster(
        self,
        articles: list[dict],
        labels: list[int],
        embeddings: list[list[float]],
    ) -> dict[int, tuple[list[dict], list[list[float]]]]:
        """按簇标签分组文章和对应的 embedding"""
        groups: dict[int, tuple[list[dict], list[list[float]]]] = {}
        for article, label, emb in zip(articles, labels, embeddings):
            if label not in groups:
                groups[label] = ([], [])
            groups[label][0].append(article)
            groups[label][1].append(emb)
        return groups

    def _get_text_for_embedding(self, article: dict) -> str:
        """从文章中提取用于 embedding 的文本（前 500 字符截断）"""
        title = article.get("title", "")
        summary = (article.get("summary") or "")[:500]
        return f"{title} {summary}".strip()[:512]

    def _cluster_embedding_similarity(
        self,
        cluster1: list[dict],
        cluster2: list[dict],
    ) -> float:
        """
        计算两个簇的语义相似度（基于 centroid 余弦相似度）。
        """
        if not cluster1 or not cluster2:
            return 0.0

        texts1 = [self._get_text_for_embedding(a) for a in cluster1[:10]]
        texts2 = [self._get_text_for_embedding(a) for a in cluster2[:10]]

        emb1 = self._embed(texts1) or []
        emb2 = self._embed(texts2) or []

        if not emb1 or not emb2:
            return 0.0

        import numpy as np

        centroid1 = np.mean(emb1, axis=0).tolist()
        centroid2 = np.mean(emb2, axis=0).tolist()

        return self.compute_similarity(centroid1, centroid2)
