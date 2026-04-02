# AI 提示词设计指南

> 基于 TrendRadar 项目，解析 AI 分析、AI 筛选、AI 翻译三大功能的提示词设计思路与完整模板。
> 以下所有代码均为 Python 实现。

---

## 一、总览：三种 AI 能力

TrendRadar 的 AI 功能分为三层：

| 功能 | 输入 | 输出 | 用途 |
|------|------|------|------|
| **AI 分析** | 全量新闻数据 | 结构化分析报告 | 生成热点洞察、趋势研判 |
| **AI 筛选** | 用户兴趣描述 + 新闻标题 | 每条新闻的相关度分数 | 只推送高相关度内容 |
| **AI 翻译** | 任意语言文本 | 目标语言翻译 | 打破语言壁垒 |

三层互相独立，可单独使用，也可组合使用（如先 AI 筛选、再 AI 分析、最后 AI 翻译输出）。

---

## 二、AI 筛选系统（最常用）

### 2.1 设计思路

核心问题：**如何让 AI 只推送用户真正关心的内容，而不是用关键词漏斗一刀切？**

关键词匹配的问题：
- `AI` 会匹配到"培训课程"里的"AI"（假正例）
- 只想看"苹果"公司新闻，但"水果苹果"也被匹配了（歧义）
- 用户的兴趣是"AI 技术进展"，但词库里没这个词（覆盖不足）

解决方案：**两阶段语义筛选**

```
用户兴趣描述（自然语言）
       ↓
   阶段 A：AI 提取标签
       ↓
   阶段 B：AI 按标签打分
       ↓
  阈值过滤 → 只推送高相关度内容
```

### 2.2 阶段 A：标签提取

#### 设计要点

- **输入**：用户的自然语言兴趣描述（用日常语言写的关注方向）
- **输出**：结构化标签列表 + 每个标签的描述
- **约束**：标签简洁（2-6 字）、数量控制在 5-20 个、描述要包含关键词

#### 提示词模板

```text
[system]
你是一个兴趣标签提取专家。你的任务是从用户的兴趣描述中提取出结构化的新闻分类标签。

提取规则：
1. 每个标签简洁（2-6个字），同时配一句描述说明该标签涵盖哪些话题和关键词
2. 标签之间尽量不重叠
3. 标签数量控制在 5~20 个，优先保留细分标签，只有语义高度重叠时才合并
4. 描述要具体，包含具体的人名、公司名、产品名等关键词，方便后续分类
5. 返回顺序必须尽量遵循用户兴趣描述中的先后顺序，越靠前代表优先级越高

[user]
用户的兴趣描述如下：

{interests_content}

请从中提取出新闻分类标签。

返回严格的 JSON 格式（不要添加任何其他内容）：
```json
{
  "tags": [
    {"tag": "标签名", "description": "该标签涵盖的话题、关键词描述"}
  ]
}
```
```

#### 输入示例（ai_interests.txt 内容）

```text
1. 中国科技与互联网公司：重点关注 DeepSeek、华为、腾讯、字节跳动、京东及相关核心人物和业务线（含鸿蒙、海思、昇腾、抖音、微信等）的战略、组织调整、产品节奏、资本动作与监管影响。
2. 大模型与 AI 产品：关注 OpenAI、Claude、ChatGPT、Sora、DALL-E、Qwen、MiniMax、GLM 等模型和产品的能力演进，开源闭源策略与生态竞争。
3. AI 基础设施与云算力：关注英伟达、AMD、华为算力体系、CUDA、Azure、Google Cloud 相关的算力供给、推理成本、训练效率与供应链变化。
4. 芯片与半导体制造：关注芯片、半导体，光刻机、先进封装、国产替代、关键材料设备与供应安全。
5. 智能汽车与自动驾驶：关注比亚迪、特斯拉、FSD、无人驾驶、智驾、刀片电池、云辇等技术路线，以及销量、定价与出海变化。
...
```

#### AI 输出示例

