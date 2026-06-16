"""
Schema Catalog Engine
Loads schema_catalog.json and provides:
  - Smart view selection (top-N most relevant views per query)
  - Compact schema context for AI SQL-generation prompts
  - Intent-aware view routing for all 28 ERP views

This replaces the manually-maintained schema.py approach. Every view
is described exactly as it exists in the real database, so the AI
generates column names and table names that are 100% correct.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Catalog load (once at import) ───────────────────────────────────────────

_CATALOG_PATH = Path(__file__).parent.parent.parent / "data" / "schema_catalog.json"


@lru_cache(maxsize=1)
def _load_catalog() -> Dict[str, Any]:
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _objects() -> List[Dict[str, Any]]:
    return _load_catalog()["objects"]


def _by_name() -> Dict[str, Dict[str, Any]]:
    return {o["short_name"]: o for o in _objects()}


# ─── View routing — keyword → view mapping ────────────────────────────────────
#
# Each entry is (view_short_name, score_weight, [keyword_triggers]).
# The primary sales view is included by default for most queries.

# PRIMARY populated sales view. NOTE: the legacy VW_MB_POWERBI_APP_REPORT
# (NetAmount/XnDt/AppQty) is EMPTY in this database — never route to it, or
# generated SQL returns 0 rows. Everything sales/revenue/performance related
# uses this canonical view (SalesNetAmount/CashmemoDt/SalesQuantity/CashmemoNo).
_PRIMARY_VIEW = "VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID"  # populated; ~90% of queries

_ROUTING: List[tuple] = [
    # ── Sales / Revenue / Performance — PRIMARY view (also covers salesperson) ──
    ("VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID", 4, [
        "sale", "sales", "revenue", "net amount", "net sales", "net revenue",
        "branch", "category", "department", "month", "year", "quarter",
        "mtd", "ytd", "qtd", "analytics", "performance", "performing", "kpi",
        "bill", "bills", "footfall", "traffic", "transaction", "transactions", "trend",
        "revenue trend", "growth", "top branch", "top category", "top department",
        "top product", "top products", "best product", "best products",
        "top selling", "best selling", "good performing", "best performing",
        "product", "products", "item", "items",
        "salesperson", "sales person", "sales rep", "who sold", "staff",
        "employee", "agent", "top seller", "best seller", "sales associate",
        "discount", "margin", "average order", "average ticket", "basket",
        "atv", "aov", "ats",
    ]),
    ("VwAISalesPerson", 3, [
        "salesperson", "sales person", "sales rep", "salesperson name",
    ]),
    # ── Trend / Time Series ───────────────────────────────────────────────
    ("VwAISalesData", 3, [
        "trend", "daily", "weekly", "monthly", "over time", "time series",
        "growth rate", "by day", "by week", "by month", "last 30 days",
        "last 7 days", "prior", "previous", "comparison over time",
    ]),
    # ── Branch ────────────────────────────────────────────────────────────
    ("VwAIBranch", 3, [
        "branch list", "all branches", "branch name", "branch address",
        "branch city", "branch state", "branch location", "which branch",
        "store", "outlet", "location", "city", "state",
    ]),
    ("VW_MB_POWERBI_BRANCH_LIST", 2, [
        "branch master", "branch code", "branch alias", "all stores",
    ]),
    # ── Customer ──────────────────────────────────────────────────────────
    ("VwAICustomerDetails", 4, [
        "customer", "client", "new customer", "loyalty", "member",
        "registered customer", "customer count", "customer group",
        "birthday", "anniversary", "credit limit", "who are our customers",
    ]),
    # ── Product / Item / Article ──────────────────────────────────────────
    ("VW_MB_POWERBI_PRODUCT_MASTER", 4, [
        "product", "item", "sku", "article", "article no", "barcode",
        "style", "fabric", "color", "size", "mrp", "cost price",
        "item master", "product master", "which items", "item list",
        "products", "items",
    ]),
    ("VwMstItems", 3, [
        "item master", "sku", "product code", "item code", "all items",
        "item detail", "product parameter", "item attribute",
    ]),
    ("VW_MB_POWERBI_SLS_ARTICLE_REPORT", 3, [
        "article", "style no", "style number", "article number",
        "sales by article", "sales by style", "net sales by item",
    ]),
    # ── Category / Department Hierarchy ──────────────────────────────────
    ("VW_MB_POWERBI_CATEGORY_MASTER", 3, [
        "category master", "category list", "all categories",
        "department list", "sub-category", "category hierarchy",
        "category code",
    ]),
    # ── Stock / Inventory ─────────────────────────────────────────────────
    ("VwAIStockData", 3, [
        "stock", "inventory", "on hand", "closing stock", "stock level",
        "out of stock", "in stock",
    ]),
    ("VW_MB_POWERBI_STOCK_REPORT", 4, [
        "stock report", "stock by branch", "stock by category",
        "stock value", "inventory value", "current stock",
        "stock on hand", "item stock", "low on stock", "low stock",
        "low stock items", "stock quantity", "available stock",
        "which products", "which items",
    ]),
    ("VW_MB_POWERBI_CBS_WITH_GIT", 3, [
        "goods in transit", "git", "inter branch transfer",
        "transit stock", "stock in transit",
    ]),
    # ── Purchase / Procurement ────────────────────────────────────────────
    ("VW_MB_POWERBI_PUR_REPORT", 4, [
        "purchase", "procurement", "buying", "grn", "goods receipt",
        "vendor receipt", "purchase order", "inward",
    ]),
    ("VW_MB_POWERBI_PURXNS_REPORT", 3, [
        "purchase transaction", "purchase detail", "purchase return",
        "purchase and return", "purchase vs return",
    ]),
    ("VW_MB_POWERBI_PRT_REPORT", 4, [
        "purchase return", "vendor return", "return to supplier",
        "purchase return report",
    ]),
    ("VW_MB_POWERBI_PUR_QTY_WITH_COST", 3, [
        "purchase quantity", "purchase cost", "quantity purchased",
        "total purchased",
    ]),
    # ── Supplier / Vendor ─────────────────────────────────────────────────
    ("VwAISupplier", 3, [
        "supplier", "vendor", "supplier name", "supplier list",
        "which supplier", "supplier details",
    ]),
    ("VW_MB_POWERBI_VENDOR_MASTER", 4, [
        "vendor master", "supplier master", "supplier contact",
        "supplier tax", "supplier credit", "supplier gst", "gstin",
        "vendor profile",
    ]),
    ("VW_MB_POWERBI_SUPPLIER_PUR_REPORT", 4, [
        "supplier purchase", "supplier-wise purchase", "vendor purchase",
        "supplier performance", "top supplier", "supplier revenue",
        "mis supplier",
    ]),
    ("VW_MB_POWERBI_MIS_SUPPLIER_SLS_DATA", 3, [
        "mis", "supplier sales", "vendor sales", "monthly supplier",
    ]),
    # ── Stock Transfers ───────────────────────────────────────────────────
    ("VW_MB_POWERBI_STI_REPORT", 4, [
        "transfer in", "transfers in", "stock transfer in", "inbound transfer",
        "received transfer", "inter branch in", "sti report",
        "stock transfers in", "transfer received",
    ]),
    ("VW_MB_POWERBI_STO_REPORT", 4, [
        "transfer out", "transfers out", "stock transfer out", "outbound transfer",
        "dispatched transfer", "inter branch out", "sto report", "sent transfer",
        "stock transfers out", "transfer sent", "transfer dispatched",
    ]),
    # ── Detailed Sales Transactions ───────────────────────────────────────
    ("VW_MB_POWERBI_SLSXNS_REPORT", 3, [
        "sales transaction", "transaction detail", "sales return",
        "net sales with return", "sales and return", "gst detail",
        "tax detail", "invoice detail",
    ]),
    ("VW_MB_POWERBI_SLS_REPORT", 3, [
        "item level", "item sales", "salesperson sales", "item-level",
        "detailed sales",
    ]),
    ("VW_MB_POWERBI_APR_REPORT", 2, [
        "app report", "application sales", "appl transaction",
    ]),
    # ── Bill Count / Footfall ─────────────────────────────────────────────
    ("VW_MB_POWERBI_SLS_BILLCOUNT", 4, [
        "bill count", "footfall", "daily bills", "number of bills",
        "transaction count by branch", "how many bills",
    ]),
]

# Build inverted index: keyword → [(view_name, weight)]
_INDEX: Dict[str, List[tuple]] = {}
for _vname, _weight, _kws in _ROUTING:
    for _kw in _kws:
        _INDEX.setdefault(_kw, []).append((_vname, _weight))


def select_relevant_views(query: str, max_views: int = 4) -> List[Dict[str, Any]]:
    """
    Given a natural language query, return the most relevant view schemas
    from the catalog. Always includes the primary sales view for sales queries.

    max_views=4 is the default — more views = richer context but longer prompt.
    """
    q = query.lower()

    # Score views
    scores: Dict[str, float] = {}
    for kw, entries in _INDEX.items():
        if kw in q:
            for vname, weight in entries:
                scores[vname] = scores.get(vname, 0) + weight

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected: List[str] = []

    # Always include primary sales view for sales/analytics queries
    # (unless the query is clearly about non-sales topics)
    _SALES_TERMS = {
        "sale", "revenue", "branch", "category", "department", "trend",
        "kpi", "analytics", "performance", "mtd", "ytd", "qtd",
        "transaction", "bill", "footfall",
    }
    q_words = set(re.findall(r'\w+', q))
    is_sales_query = bool(q_words & _SALES_TERMS)

    if is_sales_query:
        selected.append(_PRIMARY_VIEW)

    for vname, _ in ranked:
        if vname not in selected:
            selected.append(vname)
        if len(selected) >= max_views:
            break

    # Default if nothing matched
    if not selected:
        selected = [_PRIMARY_VIEW, "VwAISalesData"]

    # Retrieve full schema objects from catalog
    catalog = _by_name()
    result = [catalog[n] for n in selected if n in catalog]

    # If after deduplication we're under max, pad with top-scoring unselected views
    if len(result) < min(max_views, 2):
        for vname, _ in ranked:
            if vname not in selected and vname in catalog:
                result.append(catalog[vname])
                if len(result) >= max_views:
                    break

    return result[:max_views]


# ─── Prompt Builder ───────────────────────────────────────────────────────────

_BUSINESS_GLOSSARY = """
## ERP Business Glossary
- **MTD**: Month-to-Date (1st of current month → today)
- **YTD**: Year-to-Date on the INDIAN FINANCIAL YEAR — 1 April of the current
  financial year through today (NOT 1 January). If today is in Jan–Mar, the FY
  started 1 April of the PREVIOUS calendar year. Always prefer @startDate/@endDate,
  which the backend has already resolved to the correct FY window.
