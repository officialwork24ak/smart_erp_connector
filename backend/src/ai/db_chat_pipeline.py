"""
db_chat_pipeline — 3-step AI-to-SQL pipeline (ported from db-chat/db_chat.py)

  Step 1  AI picks 1-4 relevant views  (compact schema)
  Step 2  AI generates SQL              (focused schema for selected views only)
  Step 3  Column/table validator        (rejects hallucinated names, auto-retries)
  Step 4  Execute SQL on the database
  Step 5  AI explains results in plain English
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

from src.config import cfg
from src.utils.logger import logger
from src.utils.date_utils import today_ist

# ─── Paths ────────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_CACHE_FILE = _PROJECT_ROOT / "db-chat" / "schema_cache.json"

MAX_RESULT_ROWS = int(os.getenv("DB_CHAT_MAX_ROWS", "3000"))
# Only a small sample of rows is sent to the LLM for the plain-English explanation.
# Sending thousands of rows overflows the model context (157K > 128K tokens on
# huge results like Product Sell-Through). The display table is unaffected.
EXPLAIN_MAX_ROWS = int(os.getenv("DB_CHAT_EXPLAIN_MAX_ROWS", "40"))

_snap_cache: Optional[dict] = None


# ─── Result type ──────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    sql: Optional[str]
    records: list[dict[str, Any]]
    record_count: int
    summary: str
    description: str
    selected_views: list[str] = field(default_factory=list)
    view_selection_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    corrected: bool = False
    truncated: bool = False
    conversational: bool = False
    from_template: bool = False
    faq_template_id: Optional[str] = None


# ─── Schema loading ───────────────────────────────────────────────────────────

async def load_snapshot(force_refresh: bool = False) -> dict:
    """Return schema snapshot dict (from file or live DB)."""
    global _snap_cache
    if _snap_cache and not force_refresh and _snap_cache.get("objects"):
        return _snap_cache

    if _snap_cache and not _snap_cache.get("objects"):
        _snap_cache = None  # discard failed/empty cache

    if _SCHEMA_CACHE_FILE.exists() and not force_refresh:
        try:
            with open(_SCHEMA_CACHE_FILE, "r", encoding="utf-8") as f:
                _snap_cache = json.load(f)
            logger.info(
                "Schema loaded from cache",
                path=str(_SCHEMA_CACHE_FILE),
                snapshotted_at=_snap_cache.get("snapshotted_at"),
            )
            return _snap_cache
        except Exception as exc:
            logger.warning("Could not read schema cache — querying DB", error=str(exc))

    snap = await _build_live_snapshot()
    if not snap.get("objects"):
        raise RuntimeError(
            "Schema discovery returned 0 views/tables. "
            "Run: cd db-chat && python schema_cache.py"
        )
    _snap_cache = snap
    return _snap_cache


async def _build_live_snapshot() -> dict:
    # Must NOT use NOLOCK hints — they break INFORMATION_SCHEMA queries
    # (regex inserts WITH (NOLOCK) before table aliases).
    from src.db.mssql import execute_raw

    sql = """
        SELECT o.TABLE_SCHEMA + '.' + o.TABLE_NAME AS object_name,
               o.TABLE_TYPE, c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE
        FROM INFORMATION_SCHEMA.TABLES o
        JOIN INFORMATION_SCHEMA.COLUMNS c
          ON c.TABLE_SCHEMA = o.TABLE_SCHEMA AND c.TABLE_NAME = o.TABLE_NAME
        WHERE o.TABLE_TYPE IN ('BASE TABLE','VIEW')
          AND o.TABLE_SCHEMA NOT IN ('sys','INFORMATION_SCHEMA')
        ORDER BY o.TABLE_SCHEMA, o.TABLE_NAME, c.ORDINAL_POSITION
    """
    try:
        result = await execute_raw(sql)
        rows = result["records"]
        logger.info("Schema discovered from live DB", columns=len(rows))
    except Exception as exc:
        logger.warning("Schema discovery failed", error=str(exc))
        rows = []

    objects: dict = {}
    for r in rows:
        name = r["object_name"]
        if name not in objects:
            objects[name] = {
                "type": "VIEW" if r["TABLE_TYPE"] == "VIEW" else "TABLE",
                "columns": [],
            }
        objects[name]["columns"].append({
            "name": r["COLUMN_NAME"],
            "type": r["DATA_TYPE"],
            "nullable": r["IS_NULLABLE"] == "YES",
        })

    return {
        "db": cfg.mssql_database,
        "server": f"{cfg.mssql_server}:{cfg.mssql_port}",
        "snapshotted_at": datetime.now().isoformat(timespec="seconds"),
        "curated": {},
        "objects": objects,
    }


# ─── Schema rendering ─────────────────────────────────────────────────────────

def _col_names(cols: list) -> list[str]:
    result = []
    for c in cols:
        if isinstance(c, dict):
            result.append(c["name"])
        else:
            result.append(str(c).split(" ")[0])
    return result


def _col_detail(cols: list) -> list[str]:
    result = []
    for c in cols:
        if isinstance(c, dict):
            nullable = "?" if c.get("nullable") else ""
            result.append(f"{c['name']} ({c['type']}{nullable})")
        else:
            result.append(str(c))
    return result


def compact_schema_for_view_selection(snap: dict) -> str:
    lines = [
        f"DATABASE: {snap.get('db', cfg.mssql_database)}",
        f"TODAY: {today_ist().isoformat()}",
        "",
        "AVAILABLE VIEWS AND TABLES:",
        "(column names only — full details provided after you select views)",
        "",
    ]

    curated = snap.get("curated", {})
    if curated:
        lines.append("=== PREFERRED VIEWS (curated — use these when they fit) ===")
        for key, info in curated.items():
            view_name = info.get("name", "")
            alias = info.get("alias", key)
            lines.append(f"\n  {view_name}  [{alias}]")
            obj = snap.get("objects", {}).get(view_name)
            if obj:
                names = _col_names(obj["columns"])
                lines.append(f"  Columns: {', '.join(names)}")
            for k, v in info.items():
                if k.endswith("_column") or k in ("date_column", "amount_column"):
                    lines.append(f"  {k}: {v}")
        lines.append("\n=== ALL VIEWS AND TABLES ===")

    for obj_name in sorted(snap.get("objects", {})):
        obj = snap["objects"][obj_name]
        names = _col_names(obj["columns"])
        lines.append(f"\n[{obj.get('type', 'VIEW')}] {obj_name}")
        lines.append(f"  Columns: {', '.join(names)}")

    return "\n".join(lines)


def focused_schema_for_sql(snap: dict, selected_views: list[str]) -> str:
    lines = [
        f"DATABASE: {snap.get('db', cfg.mssql_database)}",
        f"TODAY: {today_ist().isoformat()}",
        "",
        "SCHEMA FOR SELECTED VIEWS ONLY:",
        "(Use ONLY these views and ONLY the columns listed below)",
        "",
    ]

    curated = snap.get("curated", {})
    curated_by_name = {info["name"]: info for info in curated.values() if "name" in info}
    objects = snap.get("objects", {})
    found_any = False

    for view_name in selected_views:
        obj = objects.get(view_name)
        if obj is None:
            for k in objects:
                if k.lower() == view_name.lower():
                    obj = objects[k]
                    view_name = k
                    break
        if obj is None:
            continue
        found_any = True

        lines.append(f"[{obj.get('type', 'VIEW')}] {view_name}")
        lines.append("  Columns:")
        for c in _col_detail(obj["columns"]):
            lines.append(f"    - {c}")

        c_info = curated_by_name.get(view_name)
        if c_info:
            lines.append("  Key mappings (use these column names):")
            for k, v in c_info.items():
                if k not in ("name", "alias", "key_columns", "sample_query", "note") and isinstance(v, str):
                    lines.append(f"    {k}: {v}")
            if "sample_query" in c_info:
                lines.append(f"  Sample query: {c_info['sample_query']}")
        lines.append("")

    if not found_any:
        for obj_name in sorted(objects):
            obj = objects[obj_name]
            lines.append(f"[{obj.get('type', 'VIEW')}] {obj_name}")
            for c in _col_detail(obj["columns"]):
                lines.append(f"  - {c}")
            lines.append("")

    return "\n".join(lines)


# ─── AI providers ─────────────────────────────────────────────────────────────

def _call_claude(messages: list[dict], system: str) -> str:
    import anthropic

    if not cfg.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set.")
    client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=cfg.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=system,
        messages=messages,
    )
    return response.content[0].text


def _openai_chat_kwargs(model: str, *, max_out: int = 2048) -> dict[str, Any]:
    """GPT-5 / o-series models use max_completion_tokens, not max_tokens."""
    m = model.lower()
    if m.startswith(("gpt-5", "o1", "o3", "gpt-4.1")):
        return {"max_completion_tokens": max_out}
    return {"max_tokens": max_out, "temperature": 0}


def _call_gpt(messages: list[dict], system: str) -> str:
    from openai import OpenAI

    if not cfg.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set.")
    client = OpenAI(api_key=cfg.OPENAI_API_KEY)
    full_messages = [{"role": "system", "content": system}] + messages
    response = client.chat.completions.create(
        model=cfg.OPENAI_MODEL,
        messages=full_messages,
        **_openai_chat_kwargs(cfg.OPENAI_MODEL),
    )
    return response.choices[0].message.content or ""


def call_ai(messages: list[dict], system: str, provider: str) -> str:
    if provider in ("gpt", "openai"):
        return _call_gpt(messages, system)
    return _call_claude(messages, system)


async def call_ai_async(messages: list[dict], system: str, provider: str) -> str:
    return await asyncio.to_thread(call_ai, messages, system, provider)


def _decode_json_string_literal(value: str) -> str:
    """Decode a JSON string body (handles \\n, \\\", etc.)."""
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return (
            value.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )


def _extract_json_string_field(raw: str, field: str) -> str:
    """Pull a string field from AI JSON even when the response is truncated."""
    closed = re.search(
        rf'"{field}"\s*:\s*"((?:\\.|[^"\\])*)"',
        raw,
        re.DOTALL | re.IGNORECASE,
    )
    if closed:
        return _decode_json_string_literal(closed.group(1))
    open_ = re.search(rf'"{field}"\s*:\s*"(.*)', raw, re.DOTALL | re.IGNORECASE)
    if not open_:
        return ""
    body = open_.group(1)
    for trailer in ('",\n  "explanation"', '",\n  "estimatedRows"', '",\n  "', '"\n}', '"}'):
        if trailer in body:
            body = body.split(trailer)[0]
    return _decode_json_string_literal(body.rstrip('"'))


def parse_json_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
    sql = _extract_json_string_field(text, "sql")
    explanation = _extract_json_string_field(text, "explanation")
    answer = _extract_json_string_field(text, "answer")
    if sql or explanation or answer:
        out: dict = {}
        if sql:
            out["sql"] = sql
        if explanation:
            out["explanation"] = explanation
        if answer:
            out["answer"] = answer
        return out
    return {"answer": text}


def normalize_provider(provider: str) -> str:
    return "gpt" if provider == "openai" else "claude"


# ─── Step 1 — View selection ──────────────────────────────────────────────────

VIEW_SELECTOR_SYSTEM = """
You are a database expert for a retail ERP on Microsoft SQL Server.
Your ONLY job is to choose which database views/tables are needed to answer a question.

Rules:
- Choose 1 to 4 views maximum. Fewer is better.
- Return ONLY exact view/table names from the list provided. Never invent names.
- For revenue / sales / branch / category / department / salesperson SALES performance → dbo.VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID (has SalesPersonName, BranchAlias, CategoryShortName, SalesNetAmount, SalesQuantity, CashmemoNo)
- For detailed per-item sales with product attributes → dbo.VW_MB_POWERBI_SLSXNS_REPORT
- For customer master data (name, address, DOB) → dbo.VwAICustomerDetails
- For stock / inventory levels → dbo.VwAIStockData or dbo.VW_MB_POWERBI_STOCK_REPORT
- For purchases / procurement → dbo.VW_MB_POWERBI_PURXNS_REPORT or dbo.VW_MB_POWERBI_PUR_REPORT
- For purchase returns → dbo.VW_MB_POWERBI_PRT_REPORT or PURXNS_REPORT
- For stock transfers out → dbo.VW_MB_POWERBI_STO_REPORT; transfers in → dbo.VW_MB_POWERBI_STI_REPORT
- For footfall / bill count → dbo.VW_MB_POWERBI_SLS_BILLCOUNT or COUNT(DISTINCT CashmemoNo) on SLS_DATA_WITHOUT_ITEMID
- For gross margin → dbo.VW_MB_POWERBI_SLSXNS_REPORT (NetSlsNetAmount vs NetSlsCostValue) or SLS_DATA (SalesNetAmount vs SalesCost)
- For product/item catalog → dbo.VW_MB_POWERBI_PRODUCT_MASTER or dbo.VwMstItems
- For salesperson dimension only (name lookup) → dbo.VwAISalesPerson
- NEVER use dbo.VwAISalesPerson for sales queries — use dbo.VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID which already has SalesPersonName
- NEVER use dbo.VW_MB_POWERBI_APP_REPORT or dbo.VW_MB_POWERBI_APR_REPORT — empty/sparse; use SLS_DATA_WITHOUT_ITEMID or SLSXNS_REPORT instead

Return ONLY a JSON object like:
{
  "views": ["dbo.ViewName1", "dbo.ViewName2"],
  "reason": "one sentence explaining why these views"
}
""".strip()


async def select_views(question: str, snap: dict, provider: str) -> tuple[list[str], str]:
    compact = compact_schema_for_view_selection(snap)
    user_msg = f"Question: {question}\n\nSchema:\n{compact}"

    raw = await call_ai_async(
        [{"role": "user", "content": user_msg}],
        VIEW_SELECTOR_SYSTEM,
        provider,
    )
    result = parse_json_response(raw)
    selected = result.get("views", [])
    reason = result.get("reason", "")

    objects = snap.get("objects", {})
    objects_lower = {k.lower(): k for k in objects}
    valid: list[str] = []
    for v in selected:
        if v in objects:
            valid.append(v)
        elif v.lower() in objects_lower:
            valid.append(objects_lower[v.lower()])

    if not valid:
        valid = _keyword_fallback(question, snap)

    return valid, reason


def _keyword_fallback(question: str, snap: dict) -> list[str]:
    q = question.lower()
    curated = snap.get("curated", {})
    objects = snap.get("objects", {})

    scores: list[tuple[float, str]] = []
    for key, info in curated.items():
        view_name = info.get("name", "")
        if view_name not in objects:
            continue
        alias = (info.get("alias", "") + " " + key).lower()
        score = sum(1 for word in q.split() if word in alias or word in view_name.lower())
        scores.append((score, view_name))

    scores.sort(reverse=True)
    top = [v for s, v in scores if s > 0][:2]

    primary = "dbo.VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID"
    if any(w in q for w in ("sales", "revenue", "branch", "category", "amount")):
        if primary not in top and primary in objects:
            top = [primary] + top[:1]

    return top or ([primary] if primary in objects else list(objects.keys())[:1])


# ─── Step 2 — SQL generation ──────────────────────────────────────────────────

SQL_GEN_SYSTEM = """
You are an expert T-SQL analyst for a retail ERP on Microsoft SQL Server (zRetailHQ0).
Generate T-SQL SELECT queries using ONLY the views and columns listed in the schema provided.

Rules:
1. ONLY use table/view names and column names from the provided schema. NEVER invent names.
2. Always add WITH (NOLOCK) after every table/view reference.
3. Do NOT add TOP N limits unless the user explicitly asks for "top N" or a ranking query. Return all matching rows.
4. NEVER write DROP, DELETE, UPDATE, INSERT, EXEC, or DDL. SELECT and WITH (CTEs) only.
5. Use square brackets around column names: [ColumnName].
6. For date filtering use CAST(@date AS DATE) comparisons.

DATE PATTERNS — use EXACTLY these:
  This month (MTD)  : [DateCol] >= DATEFROMPARTS(YEAR(GETDATE()),MONTH(GETDATE()),1)
                      AND [DateCol] < DATEADD(month,1,DATEFROMPARTS(YEAR(GETDATE()),MONTH(GETDATE()),1))
  Today             : CAST([DateCol] AS DATE) = CAST(GETDATE() AS DATE)
  This quarter (QTD): [DateCol] >= DATEFROMPARTS(YEAR(GETDATE()),((MONTH(GETDATE())-1)/3)*3+1,1)
                      AND [DateCol] <= CAST(GETDATE() AS DATE)
  Financial YTD     : [DateCol] >= CASE WHEN MONTH(GETDATE())>=4
                                        THEN DATEFROMPARTS(YEAR(GETDATE()),4,1)
                                        ELSE DATEFROMPARTS(YEAR(GETDATE())-1,4,1) END
                      AND [DateCol] <= CAST(GETDATE() AS DATE)
  Last month        : [DateCol] >= DATEFROMPARTS(YEAR(DATEADD(month,-1,GETDATE())),MONTH(DATEADD(month,-1,GETDATE())),1)
                      AND [DateCol] < DATEFROMPARTS(YEAR(GETDATE()),MONTH(GETDATE()),1)
  Last N days       : [DateCol] >= CAST(DATEADD(day,-N,GETDATE()) AS DATE)
  NOTE: "YTD" always means Indian Financial Year (Apr 1 start), NOT Jan 1.

PERIOD / SIDE-BY-SIDE COMPARISONS (this month vs last month, today vs same day last week, vs last year, etc.):
- Return ONE result set only. Never use semicolons or multiple batches.
- CRITICAL: the result MUST make every period distinguishable. The reader has to tell the periods apart.
- WHEN COMPARING ACROSS A DIMENSION (by branch / category / department / supplier / salesperson, or any
  per-row breakdown): use CONDITIONAL AGGREGATION so each period is its OWN COLUMN and there is exactly
  ONE row per dimension value. This is the PREFERRED pattern. Example — today vs same day last week, by branch:
    SELECT [BranchAlias],
           SUM(CASE WHEN CAST([CashmemoDt] AS DATE) = CAST(GETDATE() AS DATE)
                    THEN [SalesNetAmount] ELSE 0 END) AS TodaySales,
           SUM(CASE WHEN CAST([CashmemoDt] AS DATE) = CAST(DATEADD(day,-7,GETDATE()) AS DATE)
                    THEN [SalesNetAmount] ELSE 0 END) AS SameDayLastWeekSales
    FROM [dbo].[VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID] WITH (NOLOCK)
    WHERE CAST([CashmemoDt] AS DATE) IN (CAST(GETDATE() AS DATE), CAST(DATEADD(day,-7,GETDATE()) AS DATE))
    GROUP BY [BranchAlias]
    ORDER BY TodaySales DESC
  Add a GrowthPct column = (current - prior) * 100.0 / NULLIF(prior, 0) when the user mentions growth/change.
- WHEN COMPARING TOTALS ONLY (no dimension breakdown): use UNION ALL, but EVERY SELECT MUST begin with a
  literal PeriodLabel column AND the value column MUST use the SAME alias in every branch of the UNION:
    SELECT N'Today' AS PeriodLabel, SUM([SalesNetAmount]) AS Sales FROM ... WHERE <today>
    UNION ALL
    SELECT N'Same Day Last Week' AS PeriodLabel, SUM([SalesNetAmount]) AS Sales FROM ... WHERE <same day last week>
- NEVER UNION ALL two periods without a PeriodLabel column, and NEVER give the value columns different
  aliases across a UNION — SQL keeps only the first SELECT's names, so the periods become indistinguishable.
- Use SalesNetAmount + CashmemoDt on SLS_DATA_WITHOUT_ITEMID for revenue comparisons.

SAFETY / PERFORMANCE:
- NEVER use dbo.VW_MB_POWERBI_APP_REPORT or dbo.VW_MB_POWERBI_APR_REPORT.
- For "zero sales" / full catalog anti-joins, always use TOP 100 (or TOP 50) on the outer query.
- INVENTORY / STOCK queries (stock on hand, low stock, out-of-stock, dead / slow-moving
  stock, inventory aging) read very large stock views — NEVER return every row unfiltered.
  ALWAYS bound them: add TOP 100, ORDER BY the stock-quantity column from the schema, and
  apply a sensible filter — e.g. low stock = quantity between 1 and a small threshold (say <= 10),
  out of stock = quantity <= 0. When the user asks "by branch" or "by category", AGGREGATE
  (SUM(...) GROUP BY branch/category) instead of listing every SKU. Keep stock queries lean so
  they return in a few seconds, not by scanning the whole view.
- Footfall = COUNT(DISTINCT [CashmemoNo]) unless a dedicated bill-count view is in schema.
- Bills / invoices: always COUNT(DISTINCT [CashmemoNo]) — line-level rows repeat the same bill.
- Average order value / basket / ATV: SUM([SalesNetAmount]) / NULLIF(COUNT(DISTINCT [CashmemoNo]), 0), not AVG(line amount).

Return ONLY a JSON object:
{
  "sql": "<valid T-SQL SELECT statement>",
  "explanation": "<one sentence describing what the query does>"
}

If no SQL is needed (e.g. the question is conversational), set sql to null and add an "answer" field.

Keep SQL compact (under ~60 lines). Prefer simple GROUP BY over large festival/date CTE tables unless the schema provides a calendar table.
""".strip()


async def generate_sql(
    question: str,
    focused_schema: str,
    provider: str,
    prior_error: Optional[str] = None,
    top_n: Optional[int] = None,
) -> tuple[str, str, str]:
    content = f"Question: {question}\n\nSchema to use:\n{focused_schema}"
    if top_n:
        content += f"\n\nUse TOP {top_n} when ranking or limiting rows."
    if prior_error:
        content += (
            f"\n\nPREVIOUS ATTEMPT FAILED with this error/problem:\n{prior_error}\n\n"
            "Please fix and regenerate."
        )

    raw = await call_ai_async(
        [{"role": "user", "content": content}],
        SQL_GEN_SYSTEM,
        provider,
    )
    result = parse_json_response(raw)

    sql = result.get("sql") or ""
    explanation = result.get("explanation", "")
    answer = result.get("answer", "")

    if not sql or str(sql).lower() in ("null", "none"):
        return "", answer or explanation, answer or explanation

    return sql.strip(), explanation, ""


# ─── Step 3 — SQL validation ──────────────────────────────────────────────────

def _sql_aliases(sql: str) -> set[str]:
    """Collect column aliases so we don't flag them as unknown columns."""
    aliases: set[str] = set()
    for m in re.finditer(r"\bAS\s+\[?(\w+)\]?", sql, re.IGNORECASE):
        aliases.add(m.group(1).lower())
    return aliases


def _sql_table_tokens(sql: str) -> set[str]:
    """Bracketed names used as tables/views in FROM/JOIN (not columns)."""
    tokens: set[str] = set()
    for m in re.finditer(
        r"(?:FROM|JOIN)\s+(?:\[?\w+\]?\.)?\[?(\w+)\]?",
        sql,
        re.IGNORECASE,
    ):
        tokens.add(m.group(1).lower())
    return tokens


def _sql_cte_names(sql: str) -> set[str]:
    """Names defined in WITH … AS (…) so they are not validated as dbo views."""
    names: set[str] = set()
    for m in re.finditer(r"\bWITH\s+(\w+)\s+AS\s*\(", sql, re.IGNORECASE):
        names.add(m.group(1).lower())
    for m in re.finditer(r",\s*(\w+)\s+AS\s*\(", sql, re.IGNORECASE):
        names.add(m.group(1).lower())
    return names


def validate_sql(sql: str, snap: dict, selected_views: list[str]) -> list[str]:
    problems: list[str] = []
    sql_upper = sql.upper()
    for dead in ("VW_MB_POWERBI_APP_REPORT", "VW_MB_POWERBI_APR_REPORT"):
        if dead in sql_upper:
            problems.append(
                f"{dead} is sparse/empty in this database — use "
                "VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID or VW_MB_POWERBI_SLSXNS_REPORT instead."
            )
    objects = snap.get("objects", {})
    objects_lower = {k.lower(): k for k in objects}
    aliases = _sql_aliases(sql)
    table_tokens = _sql_table_tokens(sql)
    cte_names = _sql_cte_names(sql)

    table_pattern = re.compile(
        r"(?:FROM|JOIN)\s+(\[?\w+\]?\.\[?\w+\]?|\[?\w+\]?)",
        re.IGNORECASE,
    )
    for m in table_pattern.finditer(sql):
        raw = m.group(1).replace("[", "").replace("]", "")
        if raw.upper() in ("WITH", "NOLOCK", "SELECT", "WHERE", "AND", "OR", "ON"):
            continue
        if raw in objects or raw.lower() in objects_lower:
            continue
        if f"dbo.{raw}" in objects or f"dbo.{raw}".lower() in objects_lower:
            continue
        if raw.lower() in cte_names:
            continue
        problems.append(f"Unknown table/view '{raw}' — not found in schema.")

    all_cols: set[str] = set()
    for obj in objects.values():
        for c in _col_names(obj["columns"]):
            all_cols.add(c.lower())

    col_pattern = re.compile(r"\[(\w+)\]")
    for m in col_pattern.finditer(sql):
        col = m.group(1)
        # Skip schema/table qualifiers in dotted names like [dbo].[View] or [schema].[table] —
        # these are NOT columns. A bracketed token immediately followed by '.' is a qualifier.
        if col.lower() in ("dbo", "sys", "information_schema"):
            continue
        if sql[m.end():m.end() + 1] == ".":
            continue
        if col.isdigit() or col.lower() in aliases:
            continue
        if col.lower() in table_tokens:
            continue
        if col.lower() not in all_cols:
            problems.append(
                f"Unknown column '[{col}]' — not found in any view in the schema."
            )

    return problems


# ─── Step 5 — Explain results ─────────────────────────────────────────────────

EXPLAIN_SYSTEM = """
You are a helpful retail business analyst. You have run a SQL query against an ERP database
and received results. Explain what the data means in clear, plain English.

Rules:
- Be specific: include actual numbers, names, and values from the data.
- Currency values in the Results are ALREADY formatted as "₹X.XX L" (Lakhs).
  Quote them EXACTLY as shown — do NOT recompute, convert, change the scale, or use crore.
  Non-currency numbers (counts, quantities, percentages) are raw — report them as-is.
- "YTD" means Indian financial year (1 April → today), not calendar Jan–Dec.
- If the result is empty (0 rows), explain what that means in context.
- Structure the answer for a busy executive, using line breaks between parts:\n  (1) a one-line headline with the single most important figure or finding;\n  (2) one or two short supporting sentences with the key numbers;\n  (3) optionally, one short insight or recommendation.\n  Keep it crisp — under ~6 sentences total. Use plain, professional business English.
- Do NOT repeat the SQL query.

Return ONLY a JSON object:
{
  "answer": "<plain English explanation of the results>"
}
""".strip()


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fmt_inr_narrative(amount: float) -> str:
    """Format raw rupees for AI/user-facing summaries."""
    # Express in Lakhs (₹X.XX L) to match the Analytics dashboard cards exactly,
    # so a side-by-side of dashboard vs AI shows identical units (no crore/L mismatch).
    a = abs(amount)
    sign = "−" if amount < 0 else ""
    if a >= 100_000:
        return f"{sign}₹{a / 100_000:,.2f} L"
    return f"{sign}₹{a:,.0f}"


def _norm_period_label(label: str) -> str:
    return re.sub(r"[_\s]+", " ", str(label or "").lower()).strip()


def _is_current_period_label(label: str) -> bool:
    l = _norm_period_label(label)
    return (
        l in ("this month", "thismonth", "mtd", "current")
        or l.startswith("this ")
        or "current ytd" in l
        or "current qtd" in l
        or "current mtd" in l
    )


def _is_prior_period_label(label: str) -> bool:
    l = _norm_period_label(label)
    if _is_current_period_label(label):
        return False
    return (
        l in ("last month", "lastmonth", "prior", "previous")
        or l.startswith("last ")
        or "last year" in l
        or l.endswith(" ly")
        or l == "ly"
        or "lastyear" in l.replace(" ", "")
    )


def _comparison_kind(labels: list[str], question: str = "") -> str:
    """month | ytd | period — drives narration wording."""
    joined = " ".join(_norm_period_label(l) for l in labels)
    q = question.lower()
    month_hint = any(
        x in joined or x in q
        for x in ("this month", "thismonth", "last month", "lastmonth", "previous month", "prior month")
    )
    ytd_hint = any(
        x in joined or x in q
        for x in ("ytd", "financial year", "fiscal year", "last year", "lastyear")
    )
    if month_hint and not ytd_hint:
        return "month"
    if ytd_hint:
        return "ytd"
    return "period"


def _try_period_comparison_summary(
    records: list[dict], question: str = ""
) -> Optional[str]:
    """
    Deterministic summary for 2-row current-vs-prior period tables
    (e.g. month-over-month or YTD vs LY) — avoids LLM crore/lakh mistakes.
    """
    if len(records) != 2:
        return None
    keys = list(records[0].keys())
    if len(keys) < 2:
        return None
    label_col = next(
        (k for k in keys if any(h in k.lower() for h in ("period", "label", "metric", "name"))),
        keys[0],
    )
    val_col = next(
        (k for k in keys if k != label_col and _to_float(records[0].get(k)) is not None),
        None,
    )
    if not val_col:
        return None

    def _row_val(row: dict) -> tuple[str, float]:
        label = str(row.get(label_col) or "")
        val = _to_float(row.get(val_col))
        return label, val if val is not None else 0.0

    rows = [_row_val(r) for r in records]
    cur = next((r for r in rows if _is_current_period_label(r[0])), None)
    prior = next((r for r in rows if _is_prior_period_label(r[0])), None)
    if cur is None:
        cur = next((r for r in rows if "current" in _norm_period_label(r[0])), rows[0])
    if prior is None:
        prior = next(
            (r for r in rows if r[0] != cur[0]),
            rows[1] if rows[1][0] != cur[0] else rows[0],
        )
    if prior[0] == cur[0]:
        return None

    kind = _comparison_kind([cur[0], prior[0]], question)
    cur_amt, prior_amt = cur[1], prior[1]
    delta = cur_amt - prior_amt
    growth = (delta / prior_amt * 100) if prior_amt else None
    growth_txt = f"{growth:+.1f}%" if growth is not None else "N/A"
    direction = "ahead of" if delta > 0 else "behind" if delta < 0 else "even with"

    if kind == "month":
        ref = "last month"
        footnote = (
            "This month is MTD (calendar month start through today); "
            "last month is the full prior calendar month. "
            "Revenue uses SUM(SalesNetAmount) on CashmemoDt, matching the Analytics dashboard."
        )
    elif kind == "ytd":
        ref = "last year (same FY day-range)"
        footnote = (
            "Figures use Indian FY YTD (1 April through today), "
            "compared to the same calendar day-range last financial year — matching the Analytics dashboard."
        )
    else:
        ref = prior[0]
        footnote = (
            f"Compared {_norm_period_label(cur[0])} vs {_norm_period_label(prior[0])} "
            "using SalesNetAmount on CashmemoDt."
        )

    return (
        f"{cur[0]} sales are {_fmt_inr_narrative(cur_amt)} "
        f"({_fmt_inr_narrative(prior_amt)} for {prior[0]}). "
        f"That is {_fmt_inr_narrative(delta)} {direction} {ref} "
        f"({growth_txt} change). "
        f"{footnote}"
    )


_CURRENCY_INCLUDE = ("sales", "revenue", "amount", "value", "ats", "mrp",
                     "profit", "cost", "ticket", "basket", "forecast", "discount", "networth")
_CURRENCY_EXCLUDE = ("pct", "percent", "qty", "quantity", "count", "rate", "ratio",
                     "days", "month", "year", "growth", "score", "rank", "id")


def _is_currency_key(key: str) -> bool:
    k = key.lower()
    if any(x in k for x in _CURRENCY_EXCLUDE):
        return False
    return any(x in k for x in _CURRENCY_INCLUDE)


def _lakhify_rows(rows: list[dict]) -> list[dict]:
    """Pre-format currency columns (raw INR) as '₹X.XX L' so the LLM quotes
    already-correct Lakh figures instead of doing its own (often wrong) math.
    Handles Decimal/None/strings safely; non-currency values pass through."""
    out: list[dict] = []
    for r in rows:
        nr: dict = {}
        for k, v in r.items():
            if _is_currency_key(k) and v is not None and not isinstance(v, str):
                try:
                    nr[k] = f"₹{float(v) / 100000:,.2f} L"
                except (TypeError, ValueError):
                    nr[k] = v
            else:
                nr[k] = v
        out.append(nr)
    return out


def _data_digest(rows: list[dict]) -> str:
    """Compute total / highest / lowest of the primary currency column over ALL
    rows (not just the sample). Gives the LLM accurate peaks and totals even when
    the dataset is too large to send in full — fixes wrong/partial summaries."""
    if not rows or len(rows) < 2:
        return ""
    keys = list(rows[0].keys())
    cur_key = next((k for k in keys if _is_currency_key(k)), None)
    if not cur_key:
        return ""

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    pairs = [(_num(r.get(cur_key)), r) for r in rows]
    pairs = [(v, r) for v, r in pairs if v is not None]
    if not pairs:
        return ""

    def _label(r: dict) -> str:
        parts = [str(r.get(k)) for k in keys
                 if k != cur_key and not isinstance(r.get(k), (int, float))
                 and r.get(k) not in (None, "")]
        return " / ".join(parts) or "—"

    def _L(v: float) -> str:
        return f"₹{v / 100000:,.2f} L"

    total = sum(v for v, _ in pairs)
    hi_v, hi_r = max(pairs, key=lambda x: x[0])
    lo_v, lo_r = min(pairs, key=lambda x: x[0])
    return (
        f"DATA DIGEST (computed over ALL {len(rows)} rows, column '{cur_key}'): "
        f"total = {_L(total)}; highest = {_L(hi_v)} at [{_label(hi_r)}]; "
        f"lowest = {_L(lo_v)} at [{_label(lo_r)}]. "
        f"Use these for any total / peak / lowest claims — the sample below is only the first rows."
    )


async def explain_results(
    question: str,
    sql: str,
    rows: list[dict],
    row_count: int,
    truncated: bool,
    provider: str,
) -> str:
    sample = _lakhify_rows(rows[:EXPLAIN_MAX_ROWS])
    sample_truncated = truncated or len(rows) > EXPLAIN_MAX_ROWS
    results_json = json.dumps(sample, indent=2, default=str)
    truncation_note = (
        f" (narrating a sample of the first {len(sample)} of {row_count}+ rows)"
        if sample_truncated else ""
    )

    digest = _data_digest(rows)
    digest_block = f"{digest}\n\n" if digest else ""
    content = (
        f"Original question: {question}\n\n"
        f"SQL that was run:\n{sql}\n\n"
        f"{digest_block}"
        f"Results ({row_count} rows{truncation_note}):\n{results_json}\n\n"
        "Explain the results in plain business English."
    )

    raw = await call_ai_async(
        [{"role": "user", "content": content}],
        EXPLAIN_SYSTEM,
        provider,
    )
    result = parse_json_response(raw)
    answer = (result.get("answer") or "").strip()
    if answer.startswith("{") and '"sql"' in answer:
        answer = ""
    if answer:
        return answer
    if row_count > 0:
        return f"Returned {row_count} row(s) for your question."
    return "No rows matched this query for the selected period."


import re as _re_st

_SMALLTALK_HELP = (
    "I can answer questions about your live ERP data — here are things you can ask:\n\n"
    "Sales — \"Today's sales\", \"Month-to-date sales vs last year\", \"YTD, QTD and MTD growth\"\n"
    "Stores — \"Which store has the highest sales this month?\", \"Top 10 stores by growth\"\n"
    "Products — \"Most selling product\", \"Top 20 products by revenue\", \"Slow-moving inventory\"\n"
    "Categories — \"Category contribution % in total revenue\", \"Gross margin by category\"\n"
    "Customers — \"New vs repeat customers\", \"Top customers by value\"\n"
    "Suppliers — \"Supplier contribution %\", \"Which supplier has the highest sales?\"\n\n"
    "You can also click any verified question in the left panel, or ask a follow-up after any answer."
)


def _smalltalk(question: str) -> Optional[str]:
    """Fast, deterministic replies for greetings / chit-chat / help — no LLM call,
    so it works instantly even without API credits. Returns None for real queries."""
    q = (question or "").strip().lower()
    if not q:
        return None
    qn = _re_st.sub(r"[^a-z0-9\s']", " ", q).strip()
    qn = _re_st.sub(r"\s+", " ", qn)
    if not qn:
        return None

    if any(w in qn for w in ("what can you do", "what can i ask", "what do you do",
                             "how do i use", "how to use", "capabilities", "show examples",
                             "what can this", "help me", "what questions")) or qn in ("help", "menu", "options"):
        return _SMALLTALK_HELP
    _short = len(qn.split()) <= 4  # only treat as a greeting when it's a short message
    if (_short and _re_st.match(r"^(hi+|hey+|hello+|hii+|yo|hola|namaste|greetings|good (morning|afternoon|evening|day))\b", qn)) \
            or qn in ("hi", "hey", "hello", "hi there", "hey there", "hello there"):
        return ("Hi! I'm your SmarterP analytics assistant. I pull live numbers from your "
                "ERP — sales, growth, top stores and products, customers, suppliers and "
                "inventory.\n\nTry: \"Which store has the highest sales this month?\" or "
                "\"Category contribution % in total revenue\". You can also pick a verified "
                "question from the panel on the left, or type \"help\" to see what I can do.")
    if "how are you" in qn or "how r u" in qn or "how is it going" in qn or "how's it going" in q or "how do you do" in qn:
        return ("I'm doing great and ready to help! Ask me anything about your sales or "
                "operations — for example \"Today's sales\" or \"Top 10 stores by growth\". "
                "Type \"help\" for more examples.")
    if "who are you" in qn or "your name" in qn or "what are you" in qn:
        return ("I'm the SmarterP AI assistant. I turn your questions into safe, read-only "
                "SQL against your ERP and explain the results in plain English. What would "
                "you like to know about your business?")
    if "thank" in qn or qn in ("thanks", "thx", "ty", "great", "nice", "cool", "perfect", "awesome", "good job", "well done"):
        return "You're welcome! Ask me anything else about your sales, branches, products or customers."
    if qn in ("bye", "goodbye", "see you", "see ya", "cya", "good night", "goodnight", "take care"):
        return "Goodbye! Come back anytime for a live look at your numbers."
    return None


# ─── Main pipeline ────────────────────────────────────────────────────────────

def _views_referenced_in_sql(sql: str, snap: dict) -> list[str]:
    """Map FROM/JOIN targets in SQL to schema object keys."""
    objects = snap.get("objects", {})
    if not objects:
        return []
    found: list[str] = []
    lower_sql = sql.lower()
    for name in objects:
        bare = name.split(".")[-1].lower()
        if bare in lower_sql or name.lower() in lower_sql:
            found.append(name)
    return found[:4]


def _is_comparison_question(question: str) -> bool:
    """True when the user is asking to compare two+ periods/groups (vs, versus, this/last, etc.)."""
    q = (question or "").lower()
    return (
        any(t in q for t in ("compare", " vs ", " vs.", "versus", " v/s ", "compared to", "against"))
        or (" last " in q and (" this " in q or "today" in q or " current" in q))
        or ("same day" in q or "same period" in q or "same month" in q or "same quarter" in q or "same week" in q)
        or ("month-over-month" in q or "month over month" in q or "mom" in q)
        or ("year-over-year" in q or "year over year" in q or "yoy" in q)
        or ("grew" in q and ("declin" in q or "fell" in q or "drop" in q))
    )


# A verified FAQ template only "handles" a comparison if its id signals one of these.
_COMPARISON_FAQ_HINTS = (
    "compare", "_vs_", "vs_last", "yoy", "year_over_year", "mom", "month_over_month",
    "growth", "_comparison", "comparison", "trend", "since",
)


def _faq_handles_comparison(template_id: Optional[str]) -> bool:
    t = (template_id or "").lower()
    return any(h in t for h in _COMPARISON_FAQ_HINTS)


def _comparison_shape_problem(question: str, sql: str) -> Optional[str]:
    """
    Detect a COMPARISON question whose generated SQL uses UNION ALL without a period-label
    column. In that shape SQL Server keeps only the FIRST SELECT's column names, so the two
    periods collapse into one indistinguishable column (e.g. both show as 'TodaySales').
    Returns a repair instruction (fed back to the model) or None if the SQL is fine.
    """
    import re as _re

    if not _is_comparison_question(question):
        return None
    q = (question or "").lower()  # noqa: F841 (kept for parity / future use)

    s = (sql or "").lower()
    if "union all" not in s:
        return None  # single SELECT / conditional aggregation — already correct shape

    # A proper UNION comparison labels each period with a literal string aliased as a label-ish column.
    has_label = bool(
        _re.search(
            r"n?'[^']+'\s+as\s+\[?(period|periodlabel|label|metric|monthname|day|week|year|quarter|name)\b",
            s,
        )
    )
    if has_label:
        return None

    return (
        "COMPARISON-SHAPE ERROR: this is a comparison but the SQL uses UNION ALL without a period "
        "label, so the periods are indistinguishable (UNION keeps only the first SELECT's column "
        "names — the second period's alias is dropped). REWRITE using CONDITIONAL AGGREGATION: ONE "
        "row per dimension with ONE column per period, e.g. "
        "SUM(CASE WHEN <period A> THEN <amount> ELSE 0 END) AS <PeriodAName>, "
        "SUM(CASE WHEN <period B> THEN <amount> ELSE 0 END) AS <PeriodBName>, GROUP BY the dimension, "
        "and add a GrowthPct column when growth/change is implied. If there is no dimension (totals "
        "only), keep UNION ALL but give EVERY SELECT a literal PeriodLabel column. Do NOT return "
        "UNION ALL without per-period labels."
    )


async def run_pipeline(
    question: str,
    provider: str = "openai",
    snap: Optional[dict] = None,
    top_n: Optional[int] = None,
    execute_fn: Optional[Callable] = None,
    force_dynamic: bool = False,
) -> PipelineResult:
    """
    Full db_chat pipeline for the AI Query page.
    """
    from src.db.mssql import execute_query
    from src.ai.test_faq_loader import try_verified_faq

    if execute_fn is None:
        execute_fn = execute_query

    ai_provider = normalize_provider(provider)
    warnings: list[str] = []
    corrected = False
    faq_template_id: Optional[str] = None
    from_template = False

    if snap is None:
        snap = await load_snapshot()

    if not snap.get("objects"):
        raise RuntimeError(
            "No database schema loaded — cannot answer queries. "
            "Run: cd db-chat && python schema_cache.py"
        )

    sql = ""
    explanation = ""
    conversational_answer = ""

    # Fast path: greetings / chit-chat / "help" — answer instantly, no SQL or LLM.
    _st = _smalltalk(question)
    if _st is not None:
        return PipelineResult(
            sql=None, records=[], record_count=0,
            summary=_st, description="Conversational response",
            conversational=True,
        )

    faq = None if force_dynamic else try_verified_faq(question)
    # A comparison question (this vs last, etc.) must show BOTH periods. Single-period FAQ
    # templates can't — so for comparison questions, skip any matched FAQ that isn't itself a
    # comparison template and fall through to the adaptive SQL generator (which builds the
    # multi-period query). This does NOT modify any template — it only changes routing.
    if faq and _is_comparison_question(question) and not _faq_handles_comparison(faq.get("template_id")):
        logger.info(
            "Comparison question — skipping single-period FAQ, using adaptive SQL",
            template_id=faq.get("template_id"),
        )
        faq = None
    if faq and (faq.get("sql") or "").strip():
        sql = str(faq["sql"]).strip()
        explanation = str(
            faq.get("explanation") or faq.get("description") or "Verified FAQ SQL"
        )
        faq_template_id = faq.get("template_id")
        from_template = True
        selected_views = _views_referenced_in_sql(sql, snap) or _keyword_fallback(question, snap)
        view_reason = f"Verified FAQ template ({faq_template_id})"
        for note in faq.get("assumptions") or []:
            warnings.append(str(note))
        logger.info("db_chat FAQ template hit", template_id=faq_template_id)
    else:
        selected_views, view_reason = await select_views(question, snap, ai_provider)
        logger.info(
            "db_chat view selection",
            views=selected_views,
            reason=view_reason,
        )

        focused = focused_schema_for_sql(snap, selected_views)
        sql, explanation, conversational_answer = await generate_sql(
            question, focused, ai_provider, top_n=top_n
        )

    focused = focused_schema_for_sql(snap, selected_views)

    if not sql:
        summary = conversational_answer or explanation
        if summary.strip().startswith("{") and '"sql"' in summary:
            summary = (
                "Could not run this query — the model returned SQL text without a "
                "complete result. Try **FAQ templates** on the left, or rephrase with "
                "a shorter date range (e.g. last 12 months by month)."
            )
        return PipelineResult(
            sql=None,
            records=[],
            record_count=0,
            summary=summary,
            description=explanation or "Conversational response",
            selected_views=selected_views,
            view_selection_reason=view_reason,
            warnings=warnings,
            conversational=True,
            from_template=from_template,
            faq_template_id=faq_template_id,
        )

    # Strip leading comments before safety check
    import re as _re
    sql_no_comments = _re.sub(r'--[^\n]*', '', sql).strip()
    first_word = sql_no_comments.split()[0].upper() if sql_no_comments.split() else ""
    if first_word not in ("SELECT", "WITH"):
        raise ValueError("AI generated a non-SELECT statement — blocked for safety.")

    problems = validate_sql(sql, snap, selected_views)
    # Semantic guard: a comparison rendered as an unlabeled UNION ALL is valid SQL but unreadable —
    # force a repair pass so each period gets its own labelled column.
    if not from_template:
        _cmp_problem = _comparison_shape_problem(question, sql)
        if _cmp_problem:
            problems = [*(problems or []), _cmp_problem]
    if problems:
        problem_str = "; ".join(problems)
        warnings.append(f"SQL validation issues: {problem_str}")
        # Verified FAQ SQL is trusted — schema linter can false-positive on CTE aliases.
        if not from_template:
            sql2, explanation2, _ = await generate_sql(
                question, focused, ai_provider, prior_error=problem_str, top_n=top_n
            )
            if sql2:
                sql, explanation = sql2, explanation2
                corrected = True
                problems2 = validate_sql(sql, snap, selected_views)
                if problems2:
                    warnings.append(
                        f"SQL still has issues after retry: {'; '.join(problems2)}"
                    )

    try:
        result = await execute_fn(sql, nolock=True, recompile=False)
        records = result["records"]
    except Exception as exc:
        if from_template:
            raise RuntimeError(
                f"Verified FAQ SQL failed on the database: {exc}"
            ) from exc
        logger.warning("SQL execution failed — retrying with AI fix", error=str(exc))
        sql2, explanation2, _ = await generate_sql(
            question, focused, ai_provider, prior_error=str(exc), top_n=top_n
        )
        if not sql2:
            raise RuntimeError(str(exc)) from exc
        sql, explanation = sql2, explanation2
        corrected = True
        from_template = False
        result = await execute_fn(sql, nolock=True, recompile=False)
        records = result["records"]

    row_count = len(records)
    truncated = row_count >= MAX_RESULT_ROWS
    if truncated:
        records = records[:MAX_RESULT_ROWS]
        warnings.append(f"Results capped at {MAX_RESULT_ROWS} rows for display.")

    if len(records) > cfg.DATASET_HARD_CAP:
        records = records[: cfg.DATASET_HARD_CAP]
        warnings.append(f"Results capped at {cfg.DATASET_HARD_CAP:,} rows.")

    summary = _try_period_comparison_summary(records, question)
    if not summary:
        summary = await explain_results(
            question, sql, records, row_count, truncated, ai_provider
        )

    if summary.strip().startswith("{") and '"sql"' in summary:
        summary = (
            f"Query returned {len(records)} row(s). "
            f"{explanation or 'See chart and table below.'}"
        )

    return PipelineResult(
        sql=sql,
        records=records,
        record_count=len(records),
        summary=summary,
        description=explanation,
        selected_views=selected_views,
        view_selection_reason=view_reason,
        warnings=warnings,
        corrected=corrected,
        truncated=truncated,
        from_template=from_template,
        faq_template_id=faq_template_id,
    )