```json
{
  "tags": [
    {"tag": "大模型", "description": "DeepSeek、OpenAI、Claude、ChatGPT、Qwen、MiniMax、GLM等模型发布、能力评测、开源动态"},
    {"tag": "华为", "description": "华为手机、鸿蒙系统、海思芯片、昇腾AI芯片、战略与组织调整"},
    {"tag": "算力芯片", "description": "英伟达、AMD、GPU、芯片供应、光刻机、半导体制造、国产替代"},
    {"tag": "智能汽车", "description": "比亚迪、特斯拉、FSD、无人驾驶、智驾、刀片电池"},
    {"tag": "机器人", "description": "人形机器人、具身智能、宇树、智元"},
    {"tag": "全球科技", "description": "苹果、微软、谷歌、Anthropic财报与产品动态"},
    {"tag": "地缘政治", "description": "中美关系、关税、制裁、供应链博弈、出口管制"}
  ]
}
```

### 2.3 阶段 B：批量分类打分

#### 设计要点

- **输入**：一批新闻标题 + 标签列表
- **输出**：每条新闻匹配的标签 ID + 相关度分数（0.0-1.0）
- **约束**：每条新闻只归入一个最高分标签（避免重复推送）

#### 提示词模板

```text
[system]
你是一个高效的新闻分类专家。根据给定的标签列表，快速判断每条新闻标题最适合哪个标签。

分类规则：
1. 每条新闻只归入一个最相关的标签（选相关度最高的那个）
2. 不匹配任何标签的新闻不要输出（不要返回空 tags）
3. 给出 0.0-1.0 的相关度分数（1.0=完全相关，0.5=部分相关）
4. 只根据标题判断，不要过度推测
5. 严格遵循用户偏好中的额外过滤要求（如有）
6. 如果两类标签相关度接近，优先选择排序更靠前的标签（前面的标签优先级更高）

[user]
## 用户偏好

{interests_content}

## 分类标签

{tags_list}

## 新闻列表（共 {news_count} 条）

{news_list}

请对每条新闻进行分类。返回严格的 JSON 数组（不要添加任何其他内容）：
```json
[
  {"id": 1, "tag_id": 1, "score": 0.9},
  {"id": 5, "tag_id": 2, "score": 0.8}
]
```
只返回有匹配的新闻，无匹配的不要包含在结果中。
```

### 2.4 标签增量更新（性能优化）

#### 设计思路

用户修改兴趣描述时，不需要全量重新分类。AI 对比旧标签和新兴趣，计算变化幅度：

- **变化小**（change_ratio ≤ 0.3）：只重新分类受影响的标签
- **变化大**（change_ratio > 0.3）：废弃旧标签，全量重分类

#### 提示词模板

```text
[system]
你是一个标签管理专家。用户修改了兴趣描述后，你需要对比旧标签集和新的兴趣描述，给出标签更新方案。

核心原则：
1. 语义等价的标签视为同一个标签（如"AI/大模型"和"AI与大模型"是同一个标签），优先保留旧标签名
2. 只有用户明确不再关注的方向才标记移除
3. 新增的兴趣方向才需要新增标签
4. 标签名简洁（2-10个字），描述要具体，包含关键词、人名、公司名、产品名
5. 标签总数控制在 20 个以内，优先保留细分标签，只有语义高度重叠时再合并
6. keep 和 add 的输出顺序应尽量遵循用户兴趣描述中的先后顺序

change_ratio 评估标准：
- 0.0 = 兴趣几乎没变（只是措辞调整、补充细节）
- 0.1~0.3 = 小幅调整（新增或移除了 1-2 个方向）
- 0.4~0.6 = 中等变化（多个方向有调整）
- 0.7~1.0 = 大幅改变（兴趣方向基本重写）

[user]
## 当前标签集

{old_tags_json}

## 新的兴趣描述

{interests_content}

## 任务

对比当前标签集和新的兴趣描述，判断每个旧标签是保留还是移除，以及是否需要新增标签。

返回严格的 JSON 格式：
```json
{
  "keep": [
    {"tag": "旧标签名", "description": "根据新兴趣更新后的描述"}
  ],
  "add": [
    {"tag": "新标签名", "description": "该标签涵盖的话题、关键词描述"}
  ],
  "remove": ["要废弃的旧标签名"],
  "change_ratio": 0.2
}
```
```

