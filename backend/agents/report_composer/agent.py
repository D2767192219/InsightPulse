# ─────────────────────────────────────────────────────────────────────────────
# agents/report_composer/agent.py
#
# Report Composer — 报告聚合
# 接收：HotTopics + DeepSummary + Trend 三路输出
# 输出：结构化日报 JSON + Markdown 全文
# ─────────────────────────────────────────────────────────────────────────────

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
你是一名高级情报报告撰写专家。你的任务是综合四路分析结果，生成专业日报。

四路输入：
1. HotTopics（热点榜单）：今日最热门的 AI 话题排名
2. DeepSummary（深度总结）：重要事件的 What/Why/Who/Impact 结构化摘要
3. Trend（趋势洞察）：技术/应用/政策/资本四个维度的趋势信号
4. OpportunityScanner（风险/机会）：潜在风险信号与投资/布局机会

日报结构要求：
一、Executive Summary：一句话概括今日最重要事件 + 情感定性 + 风险等级
二、今日热点 Top 5：最热门的 5 个话题（简要一句话）
三、重要事件深度总结：2-3 个最重要的事件（What/Why/Who/Impact）
四、趋势洞察：技术 / 应用 / 政策 / 资本 四个维度的核心信号
五、风险/机会提示：2-4 条（可选）
六、综合研判：明日值得关注的事件或走向

