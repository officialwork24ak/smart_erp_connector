#!/usr/bin/env python3
"""Stress-test NLQ dynamic fallback across ERP views (read-only)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except ImportError:
    pass

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:3000")
API_EMAIL = os.environ.get("DASHBOARD_EMAIL") or os.environ.get("APP_LOGIN_EMAIL", "asha24@gmail.com")
API_PASSWORD = os.environ.get("DASHBOARD_PASSWORD") or os.environ.get("APP_LOGIN_PASSWORD", "")
os.chdir(BACKEND)

QUERIES = [
    # Sales & revenue
    ("sales", "What's our total revenue this month?"),
    ("sales", "Show revenue by branch for the quarter"),
    ("sales", "Which department earns the most?"),
    ("sales", "Daily sales trend for the last 30 days"),
    ("sales", "Compare this month's revenue to last month"),
    ("sales", "What's the average order value right now?"),
    ("sales", "How many bills did we generate today?"),
    ("sales", "Revenue split by category as a percentage"),
    # Products & articles
    ("products", "Top 10 good performing products"),
    ("products", "Worst selling articles this month"),
    ("products", "Which products had zero sales recently?"),
    ("products", "Highest MRP items we sold"),
    ("products", "Sales by article number for the quarter"),
    # Branches & stores
    ("branches", "Which branch has the highest footfall?"),
    ("branches", "Rank all branches by units sold"),
    ("branches", "Slowest branch this month"),
    ("branches", "Branch-wise average basket size"),
    # Customers
    ("customers", "Top 10 customers by spend this month"),
    ("customers", "How many unique customers bought today?"),
    ("customers", "New customer signups this quarter"),
    ("customers", "Which customers visit most often?"),
    # Suppliers
    ("suppliers", "Revenue by supplier this quarter"),
    ("suppliers", "Top 5 suppliers by units sold"),
    ("suppliers", "Which supplier contributes the most to sales?"),
    # Salespeople
    ("salespeople", "Who is our best salesperson this month?"),
    ("salespeople", "Rank salespersons by revenue"),
    ("salespeople", "Average sale value per salesperson"),
    # Discounts & margins
    ("margins", "Which branch gives the most discount?"),
    ("margins", "Gross margin by category"),
    ("margins", "Total discount given this month"),
    ("margins", "Products sold below cost"),
    # Stock & inventory
    ("inventory", "What's low on stock right now?"),
    ("inventory", "Stock on hand by category"),
    ("inventory", "Inventory value by branch"),
    # Purchases & transfers
    ("purchases", "Total purchases this month"),
    ("purchases", "Purchase returns this quarter"),
    ("purchases", "Stock transfers out by branch"),
]

DEAD_VIEWS = ("APP_REPORT", "VW_MB_POWERBI_APP_REPORT")
GOOD_SALES = ("SLS_DATA_WITHOUT_ITEMID", "SLSXNS", "SALESPERSON")


def _views_in_sql(sql: str) -> list[str]:
    if not sql:
        return []
    return re.findall(r"VW_MB_POWERBI_\w+", sql.upper())


def _is_compare_sql(sql: str) -> bool:
    u = (sql or "").upper()
    return "UNION" in u or ("CASE" in u and "MONTH" in u) or u.count("SELECT") >= 2


def _api_post(path: str, body: dict, token: str, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{API_BASE.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def _api_login(email: str, password: str) -> str:
    out = _api_post("/auth/login", {"email": email, "password": password}, "", 120)
    token = out.get("access_token")
    if not token:
        raise RuntimeError(f"Login failed: {out}")
    return token


async def run_one_api(
    question: str,
    provider: str,
    force_dynamic: bool,
    timeout: float,
    token: str,
) -> dict:
    t0 = time.perf_counter()
    try:
        out = await asyncio.to_thread(
            _api_post,
            "/ai/query",
            {
                "query": question,
                "provider": provider,
                "force_dynamic": force_dynamic,
            },
            token,
            timeout,
        )
        elapsed = time.perf_counter() - t0
        sql = out.get("sql") or ""
        views = _views_in_sql(sql)
        dead = any(d in " ".join(views) for d in DEAD_VIEWS)
        rows = int(out.get("record_count") or 0)
        return {
            "ok": bool(out.get("success")),
            "rows": rows,
            "from_template": bool(out.get("from_template")),
            "template_id": out.get("faq_template_id"),
            "views": views,
            "dead_view": dead,
            "compare_sql": _is_compare_sql(sql),
            "sql_preview": sql[:400].replace("\n", " "),
            "summary_preview": (out.get("summary") or "")[:200],
            "elapsed_s": round(elapsed, 1),
            "warnings": (out.get("warnings") or [])[:3],
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc)[:300],
            "elapsed_s": round(time.perf_counter() - t0, 1),
        }


async def run_one(
    question: str,
    provider: str,
    dynamic_only: bool,
    timeout: float,
    skip_explain: bool,
    snap: dict | None = None,
):
    import src.ai.test_faq_loader as faq_loader
    import src.ai.db_chat_pipeline as pipe

    orig_faq = faq_loader.try_verified_faq
    orig_explain = pipe.explain_results
    if dynamic_only:
        faq_loader.try_verified_faq = lambda _q: None  # type: ignore[assignment]
    if skip_explain:
        async def _fast_explain(*_a, **_k):
            return ""

        pipe.explain_results = _fast_explain  # type: ignore[assignment]

    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            pipe.run_pipeline(question, provider=provider, snap=snap),
            timeout=timeout,
        )
        elapsed = time.perf_counter() - t0
        sql = result.sql or ""
        views = _views_in_sql(sql)
        dead = any(d in " ".join(views) for d in DEAD_VIEWS)
        return {
            "ok": True,
            "rows": result.record_count,
            "from_template": result.from_template,
            "template_id": result.faq_template_id,
            "views": views,
            "dead_view": dead,
            "compare_sql": _is_compare_sql(sql),
            "sql_preview": sql[:400].replace("\n", " "),
            "summary_preview": (result.summary or "")[:200],
            "elapsed_s": round(elapsed, 1),
            "warnings": result.warnings[:3] if result.warnings else [],
        }
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout>{timeout}s", "elapsed_s": round(time.perf_counter() - t0, 1)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "elapsed_s": round(time.perf_counter() - t0, 1)}
    finally:
        if dynamic_only:
            faq_loader.try_verified_faq = orig_faq
        if skip_explain:
            pipe.explain_results = orig_explain


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openai", choices=("openai", "claude"))
    ap.add_argument("--api", action="store_true", help="Hit running backend /ai/query (recommended)")
    ap.add_argument("--email", default=API_EMAIL)
    ap.add_argument("--password", default=API_PASSWORD)
    ap.add_argument("--dynamic-only", action="store_true", help="Skip FAQ templates")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--skip-explain", action="store_true", default=True)
    ap.add_argument("--with-explain", action="store_true", help="Include LLM narration (slower)")
    ap.add_argument("--out", default=str(ROOT / "test" / "stress_nlq_results.json"))
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    subset = QUERIES[args.start :]
    if args.limit:
        subset = subset[: args.limit]

    skip_explain = args.skip_explain and not args.with_explain
    token = ""
    if args.api:
        pwd = args.password or input(f"Password for {args.email}: ").strip()
        print(f"Logging in to {API_BASE}...", flush=True)
        token = _api_login(args.email, pwd)
        snap = None
    else:
        from src.ai.db_chat_pipeline import load_snapshot
        from src.db.mssql import execute_query

        print("Warming DB connection...", flush=True)
        await execute_query("SELECT 1 AS ok", nolock=True)
        snap = await load_snapshot()

    mode = "api" if args.api else "direct"
    print(
        f"Running {len(subset)} queries via {mode} "
        f"(dynamic_only={args.dynamic_only}, skip_explain={skip_explain})...",
        flush=True,
    )
    results: list[dict] = []
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    for i, (cat, q) in enumerate(subset, args.start + 1):
        print(f"[{i}/{args.start + len(subset)}] {q[:60]}...", flush=True)
        if args.api:
            r = await run_one_api(
                q, args.provider, args.dynamic_only, args.timeout, token
            )
        else:
            r = await run_one(
                q, args.provider, args.dynamic_only, args.timeout, skip_explain, snap
            )
        row = {"category": cat, "question": q, **r}
        results.append(row)
        out.write_text(json.dumps(results, indent=2), encoding="utf-8")
        status = "OK" if r.get("ok") and r.get("rows", 0) > 0 else ("OK0" if r.get("ok") else "FAIL")
        tpl = "TPL" if r.get("from_template") else "DYN"
        print(
            f"  -> {status} {tpl} rows={r.get('rows','-')} "
            f"t={r.get('elapsed_s')}s views={r.get('views', r.get('error',''))}",
            flush=True,
        )

    ok = sum(1 for r in results if r.get("ok") and r.get("rows", 0) > 0)
    zero = sum(1 for r in results if r.get("ok") and r.get("rows", 0) == 0)
    fail = sum(1 for r in results if not r.get("ok"))
    dead = sum(1 for r in results if r.get("dead_view"))
    tpl = sum(1 for r in results if r.get("from_template"))
    print(f"\nDone: {ok} with rows, {zero} zero-row, {fail} fail, {dead} dead-view, {tpl} template")
    print(f"Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