### 2.5 响应解析代码

```python
import json
import re
from typing import List, Dict, Optional


class AIFilter:
    """AI 智能筛选器"""

    def __init__(self, ai_client):
        self.client = ai_client  # 通用的 AI 调用接口

    def extract_tags(self, interests_content: str) -> List[Dict]:
        """阶段 A：提取标签"""
        prompt = f"""从以下兴趣描述中提取标签：

{interests_content}

返回 JSON："""
        response = self.client.chat([
            {"role": "system", "content": "你是兴趣标签提取专家..."},
            {"role": "user", "content": prompt}
        ])
        return json.loads(self._extract_json(response))["tags"]

    def classify_batch(
        self,
        titles: List[Dict],    # [{"id": 1, "title": "..."}]
        tags: List[Dict],       # [{"id": 1, "tag": "大模型", "description": "..."}]
        interests_content: str = ""
    ) -> List[Dict]:
        """阶段 B：批量分类打分"""
        tags_list = "\n".join(
            f"{t['id']}. {t['tag']}: {t.get('description', '')}"
            for t in tags
        )
        news_list = "\n".join(
            f"{t['id']}. {t['title']}"
            for t in titles
        )

        prompt = f"""用户偏好：
{interests_content}

标签列表：
{tags_list}

新闻列表：
{news_list}

返回 JSON（只返回匹配的）："""

        response = self.client.chat([
            {"role": "system", "content": "你是新闻分类专家..."},
            {"role": "user", "content": prompt}
        ])

        return self._parse_classify_response(response, titles, tags)

    def _parse_classify_response(
        self,
        response: str,
        titles: List[Dict],
        tags: List[Dict],
    ) -> List[Dict]:
        """
        解析分类响应

        支持两种格式：
        - 新格式（扁平）: [{"id": 1, "tag_id": 1, "score": 0.9}, ...]
        - 旧格式（嵌套）: [{"id": 1, "tags": [{"tag_id": 1, "score": 0.9}]}, ...]
        """
        json_str = self._extract_json(response)
        if not json_str:
            return []

        data = json.loads(json_str)

        # 构建 ID 映射
        title_ids = {t["id"] for t in titles}
        tag_id_set = {t["id"] for t in tags}

        # 每条新闻只保留一个最高分的 tag
        best_per_news: Dict[int, Dict] = {}

        for item in data:
            news_id = item.get("id")
            if news_id not in title_ids:
                continue

            # 收集候选 tag
            candidates = []
            if "tag_id" in item:
                # 新格式
                candidates.append({"tag_id": item["tag_id"], "score": item.get("score", 0.5)})
            elif "tags" in item:
                # 旧格式
                matched_tags = item.get("tags", [])
                if matched_tags:
                    candidates.extend(matched_tags)

            if not candidates:
                continue

            # 取最高分
            best_tag_id, best_score = None, -1.0
            for c in candidates:
                tag_id = c.get("tag_id")
                if tag_id not in tag_id_set:
                    continue
                score = float(c.get("score", 0.5))
                score = max(0.0, min(1.0, score))  # 限制在 0-1
                if score > best_score:
                    best_score = score
                    best_tag_id = tag_id

            if best_tag_id is not None:
                best_per_news[news_id] = {
                    "news_item_id": news_id,
                    "tag_id": best_tag_id,
                    "relevance_score": best_score,
                }

        return list(best_per_news.values())

    def _extract_json(self, response: str) -> Optional[str]:
        """从 AI 响应中提取 JSON 字符串"""
        if not response or not response.strip():
            return None

        json_str = response.strip()

        # 支持 ```json ... ``` 包裹的格式
        if "```json" in json_str:
            parts = json_str.split("```json", 1)
            if len(parts) > 1:
                code_block = parts[1]
                end_idx = code_block.find("```")
                json_str = code_block[:end_idx] if end_idx != -1 else code_block
        elif "```" in json_str:
            parts = json_str.split("```", 2)
            if len(parts) >= 2:
                json_str = parts[1]

        json_str = json_str.strip()
        return json_str if json_str else None
