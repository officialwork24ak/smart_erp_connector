"""
AI Routes
POST /ai/query             — NLQ: natural language → data + insights
POST /ai/explain-sql       — Explain a SQL query in plain English
GET  /ai/conversations     — List user's conversations
GET  /ai/conversations/{id} — Get a conversation's turns
DELETE /ai/conversations/{id}
POST /ai/insights          — Generate insights for provided data
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.ai.nlq import process_query
from src.ai.test_faq_loader import list_verified_top_queries, loader_status
from src.ai.memory import (
    list_conversations, get_conversation,
    delete_conversation,
)
from src.ai.insights import generate_insights
from src.middleware.auth import get_current_user, get_optional_user, require_permission
from src.auth.jwt import TokenPayload
from src.utils.logger import logger

router = APIRouter(prefix="/ai", tags=["ai"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class NLQRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    conversation_id: Optional[str] = None
    top_n: Optional[int] = Field(default=None, ge=1, le=200)
    provider: str = Field(default="openai", pattern="^(claude|openai)$")
    force_dynamic: bool = Field(
        default=False,
        description="Skip verified FAQ templates; use AI view selection + SQL generation only.",
    )


class ExplainSQLRequest(BaseModel):
    sql: str = Field(min_length=10)


class InsightRequest(BaseModel):
    query: str
    records: List[Dict[str, Any]]
    intent_type: str = "aggregate"
    period_label: str = "this period"
    value_column: str = "Revenue"
    label_column: Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/verified-suggestions", dependencies=[Depends(require_permission("query:*"))])
async def nlq_verified_suggestions(
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Top N natural-language prompts that map to the same verified FAQ SQL builders
    used in `test/nlq_faq_sql.py` + `test/nlq_faq_kpi.py`.
    """
    capped = max(1, min(limit, 80))
    qs = list_verified_top_queries(limit=capped)
    return {
        "success": True,
        "queries": qs,
        "count": len(qs),
        "source": "nlq_faq_kpi.FREQUENT_AI_QUERIES",
        "faq_loader": loader_status(),
    }


@router.post("/query", dependencies=[Depends(require_permission("query:*"))])
async def nlq_query(
    body: NLQRequest,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Full NLQ pipeline:
    natural language → intent → SQL → validate → execute → insights → response
    """
    try:
        result = await process_query(
            query=body.query,
            user_id=user.user_id,
            conv_id=body.conversation_id,
            top_n_override=body.top_n,
            provider=body.provider,
            force_dynamic=body.force_dynamic,
        )

        return {
            "success": True,
            "query": result.query,
            "sql": result.sql,
            "records": result.records,
            "record_count": result.record_count,
            "intent": result.intent,
            "chart_type": result.chart_type,
            "period": result.period,
            "period_label": result.period_label,
            "description": result.description,
            "summary": result.summary,
            "insights": result.insights,
            "conversation_id": result.conv_id,
            "duration_ms": result.duration_ms,
            "from_template": result.from_template,
            "corrected": result.corrected,
            "warnings": result.warnings,
            "faq_template_id": result.faq_template_id,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.error("NLQ query failed", error=str(exc), query=body.query[:100])
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.exception("NLQ query unexpected failure", query=body.query[:100])
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/explain-sql", dependencies=[Depends(require_permission("query:*"))])
async def explain_sql(body: ExplainSQLRequest) -> Dict[str, Any]:
    """Use AI to explain a SQL query in plain business English."""
    import anthropic
    from src.config import cfg

    if not cfg.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="AI service not configured")

    client = anthropic.AsyncAnthropic(api_key=cfg.ANTHROPIC_API_KEY)
    try:
        response = await client.messages.create(
            model=cfg.ANTHROPIC_MODEL,
            max_tokens=512,
            system="You are a business analyst. Explain what this SQL query does in 2-3 plain English sentences a non-technical user can understand. Mention the data being retrieved and any filters applied.",
            messages=[{"role": "user", "content": f"Explain this SQL:\n\n{body.sql}"}],
        )
        explanation = (response.content[0].text or "").strip() if response.content else ""
        return {"success": True, "explanation": explanation, "sql": body.sql}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/conversations")
async def get_conversations(
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    convs = list_conversations(user.user_id)
    return {
        "success": True,
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "turn_count": len(c.turns),
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            }
            for c in convs
        ],
    }


@router.get("/conversations/{conv_id}")
async def get_conversation_detail(
    conv_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id and user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "success": True,
        "conversation": {
            "id": conv.id,
            "title": conv.title,
            "turns": [
                {
                    "role": t.role,
                    "content": t.content,
                    "sql": t.sql,
                    "intent": t.intent,
                    "result_summary": t.result_summary,
                    "ts": t.ts,
                }
                for t in conv.turns
            ],
        },
    }


@router.delete("/conversations/{conv_id}")
async def remove_conversation(
    conv_id: str,
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    conv = get_conversation(conv_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    delete_conversation(conv_id)
    return {"success": True, "message": "Conversation deleted"}


@router.get("/page-insights", dependencies=[Depends(require_permission("query:*"))])
async def page_insights(
    period: str = "mtd",
) -> Dict[str, Any]:
    """
    Auto-generate AI business insights from cached ERP analytics data.
    Reads only from in-memory/PG cache — never fires SQL queries directly.
    Falls back to an empty list if no data is cached yet.
    """
    from src.ai.auto_insights import generate_page_insights
    from fastapi import Query as Q
    try:
        return await generate_page_insights(period=period)
    except Exception as exc:
        logger.warning("Auto-insights generation failed", error=str(exc))
        return {
            "success": False,
            "period": period,
            "insights": [],
            "executive_summary": None,
            "data_available": False,
            "from_cache": True,
            "_error": str(exc),
        }


@router.post("/insights", dependencies=[Depends(require_permission("query:*"))])
async def get_insights(body: InsightRequest) -> Dict[str, Any]:
    """Generate insights from a provided records array."""
    try:
        result = await generate_insights(
            query=body.query,
            records=body.records,
            intent_type=body.intent_type,
            period_label=body.period_label,
            value_column=body.value_column,
            label_column=body.label_column,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