- **QTD**: Quarter-to-Date (1st of current quarter → today)
- **SalesNetAmount**: Net sales revenue after discounts on the PRIMARY view
  (VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID) — this is the PRIMARY revenue metric. SUM it for revenue.
- **CashmemoDt**: Bill / transaction date on the primary view — USE THIS for date filtering.
- **CashmemoNo**: Bill / invoice number — COUNT(DISTINCT [CashmemoNo]) for bills / transactions / footfall.
- **SalesQuantity**: Units sold — SUM it for quantity.
- **SalesCost**: Cost of goods sold (for margin = SalesNetAmount − SalesCost).
- **ItemMRP**: Unit MRP (MRP value = SUM(ItemMRP * SalesQuantity), before discounts).
- **BranchAlias**: Short branch name used in all groupings
- **CategoryShortName**: Short category name used in all groupings
- **DepartmentShortName**: Short department name used in all groupings
- **SupplierName / SupplierAlias**: Supplier identity used in supplier groupings
- **DO NOT USE** NetAmount, XnDt, AppQty, BillCount or the VW_MB_POWERBI_APP_REPORT view —
  that legacy view is EMPTY in this database and will return 0 rows.
- **@startDate / @endDate**: Named T-SQL parameters for date range filtering
"""


def build_catalog_schema_prompt(query: str, max_views: int = 4) -> str:
    """
    Build a prompt section containing the relevant view schemas for a query.
    Each selected view shows its description and all column definitions.
    """
    views = select_relevant_views(query, max_views=max_views)
    catalog = _load_catalog()

    lines = [
        f"## Database Schema (zRetailHQ0 — {catalog['object_counts']['views']} views available)",
        "",
        "The following views are most relevant to this query:",
        "",
    ]

    for view in views:
        lines.append(f"### [{view['short_name']}] — {view['title']}")
        lines.append(f"*{view['description']}*")
        lines.append(f"Columns ({view['column_count']} total):")
        for col in view["columns"]:
            lines.append(f"  - `{col['name']}` ({col['type']}) — {col['used_for']}")
        lines.append("")

    lines.append(_BUSINESS_GLOSSARY)
    return "\n".join(lines)


def get_compact_view_index() -> str:
    """
    One-liner per view — used as context for intent extraction so Claude
    knows all available views before choosing which tables to query.
    """
    lines = ["Available database views (short_name | description | key columns):"]
    for obj in _objects():
        key_cols = ", ".join(c["name"] for c in obj["columns"][:6])
        extra = len(obj["columns"]) - 6
        if extra > 0:
            key_cols += f" (+{extra} more)"