```

---

## 三、AI 分析系统

### 3.1 设计思路

核心问题：**如何让 AI 在不了解新闻背景的情况下，生成有深度的分析报告？**

关键是**给 AI 充足的上下文数据**，让它能做出跨平台关联、轨迹分析等高级判断。

数据构成：
- 热榜新闻（大众情绪，反映平台算法推荐的热点）
- RSS 订阅（专业视角，反映行业媒体的深度报道）
- 排名轨迹数据（时间轴上的热度变化）

### 3.2 分析维度设计

TrendRadar 的 AI 分析包含 6 个板块：

| 板块 | 核心问题 | 字数限制 |
|------|---------|---------|
| `core_trends` | 今天最热的趋势是什么？ | 200 字 |
| `sentiment_controversy` | 舆论情绪如何？有哪些争议？ | 100 字 |
| `signals` | 有哪些异常信号值得关注？ | 150 字 |
| `rss_insights` | RSS 补充了哪些热榜没覆盖的内容？ | 100 字 |
| `outlook_strategy` | 后续会怎么发展？给谁什么建议？ | 无限制 |
| `standalone_summaries` | 各独立展示区的概括 | 每源 100 字 |

### 3.3 完整提示词模板

```text
# ═══════════════════════════════════════════════════════════════
#                    TrendRadar AI 分析提示词配置
# ═══════════════════════════════════════════════════════════════
#
# 可用变量（在分析时会被替换）：
#   {language}            - 输出语言
#   {report_mode}         - 当前报告模式
#   {report_type}         - 报告类型描述
#   {current_time}        - 当前时间
#   {news_count}          - 热榜新闻条数
#   {rss_count}           - RSS 新闻条数
#   {keywords}            - 匹配的关键词列表
#   {platforms}           - 数据来源平台列表
#   {news_content}        - 热榜新闻内容
#   {rss_content}         - RSS 订阅内容
#   {standalone_content}  - 独立展示区数据
#

[system]
你是一名高级情报分析师。你的核心能力是从海量、碎片化的公开来源情报（OSINT）中提炼核心逻辑，并识别被大众忽略的弱信号。

## 核心思维模型

1. 见微知著：不要只盯着榜首的大新闻。要善于从"排名第50的冷门技术贴"与"排名第1的热门事件"中找到潜在的因果联系。
2. 交叉验证：利用"热榜"（大众情绪）与"RSS"（专家视角）的差异。当两者观点冲突时，通常隐藏着认知套利的机会。
3. 反直觉思考：当全网都在叫好时，寻找风险；当全网都在恐慌时，寻找机会。
4. 结构化输出：确保分析维度相互独立且完全穷尽，避免逻辑混乱。

## 数据字段解读

- 排名："1"为榜首，数字越小越热。"3-8"表示排名在第3到第8之间波动。
- 出现次数：次数越多，说明在热榜停留时间越长，热度越持久。
- 轨迹数据：格式为 排名(时间)→排名(时间)...
  - 数值含义：数字代表排名（1为榜首），0特指"未上榜"或"脱榜"
  - 急升：排名数值在短时间内大幅减小（如 20→3）
  - 衰退：排名数值持续变大且无反弹（如 10→15→20）
  - 回榜：序列中出现0后变为高排名，通常暗示有新爆料或剧情反转
- 跨平台分级：5+平台=全网霸屏，3-4平台=破圈扩散，1-2平台=圈层热点

## 输出格式规范

