"""
Cross-verify ALL 47 verified templates — data AND predicted chart rendering.

For every entry in FREQUENT_AI_QUERIES this:
  1. matches the question to its template and runs the SQL on the live SQL Server,
  2. reads the real result columns,
  3. replicates the frontend visualization logic (src/lib/nlqVisualization.ts) to predict
     what the AI Query page will draw — single bar, GROUPED bars (multi-series comparison),
     pie, line, or KPI cards — and which columns become the series,
  4. flags anything that would render badly: 0 rows, no numeric column, all-zero numbers,
     or a numeric value that won't parse (would make bars invisible).

Run from repo root (needs backend/.env DB creds, same as the other verify_*.py):
    python test/verify_47_charts.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

from nlq_faq_sql import try_faq_template          # noqa: E402
from nlq_faq_kpi import FREQUENT_AI_QUERIES         # noqa: E402

# ── Mirror of the frontend column classification (nlqVisualization.ts) ──────────
SALES = ("sales", "revenue", "amount", "netsales", "mtdsales", "totalsales", "turnover", "margin")
COUNT = ("count", "customers", "customer", "invoices", "invoice", "bills", "billcount", "qty", "quantity", "units")
AVG = ("ats", "avg", "average", "ticket", "basket", "billvalue", "invoicevalue", "avginvoice")
PCT = ("percent", "pct", "growth", "contribution", "rate", "share")
SKIP = {"id", "rownum", "rn"}
DATE_COL_HINTS = ("monthstart", "monthlabel", "transactiondate", "invoicedt", "xndt", "date", "periodlabel", "latestmonth")
NON_METRIC_KEYS = (
    "salesrank", "rank", "ranking", "firstname", "lastname", "customername", "suppliername",
    "productname", "itemname", "agebucket", "bucket", "purinvoicedate", "invoicedate",
    "monthsin", "monthsof", "monthcount", "dayssince", "position", "sno", "srno", "detail",
)


def _to_num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("%", "").replace("₹", "").strip()
    scaled = re.match(r"^(-?\d*\.?\d+)\s*([Ll]|Cr|CR|cr|K|k|M|m)?$", s)
    if scaled:
        n = float(scaled.group(1))
        suf = (scaled.group(2) or "").lower()
        if suf == "l":
            n *= 100_000
        elif suf == "cr":
            n *= 10_000_000
        elif suf == "k":
            n *= 1_000
        elif suf == "m":
            n *= 1_000_000
        return n
    m = re.match(r"^-?\d*\.?\d+", s)
    return float(m.group()) if m else None


def _coll(c: str) -> str:
    return re.sub(r"[^a-z0-9]", "", c.lower())


def _is_non_metric(col: str) -> bool:
    l = _coll(col)
    if l.endswith("id") and l != "grid":
        return True
    return any(k in l for k in NON_METRIC_KEYS)


def _is_date_col(col: str, records) -> bool:
    l = col.lower()
    if any(h in l for h in DATE_COL_HINTS):
        return True
    samples = [str(r.get(col) or "") for r in records[:8]]
    nonempty = [s for s in samples if s]
    if not nonempty:
        return False
    return all(re.match(r"^\d{4}-\d{2}-\d{2}", s) or re.search(r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec", s, re.I) for s in nonempty)


def _cat(c: str) -> str:
    l = _coll(c)
    if any(h in l for h in PCT):
        return "percent"
    if any(h in l for h in AVG):
        return "rupeeAvg"
    if any(h in l for h in COUNT) and "sales" not in l:
        return "count"
    if any(h in l for h in SALES):
        return "sales"
    return "other"


def _is_numeric(records, col) -> bool:
    return sum(1 for r in records[:12] if _to_num(r.get(col)) is not None) > 0


def _series_has_signal(records, col) -> bool:
    sample = records[:80] if len(records) > 80 else records
    return any((_to_num(r.get(col)) or 0) != 0 for r in sample)


def predict_chart(records):
    """Return (chart_kind, detail, flags) mirroring buildNLQVisualization."""
    flags = []
    if not records:
        return "NONE", "0 rows", ["EMPTY"]
    cols = list(records[0].keys())
    numeric = [
        c for c in cols
        if _is_numeric(records, c)
        and c.lower() not in SKIP
        and not _is_date_col(c, records)
        and not _is_non_metric(c)
    ]
    rown = len(records)

    if not numeric:
        return "TABLE", "no numeric column", ["NO-NUMERIC"]

    if rown == 1:
        return "KPI", "single-row KPI cards", []

    # multi-series grouped bars: 2+ same-scale numeric cols with real signal
    by_cat: dict[str, list[str]] = {}
    for c in numeric:
        by_cat.setdefault(_cat(c), []).append(c)
    chosen = next((cat for cat in ("sales", "count", "rupeeAvg", "percent", "other")
                   if len(by_cat.get(cat, [])) >= 2), None)
    if chosen:
        series = [c for c in by_cat[chosen][:4] if _series_has_signal(records, c)]
        if len(series) >= 2:
            return "GROUPED-BARS", " + ".join(series), flags

    # single series — prefer columns with non-zero signal
    signal = [c for c in numeric if _series_has_signal(records, c)]
    cands = signal or numeric
    main = max(
        cands,
        key=lambda c: (3 if any(h in _coll(c) for h in PCT) else 0)
        + (3 if any(h in _coll(c) for h in SALES) else 0),
    )
    vals = [_to_num(r.get(main)) for r in records[:20]]
    if all((v is None or v == 0) for v in vals):
        flags.append(f"ZERO-VALUES:{main}")
    kind = "PIE" if rown <= 6 else (
        "LINE/AREA" if rown > 14 and any("date" in c.lower() or "month" in c.lower() for c in cols) else "BAR"
    )
    return kind, main, flags


async def main() -> int:
    from src.db.mssql import init_mssql, execute_raw, close_mssql  # noqa: E402

    await init_mssql()
    print("=" * 110)
    print(f"ALL-47 CHART CROSS-CHECK   ({len(FREQUENT_AI_QUERIES)} templates)")
    print("=" * 110)
    print(f"{'#':>2}  {'TEMPLATE':40} {'ROWS':>5}  {'CHART':13} {'SERIES / VALUE':28} FLAGS")
    print("-" * 110)

    ok = warn = bad = 0
    for i, q in enumerate(FREQUENT_AI_QUERIES, 1):
        hit = try_faq_template(q)
        if not hit:
            print(f"{i:2}. {'(no template — dynamic)':40} {'-':>5}  {'-':13} {'-':28} NO-MATCH")
            continue
        tid = hit.get("template_id", "?")
        try:
            r = await execute_raw(hit["sql"])
            records = r.get("records") or []
        except Exception as exc:
            bad += 1
            print(f"{i:2}. {tid[:40]:40} {'ERR':>5}  {'-':13} {'-':28} SQL-ERROR: {str(exc)[:30]}")
            continue
        kind, detail, flags = predict_chart(records)
        if flags:
            warn += 1 if all(not f.startswith(("ZERO", "EMPTY", "SQL")) for f in flags) else 0
            bad += 1 if any(f.startswith(("ZERO", "EMPTY", "SQL")) for f in flags) else 0
        else:
            ok += 1
        flagstr = ", ".join(flags) if flags else "ok"
        print(f"{i:2}. {tid[:40]:40} {len(records):>5}  {kind:13} {detail[:28]:28} {flagstr}")

    print("-" * 110)
    print(f"SUMMARY:  clean={ok}  needs-review={warn}  problems={bad}   (of {len(FREQUENT_AI_QUERIES)})")
    print("GROUPED-BARS = comparison rendered as grouped bars · ZERO-* / EMPTY / SQL-ERROR = needs a look")
    print("=" * 110)
    await close_mssql()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