写作风格：
- 中文，专业简洁，有见地
- 核心判断要具体，禁止"建议持续关注"等废话
- 引用话题用「」，引用公司/人名用【】
- 禁止 Markdown 语法（## 标题、**加粗**、列表符号等）
- 日报面向 AI 从业者、投资人、行业研究员
- 300-500 字为宜
"""


class ReportComposer:
    """
    报告聚合 Agent

    接收 Orchestrator 聚合后的三路结果，
    生成最终日报（JSON + Markdown 双格式）。
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def compose(
        self,
        date: str,
        hot_topics: dict,
        deep_summaries: dict,
        trend_insights: dict,
        opportunity_signals: dict | None = None,
        fast_mode: bool = False,
    ) -> dict:
        """
        聚合三路输出，生成最终日报

        Args:
            date: 日报日期
            hot_topics: HotTopicsAgent 输出
            deep_summaries: DeepSummaryAgent 输出
            trend_insights: TrendAgent 输出

        Returns:
            {
                "report_id": str,
                "date": str,
                "generated_at": str,
                "executive_summary": {...},
                "hot_topics": [...],
                "deep_summaries": [...],
                "trend_insights": {...},
                "markdown_report": str,
            }
        """
        from datetime import datetime, timezone

        logger.info(f"[ReportComposer] 开始聚合日报，日期={date}")

        # ── 构建摘要上下文（控制 token 长度）───────────────────────────
        hot_topics_text = self._summarize_hot(hot_topics)
        deep_summaries_text = self._summarize_events(deep_summaries)
        trend_insights_text = self._summarize_trends(trend_insights)
        opportunity_text = self._summarize_opportunities(opportunity_signals or {})

        user_prompt = f"""## 数据输入

### 热点榜单（HotTopics）
{hot_topics_text}

### 重要事件（DeepSummary）
{deep_summaries_text}

### 趋势洞察（Trend）
{trend_insights_text}

### 风险/机会信号（OpportunityScanner）
{opportunity_text}

## 输出要求
综合以上三部分数据，生成两部分内容：

### Part 1：JSON 执行摘要
{{
  "headline": "一句话概括今日最重要事件",
  "key_count": 3,
  "overall_sentiment": "极度正面|偏正面|中性|偏负面|极度负面",
  "risk_level": "低|中|高"
}}

### Part 2：Markdown 日报全文（{"220-360字" if fast_mode else "300-500字"}）
按以下结构撰写：
一、Executive Summary（一句话 + 情感 + 风险）
二、今日热点 Top 5（每条一句话）
三、重要事件深度总结（2-3个，What/Why/Impact各一句话）
四、趋势洞察（四个维度各一句话核心信号）
五、风险/机会提示（如有，列 2-4 条）
六、综合研判（明日值得关注）

注意：Part 2 直接输出 Markdown 纯文本，不需要代码块包裹。
"""

        try:
            raw_response = await self.llm.ainvoke(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                json_mode=False,
            )
        except Exception as e:
            logger.error(f"[ReportComposer] LLM 调用失败: {e}")
            return {
                "report_id": f"report_{date}",
                "date": date,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "executive_summary": {
                    "headline": "日报生成失败",
                    "key_count": 0,
                    "overall_sentiment": "unknown",
                    "risk_level": "unknown",
                },
                "hot_topics": hot_topics.get("items", []),
                "deep_summaries": deep_summaries.get("events", []),
                "trend_insights": trend_insights,
                "markdown_report": f"# 日报生成失败\n\n错误：{e}",
                "error": str(e),
            }

        # ── 分离 JSON 执行摘要和 Markdown 正文 ────────────────────────
        exec_summary, markdown_body = self._parse_response(raw_response)

        result = {
            "report_id": f"report_{date}",
            "date": date,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "executive_summary": exec_summary,
            "hot_topics": hot_topics.get("items", [])[:5],
            "deep_summaries": deep_summaries.get("events", [])[:3],
            "trend_insights": trend_insights,
            "opportunity_signals": (opportunity_signals or {}),
            "markdown_report": markdown_body,
        }

        logger.info(f"[ReportComposer] 日报聚合完成")
        return result

    def _summarize_hot(self, hot_topics: dict) -> str:
        """提炼热点数据为摘要文本"""
        items = hot_topics.get("items", [])
        if not items:
            return "暂无热点数据"

        lines = []
        for i, item in enumerate(items[:5], 1):
            topic = item.get("topic", "")
            summary = item.get("summary", "")
            score = item.get("hot_score", "")
            lines.append(
                f"{i}. 【{topic}】{summary}（热度：{score}）"
            )
        return "\n".join(lines)

    def _summarize_events(self, deep_summaries: dict) -> str:
        """提炼事件数据为摘要文本"""
        events = deep_summaries.get("events", [])
        if not events:
            return "暂无事件数据"

        lines = []
        for i, evt in enumerate(events[:3], 1):
            topic = evt.get("topic", "")
            what = evt.get("what", "")
            who = evt.get("who", "")
            impact = evt.get("impact", "")
            lines.append(
                f"事件{i}：{topic}\n"
                f"  What：{what}\n"
                f"  Who：{who}\n"
                f"  Impact：{impact}"
            )
        return "\n\n".join(lines)

    def _summarize_trends(self, trend_insights: dict) -> str:
        """提炼趋势数据为摘要文本"""
        lines = []
        for key, label in [
            ("tech_trend", "技术趋势"),
            ("app_trend", "应用趋势"),
            ("policy_trend", "政策趋势"),
            ("capital_trend", "资本趋势"),
        ]:
            dim = trend_insights.get(key, {})
            if dim:
                summary = dim.get("summary", "")
                signals = dim.get("signals", [])[:2]
                lines.append(
                    f"【{label}】{summary}\n"
                    f"  信号：{'；'.join(signals) if signals else '暂无'}"
                )
        return "\n\n".join(lines) if lines else "暂无趋势数据"

    def _summarize_opportunities(self, opportunity_signals: dict) -> str:
        """提炼风险/机会为摘要文本"""
        risks = opportunity_signals.get("risk_signals", []) if opportunity_signals else []
        opps = opportunity_signals.get("opportunity_signals", []) if opportunity_signals else []

        parts = []
        if risks:
            parts.append("【风险】")
            for r in risks[:3]:
                parts.append(
                    f"- {r.get('title','')}（urgency={r.get('urgency','')}, severity={r.get('severity','')}, ref={','.join(r.get('source_refs', [])[:2])}）"
                )
        if opps:
            parts.append("【机会】")
            for o in opps[:3]:
                parts.append(
                    f"- {o.get('title','')}（window={o.get('time_window','')}, confidence={o.get('confidence','')}, ref={','.join(o.get('source_refs', [])[:2])}）"
                )
        return "\n".join(parts) if parts else "暂无风险/机会信号"

    def _parse_response(self, raw_response: str) -> tuple[dict, str]:
        """
        解析 LLM 返回，提取：
        1. JSON 执行摘要
        2. Markdown 日报正文
        """
        import json
        import re

        exec_summary = {
            "headline": "暂无概述",
            "key_count": 0,
            "overall_sentiment": "unknown",
            "risk_level": "unknown",
        }
        markdown_body = raw_response.strip()

        # 尝试从 JSON 代码块中提取执行摘要
        json_patterns = [
            r"```json\s*(\{.*?\})\s*```",
            r"```\s*(\{.*?\})\s*```",
            r'(\{[\s\S]*?"headline"[\s\S]*?\})',
        ]

        for pattern in json_patterns:
            matches = re.findall(pattern, raw_response, re.DOTALL)
            for match in matches:
                try:
                    parsed = json.loads(match)
                    if "headline" in parsed or "key_count" in parsed:
                        exec_summary = parsed
                        # 从原文中移除 JSON 部分
                        markdown_body = raw_response.replace(match, "").strip()
                        # 清理残留的 markdown 代码块标记
                        markdown_body = re.sub(
                            r"```json\s*|```\s*", "", markdown_body
                        ).strip()
                        break
                except json.JSONDecodeError:
                    continue

        return exec_summary, markdown_body