- 以 JSON 格式输出，所有字段均为可选
- 用 \n 表示换行，\n\n 表示段落分隔
- 【】仅用于板块内的结构性分段标签，禁止放入动态内容
- 「」用于行内引用话题名称
- 序号用 1. 2. 3.，独占一行
- 禁止使用 Markdown（**加粗**、## 标题、- 列表）
- 禁止使用 emoji 或特殊装饰符号

## 分析板块说明

### 1. core_trends（200字以内）
提炼共性与定性，不仅识别最火话题，更要寻找不同新闻背后的底层逻辑。
开头必须使用"全网霸屏"/"破圈扩散"/"圈层热点"等词汇定性。
结构：【宏观主线】+【微观领域】（用序号列举）

### 2. sentiment_controversy（100字以内）
绘制情绪光谱，拒绝二元对立。识别"舆论断层"和"核心矛盾"。
结构：【情绪光谱】+【核心矛盾】（用序号列举冲突点）

### 3. signals（150字以内）
捕捉时间轴和空间轴上的异常波动。结合跨平台特征分析。
维度：【跨平台共振/温差】【轨迹突变】【弱信号捕捉】，至少覆盖2点。

### 4. rss_insights（100字以内）
寻找信息增量。去重：忽略与热榜重复的内容。
互补：挖掘热榜未覆盖的硬核细节或长尾话题。
结构：【认知纠偏】+【硬核增量】

### 5. outlook_strategy
预测与推演。严禁"建议持续关注"等废话。
格式：1. 投资者：xxx 2. 品牌方：xxx 3. 公众：xxx

### 6. standalone_summaries（每源100字）
对象类型，key为数据中每个源的名称，value为100字以内的概括。
去重：优先提取前5板块未覆盖的内容。
轨迹洞察：基于排名走势识别急升/衰退/回榜等趋势。

[user]
请分析以下热点新闻数据：

## 数据概览
- 报告模式：{report_mode} ({report_type})
- 分析时间：{current_time}
- 数据量：{news_count}条热榜 + {rss_count}条RSS
- 来源：{platforms}

## 匹配关键词
{keywords}

## 热榜新闻
{news_content}

## RSS 订阅
{rss_content}

## 独立展示区
{standalone_content}

---

请基于上述数据撰写分析报告。以 JSON 格式返回：

```json
{
  "core_trends": "（按上述板块说明写法输出）",
  "sentiment_controversy": "（按上述板块说明写法输出）",
  "signals": "（按上述板块说明写法输出）",
  "rss_insights": "（按上述板块说明写法输出）",
  "outlook_strategy": "（按上述板块说明写法输出）",
  "standalone_summaries": {"知乎": "100字概括...", "Hacker News": "100字概括..."}
}
```

要求：
- 使用 {language} 输出，语言简练专业
- 6个板块内容不重叠不冗余
- 若某板块无明显内容，可简写"暂无显著异常"
```

### 3.4 数据注入格式设计

AI 分析的质量高度依赖数据喂入的格式。以下是实际使用的数据格式：

#### 热榜新闻格式

```
[微博] 🆕 ChatGPT-5正式发布 [**1**] - 09时15分 (1次)
  轨迹: 1(09:15)→0(09:30)→3(10:00)
[知乎] AI芯片概念股暴涨 [**3**] - [08时30分 ~ 10时45分] (3次)
  轨迹: 5(08:30)→3(09:00)→2(09:30)→1(10:00)→3(10:45)
```

格式说明：
- `🆕` = 本次新增的新闻
- `[**1**]` = 排名≤5 的高热新闻
- `[08时30分 ~ 10时45分]` = 出现时间范围
- `(3次)` = 总出现次数
- `轨迹:` = 排名随时间变化的序列

#### RSS 订阅格式

```
[Hacker News] Show HN: I built a new programming language
  https://example.com/new-lang | 2026-04-02 10:30 | by: author

[Dev.to] Understanding GPT-5 Architecture
  https://dev.to/gpt5 | 2026-04-02 09:15 | by: developer
