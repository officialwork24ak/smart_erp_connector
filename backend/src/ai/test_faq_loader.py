"""
Load curated FAQ templates from repo `test/nlq_faq_sql.py` (same sources as CLI verification).

Requires project layout: `<root>/backend/...` and `<root>/test/nlq_faq_sql.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys
from typing import Any, Callable, Dict, List, Optional

_LOG = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TEST_DIR = _PROJECT_ROOT / "test"

_faq_initialized = False
_try_faq_template: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None
_list_frequent_ai_queries: Optional[Callable[[], List[str]]] = None
_load_error: Optional[str] = None
_faq_source_mtime: float = 0.0


_FALLBACK_FREQUENT: List[str] = [
    "Store Wise MTD Sales, Unique Customer Count, ATS",
    "Department Wise MTD Sales, Unique Customer Count, ATS",
    "Category Wise MTD Sales, Unique Customer Count, ATS",
    "Month-wise Sales Comparison since Apr'24",
    "Last 5 Years Sales Analysis at Department and Category Level",
    "Average Sales at MTD Level",
    "Today's Sales with Unique Customer Count and Unique Invoices Billed",
    "YTD, QTD and MTD Growth vs Last Year",
    "Which Store has the Highest Sales in the Current Month?",
    "Which Department has the Highest Sales in the Current Month?",
    "Which Category has the Highest Sales in the Current Month?",
    "Most Selling Product in the Current Month or Year",
    "Least Selling Product in the Current Month or Year",
    "Which Supplier has the Highest Sales in the Current Month?",
    "Which Supplier has the Lowest Sales in the Current Month?",
    "Top 10 Performing Stores based on Growth %",
    "Bottom 10 Performing Stores based on Sales Decline",
    "Which Products are Growing Fastest Month-over-Month?",
    "Which Categories are Showing Negative Growth Trends?",
    "Predict Next Month Sales using AI Forecasting",
    "Expected Stock Requirement for Next 30 Days",
    "Potential Stock-Out Products Prediction",
    "Slow-Moving Inventory Identification",
    "Fast-Moving Inventory Identification",
    "Customer Repeat Purchase Analysis",
    "Peak Sales Hours / Peak Billing Time Analysis",
    "Festival vs Non-Festival Sales Comparison",
    "Region Wise Sales Performance Comparison",
    "Supplier Contribution % in Overall Sales",
    "Average Basket Size by Store",
    "Average Invoice Value Trend Analysis",
    "Discount Impact on Sales Performance",
    "Store Ranking based on Sales, ATS, and Customer Count",
    "Product Recommendation based on Customer Buying Pattern",
    "AI-based Demand Forecasting by Store and Category",
    "Daily Sales Target vs Achievement Tracking",
    "Weather/Festival Impact on Sales Trend",
    "High Return / Low Conversion Product Identification",
    "AI-based Alerts for Sudden Sales Drop or Spike",
    "Top Customers based on Purchase Value",
    "New vs Repeat Customer Analysis",
    "Category Contribution % in Total Revenue",
    "Gross Margin Analysis by Department/Category",
    "Inventory Aging Analysis",
    "Dead Stock Identification",
    "Sales Trend Prediction for Upcoming Festivals/Seasons",
    "AI-generated Business Insights and Recommendations",
]


def _faq_sources_mtime() -> float:
    """Max mtime of FAQ Python sources — reload when templates change on disk."""
    mtimes: list[float] = []
    for name in ("nlq_faq_sql.py", "nlq_faq_kpi.py"):
        p = _TEST_DIR / name
        if p.exists():
            mtimes.append(p.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0


def _ensure_loaded() -> None:
    global _faq_initialized, _try_faq_template, _list_frequent_ai_queries, _load_error
    global _faq_source_mtime

    source_mtime = _faq_sources_mtime()
    if _faq_initialized and source_mtime <= _faq_source_mtime:
        return

    _faq_initialized = True
    _faq_source_mtime = source_mtime
    td = str(_TEST_DIR)
    if not (_TEST_DIR / "nlq_faq_sql.py").exists():
        _load_error = f"FAQ module path missing: {_TEST_DIR / 'nlq_faq_sql.py'}"
        _LOG.warning("verified FAQ loader: %s", _load_error)
        return

    if td not in sys.path:
        sys.path.insert(0, td)

    for mod in ("nlq_faq_kpi", "nlq_faq_sql"):
        sys.modules.pop(mod, None)

    try:
        import nlq_faq_sql as nfs

        _try_faq_template = nfs.try_faq_template
        _list_frequent_ai_queries = nfs.list_frequent_ai_queries
        _load_error = None
    except Exception as exc:
        _load_error = str(exc)
        _LOG.warning("verified FAQ import failed", exc_info=True)


def try_verified_faq(question: str) -> Optional[Dict[str, Any]]:
    """Returns FAQ dict from test templates if patterns match."""
    _ensure_loaded()
    if _try_faq_template is None:
        return None
    try:
        return _try_faq_template(question)
    except Exception as exc:
        _LOG.warning("try_faq_template failed: %s", exc)
        return None


def list_verified_top_queries(limit: int = 50) -> List[str]:
    """Phrases wired to FREQUENT_AI_QUERIES in nlq_faq_kpi (via nlq_faq_sql)."""
    _ensure_loaded()
    if _list_frequent_ai_queries is None:
        return _FALLBACK_FREQUENT[:limit]
    try:
        qs = list(_list_frequent_ai_queries())
    except Exception as exc:
        _LOG.warning("list_frequent_ai_queries failed: %s", exc)
        return _FALLBACK_FREQUENT[:limit]
    if not qs:
        return _FALLBACK_FREQUENT[:limit]
    return qs[:limit]


def loader_status() -> Dict[str, Any]:
    _ensure_loaded()
    return {
        "faq_engine_ready": _try_faq_template is not None,
        "source_dir": str(_TEST_DIR),
        "load_error": _load_error,
    }
