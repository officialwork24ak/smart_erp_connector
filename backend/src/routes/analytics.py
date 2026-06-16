"""
Analytics Routes
GET /analytics/kpis                 — Home KPIs
GET /analytics/trend                — Revenue trend
GET /analytics/categories           — Category breakdown
GET /analytics/branches             — Branch bar chart
GET /analytics/departments          — Department breakdown
GET /analytics/products/catalog    — Paginated item master (VW_MB_POWERBI_PRODUCT_MASTER)
GET /analytics/products/top        — Top sellers by revenue for a period (+ YoY growth)
GET /analytics/heatmap              — Hourly heatmap
GET /analytics/bundle               — Fast parallel split (branches+trend+categories+kpis)
GET /analytics/branches/{alias}     — Branch detail + trend
GET /analytics/health               — DB health check
POST /analytics/cache/clear         — Clear cache (admin)
DELETE /analytics/cache/custom      — Clear custom-range cache entries only
GET /analytics/cache/stats          — Cache stats (admin)
GET /analytics/views                — List all ERP views from semantic catalog
GET /analytics/views/query          — Paginate rows from a whitelisted ERP view
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

from src.analytics.kpi import get_home_kpis
from src.analytics.charts import (
    get_revenue_trend,
    get_category_breakdown,
    get_branch_chart,
    get_department_chart,
    get_top_salespersons,
    get_hourly_heatmap,
    get_branch_detail,
)
from src.analytics.products_catalog import fetch_product_catalog, fetch_top_products
from src.analytics.customers import get_customer_count, get_custom_customer_count
from src.analytics.transactions import get_transactions, get_transaction_summary
from src.analytics.view_explorer import fetch_view_page, list_catalog_views
from src.analytics.concurrency import run_analytics_sql
from src.analytics.cache_prime import (
    assemble_bundle_from_chart_caches,
    bundle_cache_fetched_at,
    prime_chart_caches_from_bundle,
)
from src.analytics.dashboard import get_dashboard
from src.db.mssql import check_mssql_health
from src.middleware.auth import get_current_user, require_permission, require_roles
from src.auth.jwt import TokenPayload
from src.utils.logger import logger

router = APIRouter(prefix="/analytics", tags=["analytics"])

_VALID_PERIODS = {
    "today", "yesterday", "mtd", "ytd", "qtd",
    "last_7d", "last_14d", "last_30d", "last_90d",
    "last_180d", "last_6m", "last_365d",
    "last_month", "last_quarter", "last_year", "custom",
}

# Periods where COUNT(DISTINCT CustomerId) routinely exceeds request timeout.
# YTD / last_6m / qtd run in ~3–20s on SALES_AI_TABLE and are included in bundle.
_LONG_PERIODS = {
    "last_90d", "last_180d", "last_365d", "last_year", "last_quarter",
}


def _validate_period(period: str) -> str:
    if period not in _VALID_PERIODS:
        raise HTTPException(status_code=400, detail=f"Invalid period '{period}'. Valid: {sorted(_VALID_PERIODS)}")
    return period


# ─── Sales Dashboard (summary + YoY trend + contribution) ───────────────────

@router.get("/dashboard")
async def sales_dashboard(
    period: str = Query(default="mtd"),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="custom period requires start_date and end_date")
    else:
        _validate_period(period)
    try:
        data = await run_analytics_sql(
            get_dashboard(period, start_date, end_date, force_refresh=force)
        )
        return {"success": True, **data}
    except Exception as exc:
        logger.error("Dashboard fetch failed", period=period, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/customer-count")
async def customer_count_endpoint(
    period: str = Query(default="mtd"),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Fast COUNT(DISTINCT CustomerId) — used to backfill custom-range analytics KPIs."""
    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="custom period requires start_date and end_date")
        try:
            count = await run_analytics_sql(get_custom_customer_count(start_date, end_date))
            return {"success": True, "period": period, "customer_count": count}
        except Exception as exc:
            logger.error("Custom customer count failed", error=str(exc))
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    _validate_period(period)
    try:
        count = await run_analytics_sql(get_customer_count(period))
        return {"success": True, "period": period, "customer_count": count}
    except Exception as exc:
        logger.error("Customer count failed", period=period, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── KPIs ─────────────────────────────────────────────────────────────────────

@router.get("/kpis")
async def home_kpis(
    period: str = Query(default="mtd"),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    try:
        # include_extras=True only here — adds COUNT(DISTINCT) KPIs for the dashboard
        # cards. Opt-in because these are expensive on long date ranges.
        data = await get_home_kpis(period, include_extras=True)
        return {"success": True, "period": period, **data}
    except Exception as exc:
        logger.error("KPI fetch failed", period=period, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ─── Fast bundle (one HTTP round-trip; server-side parallel SQL) ───────────────

async def _fetch_analytics_bundle(
    period: str,
    top_n: int = 100,
    *,
    include_departments: bool = False,
    include_kpis: bool = False,
    include_extras: bool = False,
    include_customer_count: bool = True,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """Run branches + trend + categories (+ optional kpis/depts/customers) in parallel."""
    n = top_n

    cached = assemble_bundle_from_chart_caches(
        period,
        n,
        include_kpis=include_kpis,
        include_departments=include_departments,
        force_refresh=force_refresh,
    )
    if cached is not None:
        fetched_at = bundle_cache_fetched_at(
            period, n, include_kpis=include_kpis, include_departments=include_departments,
        )
        payload: Dict[str, Any] = {
            "success": True,
            "period": period,
            **cached,
            "from_cache": True,
            "fetched_at": fetched_at or time.time(),
        }
        # Chart caches never include customer_count or extras (distinct_clients etc).
        # Fetch them in parallel when the caller needs them.
        extra_coros = []
        extra_keys: list = []
        if include_customer_count:
            extra_coros.append(get_customer_count(period))
            extra_keys.append("customer_count")
        if include_extras and include_kpis:
            extra_coros.append(get_home_kpis(period, include_customers=False, include_extras=True))
            extra_keys.append("_extras")
        if extra_coros:
            import asyncio as _asyncio
            results = await _asyncio.gather(*extra_coros, return_exceptions=True)
            for key, result in zip(extra_keys, results):
                if isinstance(result, Exception):
                    logger.warning("Bundle cache: extra failed", key=key, period=period, error=str(result))
                    continue
                if key == "customer_count":
                    payload["customer_count"] = result
                elif key == "_extras" and isinstance(result, dict):
                    existing_kpis = dict(payload.get("kpis") or {})
                    existing_kpis["distinct_clients"]   = result.get("distinct_clients")
                    existing_kpis["distinct_suppliers"] = result.get("distinct_suppliers")
                    existing_kpis["unique_invoices"]    = result.get("unique_invoices")
                    payload["kpis"] = existing_kpis
        return payload

    specs: List[Tuple[str, Any]] = [
        ("branches", get_branch_chart(period)),
        ("trend", get_revenue_trend(period)),
        ("categories", get_category_breakdown(period, n)),
    ]
    if include_kpis:
        specs.append(("kpis", get_home_kpis(period, include_customers=False, include_extras=include_extras)))
    if include_departments:
        specs.append(("departments", get_department_chart(period, n)))
    # Skip customer COUNT(DISTINCT) for long periods — too slow (47s+) on large views.
    if include_customer_count and period not in _LONG_PERIODS:
        specs.append(("customers", get_customer_count(period)))

    timings_ms: Dict[str, float] = {}
    errors: Dict[str, str] = {}
    payload: Dict[str, Any] = {"success": True, "period": period}

    async def _timed(name: str, coro: Any) -> Tuple[str, Any, float]:
        t0 = time.perf_counter()
        try:
            data = await run_analytics_sql(coro)
            return name, data, round((time.perf_counter() - t0) * 1000, 1)
        except Exception as exc:
            return name, exc, round((time.perf_counter() - t0) * 1000, 1)

    results = await asyncio.gather(*[_timed(name, coro) for name, coro in specs])
    for name, outcome, ms in results:
        timings_ms[name] = ms
        if isinstance(outcome, Exception):
            errors[name] = str(outcome)
            logger.warning("Bundle partial failure", period=period, key=name, error=str(outcome))
            continue
        if name == "kpis":
            payload["kpis"] = outcome
        elif name == "trend":
            payload["trend"] = outcome
        elif name == "customers":
            payload["customer_count"] = outcome
        else:
            payload[name] = outcome

    if errors:
        payload["errors"] = errors
    payload["timings_ms"] = timings_ms

    required = {"branches", "trend", "categories"}
    missing = required - {k for k in required if k in payload}
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Bundle missing required keys: {sorted(missing)}. Errors: {errors}",
        )
    try:
        prime_chart_caches_from_bundle(period, payload, top_n=n)
    except Exception:
        pass
    payload["fetched_at"] = time.time()
    payload["from_cache"] = False
    return payload


@router.get("/bundle")
async def analytics_bundle(
    period: str = Query(default="mtd"),
    top_n: int = Query(default=100, ge=1, le=100),
    include_departments: bool = Query(default=False),
    include_kpis: bool = Query(default=False),
    include_customer_count: bool = Query(default=True),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Single request: branches, trend, categories, optional KPIs/departments
    in parallel on the server — one HTTP round-trip for a full analytics slice.
    """
    _validate_period(period)
    try:
        return await _fetch_analytics_bundle(
            period,
            top_n,
            include_departments=include_departments,
            include_kpis=include_kpis,
            include_customer_count=include_customer_count,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Bundle fetch failed", period=period, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/dashboard-page")
async def dashboard_page(
    force: bool = Query(default=False),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    One HTTP call for the home dashboard: MTD + Today bundles (with KPIs) in parallel.
    Pass ?force=true to bypass server cache — used by the Refresh button.
    """
    try:
        mtd, today = await asyncio.gather(
            _fetch_analytics_bundle("mtd", 100, include_kpis=True, include_extras=True, force_refresh=force),
            # include_extras=True so TODAY's distinct customer count is fetched too —
            # otherwise the "Today's Customer Count" card shows "—" while Analytics shows it.
            # A one-day COUNT(DISTINCT) is cheap, so there is no real performance cost.
            _fetch_analytics_bundle("today", 10, include_kpis=True, include_extras=True, force_refresh=force),
        )
        ts = [
            float(x)
            for x in (mtd.get("fetched_at"), today.get("fetched_at"))
            if isinstance(x, (int, float)) and x > 0
        ]
        return {
            "success": True,
            "mtd": mtd,
            "today": today,
            "fetched_at": max(ts) if ts else time.time(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Dashboard page fetch failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc




# ─── Analytics page (one-shot for the Analytics tab) ─────────────────────────

@router.get("/analytics-page")
async def analytics_page_endpoint(
    period: str = Query(default="mtd"),
    top_n: int = Query(default=100, ge=1, le=100),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    One HTTP call for the Analytics page: bundle+departments+dashboard in parallel.
    All three are cache-warm on startup, so this typically resolves in under 100 ms.
    For custom range: period=custom&start_date=YYYY-MM-DD&end_date=YYYY-MM-DD.
    """
    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="custom period requires start_date and end_date")
    else:
        _validate_period(period)

    try:
        if period == "custom":
            # Fetch dashboard + departments for the custom range in parallel so the
            # Department-wise Sales chart renders (previously returned [] → "No data").
            dash, dept_res = await asyncio.gather(
                get_dashboard(period, start_date, end_date),
                run_analytics_sql(get_department_chart(period, top_n, start_date, end_date)),
                return_exceptions=True,
            )
            if isinstance(dash, Exception):
                logger.warning("analytics-page custom dashboard failed", error=str(dash))
                dash = None
            departments = dept_res if isinstance(dept_res, list) else []
            if isinstance(dept_res, Exception):
                logger.warning("analytics-page custom departments failed", error=str(dept_res))
            return {
                "success": True,
                "period": period,
                "bundle": None,
                "departments": departments,
                "dashboard": dash,
            }

        bundle_res, dept_res, dash_res = await asyncio.gather(
            _fetch_analytics_bundle(period, top_n, include_kpis=True, include_customer_count=True),
            run_analytics_sql(get_department_chart(period, top_n)),
            run_analytics_sql(get_dashboard(period)),
            return_exceptions=True,
        )

        payload: Dict[str, Any] = {"success": True, "period": period}

        if isinstance(bundle_res, Exception):
            logger.warning("analytics-page bundle failed", period=period, error=str(bundle_res))
            payload["bundle"] = None
        else:
            payload["bundle"] = bundle_res

        payload["departments"] = dept_res if isinstance(dept_res, list) else []
        if isinstance(dept_res, Exception):
            logger.warning("analytics-page depts failed", period=period, error=str(dept_res))

        payload["dashboard"] = dash_res if not isinstance(dash_res, Exception) else None
        if isinstance(dash_res, Exception):
            logger.warning("analytics-page dashboard failed", period=period, error=str(dash_res))

        return payload

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Analytics page fetch failed", period=period, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ─── Charts ───────────────────────────────────────────────────────────────────

@router.get("/trend")
async def revenue_trend(
    period: str = Query(default="last_30d"),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    data = await get_revenue_trend(period)
    return {"success": True, "period": period, "trend": data}


@router.get("/categories")
async def category_breakdown(
    period: str = Query(default="mtd"),
    top_n: int = Query(default=10, ge=1, le=100),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    data = await get_category_breakdown(period, top_n)
    return {"success": True, "period": period, "categories": data}


@router.get("/branches")
async def branch_chart(
    period: str = Query(default="mtd"),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    data = await get_branch_chart(period)
    return {"success": True, "period": period, "branches": data}


@router.get("/departments")
async def department_chart(
    period: str = Query(default="mtd"),
    top_n: int = Query(default=10, ge=1, le=100),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="custom period requires start_date and end_date")
    else:
        _validate_period(period)
    try:
        data = await run_analytics_sql(
            get_department_chart(period, top_n, start_date, end_date)
        )
        return {"success": True, "period": period, "departments": data}
    except Exception as exc:
        logger.error("Department chart failed", period=period, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/salespersons")
async def top_salespersons(
    period: str = Query(default="mtd"),
    top_n: int = Query(default=10, ge=1, le=50),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    data = await get_top_salespersons(period, top_n)
    return {"success": True, "period": period, "salespersons": data}


@router.get("/products/catalog")
async def product_catalog_api(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=5, le=500),
    offset: int = Query(default=0, ge=0),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        data = await run_analytics_sql(fetch_product_catalog(search=search, limit=limit, offset=offset))
        return data
    except Exception as exc:
        logger.error("product_catalog_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/products/top")
async def top_products_api(
    period: str = Query(default="mtd"),
    top_n: int = Query(default=15, ge=5, le=80),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    n = max(5, min(int(top_n), 80))
    try:
        items = await run_analytics_sql(fetch_top_products(period, top_n))
        return {"success": True, "period": period, "products": items}
    except Exception as exc:
        logger.error("top_products_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/heatmap")
async def hourly_heatmap(
    period: str = Query(default="last_30d"),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    data = await get_hourly_heatmap(period)
    return {"success": True, "period": period, "heatmap": data}


# ─── Branch Detail ────────────────────────────────────────────────────────────

@router.get("/branches/{branch_alias}")
async def branch_detail(
    branch_alias: str,
    period: str = Query(default="last_14d"),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    data = await get_branch_detail(branch_alias, period)
    return {"success": True, **data}


# ─── Cache Management ─────────────────────────────────────────────────────────

@router.delete("/cache/custom")
async def clear_custom_cache(
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete all custom-range dashboard cache entries from memory + PostgreSQL."""
    from src.analytics.cache import cache as _cache
    from src.analytics.dashboard import CUSTOM_DASHBOARD_CACHE_PREFIX

    deleted = await _cache.invalidate_prefix_pg(CUSTOM_DASHBOARD_CACHE_PREFIX)
    logger.info("Custom analytics cache cleared", deleted=deleted, user=user.email)
    return {
        "success": True,
        "deleted": deleted,
        "message": f"Cleared {deleted} custom cache entr{'y' if deleted == 1 else 'ies'}",
    }


# ─── Health Check ─────────────────────────────────────────────────────────────

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    mssql = await check_mssql_health()
    overall = mssql.get("connected", False)
    return {
        "success": overall,
        "status": "healthy" if overall else "degraded",
        "mssql": mssql,
        "mode": "live",
    }
# ─── Transactions ────────────────────────────────────────────────────────────

@router.get("/transactions/summary")
async def transaction_summary(
    period: str = Query(default="mtd"),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    try:
        data = await get_transaction_summary(period)
        return {"success": True, **data}
    except Exception as exc:
        logger.error("transaction_summary_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/transactions")
async def transactions_list(
    period: str = Query(default="mtd"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    branch: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    _validate_period(period)
    try:
        data = await run_analytics_sql(get_transactions(period, page, page_size, branch, category, search))
        return {"success": True, **data}
    except Exception as exc:
        logger.error("transactions_list_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ─── View catalog / data explorer ────────────────────────────────────────────

@router.get("/views")
async def views_catalog(
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """List all whitelisted ERP views from the semantic catalog."""
    try:
        data = list_catalog_views()
        return {"success": True, **data}
    except Exception as exc:
        logger.error("views_catalog_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))



@router.post("/sql")
async def run_custom_sql(
    body: Dict[str, Any],
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Execute a read-only custom SQL query. Body: {sql, limit?}"""
    import re
    import time as _time
    from src.db.mssql import execute_query

    sql_raw: str = (body.get("sql") or "").strip()
    if not sql_raw:
        raise HTTPException(status_code=400, detail="sql is required")

    first_token = re.split(r"\s+", sql_raw.lstrip(), maxsplit=1)[0].upper()
    forbidden = {"INSERT","UPDATE","DELETE","DROP","CREATE","ALTER",
                 "TRUNCATE","EXEC","EXECUTE","GRANT","REVOKE","MERGE"}
    if first_token in forbidden:
        raise HTTPException(status_code=400, detail=f"Only SELECT allowed. Got: {first_token}")

    limit = min(int(body.get("limit", 500)), 1000)
    if sql_raw.upper().lstrip().startswith("SELECT") and "TOP " not in sql_raw.upper()[:30]:
        sql_raw = re.sub(r"(?i)^SELECT\b", f"SELECT TOP {limit}", sql_raw, count=1)

    t0 = _time.time()
    try:
        result = await execute_query(sql_raw, params={}, nolock=False, recompile=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    duration_ms = round((_time.time() - t0) * 1000)
    records = result.get("records", [])
    columns = list(records[0].keys()) if records else []

    def _safe(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, (int, float, bool, str)):
            return v
        return str(v)

    rows = [[_safe(r[c]) for c in columns] for r in records]
    logger.info("custom_sql_executed", user=user.email, rows=len(rows), duration_ms=duration_ms)
    return {"success": True, "columns": columns, "rows": rows,
            "row_count": len(rows), "duration_ms": duration_ms}

@router.get("/views/query")
async def views_query(
    view: str = Query(..., description="View key from catalog"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    skip_count: Optional[bool] = Query(
        None,
        description="Skip row count (fast). Default: auto for dimension/master views.",
    ),
    user: TokenPayload = Depends(get_current_user),
) -> Dict[str, Any]:
    """Paginate rows from a whitelisted ERP view."""
    try:
        # Do not use run_analytics_sql — view browse must not queue behind dashboard warmup.
        data = await fetch_view_page(view, page, page_size, skip_count=skip_count)
        return {"success": True, **data}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("views_query_failed", view=view, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