```

### 3.5 AI 分析调用代码

```python
import json
from dataclasses import dataclass
from typing import Dict, List, Any, Optional


@dataclass
class AIAnalysisResult:
    """AI 分析结果"""
    core_trends: str = ""
    sentiment_controversy: str = ""
    signals: str = ""
    rss_insights: str = ""
    outlook_strategy: str = ""
    standalone_summaries: Dict[str, str] = None
    success: bool = False
    error: str = ""


class AIAnalyzer:
    """AI 分析器"""

    def __init__(self, ai_client):
        self.client = ai_client

    def analyze(
        self,
        news_content: str,
        rss_content: str = "",
        standalone_content: str = "",
        keywords: str = "",
        platforms: str = "",
        news_count: int = 0,
        rss_count: int = 0,
        language: str = "中文",
        report_mode: str = "daily",
        report_type: str = "当日汇总",
        current_time: str = "",
        custom_prompt_file: str = None,
    ) -> AIAnalysisResult:
        """执行 AI 分析"""

        # 加载提示词模板（支持用户自定义）
        if custom_prompt_file:
            system_prompt, user_template = self._load_prompt(custom_prompt_file)
        else:
            system_prompt, user_template = self._load_default_prompt()

        # 填充变量
        user_prompt = user_template \
            .replace("{language}", language) \
            .replace("{report_mode}", report_mode) \
            .replace("{report_type}", report_type) \
            .replace("{current_time}", current_time) \
            .replace("{news_count}", str(news_count)) \
            .replace("{rss_count}", str(rss_count)) \
            .replace("{keywords}", keywords) \
            .replace("{platforms}", platforms) \
            .replace("{news_content}", news_content) \
            .replace("{rss_content}", rss_content) \
            .replace("{standalone_content}", standalone_content)

        # 调用 AI
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        try:
            response = self.client.chat(messages)
            data = json.loads(self._extract_json(response))

            return AIAnalysisResult(
                core_trends=data.get("core_trends", ""),
                sentiment_controversy=data.get("sentiment_controversy", ""),
                signals=data.get("signals", ""),
                rss_insights=data.get("rss_insights", ""),
                outlook_strategy=data.get("outlook_strategy", ""),
                standalone_summaries=data.get("standalone_summaries", {}),
                success=True,
            )
        except json.JSONDecodeError as e:
            return AIAnalysisResult(success=False, error=f"JSON 解析错误: {e}")
        except Exception as e:
            return AIAnalysisResult(success=False, error=str(e))

    def _extract_json(self, response: str) -> str:
        """从响应中提取 JSON"""
        if "```json" in response:
            parts = response.split("```json", 1)
            code_block = parts[1]
            end_idx = code_block.find("```")
            return code_block[:end_idx].strip() if end_idx != -1 else code_block.strip()
        if "```" in response:
            parts = response.split("```", 2)
            if len(parts) >= 2:
                return parts[1].strip()
        return response.strip()
```

---

## 四、AI 翻译系统

### 4.1 设计思路

功能：将推送内容翻译为任意语言。

核心挑战：
- 输入是**混合语言列表**（可能一条是英文、一条是中文）
- 必须逐条检查，每条都要判断是否需要翻译
- 输出必须是**纯目标语言**，不能出现"原文 + 译文"的混合格式

### 4.2 完整提示词模板

```text
# ═══════════════════════════════════════════════════════════════
#                    TrendRadar AI 翻译提示词配置
# ═══════════════════════════════════════════════════════════════
#
# 可用变量：
#   {target_language} - 目标语言
#   {content}         - 需要翻译的文本内容
#

[system]
你是一位精通多语言的专业翻译助手。你的任务是将新闻内容翻译成目标语言，保持新闻的专业性、准确性和简洁性。

