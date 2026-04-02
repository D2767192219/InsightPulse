# ─────────────────────────────────────────────────────────────────────────────
# agents/opportunity/agent.py
#
# OpportunityScanner Agent — 风险与机会识别（串行第四步）
# 输入：Agent1 热点、Agent2 事件、Agent3 趋势，以及信号上下文
# 输出：风险信号 + 机会信号（结构化）
# ─────────────────────────────────────────────────────────────────────────────

import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


RISK_SYSTEM_PROMPT = """\
你是一名 AI 行业风险分析师，任务是基于上游分析结果，输出结构化风险信号列表。

输入包含：
- 今日热点（hot_topics）
- 重要事件（events）
- 趋势研判（trend: PEST/SWOT/预测）
- 信号上下文（新兴主题簇/权威度等摘要）

请输出 JSON（无 Markdown 代码块）：
{
  "risk_signals": [
    {
      "signal_id": "risk_001",
      "title": "一句话风险描述（20字以内）",
      "description": "风险成因与影响（80字以内）",
      "urgency": 1-5,
      "severity": 1-5,
      "confidence": 0.0-1.0,
      "source_refs": ["ht_001", "evt_002", "policy_trend"],
      "category": "技术风险|监管风险|市场风险|竞争风险|资本风险",
      "monitor_indicators": ["需跟踪的指标1", "指标2"]
    }
  ]
}
"""

OPPORTUNITY_SYSTEM_PROMPT = """\
你是一名 AI 行业机会分析师，任务是基于上游分析结果，输出结构化机会信号列表。

输入包含：
- 今日热点（hot_topics）
- 重要事件（events）
- 趋势研判（trend: PEST/SWOT/预测）
- 信号上下文（新兴主题簇/权威度等摘要）

请输出 JSON（无 Markdown 代码块）：
{
  "opportunity_signals": [
    {
      "signal_id": "opp_001",
      "title": "一句话机会描述（20字以内）",
      "description": "机会成因与潜在收益（80字以内）",
      "time_window": "3-7天|1-4周|1-3月",
      "confidence": 0.0-1.0,
      "signal_strength": 0.0-1.0,
      "source_refs": ["ht_001", "evt_002", "tech_trend"],
      "category": "技术布局机会|投资机会|产品机会|人才机会",
      "beneficiaries": ["受益方1", "受益方2"],
      "key_indicators_to_watch": ["指标1", "指标2"],
      "associated_risks": ["伴随风险1", "伴随风险2"]
    }
  ]
}
"""


class SignalContext:
    date: str
    scored_articles: list[dict] = field(default_factory=list)
    top_articles: list[dict] = field(default_factory=list)
    top_events_articles: list[dict] = field(default_factory=list)
    signal_summary: dict = field(default_factory=dict)
    top_articles_by_source: dict = field(default_factory=dict)
    sentiment_summary: dict = field(default_factory=dict)
    clusters: list[dict] = field(default_factory=list)
    emerging_clusters: list[dict] = field(default_factory=list)


class OpportunityScannerAgent:
    """
    风险与机会识别 Agent（串行第四步）

    输入：hot_topics, deep_summaries, trend_insights, signal_ctx
    输出：risk_signals + opportunity_signals
    """

    def __init__(self, llm_client):
        self.llm = llm_client

    async def analyze(
        self,
        ht_result: dict,
        ds_result: dict,
        t_result: dict,
        signal_ctx: Optional[SignalContext] = None,
        fast_mode: bool = False,
    ) -> dict:
        logger.info("[OpportunityScanner] 开始分析")

        hot_text = self._summarize_hot(ht_result)
        events_text = self._summarize_events(ds_result)
        trend_text = self._summarize_trend(t_result)
        signal_text = self._summarize_signals(signal_ctx)

        common_context = f"""# 上下文
## 热点
{hot_text or '无'}

## 事件
{events_text or '无'}

## 趋势
{trend_text or '无'}

## 信号摘要
{signal_text or '无'}
"""
        if fast_mode:
            # 性能模式下缩减一次调用：仅输出核心风险/机会各最多 2 条
            compact_prompt = common_context + "\n请输出 risk_signals 与 opportunity_signals 各最多 2 条。"
            merged = await self._call_llm(
                RISK_SYSTEM_PROMPT + "\n并同时输出 opportunity_signals。",
                compact_prompt,
                key="risk_signals",
                allow_full_payload=True,
            )
            risk = merged.get("risk_signals", [])
            opp = merged.get("opportunity_signals", [])
        else:
            risk = await self._call_llm(RISK_SYSTEM_PROMPT, common_context, key="risk_signals")
            opp = await self._call_llm(OPPORTUNITY_SYSTEM_PROMPT, common_context, key="opportunity_signals")

        logger.info(
            "[OpportunityScanner] 完成，风险 %d 条，机会 %d 条",
            len(risk),
            len(opp),
        )

        return {
            "date": ht_result.get("date")
            or ds_result.get("date")
            or t_result.get("date"),
            "risk_signals": risk,
            "opportunity_signals": opp,
        }

    async def _call_llm(
        self,
        system_prompt: str,
        user_context: str,
        key: str,
        allow_full_payload: bool = False,
    ) -> list[dict] | dict:
        raw = await self.llm.ainvoke(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_context},
            ],
            json_mode=True,
        )
        parsed = self.llm._extract_json(raw)
        if allow_full_payload and isinstance(parsed, dict):
            return parsed
        if parsed and key in parsed:
            return parsed[key]
        logger.warning("[OpportunityScanner] LLM 返回缺少 %s，原始长度=%d", key, len(str(raw)))
        return {} if allow_full_payload else []

    def _summarize_hot(self, ht_result: dict) -> str:
        items = ht_result.get("hot_topics") or ht_result.get("items") or []
        lines = []
        for h in items[:5]:
            lines.append(
                f"{h.get('topic_id','')} | {h.get('topic_name',h.get('topic',''))} | score={h.get('composite_score', h.get('hot_score',''))}"
            )
        return "\n".join(lines)

    def _summarize_events(self, ds_result: dict) -> str:
        evts = ds_result.get("events", [])
        lines = []
        for e in evts[:5]:
            lines.append(
                f"{e.get('event_id','')} | {e.get('topic','')} | importance={e.get('importance_score','')} | impact={e.get('impact','')[:60]}"
            )
        return "\n".join(lines)

    def _summarize_trend(self, t_result: dict) -> str:
        parts = []
        for key in ("tech_trend", "app_trend", "policy_trend", "capital_trend"):
            tr = t_result.get(key) or {}
            if tr:
                parts.append(f"{tr.get('dimension', key)}: {tr.get('summary','')}")
        pred = t_result.get("trend_prediction")
        if pred:
            parts.append(f"Prediction: {pred}")
        return "\n".join(parts)

    def _summarize_signals(self, signal_ctx: Optional[SignalContext]) -> str:
        if not signal_ctx or not signal_ctx.signal_summary:
            return ""
        sm = signal_ctx.signal_summary
        emerging = signal_ctx.emerging_clusters or []
        return (
            f"articles={sm.get('total_articles',0)}, authority_mean={sm.get('authority_mean',0)}, "
            f"community_coverage={sm.get('community_coverage_pct',0)}, emerging_clusters={len(emerging)}"
        )
