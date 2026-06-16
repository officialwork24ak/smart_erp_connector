"""
NLQ Orchestrator
Uses the db_chat 3-step pipeline: view selection → SQL gen → validate → execute → explain.

Entry point: process_query(query, user_id, conv_id)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.config import cfg
from src.utils.logger import logger
from src.ai.db_chat_pipeline import run_pipeline, load_snapshot, PipelineResult
from src.ai.memory import (
    create_conversation, get_conversation, add_turn,
)


# ─── Response Types ───────────────────────────────────────────────────────────

@dataclass
class NLQResponse:
    query: str
    sql: Optional[str]
    records: List[Dict[str, Any]]
    record_count: int
    intent: Optional[Dict[str, Any]]
    chart_type: str
    period: str
    period_label: str
    description: str
    summary: Optional[str]
    insights: List[Dict[str, Any]]
    conv_id: Optional[str]
    duration_ms: int
    corrected: bool
    from_template: bool
    warnings: List[str]
    faq_template_id: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _infer_chart_type(records: List[Dict[str, Any]]) -> str:
    if not records:
        return "none"
    if len(records) == 1:
        return "kpi"
    cols = list(records[0].keys())
    date_hints = ("date", "month", "day", "period")
    has_date = any(any(h in c.lower() for h in date_hints) for c in cols)
    if has_date and len(records) > 1:
        return "line"
    if len(cols) == 2 or len(cols) <= 4:
        return "bar"
    return "table"


def _pipeline_to_intent(result: PipelineResult) -> Dict[str, Any]:
    return {
        "intent": "query",
        "period": "auto",
        "metric": "",
        "dimension": "",
        "tables": result.selected_views,
        "chart_type": _infer_chart_type(result.records),
        "top_n": None,
        "filters": {},
        "compare_with": None,
        "confidence": 1.0,
        "raw": result.view_selection_reason,
        "pipeline": "db_chat",
    }


def _summary_to_insights(summary: str) -> List[Dict[str, Any]]:
    # The summary is already rendered as the main answer bubble. Do NOT echo it
    # again as an "Analysis" insight under the table — that produced a duplicate
    # block (the same paragraph shown twice). Return no extra insight.
    return []


# ─── Main Orchestrator ────────────────────────────────────────────────────────

async def process_query(
    query: str,
    user_id: str = "anonymous",
    conv_id: Optional[str] = None,
    top_n_override: Optional[int] = None,
    provider: str = "openai",
    force_dynamic: bool = False,
) -> NLQResponse:
    start = time.perf_counter()

    if conv_id:
        conv = get_conversation(conv_id)
        if conv is None:
            conv_id = None

    if not conv_id:
        conv = create_conversation(user_id, title=query[:60])
        conv_id = conv.id

    snap = await load_snapshot()
    result = await run_pipeline(
        question=query,
        provider=provider,
        snap=snap,
        top_n=top_n_override,
        force_dynamic=force_dynamic,
    )

    chart_type = _infer_chart_type(result.records)
    intent = _pipeline_to_intent(result)
    insights = _summary_to_insights(result.summary)

    add_turn(conv_id, "user", query)
    add_turn(
        conv_id,
        "assistant",
        result.summary or result.description,
        sql=result.sql,
        intent=intent,
        result_summary=f"{result.record_count} rows returned",
    )

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "NLQ query processed (db_chat pipeline)",
        duration_ms=duration_ms,
        records=result.record_count,
        views=result.selected_views,
        corrected=result.corrected,
    )

    return NLQResponse(
        query=query,
        sql=result.sql,
        records=result.records,
        record_count=result.record_count,
        intent=intent,
        chart_type=chart_type,
        period="auto",
        period_label="",
        description=result.description,
        summary=result.summary,
        insights=insights,
        conv_id=conv_id,
        duration_ms=duration_ms,
        corrected=result.corrected,
        from_template=result.from_template,
        warnings=result.warnings,
        faq_template_id=result.faq_template_id,
    )