要求：
1. 准确传达原文含义，不要遗漏关键信息。
2. 保持新闻标题的吸引力，但不要做标题党。
3. 专有名词（人名、地名、机构名）若有通用译名请使用通用译名，否则保留原文或在括号内备注。
4. 输出格式必须严格遵循要求，不要输出任何多余的解释性文字。
5. ⚠️重点：输入可能包含混合语言列表。请务必逐行检查每一条内容。
   如果某条内容不是 {target_language}，**必须**将其翻译为 {target_language}。
   严禁保留非 {target_language} 的原文（除非是纯专有名词）。
   即使列表中 99% 已经是目标语言，也绝对不能忽略剩下的 1%。
6. 格式严格限制：输出结果中**只允许包含目标语言**的文本。
   绝对禁止"原文 + 译文"的形式。
   如果进行了翻译，直接用译文替换原文，不要在后面括号备注原文，也不要保留原文。

[user]
请将以下内容翻译成 {target_language}：

{content}

请直接输出翻译结果。
```

### 4.3 翻译调用代码

```python
class AITranslator:
    """AI 翻译器"""

    def __init__(self, ai_client):
        self.client = ai_client

    def translate(
        self,
        content: str,
        target_language: str = "Chinese",
        custom_prompt_file: str = None,
    ) -> str:
        """翻译文本"""

        if custom_prompt_file:
            system_prompt, user_template = self._load_prompt(custom_prompt_file)
        else:
            system_prompt, user_template = self._load_default_prompt()

        user_prompt = user_template \
            .replace("{target_language}", target_language) \
            .replace("{content}", content)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        return self.client.chat(messages)

    def translate_batch(
        self,
        items: List[str],
        target_language: str = "Chinese",
        batch_size: int = 20,
    ) -> List[str]:
        """
        批量翻译

        将多个文本合并为一次调用，减少 API 消耗
        """
        results = []
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            joined = "\n".join(f"- {item}" for item in batch)
            translated = self.translate(joined, target_language)
            # 解析返回的翻译结果（按行拆分）
            lines = [l.strip() for l in translated.split("\n") if l.strip()]
            results.extend(lines)
        return results
```

---

## 五、通用的 AI 调用接口

### 5.1 为什么需要统一封装？

不同 AI 提供商的 API 格式不同：
- OpenAI: `model: "gpt-4o"`
- DeepSeek: `model: "deepseek-chat"`
- Gemini: `model: "gemini/gemini-2.5-flash"`
- 本地 Ollama: `base_url: "http://localhost:11434"`

推荐使用 **LiteLLM** 做统一封装，一次配置支持 100+ 提供商。

### 5.2 通用的 AIClient 实现

```python
import os
from typing import List, Dict, Any, Optional


