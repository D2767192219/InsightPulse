# BettaFish 事件预测机制深度解析

> 基于 [BettaFish (微舆)](https://github.com/YaoYiYao/BettaFish) 完整源码分析
> 深入剖析其「事件预测」和「趋势研判」能力的技术原理与实现细节

---

## 目录

1. [核心结论：预测的本质是什么？](#一核心结论预测的本质是什么)
2. [数据采集层：预测的原材料](#二数据采集层预测的原材料)
3. [热度信号工程：如何将多源数据转化为预测特征](#三热度信号工程如何将多源数据转化为预测特征)
4. [情感分析引擎：群体情绪的量化建模](#四情感分析引擎群体情绪的量化建模)
5. [语义聚类：新兴主题的发现机制](#五语义聚类新兴主题的发现机制)
6. [关键词优化中间件：搜索质量保障](#六关键词优化中间件搜索质量保障)
7. [论坛主持人：LLM 驱动的趋势研判](#七论坛主持人llm-驱动的趋势研判)
8. [综合报告 IR Schema：结构化预测输出](#八综合报告-ir-schema-结构化预测输出)
9. [MindSpider 主题发现：为预测提供种子话题](#九mindspider-主题发现为预测提供种子话题)
10. [完整的预测流水线架构](#十完整的预测流水线架构)
11. [方法论总结与局限性](#十一方法论总结与局限性)

---

## 一、核心结论：预测的本质是什么？

BettaFish 的「事件预测」是**多信号模式识别 + LLM 判断性预测**的混合系统，而非统计时序预测。

### 它「没有」什么

- **没有** ARIMA / Prophet / LSTM 等统计时序模型
- **没有** 回归分析、协整检验等计量经济学工具
- **没有** 基于贝叶斯推断的概率预测框架
- **没有** 知识图谱或因果推理引擎
- **没有** 实时流式计算（Flink / Spark Streaming）

### 它「有」什么

| 预测机制 | 类型 | 实现位置 |
|---|---|---|
| 加权热度分数（share×10 > comment×5 > like×1） | 经验公式型信号 | `InsightEngine/tools/search.py` |
| IP 地理位置扩散速度 | 早期预警信号 | 各平台的 `ip_location` 字段 |
| `relevance_score`（每日话题相关度） | 时序排名信号 | `MindSpider/schema/models_sa.py` |
| 5级情感分类 + 置信度 | 情绪量化信号 | `WeiboMultilingualSentiment` |
| KMeans 语义聚类 | 新兴主题发现 | `agent.py` |
| ForumHost LLM 研判 | LLM 叙事性预测 | `ForumEngine/llm_host.py` |
| `swotTable` + `pestTable` IR | 结构化预测输出 | `ReportEngine/ir/schema.py` |

**本质**：它是一个**以数据为中心的观察系统** + **以 LLM 为主观判断引擎**的舆情分析平台，预测能力来自于 LLM 对多维信号的综合判断，而非统计模型的推演。

---

## 二、数据采集层：预测的原材料

### 2.1 MindSpider 爬虫数据模型

MindSpider 是一个基于 Playwright 的多平台爬虫，对应 8 个平台的数据表（`MindSpider/schema/models_bigdata.py`）：

#### 内容表（7 张）

```
bilibili_video
douyin_aweme
weibo_note
xhs_note
kuaishou_video
zhihu_content
tieba_note
```

#### 评论表（7 张）

```
bilibili_comment
douyin_comment
weibo_comment
xhs_comment
kuaishou_comment
zhihu_comment
tieba_comment
```

### 2.2 预测相关的核心字段

#### 参与度指标（所有内容表均有）

| 字段 | 来源平台 | 预测含义 |
|---|---|---|
| `liked_count` | 全部 | 基础认可信号 |
| `comments_count` / `comment_count` | 全部 | 讨论深度信号（互动质量） |
| `share_count` / `shared_count` | 全部 | **传播意愿信号**（最具预测价值） |
| `collected_count` | 抖音/小红书 | 保存意愿 = 长期价值信号 |
| `video_play_count` | B站 | 曝光量基数 |
| `video_danmaku` | B站 | 实时互动强度 |
| `video_coin_count` | B站 | 深度认可（需主动操作） |
| `ip_location` | 微博/抖音/小红书/知乎/贴吧 | **地理扩散速度**（早期预警核心） |

#### 时间字段（所有表均有）

```
create_time / create_date_time / publish_time / time
```

跨平台统一时间格式（`search.py` 中的 `_to_datetime` 工具），使跨平台时序对齐成为可能。

#### 话题相关度

```
daily_topics.relevance_score  (Float)  — 每日话题相关度分数
daily_topics.news_count       (Integer) — 当日新闻数量
daily_news.rank_position      (Integer) — 话题排名（索引）
```

`rank_position` 随时间的变化轨迹是最直接的**舆情热度时序信号**。

---

## 三、热度信号工程：如何将多源数据转化为预测特征

### 3.1 加权热度公式

`search_hot_content` 方法（`InsightEngine/tools/search.py` 线 130–185）为每个平台定义了**经验加权的参与度公式**：

```python
# B站视频（考虑弹幕文化）
hotness = (
    liked_count      * 1.0 +     # 点赞：基础认可
    video_comment    * 5.0 +     # 评论：互动深度
    video_share      * 10.0 +    # 分享：传播意愿 ← 最强信号
    video_favorite   * 10.0 +    # 收藏：长期价值
    video_coin       * 10.0 +    # 投币：深度认可
    video_danmaku    * 0.5 +     # 弹幕：实时强度
    video_play       * 0.1       # 播放：曝光基数
)

# 抖音短视频
hotness = (
    liked_count   * 1.0 +   # 点赞
    comment_count * 5.0 +   # 评论
    share_count   * 10.0 +  # 分享 ← 最强信号
    collected_count* 10.0    # 收藏
)

# 微博帖子
hotness = (
    liked_count    * 1.0 +
    comments_count * 5.0 +
    shared_count   * 10.0    # 转发 ← 最强信号
)
```

**设计原理**：分享行为的认知成本远高于点赞——用户愿意主动分享，说明话题具有社交货币属性，是**传播链延伸的强预测信号**。这与传播学中「分享意愿 = 话题生命周期」的结论一致。

### 3.2 跨平台统一参与度字典

`MediaCrawlerDB._extract_engagement()` 方法（`search.py` 线 118）将 7 个平台的异构字段名映射为统一的字典结构：

```python
engagement = {
    "likes":     liked_count,           # 点赞数
    "comments":  comment_count,         # 评论数
    "shares":    shared_count,          # 分享/转发数
    "views":     play_count,            # 播放/阅读数
    "favorites": collected_count,        # 收藏数
    "coins":     coin_count,             # 投币/充电数（B站特有）
    "danmaku":   danmaku_count,         # 弹幕数（B站特有）
}
```

这一归一化使跨平台横向对比和聚合计算成为可能。

### 3.3 IP 地理位置扩散速度

部分平台的评论数据包含 `ip_location` 字段（如微博、抖音、小红书）。虽然没有显式的时间窗口计算，但这个字段理论上可以支持：

- **地理扩散广度分析**：话题在多少个不同 IP 地区出现
- **地理聚集模式**：评论 IP 是否集中在某地区（圈子内传播）还是均匀分布（破圈传播）
- **IP 突变检测**：评论突然来自新地区 = 新增用户群涌入 = 话题加速扩散信号

---

## 四、情感分析引擎：群体情绪的量化建模

### 4.1 模型架构

**模型**：`tabularisai/multilingual-sentiment-analysis`
**架构**：DistilBERT-based（轻量化 transformer）
**部署**：本地缓存（`SentimentAnalysisModel/WeiboMultilingualSentiment/model/`）
**语言支持**：22 种语言

### 4.2 五级情感分类

```python
# sentiment_analyzer.py — sentiment_map
SENTIMENT_LABELS = {
    0: "非常负面",   # Very Negative
    1: "负面",       # Negative
    2: "中性",       # Neutral
    3: "正面",       # Positive
    4: "非常正面",   # Very Positive
}
```

### 4.3 完整分析流水线

```python
def analyze_query_results(self, query_results, text_field="content",
                         min_confidence=0.5):
    # Step 1: 提取文本
    texts = [r[text_field] for r in query_results]

    # Step 2: 批量推理
    batch_result = self.analyze_batch(texts, show_progress=True)

    # Step 3: 计算分布
    sentiment_counts = {0:0, 1:0, 2:0, 3:0, 4:0}
    for result in batch_result.results:
        if result.analysis_performed:
            sentiment_counts[result.predicted_class] += 1

    total = sum(sentiment_counts.values())
    distribution = {k: v/total for k, v in sentiment_counts.items()}

    # Step 4: 高置信度过滤
    high_confidence = [r for r in results
                       if r.confidence >= min_confidence]

    return {
        "sentiment_distribution": distribution,
        "high_confidence_results": high_confidence,
        "average_confidence": batch_result.average_confidence,
        "dominant_sentiment": max(sentiment_counts, key=sentiment_counts.get)
    }
```

### 4.4 预测输出详解

| 输出字段 | 预测含义 |
|---|---|
| `sentiment_distribution` | 情感比例分布，追踪变化趋势 |
| `dominant_sentiment` | 主导情感方向（0-4 级） |
| `high_confidence_results` | 高置信度结果 = 可靠信号，过滤模糊数据 |
| `average_confidence` | 整体模型确定性，低于阈值时触发告警 |
| `sentiment_trajectory` | （通过时间窗口对比）情感随时间的变化方向 |

**预测应用**：
- 情感「由正转负」= 舆情危机信号
- 高置信度负面结果密集出现 = 快速发酵中的负面事件
- 中性主导但正面下降 = 沉默螺旋形成中

---

## 五、语义聚类：新兴主题的发现机制

### 5.1 算法流程

`_cluster_and_sample_results` 方法（`agent.py` 线 129）：

```python
def _cluster_and_sample_results(self, results, max_results=50,
                                 results_per_cluster=5):
    # Step 1: 提取文本（截取前500字符用于 embedding）
    texts = [r.title_or_content[:500] for r in results]

    # Step 2: 生成语义向量
    model = SentenceTransformer(
        "paraphrase-multilingual-MiniLM-L12-v2"  # 12 层 multilingual BERT
    )
    embeddings = model.encode(texts, show_progress_bar=False)
    # 输出: shape = (n_samples, 384) dense vectors

    # Step 3: KMeans 聚类
    n_clusters = min(max(2, max_results // results_per_cluster), len(results))
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)

    # Step 4: 每类内按热度降序采样
    sampled = []
    for cluster_id in range(n_clusters):
        cluster_indices = np.flatnonzero(labels == cluster_id)
        cluster_results = sorted(
            [results[i] for i in cluster_indices],
            key=lambda x: x.hotness_score or 0,
            reverse=True
        )
        sampled.extend(cluster_results[:results_per_cluster])

    return sampled  # 总数上限 50 条，多样性有保障
```

### 5.2 为什么这有助于预测

传统方法只返回「最热的 N 条」，这会导致：

- **热点掩盖效应**：一个爆款事件（1亿热度）会让所有其他话题都显得「不重要」
- **新兴信号丢失**：刚兴起的话题（热度低但语义相似内容在增加）永远无法进入 Top-N

聚类采样的效果：

- **多样性保障**：每个语义簇都有 `results_per_cluster=5` 的固定配额
- **新兴簇发现**：即使一个簇的总热度低，只要簇内有内容被采样，就说明存在独立的讨论方向
- **簇内排序**：同一簇内按热度降序，确保簇代表性内容的质量

### 5.3 新兴主题检测的隐含逻辑

```python
# 如果聚类后发现某个簇：
#   - 簇内结果数量在增加（跨时间窗口对比）
#   - 簇内平均 hotness_score 在上升
# → 这是一个正在壮大的新兴主题
# 但这个跨时间窗口的对比逻辑目前需要人工介入或额外开发
```

目前代码只做单次聚类，跨时间窗口的「新兴主题」检测需要额外的数据pipeline。

---

## 六、关键词优化中间件：搜索质量保障

### 6.1 作用

`KeywordOptimizer`（`InsightEngine/tools/keyword_optimizer.py`）是一个 **LLM 中间件**，在原始查询和数据库搜索之间插入一个改写步骤：

```
用户/Agent 口语化查询: "武汉大学出事大家怎么看"
        ↓
KeywordOptimizer (Qwen3 LLM)
        ↓
多关键词展开: ["武汉大学", "武大", "武大事件", "武汉大学最新",
              "武汉大学舆情", "武汉大学热点"]
        ↓
多路并行数据库查询
        ↓
结果去重 + 聚类采样
```

### 6.2 优化提示词策略

关键词黑名单（阻止预测性词汇污染搜索）：
```python
BLOCKED_KEYWORDS = [
    "未来展望", "发展趋势", "战略规划", "政策导向", "管理机制",
    "舆情传播", "公众反应", "情绪倾向",  # 这些词会让搜索结果偏向分析而非原始数据
]
```

系统提示词明确要求（`keyword_optimizer.py`）：
> "避免使用'舆情传播'、'公众反应'、'情绪倾向'、'展望'、'发展趋势'等官方词汇"

这是**刻意设计的**：预测必须基于原始数据信号，而非二手分析。二手分析文章本身就包含预测，会导致递归放大而非真实观测。

### 6.3 多关键词并行查询

```python
for keyword in optimized_response.optimized_keywords:
    # 每个关键词独立查询
    response = search_agency.search_topic_globally(topic=keyword)
    all_results.extend(response.results)

# 跨关键词去重
unique_results = self._deduplicate_results(all_results)
```

---

## 七、论坛主持人：LLM 驱动的趋势研判

### 7.1 这是什么

`ForumHost`（`ForumEngine/llm_host.py`）是 BettaFish 中**唯一一个显式要求「趋势预测」的组件**。它使用 Qwen3-235B 模型作为「主持人」，监听三个分析 Agent 的讨论，生成综合研判。

### 7.2 系统提示词中的预测指令

```python
# ForumEngine/llm_host.py — _build_system_prompt()

"""你是一个多agent舆情分析系统的论坛主持人。你的职责是：

1. 事件梳理：从各agent的发言中自动识别关键事件、人物、时间节点，
   按时间顺序整理事件脉络

2. 引导讨论：根据各agent的发言，引导深入讨论关键问题，探究深层原因

3. 纠正错误：结合不同agent的视角以及言论，
   如果发现事实错误或逻辑矛盾，请明确指出

4. 整合观点：综合不同agent的视角，形成更全面的认识，
   找出共识和分歧

5. 趋势预测：基于已有信息分析舆情发展趋势，提出可能的风险点  ← 核心

6. 推进分析：提出新的分析角度或需要关注的问题，
   引导后续讨论方向
"""
```

### 7.3 用户提示词模板

```python
# ForumEngine/llm_host.py — _build_user_prompt()

"""请你作为论坛主持人，基于以上agent的发言进行综合分析，请按以下结构组织你的发言：

**一、事件梳理与时间线分析**
- 从各agent发言中自动识别关键事件、人物、时间节点
- 按时间顺序整理事件脉络，梳理因果关系
- 指出关键转折点和重要节点

**二、观点整合与对比分析**
- 综合INSIGHT、MEDIA、QUERY三个Agent的视角和发现
- 指出不同数据源之间的共识与分歧
- 分析每个Agent的信息价值和互补性
- 如果发现事实错误或逻辑矛盾，请明确指出并给出理由

**三、深层次分析与趋势预测**      ← 预测模块
- 基于已有信息分析舆情的深层原因和影响因素
- 预测舆情发展趋势，指出可能的风险点和机遇
- 提出需要特别关注的方面和指标

**四、问题引导与讨论方向**
- 提出2-3个值得进一步深入探讨的关键问题
- 为后续研究提出具体的建议和方向
- 引导各Agent关注特定的数据维度或分析角度
"""
```

### 7.4 工作流程

```
1. LogMonitor tail -F 监听三个 Agent 日志
       ↓
2. 解析有效的 Agent 发言行（INSIGHT/MEDIA/QUERY）
       ↓
3. 每累积 5 条发言，触发一次 ForumHost LLM 调用
       ↓
4. Qwen3 生成约 1000 字的综合研判发言
       ↓
5. 写入 forum.log
       ↓
6. 各 Agent 的 FirstSummaryNode / ReflectionSummaryNode
   读取 HOST 发言 → 注入到总结 Prompt 中
       ↓
7. Report Agent 读取完整 forum.log → 作为章节生成上下文
```

### 7.5 时间戳注入

```python
def _call_qwen_api(self, system_prompt, user_prompt):
    current_time = datetime.now().strftime("%Y年%m月%d日%H时%M分")
    time_prefix = f"今天的实际时间是{current_time}"
    user_prompt = f"{time_prefix}\n{user_prompt}"
```

HOST 获得真实时间上下文，使趋势判断具有时间锚点（"基于今天（4月2日）的数据..."）。

---

## 八、综合报告 IR Schema：结构化预测输出

### 8.1 章节 JSON 结构（ReportEngine/ir/schema.py）

每个章节的 `blocks` 数组可以包含多种 block 类型，其中两种具有明确的预测语义：

### 8.2 SWOT 分析表

```json
{
  "type": "swotTable",
  "strengths": [
    {
      "title": "优势标题",
      "text": "优势描述",
      "detail": "详细说明",
      "impact": "高"    // 枚举: 低/中低/中/中高/高/极高
    }
  ],
  "weaknesses": [...],
  "opportunities": [...],
  "threats": [...]
}
```

**`impact` 字段的含义**：

| 值 | 预测含义 |
|---|---|
| 低 | 影响微弱，可忽略 |
| 中低 | 需关注，暂不行动 |
| 中 | 中等影响，建议跟踪 |
| 中高 | 重要影响，需要预案 |
| 高 | 重大影响，应立即响应 |
| 极高 | 危机级别，需最高级别关注 |

### 8.3 PEST 宏观分析表

```json
{
  "type": "pestTable",
  "political": {
    "trend": "正面利好",  // 枚举: 正面利好/负面影响/中性/不确定/持续观察
    "analysis": "..."
  },
  "economic": { "trend": "负面影响", "analysis": "..." },
  "social": { "trend": "持续观察", "analysis": "..." },
  "technological": { "trend": "正面利好", "analysis": "..." }
}
```

**`trend` 字段的含义**：

| 值 | 预测含义 |
|---|---|
| 正面利好 | 该维度有利于目标/话题的发展 |
| 负面影响 | 该维度对目标构成威胁 |
| 中性 | 影响不明确或两面性很强 |
| 不确定 | 信息不足，无法判断 |
| 持续观察 | 当前处于变化中，需继续跟踪 |

### 8.4 预测章节示例结构

```
##舆情态势综合分析
###舆情发展预判
基于当前数据的趋势预测：预计在未来3-7天内，该话题将呈现[下降/平稳/上升]趋势，
主要风险点为[具体描述]，主要机遇点为[具体描述]。
```

---

## 九、MindSpider 主题发现：为预测提供种子话题

### 9.1 BroadTopicExtraction 模块

`BroadTopicExtraction/topic_extractor.py` 是每日自动运行的主题发现 pipeline：

```python
class TopicExtractor:
    def extract_keywords_and_summary(self, news_list: List[Dict]) -> Dict:
        """
        输入: 每日热点新闻列表（from daily_news table）
        输出: {
            keywords: List[str],      # 最多100个关键词/话题
            summary: str              # 150-300字的新闻趋势摘要
        }
        """
```

### 9.2 每日主题发现流水线

```python
class BroadTopicExtraction:
    def run_daily_extraction(self):
        # Step 1: 收集全平台热点
        collector = NewsCollector()
        news = collector.collect_all()  # 从 daily_news 表获取

        # Step 2: 提取关键词和摘要
        extractor = TopicExtractor()
        result = extractor.extract_keywords_and_summary(news)

        # Step 3: 写入 daily_topics 表
        self.save_to_daily_topics(
            keywords=result["keywords"],
            summary=result["summary"],
            relevance_score=len(result["keywords"]),  # 关键词数量作为代理指标
            news_count=len(news)
        )
```

### 9.3 预测输入特征

`daily_topics` 表提供的预测种子：

- **`relevance_score`**：每日话题相关度分数，可追踪随时间的变化
- **`news_count`**：当日相关新闻数量，爆发期会有跳涨
- **`keywords[]`**：作为 Insight Agent 的搜索输入，形成「主题发现 → 深度分析 → 报告生成」闭环

---

## 十、完整的预测流水线架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     数据采集层 (MindSpider)                      │
│                                                                 │
│  bilibili_video ──→  liked_count, share_count, play_count     │
│  douyin_aweme   ──→  liked_count, share_count, collected_cnt  │
│  weibo_note     ──→  liked_count, shared_count, ip_location   │
│  xhs_note       ──→  liked_count, comment_count, ip_location  │
│  zhihu_content  ──→  voteup_count, comment_count              │
│  tieba_note     ──→  total_replay_num, ip_location            │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                   特征工程层 (InsightEngine)                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ search_hot_content() — 加权热度分数                        │  │
│  │   hotness = likes×1 + comments×5 + shares×10 +收藏×10   │  │
│  │   这是最具预测价值的原始特征                              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ _cluster_and_sample_results() — 语义聚类采样              │  │
│  │   paraphrase-multilingual-MiniLM-L12-v2 + KMeans         │  │
│  │   保证新兴主题不被热点淹没                               │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ WeiboMultilingualSentiment — 情感量化                     │  │
│  │   5级分类: [非常负面/负面/中性/正面/非常正面]             │  │
│  │   输出: distribution + high_confidence_results + avg_conf │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ KeywordOptimizer — 关键词改写                            │  │
│  │   过滤"发展趋势"等二手分析词                             │  │
│  │   确保搜索结果为原始数据而非预测性内容                    │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                   预测引擎层 (LLM Judgement)                    │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ForumHost — LLM 趋势研判                                  │  │
│  │   输入: 3个Agent的发言 + 当前时间戳                       │  │
│  │   输出: 事件梳理 + 观点整合 + 趋势预测 + 问题引导          │  │
│  │   能力: 风险点识别 / 机遇点识别 / 时间线预测              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ InsightEngine 报告章节 — 情感演变轨迹                     │  │
│  │   "舆情发展预判 [基于当前数据的趋势预测]"                 │  │
│  │   "深层原因与社会影响"                                    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ReportEngine IR — 结构化预测                              │  │
│  │   swotTable.impact ∈ {低/中低/中/中高/高/极高}           │  │
│  │   pestTable.trend ∈ {正面利好/负面影响/中性/             │  │
│  │                        不确定/持续观察}                   │  │
│  └───────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────────┐
│                   输出层 (综合报告)                              │
│                                                                 │
│  HTML 报告 ──→ swotTable + pestTable + 舆情发展预判章节       │
│  IR JSON   ──→ 可视化仪表盘 / 预警系统 / API 下游消费          │
│  forum.log ──→ 论坛主持人发言（供下次分析迭代参考）             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十一、方法论总结与局限性

### 11.1 预测能力的三层架构

| 层次 | 机制 | 预测类型 | 可靠性 |
|---|---|---|---|
| **信号层** | 加权热度分数（share×10） | 传播动能预测 | 中高（经验公式，有传播学依据） |
| **量化层** | 5级情感分类 + 聚类采样 | 新兴主题发现 | 中（受模型精度限制） |
| **研判层** | LLM 叙事性趋势分析 | 综合性趋势判断 | 低至中（依赖 LLM 推理能力） |

### 11.2 关键局限性

1. **无时序模型**：没有真正的「当前趋势外推」计算，所有「趋势」判断都是 LLM 的文字推演，缺乏统计置信区间

2. **无跨时间窗口对比**：聚类只做单次，没有时间序列上的「主题浮现」自动检测逻辑

3. **IP 数据未充分利用**：`ip_location` 字段被采集但没有自动的「地理扩散速度」计算 pipeline

4. **share/like 比率未显式计算**：这是传播学中最重要的早期预警信号之一，但目前只内嵌在热度的加权公式中，没有单独的比率追踪

5. **LLM 预测的幻觉风险**：ForumHost 和报告章节的「趋势预测」完全依赖 LLM 的推理质量，存在幻觉和过度推断的可能

### 11.3 如需增强预测能力的建议

```
当前缺失的预测能力         → 推荐引入的技术/方法

时序外推预测               → Prophet / ARIMA 对 relevance_score 列做趋势拟合
跨时间窗口主题浮现检测    → DBSCAN 密度聚类（追踪新簇出现）
地理扩散速度计算          → GeoPandas + 时间窗口滑动（ip_location 字段）
早期预警信号自动触发      → 阈值规则引擎（share/like 比突增 → 告警）
因果推理                  → 因果图模型（Causal Inference on engagement signals）
知识图谱增强预测          → Neo4j 实体关系 → 图注意力网络（GAT）
```

---

*文档基于 BettaFish (GPL-2.0 License) 源码生成，供技术分析与学习参考。*
