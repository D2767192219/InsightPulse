# ─────────────────────────────────────────────────────────────────────────────
# agents/trend/agent.py
#
# Trend Agent — 趋势洞察
# 内部结构：4 个 Sub-Nodes 并行（Tech / App / Policy / Capital）
# 汇总后输出：技术趋势 / 应用趋势 / 政策趋势 / 资本趋势
# ─────────────────────────────────────────────────────────────────────────────

import logging
import asyncio
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# 各维度的 System Prompt
DIM_SYSTEM_PROMPTS = {
    "tech": """\
你是一名 AI 技术趋势分析师。你的任务是识别今日 AI 领域的技术动态。

请从文章中识别：
1. 技术突破：大模型发布、新算法、新架构、新硬件
2. 路线竞争：OpenAI vs Google vs 开源社区 vs 大厂的技术路线动态
3. 技术风险：某技术路线被证伪或遇到瓶颈

重要：你的输出必须是一个合法的 JSON 对象，不要包含任何 Markdown 代码块标记。
格式如下：
{
  "dimension": "技术趋势",
  "summary": "该维度今日趋势总结（150字以内）",
  "signals": ["具体信号1", "具体信号2", "具体信号3"],
  "confidence": "high|medium|low"
}
""",
    "app": """\
你是一名 AI 应用落地分析师。你的任务是识别今日 AI 领域的商业应用动态。

请从文章中识别：
1. 商业落地：哪些产品/服务开始实际应用并产生效果
2. 用户增长：爆款应用的传播路径和增长数据
3. 商业模式：盈利模式的创新或验证

只关注有实际应用案例的内容，不关注纯概念描述。

重要：你的输出必须是一个合法的 JSON 对象，不要包含任何 Markdown 代码块标记。
格式如下：
{
  "dimension": "应用趋势",
  "summary": "该维度今日趋势总结（150字以内）",
  "signals": ["具体信号1", "具体信号2", "具体信号3"],
  "confidence": "high|medium|low"
}
""",
    "policy": """\
你是一名 AI 政策与监管分析师。你的任务是识别今日全球 AI 领域的政策动态。

请从文章中识别：
1. 监管动态：各国/地区的 AI 监管政策、禁令、审查措施
2. 政策利好：政府支持 AI 发展的政策、资金支持
3. 标准制定：行业标准、安全规范、伦理准则的新进展

只关注有具体政策内容的信息，不关注泛泛的"政策支持"描述。

重要：你的输出必须是一个合法的 JSON 对象，不要包含任何 Markdown 代码块标记。
格式如下：
{
  "dimension": "政策趋势",
  "summary": "该维度今日趋势总结（150字以内）",
  "signals": ["具体信号1", "具体信号2", "具体信号3"],
  "confidence": "high|medium|low"
}
""",
    "capital": """\
你是一名 AI 资本市场分析师。你的任务是识别今日 AI 领域的资本动态。

请从文章中识别：
1. 融资并购：重大投融资事件（需有具体金额）
2. 资本流向：资金从哪些领域撤出/进入
3. 估值变化：独角兽估值调整、IPO 动态

只关注有具体金额或明确资金流向的信息。

重要：你的输出必须是一个合法的 JSON 对象，不要包含任何 Markdown 代码块标记。
格式如下：
{
  "dimension": "资本趋势",
  "summary": "该维度今日趋势总结（150字以内）",
  "signals": ["具体信号1", "具体信号2", "具体信号3"],
  "confidence": "high|medium|low"
}
""",
}


# 各维度的关键词（用于筛选相关文章）
DIM_KEYWORDS = {
    "tech": [
        "模型", "算法", "训练", "参数", "架构", "GPT", "LLM",
        "benchmark", "论文", "开源", "训练", "推理", "GPU",
        "AGI", "多模态", "MoE", "DeepSeek", "Claude", "Gemini",
    ],
    "app": [
        "产品", "发布", "用户", "落地", "应用", "APP", "上线",
        "商业化", "收入", "付费", "订阅", "DAU", "MAU", "增长",
    ],
    "policy": [
        "监管", "政策", "法规", "政府", "禁止", "审查", "合规",
        "安全", "标准", "欧盟", "美国", "中国", "OpenAI", "调查",
    ],
    "capital": [
        "融资", "投资", "并购", "收购", "估值", "IPO", "上市",
        "资金", "亿美元", "亿元", "独角兽", "上市", "股票", "基金",
    ],
}

DIM_LABELS = {
    "tech": "技术趋势",
    "app": "应用趋势",
    "policy": "政策趋势",
    "capital": "资本趋势",
}


@dataclass
class DailyReportContext:
    """由 Orchestrator 构建的统一上下文"""
    date: str
    articles_count: int
    articles: list[dict]
    sources: list[str]
    language: str = "mixed"