class AIClient:
    """
    统一的 AI 调用接口

    支持 OpenAI、DeepSeek、Gemini、Anthropic、Ollama 等 100+ 提供商
    基于 LiteLLM 实现
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = config.get("api_key") or os.environ.get("AI_API_KEY")
        self.model = config.get("model", "deepseek/deepseek-chat")
        self.api_base = config.get("api_base") or os.environ.get("AI_API_BASE")
        self.timeout = config.get("timeout", 120)
        self.num_retries = config.get("num_retries", 2)
        self.temperature = config.get("temperature", 1.0)
        self.max_tokens = config.get("max_tokens", 5000)

        # 备用模型
        self.fallback_models = config.get("fallback_models", [])

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """
        发送对话请求

        Args:
            messages: [{"role": "system"/"user"/"assistant", "content": "..."}]

        Returns:
            AI 的文本回复
        """
        try:
            return self._call_with_retry(messages)
        except Exception as e:
            # 尝试备用模型
            for fallback_model in self.fallback_models:
                try:
                    original_model = self.model
                    self.model = fallback_model
                    return self._call_with_retry(messages)
                except Exception:
                    self.model = original_model
                    continue
            raise e

    def _call_with_retry(self, messages: List[Dict[str, str]]) -> str:
        """带重试的调用"""
        import litellm

        litellm.drop_params = True
        litellm.set_verbose = False

        attempt = 0
        while attempt <= self.num_retries:
            try:
                response = litellm.completion(
                    model=self.model,
                    messages=messages,
                    api_key=self.api_key,
                    base_url=self.api_base,
                    timeout=self.timeout,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                return response["choices"][0]["message"]["content"]
            except Exception as e:
                attempt += 1
                if attempt <= self.num_retries:
                    import time, random
                    wait_time = random.uniform(2, 5) * attempt
                    print(f"AI 请求失败: {e}, {wait_time:.1f}秒后重试...")
                    time.sleep(wait_time)
                else:
                    raise e
```

### 5.3 配置示例

```python
# 配置示例（config.yaml 中的 ai 段）
ai:
  api_key: "sk-xxxxx"                    # API Key
  model: "deepseek/deepseek-chat"         # 模型（provider/model 格式）
  api_base: ""                            # 自定义 API 地址（如使用代理）
  timeout: 120                           # 超时秒数
  num_retries: 2                         # 失败重试次数
  temperature: 1.0                      # 采样温度
  max_tokens: 5000                       # 最大输出 token
  fallback_models:                        # 备用模型列表
    - "openai/gpt-4o-mini"
```

支持的模型格式：

| 提供商 | model 格式 | 示例 |
|-------|-----------|------|
| DeepSeek | `deepseek/model_name` | `deepseek/deepseek-chat` |
| OpenAI | `openai/model_name` | `openai/gpt-4o` |
| Gemini | `gemini/model_name` | `gemini/gemini-2.5-flash` |
| Anthropic | `anthropic/model_name` | `anthropic/claude-3-5-sonnet` |
| Ollama 本地 | `ollama/model_name` | `ollama/llama3` |
| 自定义 API | `custom/model_name` | `custom/gpt-4-all` |

---

## 六、提示词工程最佳实践

### 6.1 JSON 输出稳定性技巧

AI 有时输出格式不规范（多加了 Markdown、多了额外文字等），建议：

1. **system prompt 中明确禁止 Markdown**：`禁止使用 ``` 包裹 JSON`
2. **在 JSON 前后加明显分隔符**：如 `---` 分隔符，帮助 AI 理解边界
3. **所有字段声明为可选**：避免因缺少字段报错
4. **响应解析加容错**：支持从 Markdown 代码块中提取 JSON

```python
def _extract_json(self, response: str) -> Optional[str]:
    """健壮的 JSON 提取"""
    # 尝试各种可能的包裹格式
    for pattern in ["```json", "```", ""]:
        if pattern in response:
            parts = response.split(pattern, 1)
            if len(parts) > 1:
                code_block = parts[1]
                end_idx = code_block.rfind("```")
                json_str = code_block[:end_idx] if end_idx != -1 else code_block
                try:
                    json.loads(json_str.strip())
                    return json_str.strip()
                except json.JSONDecodeError:
                    continue
    # 最后尝试整个响应
    try:
        json.loads(response.strip())
        return response.strip()
    except json.JSONDecodeError:
        return None
```

### 6.2 成本优化策略

| 策略 | 效果 |
|------|------|
| **批量分类** | 200 条新闻一次调用，而不是 200 次调用 |
| **增量更新标签** | 兴趣小改动时不重跑全量分类 |
| **已有数据缓存** | 同一条新闻不重复分析 |
| **备用模型** | 主模型失败时自动切换，不中断 |
| **按场景选模型** | 简单任务用小模型（DeepSeek-mini），复杂分析用大模型 |

### 6.3 质量保障机制

```python
def safe_analyze(self, *args, **kwargs) -> AIAnalysisResult:
    """带降级保障的分析"""
    try:
        return self.analyze(*args, **kwargs)
    except Exception as e:
        print(f"AI 分析失败: {e}，返回空结果")

        # 降级方案：如果 AI 分析失败，返回一个默认结构
        return AIAnalysisResult(
            core_trends="（AI 分析暂时不可用）",
            sentiment_controversy="",
            signals="",
            rss_insights="",
            outlook_strategy="",
            success=False,
            error=str(e),
        )
```