class TrendAgent:
    """
    趋势洞察 Agent

    内部结构：4 个 Sub-Nodes 并行执行
      TechTrendNode   → 技术突破与路线竞争
      AppTrendNode    → 商业落地与应用扩散
      PolicyNode      → 监管动态与政策利好
      CapitalNode     → 融资并购与资本流向

    汇总：提取跨维度高置信度信号
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def analyze(self, context: DailyReportContext) -> dict:
        """
        执行趋势洞察分析

        Args:
            context: Orchestrator 构建的统一上下文

        Returns:
            {
                "date": str,
                "tech_trend": {...},
                "app_trend": {...},
                "policy_trend": {...},
                "capital_trend": {...},
                "cross_dimension_signals": [...]
            }
        """
        logger.info(
            f"[TrendAgent] 开始分析，共 {context.articles_count} 篇文章，"
            f"4 个维度并行"
        )

        # ── 并行执行 4 个 Sub-Nodes ────────────────────────────────────
        tasks = [
            self._analyze_dimension(context, dim_key)
            for dim_key in ("tech", "app", "policy", "capital")
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        dimensions = {}
        for dim_key, result in zip(
            ("tech_trend", "app_trend", "policy_trend", "capital_trend"),
            results,
        ):
            if isinstance(result, Exception):
                logger.warning(f"[TrendAgent] {dim_key} 执行失败: {result}")
                dimensions[dim_key] = {
                    "dimension": DIM_LABELS.get(dim_key.replace("_trend", ""), dim_key),
                    "summary": "该维度分析失败",
                    "signals": [],
                    "confidence": "low",
                    "error": str(result),
                }
            else:
                dimensions[dim_key] = result

        # ── 汇总：提取跨维度高置信度信号 ────────────────────────────────
        cross_signals = self._extract_cross_signals(dimensions)

        result = {
            "date": context.date,
            "tech_trend": dimensions.get("tech_trend", {}),
            "app_trend": dimensions.get("app_trend", {}),
            "policy_trend": dimensions.get("policy_trend", {}),
            "capital_trend": dimensions.get("capital_trend", {}),
            "cross_dimension_signals": cross_signals,
        }

        logger.info(f"[TrendAgent] 分析完成，4 个维度均已输出")
        return result

    async def _analyze_dimension(
        self,
        context: DailyReportContext,
        dim_key: str,
    ) -> dict:
        """分析单个维度（单个 Sub-Node）"""
        dim_name = DIM_LABELS.get(dim_key, dim_key)
        system_prompt = DIM_SYSTEM_PROMPTS.get(dim_key, "")
        keywords = DIM_KEYWORDS.get(dim_key, [])

        # ── 为每个维度筛选相关文章（减少 token 消耗）───────────────────
        relevant = self._filter_by_keywords(context.articles, keywords)
        # 无匹配则用前20篇
        if not relevant:
            relevant = context.articles[:20]

        logger.debug(
            f"[TrendAgent][{dim_name}] 筛选出 {len(relevant)} 篇相关文章"
        )

        articles_text = self._build_articles_text(relevant)
        user_prompt = f"""## 今日文章（共 {len(relevant)} 篇，{dim_name}维度）

{articles_text}

## 输出要求
按【{dim_name}】维度分析以上文章，输出 JSON：
"""

        raw_response = await self.llm.ainvoke(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        parsed = self.llm._extract_json(raw_response)
        if not parsed:
            logger.warning(
                f"[TrendAgent][{dim_name}] LLM 返回格式异常: {raw_response[:200]}"
            )
            return {
                "dimension": dim_name,
                "summary": "该维度今日无显著趋势",
                "signals": [],
                "confidence": "low",
            }

        # 确保 dimension 字段存在
        if "dimension" not in parsed:
            parsed["dimension"] = dim_name

        return parsed

    def _filter_by_keywords(
        self,
        articles: list[dict],
        keywords: list[str],
    ) -> list[dict]:
        """根据关键词筛选相关文章"""
        if not keywords:
            return articles[:20]

        matched = []
        for a in articles:
            text = (
                (a.get("title") or "") + " " + (a.get("summary") or "")
            ).lower()
            if any(kw.lower() in text for kw in keywords):
                matched.append(a)
        return matched

    def _build_articles_text(self, articles: list[dict]) -> str:
        """将文章列表格式化为 LLM 输入文本"""
        lines = []
        for i, a in enumerate(articles[:25], 1):
            title = a.get("title", "无标题")
            summary = (a.get("summary") or "无摘要")[:300]
            source = a.get("source", "未知来源")
            lines.append(
                f"[{i}] 来源：{source}\n"
                f"    标题：{title}\n"
                f"    摘要：{summary}"
            )
        return "\n\n".join(lines)

    def _extract_cross_signals(self, dimensions: dict) -> list[str]:
        """
        提取跨维度高置信度信号

        策略：置信度为 high 的信号，优先收录
        """
        cross_signals = []
        dim_label_map = {
            "tech_trend": "技术",
            "app_trend": "应用",
            "policy_trend": "政策",
            "capital_trend": "资本",
        }

        for dim_key, signals in dimensions.items():
            if not isinstance(signals, dict):
                continue
            if signals.get("confidence") == "high":
                for sig in signals.get("signals", []):
                    label = dim_label_map.get(dim_key, dim_key)
                    cross_signals.append(f"【{label}】{sig}")

        return cross_signals[:5]
