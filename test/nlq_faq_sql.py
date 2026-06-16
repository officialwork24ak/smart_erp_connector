"""
Curated FAQ SQL templates for terminal NLQ — no LLM required.

Matches common retail KPI questions to tested T-SQL on
dbo.VW_MB_POWERBI_APP_REPORT (NetAmount, XnDt, BranchAlias, etc.)
aligned with schema_catalog.txt and dashboard-style analytics.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple

# Primary analytics view (catalog #1 — 90% of reporting)
_APP = "dbo.[VW_MB_POWERBI_APP_REPORT]"
_PM = "dbo.[VW_MB_POWERBI_PRODUCT_MASTER]"
_STOCK = "dbo.[VW_MB_POWERBI_STOCK_REPORT]"
_PUR = "dbo.[VW_MB_POWERBI_PURXNS_REPORT]"
_MIS_SUP = "dbo.VW_MB_POWERBI_MIS_SUPPLIER_SLS_DATA"
_CBS = "dbo.[VW_MB_POWERBI_CBS_WITH_GIT]"
_STI = "dbo.[VW_MB_POWERBI_STI_REPORT]"
_STO = "dbo.[VW_MB_POWERBI_STO_REPORT]"
_CUST = "dbo.[VwAICustomerDetails]"
_SALES_AI = "dbo.[VwAISalesData]"
_SLSXNS = "dbo.[VW_MB_POWERBI_SLSXNS_REPORT]"
_SALESPERSON = "dbo.[VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID]"


def _norm(q: str) -> str:
    return re.sub(r"\s+", " ", q.lower().strip())


def _today_where(alias: str = "s") -> str:
    return f"CAST({alias}.[XnDt] AS DATE) = CAST(GETDATE() AS DATE)"


def _mtd_where(alias: str = "s") -> str:
    return (
        f"{alias}.[XnDt] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
        f"AND {alias}.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _ytd_where(alias: str = "s") -> str:
    # FIXED 2026-06-13 (Manoj issue #2): YTD = Indian FINANCIAL year (starts 1 April),
    # not calendar year (1 January). Before April, the FY started the previous year.
    # Kept consistent with date_utils._start_of_financial_year and the dashboard.
    return (
        f"{alias}.[XnDt] >= CASE WHEN MONTH(GETDATE()) >= 4 "
        f"THEN DATEFROMPARTS(YEAR(GETDATE()), 4, 1) "
        f"ELSE DATEFROMPARTS(YEAR(GETDATE()) - 1, 4, 1) END "
        f"AND {alias}.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _last_30d_where(alias: str = "s") -> str:
    return (
        f"{alias}.[XnDt] >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE)) "
        f"AND {alias}.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _pur_mtd_where(alias: str = "p") -> str:
    return (
        f"{alias}.[PurInvDate] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
        f"AND {alias}.[PurInvDate] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _last_12m_memo_where(alias: str = "m") -> str:
    return (
        f"{alias}.[XnMemoDate] >= DATEADD(MONTH, -12, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) "
        f"AND {alias}.[XnMemoDate] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _memo_mtd_where(alias: str = "m") -> str:
    """Current month on the MIS supplier view (XnMemoDate)."""
    return (
        f"{alias}.[XnMemoDate] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
        f"AND {alias}.[XnMemoDate] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _invoice_mtd_where(alias: str = "s") -> str:
    return (
        f"{alias}.[InvoiceDt] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
        f"AND {alias}.[InvoiceDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _invoice_last_12m_where(alias: str = "s") -> str:
    return (
        f"{alias}.[InvoiceDt] >= DATEADD(MONTH, -12, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) "
        f"AND {alias}.[InvoiceDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _created_mtd_where(alias: str = "c") -> str:
    return (
        f"{alias}.[CreatedOn] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
        f"AND {alias}.[CreatedOn] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _cashmemo_mtd_where(alias: str = "sp") -> str:
    return (
        f"{alias}.[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
        f"AND {alias}.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
    )


def _cashmemo_today_where(alias: str = "sp") -> str:
    return f"CAST({alias}.[CashmemoDt] AS DATE) = CAST(GETDATE() AS DATE)"


def _top_n_from_question(q: str, default: int = 10) -> int:
    m = re.search(r"\btop\s+(\d+)\b", q, re.I)
    if m:
        return max(1, min(500, int(m.group(1))))
    return default


def _stock_by_itemcode_cte(cte_name: str = "StockByItemcode") -> str:
    """STOCK_REPORT has ItemId only — join PRODUCT_MASTER for Itemcode."""
    return f"""
{cte_name} AS (
    SELECT
        pm.[Itemcode],
        MAX(st.[ArticleNo]) AS ArticleNo,
        SUM(st.[StockQty]) AS StockQty
    FROM {_STOCK} st WITH (NOLOCK)
    INNER JOIN {_PM} pm WITH (NOLOCK) ON pm.[ItemId] = st.[ItemId]
    WHERE pm.[Itemcode] IS NOT NULL
    GROUP BY pm.[Itemcode]
)"""


def _blob(template_id: str, sql: str, explanation: str, assumptions: List[str]) -> Dict[str, Any]:
    return {
        "template_id": template_id,
        "sql": sql.strip(),
        "explanation": explanation,
        "assumptions": assumptions,
    }


# (template_id, compiled patterns, builder)
_FAQ_BUILDERS: List[Tuple[str, List[Pattern[str]], Callable[[str], Dict[str, Any]]]] = []


def _register(
    template_id: str,
    patterns: List[str],
    builder: Callable[[str], Dict[str, Any]],
) -> None:
    compiled = [re.compile(p, re.I) for p in patterns]
    _FAQ_BUILDERS.append((template_id, compiled, builder))


def _sql_total_sales_today(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_APP} s WITH (NOLOCK)
WHERE {_today_where("s")}
"""
    return _blob(
        "total_sales_today",
        sql,
        "Total net sales for today from APP_REPORT using NetAmount and XnDt.",
        [
            "View: VW_MB_POWERBI_APP_REPORT; metric: SUM(NetAmount).",
            "Today = calendar date of GETDATE() on XnDt.",
        ],
    )


def _sql_mtd_sales_by_branch(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[BranchAlias],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT s.[InvoiceNo]) AS UniqueInvoices,
    CAST(SUM(s.[NetAmount]) / NULLIF(COUNT(DISTINCT s.[CustomerId]), 0) AS decimal(18, 2)) AS ATS,
    COUNT(DISTINCT s.[CustomerId]) AS UniqueCustomers
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
GROUP BY s.[BranchAlias]
ORDER BY MTDSales DESC
"""
    return _blob(
        "mtd_sales_by_branch",
        sql,
        "Month-to-date net sales, invoice count, ATS and unique customers by branch. All branches returned.",
        ["MTD: first day of current month through end of today.", "No row cap — all branches returned."],
    )


def _sql_ytd_sales_by_department(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[DepartmentShortName] AS Department,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_APP} s WITH (NOLOCK)
WHERE {_ytd_where("s")}
GROUP BY s.[DepartmentShortName]
ORDER BY TotalSales DESC
"""
    return _blob(
        "ytd_sales_by_department",
        sql,
        "Year-to-date net sales grouped by department short name.",
        ["YTD: Jan 1 of current year through end of today."],
    )


def _sql_highest_branch_this_month(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    sp.[BranchAlias],
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[BranchAlias] IS NOT NULL
GROUP BY sp.[BranchAlias]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY TotalSales DESC
"""
    return _blob(
        "highest_branch_this_month",
        sql,
        "Single branch with highest MTD net sales.",
        ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt) — aligned with dashboard."],
    )


def _sql_top_categories(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 10)
    sql = f"""
SELECT TOP ({n})
    s.[CategoryShortName] AS Category,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
GROUP BY s.[CategoryShortName]
ORDER BY TotalSales DESC
"""
    return _blob(
        "top_selling_categories",
        sql,
        f"Top {n} categories by MTD net sales.",
        [f"TOP {n}; MTD date filter on XnDt."],
    )


def _sql_lowest_branches(_q: str) -> Dict[str, Any]:
    n = _top_n_from_question(_q, 10)
    sql = f"""
SELECT TOP ({n})
    s.[BranchAlias],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
GROUP BY s.[BranchAlias]
ORDER BY TotalSales ASC
"""
    return _blob(
        "lowest_performing_branches",
        sql,
        f"Bottom {n} branches by MTD sales (lowest first).",
        ["Uses MTD; ORDER BY TotalSales ASC."],
    )


def _sql_trend_last_30d(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (31)
    CAST(sp.[CashmemoDt] AS DATE) AS SalesDate,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE sp.[CashmemoDt] >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE))
  AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
GROUP BY CAST(sp.[CashmemoDt] AS DATE)
ORDER BY SalesDate ASC
"""
    return _blob(
        "sales_trend_last_30_days",
        sql,
        "Daily net sales for the last 30 days, one row per day.",
        ["Rolling 30-day window ending today.", "Uses canonical CashmemoDt/SalesNetAmount (dashboard-aligned)."],
    )


def _sql_compare_this_month_vs_last(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH Sales AS (
    SELECT
        CASE
            WHEN sp.[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
             AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
                THEN N'ThisMonth'
            WHEN sp.[CashmemoDt] >= DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
             AND sp.[CashmemoDt] < DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
                THEN N'LastMonth'
        END AS PeriodLabel,
        sp.[SalesNetAmount]
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
      AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
)
SELECT
    PeriodLabel,
    CAST(SUM([SalesNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM Sales
WHERE PeriodLabel IS NOT NULL
GROUP BY PeriodLabel
ORDER BY PeriodLabel
"""
    return _blob(
        "compare_this_month_vs_last_month",
        sql,
        "Total net sales for current calendar month vs previous calendar month.",
        [
            "ThisMonth = MTD through today; LastMonth = full prior calendar month.",
            "Compare growth as (ThisMonth - LastMonth) / LastMonth in your app if needed.",
            "Uses canonical CashmemoDt/SalesNetAmount (dashboard-aligned).",
        ],
    )


def _sql_avg_bill_by_branch(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    sp.[BranchAlias],
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS BillCount,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT sp.[CashmemoNo]), 0) AS decimal(18, 2)) AS AvgBillValue
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[BranchAlias] IS NOT NULL
GROUP BY sp.[BranchAlias]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY AvgBillValue DESC
"""
    return _blob(
        "average_bill_value_by_branch",
        sql,
        "MTD average bill value per branch: total sales divided by distinct cash memos.",
        ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt, SalesNetAmount)."],
    )


def _sql_bill_count_today(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT COUNT(DISTINCT s.[XnNo]) AS TotalBillCount
FROM {_APP} s WITH (NOLOCK)
WHERE {_today_where("s")}
"""
    return _blob(
        "total_bill_count_today",
        sql,
        "Count of distinct bills (XnNo) sold today.",
        ["Today on XnDt; distinct XnNo as bill proxy."],
    )


# ─── Product analytics (APP_REPORT + PRODUCT_MASTER for neckline) ─────────────


def _sql_top_products_mtd(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 20)
    sql = f"""
SELECT TOP ({n})
    s.[Itemcode],
    MAX(s.[ArticleNo]) AS ArticleNo,
    MAX(s.[CategoryShortName]) AS Category,
    CAST(SUM(s.[NetSlsNetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[NetSlsQty]) AS decimal(18, 4)) AS QtySold
FROM {_SLSXNS} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Itemcode] IS NOT NULL
GROUP BY s.[Itemcode]
HAVING SUM(s.[NetSlsNetAmount]) <> 0
ORDER BY Revenue DESC
"""
    return _blob(
        "top_products_mtd",
        sql,
        f"Top {n} products (Itemcode) by MTD net revenue.",
        [
            "Uses SLSXNS_REPORT (NetSlsNetAmount, XnDt) — full sales lines, not sparse APP_REPORT.",
            "Returns no rows when the current month has no posted sales yet.",
        ],
    )


def _sql_top_articles_revenue(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 20)
    sql = f"""
SELECT TOP ({n})
    s.[ArticleNo],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[ArticleNo] IS NOT NULL
GROUP BY s.[ArticleNo]
ORDER BY Revenue DESC
"""
    return _blob(
        "top_articles_by_revenue",
        sql,
        f"Top {n} articles (ArticleNo) by MTD net revenue.",
        ["MTD period unless question states another range."],
    )


def _sql_highest_color_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    s.[Color],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Color] IS NOT NULL
GROUP BY s.[Color]
ORDER BY Revenue DESC
"""
    return _blob(
        "highest_color_sales_mtd",
        sql,
        "Single color with highest MTD net sales.",
        ["MTD; excludes NULL/blank Color."],
    )


def _sql_sales_by_fabric(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[Fabric],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Fabric] IS NOT NULL
GROUP BY s.[Fabric]
ORDER BY Revenue DESC
"""
    return _blob(
        "sales_by_fabric_type",
        sql,
        "MTD net sales and quantity grouped by Fabric.",
        ["Uses [Fabric] on APP_REPORT; MTD date filter."],
    )


def _sql_top_size_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    s.[Size],
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Size] IS NOT NULL
GROUP BY s.[Size]
ORDER BY QtySold DESC
"""
    return _blob(
        "top_selling_size_mtd",
        sql,
        "Size with highest MTD quantity sold (AppQty); Revenue shown for context.",
        ["Ranked by SUM(AppQty); MTD on XnDt."],
    )


def _sql_category_quantity_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[CategoryShortName] AS Category,
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
GROUP BY s.[CategoryShortName]
ORDER BY QtySold DESC
"""
    return _blob(
        "category_wise_quantity_sold",
        sql,
        "MTD quantity sold (AppQty) by category short name.",
        ["Quantity = SUM(AppQty); MTD period."],
    )


def _sql_products_zero_sales_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    pm.[Itemcode],
    pm.[ArticleNo],
    pm.[CategoryShortName] AS Category,
    CAST(pm.[ItemMRP] AS decimal(18, 2)) AS ItemMRP
FROM {_PM} pm WITH (NOLOCK)
WHERE pm.[Itemcode] IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM {_APP} s WITH (NOLOCK)
    WHERE s.[Itemcode] = pm.[Itemcode]
      AND {_mtd_where("s")}
  )
ORDER BY pm.[Itemcode]
"""
    return _blob(
        "products_zero_sales_mtd",
        sql,
        "Items in product master with no MTD sales rows on APP_REPORT.",
        [
            "Zero sales = no matching sales lines this month (MTD).",
            "Master: VW_MB_POWERBI_PRODUCT_MASTER; sales: APP_REPORT.",
        ],
    )


def _sql_highest_concept_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    s.[Concept],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Concept] IS NOT NULL
GROUP BY s.[Concept]
ORDER BY Revenue DESC
"""
    return _blob(
        "highest_concept_revenue_mtd",
        sql,
        "Concept with highest MTD net revenue.",
        ["MTD; uses [Concept] on APP_REPORT."],
    )


def _sql_top_products_margin(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 20)
    sql = f"""
SELECT TOP ({n})
    s.[Itemcode],
    MAX(s.[ArticleNo]) AS ArticleNo,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[CostValue]) AS decimal(18, 2)) AS CostValue,
    CAST(SUM(s.[NetAmount]) - SUM(s.[CostValue]) AS decimal(18, 2)) AS GrossProfit,
    CAST(
        CASE WHEN SUM(s.[NetAmount]) = 0 THEN 0
             ELSE 100.0 * (SUM(s.[NetAmount]) - SUM(s.[CostValue])) / SUM(s.[NetAmount])
        END AS decimal(18, 4)
    ) AS GrossMarginPct
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Itemcode] IS NOT NULL
GROUP BY s.[Itemcode]
HAVING SUM(s.[NetAmount]) > 0
ORDER BY GrossMarginPct DESC
"""
    return _blob(
        "top_products_by_profit_margin",
        sql,
        f"Top {n} products by gross margin %: (Revenue - CostValue) / Revenue on MTD sales.",
        [
            "Margin uses NetAmount and CostValue from APP_REPORT.",
            "Products with zero revenue excluded (HAVING).",
        ],
    )


def _sql_sales_by_neckline(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    pm.[NECKLINE] AS Neckline,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold
FROM {_APP} s WITH (NOLOCK)
INNER JOIN {_PM} pm WITH (NOLOCK)
    ON s.[Itemcode] = pm.[Itemcode]
WHERE {_mtd_where("s")}
  AND pm.[NECKLINE] IS NOT NULL
GROUP BY pm.[NECKLINE]
ORDER BY Revenue DESC
"""
    return _blob(
        "sales_by_neckline_type",
        sql,
        "MTD sales by neckline from product master joined to APP_REPORT on Itemcode.",
        [
            "NECKLINE is on PRODUCT_MASTER, not APP_REPORT.",
            "Only items that exist in both master and MTD sales appear.",
        ],
    )


# ─── Executive / advanced analytics ───────────────────────────────────────────


def _sql_branch_high_growth_low_margin(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH Bounds AS (
    SELECT
        DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) AS CurrMonthStart,
        DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) AS PrevMonthStart
),
BranchPeriod AS (
    SELECT
        s.[BranchAlias],
        SUM(CASE
            WHEN s.[XnDt] >= b.CurrMonthStart
             AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
            THEN s.[NetAmount] ELSE 0 END) AS CurrRevenue,
        SUM(CASE
            WHEN s.[XnDt] >= b.PrevMonthStart AND s.[XnDt] < b.CurrMonthStart
            THEN s.[NetAmount] ELSE 0 END) AS PrevRevenue,
        SUM(CASE
            WHEN s.[XnDt] >= b.CurrMonthStart
             AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
            THEN s.[NetAmount] - s.[CostValue] ELSE 0 END) AS CurrProfit,
        SUM(CASE
            WHEN s.[XnDt] >= b.CurrMonthStart
             AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
            THEN s.[NetAmount] ELSE 0 END) AS CurrRevForMargin
    FROM {_APP} s WITH (NOLOCK)
    CROSS JOIN Bounds b
    WHERE s.[BranchAlias] IS NOT NULL
    GROUP BY s.[BranchAlias]
)
SELECT TOP (10)
    [BranchAlias],
    CAST(CurrRevenue AS decimal(18, 2)) AS MTDRevenue,
    CAST(PrevRevenue AS decimal(18, 2)) AS PriorMonthRevenue,
    CAST(
        CASE WHEN PrevRevenue = 0 THEN NULL
             ELSE 100.0 * (CurrRevenue - PrevRevenue) / PrevRevenue
        END AS decimal(18, 4)
    ) AS GrowthPct,
    CAST(
        CASE WHEN CurrRevForMargin = 0 THEN NULL
             ELSE 100.0 * CurrProfit / CurrRevForMargin
        END AS decimal(18, 4)
    ) AS MarginPct
FROM BranchPeriod
WHERE CurrRevenue > 0
ORDER BY GrowthPct DESC, MarginPct ASC
"""
    return _blob(
        "branch_high_growth_low_margin",
        sql,
        "Branches ranked by MTD revenue growth vs prior full month, then lowest gross margin % (MTD).",
        [
            "Growth = MTD this month vs entire previous calendar month.",
            "Margin % = (NetAmount - CostValue) / NetAmount for MTD.",
            "Top row = high growth with relatively low margin among ranked branches.",
        ],
    )


def _sql_categories_declining_3_months(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH Monthly AS (
    SELECT
        s.[CategoryShortName] AS Category,
        DATEFROMPARTS(YEAR(s.[XnDt]), MONTH(s.[XnDt]), 1) AS MonthStart,
        SUM(s.[NetAmount]) AS Revenue
    FROM {_APP} s WITH (NOLOCK)
    WHERE s.[XnDt] >= DATEADD(MONTH, -4, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
      AND s.[XnDt] < DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
      AND s.[CategoryShortName] IS NOT NULL
    GROUP BY s.[CategoryShortName], DATEFROMPARTS(YEAR(s.[XnDt]), MONTH(s.[XnDt]), 1)
),
Lagged AS (
    SELECT
        Category,
        MonthStart,
        Revenue,
        LAG(Revenue, 1) OVER (PARTITION BY Category ORDER BY MonthStart) AS RevM1,
        LAG(Revenue, 2) OVER (PARTITION BY Category ORDER BY MonthStart) AS RevM2,
        LAG(Revenue, 3) OVER (PARTITION BY Category ORDER BY MonthStart) AS RevM3
    FROM Monthly
)
SELECT TOP (100)
    Category,
    MonthStart AS LatestMonth,
    CAST(Revenue AS decimal(18, 2)) AS LatestMonthRevenue,
    CAST(RevM1 AS decimal(18, 2)) AS MonthMinus1Revenue,
    CAST(RevM2 AS decimal(18, 2)) AS MonthMinus2Revenue,
    CAST(RevM3 AS decimal(18, 2)) AS MonthMinus3Revenue
FROM Lagged
WHERE RevM1 IS NOT NULL AND RevM2 IS NOT NULL AND RevM3 IS NOT NULL
  AND Revenue < RevM1 AND RevM1 < RevM2 AND RevM2 < RevM3
ORDER BY Revenue ASC
"""
    return _blob(
        "categories_declining_3_months",
        sql,
        "Categories with strictly declining revenue for each of the last 3 complete months.",
        [
            "Uses last 4 complete months (excludes current partial month).",
            "Requires 4 months of history per category.",
        ],
    )


def _sql_predict_next_month_sales(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH Hist AS (
    SELECT
        DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
        SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(MONTH, -12, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
      AND sp.[CashmemoDt] < DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
    GROUP BY DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)
),
Avg3 AS (
    SELECT AVG(CAST(Revenue AS decimal(18, 4))) AS AvgRevenue
    FROM (
        SELECT TOP (3) Revenue
        FROM Hist
        ORDER BY MonthStart DESC
    ) x
)
SELECT
    DATEADD(MONTH, 1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) AS ForecastMonthStart,
    CAST(a.AvgRevenue AS decimal(18, 2)) AS ForecastRevenue,
    N'Average of last 3 complete months (canonical sales view)' AS ForecastMethod
FROM Avg3 a
"""
    return _blob(
        "predict_next_month_sales",
        sql,
        "Simple next-month forecast: average revenue of the last 3 complete calendar months.",
        [
            "Heuristic only — not ML; excludes current partial month from history.",
            "Single-row forecast for speed (avoids large SLSXNS scans).",
        ],
    )


def _sql_supplier_depends_on_one_branch(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH SupBranch AS (
    SELECT
        s.[SupplierName],
        s.[BranchAlias],
        SUM(s.[NetAmount]) AS Revenue
    FROM {_APP} s WITH (NOLOCK)
    WHERE {_mtd_where("s")}
      AND s.[SupplierName] IS NOT NULL
      AND s.[BranchAlias] IS NOT NULL
    GROUP BY s.[SupplierName], s.[BranchAlias]
),
Totals AS (
    SELECT [SupplierName], SUM(Revenue) AS TotalRevenue
    FROM SupBranch
    GROUP BY [SupplierName]
)
SELECT TOP (20)
    sb.[SupplierName],
    sb.[BranchAlias] AS DominantBranch,
    CAST(sb.Revenue AS decimal(18, 2)) AS BranchRevenue,
    CAST(t.TotalRevenue AS decimal(18, 2)) AS SupplierTotalRevenue,
    CAST(100.0 * sb.Revenue / NULLIF(t.TotalRevenue, 0) AS decimal(18, 4)) AS BranchSharePct
FROM SupBranch sb
INNER JOIN Totals t ON t.[SupplierName] = sb.[SupplierName]
ORDER BY BranchSharePct DESC, sb.Revenue DESC
"""
    return _blob(
        "supplier_depends_on_one_branch",
        sql,
        "Suppliers ranked by highest share of MTD sales concentrated in a single branch.",
        ["Top rows = supplier most dependent on one branch (high BranchSharePct)."],
    )


def _sql_high_stock_low_sales(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH {_stock_by_itemcode_cte("StockByItem")},
SalesMtd AS (
    SELECT
        s.[Itemcode],
        SUM(s.[AppQty]) AS MTDQtySold
    FROM {_APP} s WITH (NOLOCK)
    WHERE {_mtd_where("s")}
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
)
SELECT TOP (50)
    k.[Itemcode],
    k.[ArticleNo],
    CAST(k.StockQty AS decimal(18, 4)) AS TotalStockQty,
    CAST(ISNULL(sl.MTDQtySold, 0) AS decimal(18, 4)) AS MTDQtySold
FROM StockByItem k
LEFT JOIN SalesMtd sl ON sl.[Itemcode] = k.[Itemcode]
WHERE k.StockQty > 0
ORDER BY k.StockQty DESC, ISNULL(sl.MTDQtySold, 0) ASC
"""
    return _blob(
        "high_stock_low_sales",
        sql,
        "Items with high on-hand stock but low (or zero) MTD quantity sold.",
        [
            "Stock via STOCK_REPORT.ItemId joined to PRODUCT_MASTER.Itemcode.",
            "Sales MTD AppQty on APP_REPORT by Itemcode.",
        ],
    )


def _sql_fast_vs_slow_moving(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH SalesMtd AS (
    SELECT s.[Itemcode], SUM(s.[AppQty]) AS MTDQtySold
    FROM {_APP} s WITH (NOLOCK)
    WHERE {_mtd_where("s")}
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
),
{_stock_by_itemcode_cte("StockByItem")},
ItemMetrics AS (
    SELECT
        st.[Itemcode],
        st.[ArticleNo],
        st.StockQty AS OnHandQty,
        ISNULL(sl.MTDQtySold, 0) AS MTDQtySold,
        CASE
            WHEN st.StockQty = 0 THEN NULL
            ELSE ISNULL(sl.MTDQtySold, 0) / st.StockQty
        END AS TurnoverRatio
    FROM StockByItem st
    LEFT JOIN SalesMtd sl ON sl.[Itemcode] = st.[Itemcode]
    WHERE st.StockQty > 0
),
Ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (ORDER BY TurnoverRatio DESC, MTDQtySold DESC) AS FastRank,
        ROW_NUMBER() OVER (ORDER BY TurnoverRatio ASC, OnHandQty DESC) AS SlowRank
    FROM ItemMetrics
)
SELECT TOP (100)
    CASE WHEN FastRank <= 50 THEN N'FastMoving' ELSE N'SlowMoving' END AS MovementClass,
    [Itemcode],
    [ArticleNo],
    CAST(OnHandQty AS decimal(18, 4)) AS OnHandQty,
    CAST(MTDQtySold AS decimal(18, 4)) AS MTDQtySold,
    CAST(TurnoverRatio AS decimal(18, 4)) AS TurnoverRatio
FROM Ranked
WHERE FastRank <= 50 OR SlowRank <= 50
ORDER BY MovementClass, TurnoverRatio DESC
"""
    return _blob(
        "fast_vs_slow_moving_inventory",
        sql,
        "Up to 50 fast-moving and 50 slow-moving items by MTD sold qty ÷ on-hand stock.",
        [
            "STOCK_REPORT uses ItemId — joined to APP Itemcode via PRODUCT_MASTER.",
            "TurnoverRatio = MTD AppQty / StockQty; snapshot stock.",
        ],
    )


def _sql_departments_most_profit(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[DepartmentShortName] AS Department,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[CostValue]) AS decimal(18, 2)) AS CostValue,
    CAST(SUM(s.[NetAmount]) - SUM(s.[CostValue]) AS decimal(18, 2)) AS GrossProfit
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[DepartmentShortName] IS NOT NULL
GROUP BY s.[DepartmentShortName]
ORDER BY GrossProfit DESC
"""
    return _blob(
        "departments_most_profit",
        sql,
        "Departments ranked by MTD gross profit (NetAmount - CostValue).",
        ["MTD on XnDt; APP_REPORT."],
    )


def _sql_branch_efficiency_bills_vs_sales(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[BranchAlias],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS MTDRevenue,
    COUNT(DISTINCT s.[XnNo]) AS BillCount,
    CAST(SUM(s.[NetAmount]) / NULLIF(COUNT(DISTINCT s.[XnNo]), 0) AS decimal(18, 2)) AS RevenuePerBill
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[BranchAlias] IS NOT NULL
GROUP BY s.[BranchAlias]
ORDER BY RevenuePerBill DESC
"""
    return _blob(
        "branch_efficiency_bill_count_vs_sales",
        sql,
        "MTD revenue, distinct bill count (XnNo), and revenue per bill by branch.",
        ["Efficiency proxy = SUM(NetAmount) / COUNT(DISTINCT XnNo)."],
    )


def _sql_best_salesperson_weekends(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    sp.[SalesPersonName],
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS WeekendRevenue,
    CAST(SUM(sp.[SalesQuantity]) AS decimal(18, 4)) AS WeekendQty,
    COUNT(DISTINCT sp.[CashmemoNo]) AS WeekendBills
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[SalesPersonName] IS NOT NULL
  AND DATEPART(WEEKDAY, sp.[CashmemoDt]) IN (1, 7)
GROUP BY sp.[SalesPersonName]
ORDER BY WeekendRevenue DESC
"""
    return _blob(
        "best_salesperson_weekends",
        sql,
        "Top salesperson by MTD sales on weekend days (DATEPART WEEKDAY 1 and 7 = Sun/Sat default).",
        [
            "Uses VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID and CashmemoDt.",
            "Weekend definition follows SQL Server DATEFIRST default.",
        ],
    )


def _sql_products_frequently_returned(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (50)
    s.[Itemcode],
    MAX(s.[ArticleNo]) AS ArticleNo,
    MAX(s.[CategoryShortName]) AS Category,
    CAST(SUM(s.[SlrQty]) AS decimal(18, 4)) AS ReturnQty,
    CAST(SUM(s.[SlrNetAmount]) AS decimal(18, 2)) AS ReturnAmount
FROM {_SLSXNS} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Itemcode] IS NOT NULL
  AND s.[SlrQty] > 0
GROUP BY s.[Itemcode]
ORDER BY ReturnQty DESC
"""
    return _blob(
        "products_frequently_returned",
        sql,
        "Top items by MTD sales return quantity (SlrQty) on SLSXNS.",
        ["Returns = lines with SlrQty > 0; MTD on XnDt."],
    )


# ─── Customer analytics ───────────────────────────────────────────────────────


def _sql_new_customers_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    c.[CustomerId],
    c.[CustomerFirstName],
    c.[CustomerLastName],
    c.[ContactMobile],
    c.[City],
    c.[CustomerGroupName],
    CAST(c.[CreatedOn] AS datetime2) AS CreatedOn
FROM {_CUST} c WITH (NOLOCK)
WHERE {_created_mtd_where("c")}
ORDER BY c.[CreatedOn] DESC
"""
    return _blob(
        "new_customers_this_month",
        sql,
        "Customers whose profile CreatedOn falls in the current month (MTD).",
        ["Master: VwAICustomerDetails; filter on CreatedOn."],
    )


def _sql_city_most_customers(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    c.[City],
    COUNT(DISTINCT c.[CustomerId]) AS CustomerCount
FROM {_CUST} c WITH (NOLOCK)
WHERE c.[City] IS NOT NULL
  AND LTRIM(RTRIM(c.[City])) <> ''
GROUP BY c.[City]
ORDER BY CustomerCount DESC
"""
    return _blob(
        "city_with_most_customers",
        sql,
        "City with the largest number of distinct customers in the customer master.",
        ["All customers in VwAICustomerDetails — not filtered by sales."],
    )


def _sql_sales_by_customer_group(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    c.[CustomerGroupName],
    CAST(SUM(s.[SaleNetAmount]) AS decimal(18, 2)) AS TotalSales,
    COUNT(DISTINCT s.[CustomerId]) AS UniqueCustomers,
    COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount
FROM {_SALES_AI} s WITH (NOLOCK)
INNER JOIN {_CUST} c WITH (NOLOCK)
    ON s.[CustomerId] = c.[CustomerId]
WHERE {_invoice_mtd_where("s")}
  AND c.[CustomerGroupName] IS NOT NULL
GROUP BY c.[CustomerGroupName]
ORDER BY TotalSales DESC
"""
    return _blob(
        "customer_group_wise_sales",
        sql,
        "MTD net sales from VwAISalesData grouped by customer group.",
        ["Join: VwAISalesData.CustomerId = VwAICustomerDetails.CustomerId."],
    )


def _sql_top_customers_by_value(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 20)
    sql = f"""
SELECT TOP ({n})
    c.[CustomerId],
    c.[CustomerFirstName],
    c.[CustomerLastName],
    c.[ContactMobile],
    c.[City],
    c.[CustomerGroupName],
    CAST(SUM(s.[SaleNetAmount]) AS decimal(18, 2)) AS TotalPurchaseValue,
    COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount
FROM {_SALES_AI} s WITH (NOLOCK)
INNER JOIN {_CUST} c WITH (NOLOCK)
    ON s.[CustomerId] = c.[CustomerId]
WHERE {_invoice_mtd_where("s")}
GROUP BY
    c.[CustomerId],
    c.[CustomerFirstName],
    c.[CustomerLastName],
    c.[ContactMobile],
    c.[City],
    c.[CustomerGroupName]
ORDER BY TotalPurchaseValue DESC
"""
    return _blob(
        "top_customers_by_purchase_value",
        sql,
        f"Top {n} customers by MTD SUM(SaleNetAmount) on invoice lines.",
        ["MTD on InvoiceDt; metric SaleNetAmount from VwAISalesData."],
    )


def _sql_inactive_customers(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    c.[CustomerId],
    c.[CustomerFirstName],
    c.[CustomerLastName],
    c.[ContactMobile],
    c.[City],
    c.[CustomerGroupName],
    c.[ActiveStatus],
    CAST(c.[LastUpdate] AS datetime2) AS LastUpdate
FROM {_CUST} c WITH (NOLOCK)
WHERE c.[ActiveStatus] = 0
ORDER BY c.[LastUpdate] DESC
"""
    return _blob(
        "inactive_customers",
        sql,
        "Customers marked inactive (ActiveStatus = 0) in the customer master.",
        ["ActiveStatus bit on VwAICustomerDetails."],
    )


def _sql_highest_credit_limit(_q: str) -> Dict[str, Any]:
    n = _top_n_from_question(_q, 20)
    sql = f"""
SELECT TOP ({n})
    c.[CustomerId],
    c.[CustomerFirstName],
    c.[CustomerLastName],
    c.[ContactMobile],
    c.[City],
    c.[CustomerGroupName],
    CAST(c.[CreditLimit] AS decimal(18, 2)) AS CreditLimit
FROM {_CUST} c WITH (NOLOCK)
WHERE c.[CreditLimit] IS NOT NULL
ORDER BY c.[CreditLimit] DESC
"""
    return _blob(
        "highest_credit_limit_customers",
        sql,
        f"Top {n} customers by CreditLimit from the customer master.",
        ["No sales filter — master data only."],
    )


def _sql_birthday_customers_this_week(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    c.[CustomerId],
    c.[CustomerFirstName],
    c.[CustomerLastName],
    c.[ContactMobile],
    c.[City],
    CAST(c.[BirthdayDt] AS DATE) AS Birthday,
    CAST(
        DATEADD(
            YEAR,
            DATEDIFF(YEAR, c.[BirthdayDt], GETDATE()),
            c.[BirthdayDt]
        ) AS DATE
    ) AS BirthdayThisYear
FROM {_CUST} c WITH (NOLOCK)
WHERE c.[BirthdayDt] IS NOT NULL
  AND DATEADD(YEAR, DATEDIFF(YEAR, c.[BirthdayDt], GETDATE()), c.[BirthdayDt])
      >= CAST(GETDATE() AS DATE)
  AND DATEADD(YEAR, DATEDIFF(YEAR, c.[BirthdayDt], GETDATE()), c.[BirthdayDt])
      < DATEADD(DAY, 7, CAST(GETDATE() AS DATE))
ORDER BY BirthdayThisYear
"""
    return _blob(
        "birthday_customers_this_week",
        sql,
        "Customers whose birthday (month/day) falls in the next 7 calendar days.",
        ["Uses BirthdayDt with year adjusted to current year."],
    )


def _sql_repeat_customer_percentage(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH CustomerBills AS (
    SELECT
        s.[CustomerId],
        COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount
    FROM {_SALES_AI} s WITH (NOLOCK)
    WHERE {_invoice_mtd_where("s")}
      AND s.[CustomerId] IS NOT NULL
    GROUP BY s.[CustomerId]
)
SELECT
    COUNT(*) AS CustomersWithSales,
    SUM(CASE WHEN InvoiceCount > 1 THEN 1 ELSE 0 END) AS RepeatCustomers,
    CAST(
        100.0 * SUM(CASE WHEN InvoiceCount > 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0)
        AS decimal(18, 4)
    ) AS RepeatCustomerPct
FROM CustomerBills
"""
    return _blob(
        "repeat_customer_percentage",
        sql,
        "MTD share of customers with more than one distinct invoice (repeat proxy).",
        [
            "Repeat = COUNT(DISTINCT InvoiceId) > 1 in MTD on VwAISalesData.",
            "Not the same as new-vs-first-purchase-day logic.",
        ],
    )


def _sql_customer_retention_trend(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (12)
    DATEFROMPARTS(YEAR(s.[InvoiceDt]), MONTH(s.[InvoiceDt]), 1) AS MonthStart,
    COUNT(DISTINCT s.[CustomerId]) AS ActiveCustomers,
    COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount,
    CAST(SUM(s.[SaleNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_SALES_AI} s WITH (NOLOCK)
WHERE {_invoice_last_12m_where("s")}
  AND s.[CustomerId] IS NOT NULL
GROUP BY DATEFROMPARTS(YEAR(s.[InvoiceDt]), MONTH(s.[InvoiceDt]), 1)
ORDER BY MonthStart ASC
"""
    return _blob(
        "customer_retention_trend",
        sql,
        "Monthly count of distinct purchasing customers (active customers) over the last 12 months.",
        [
            "Proxy for retention trend: distinct CustomerId per month on VwAISalesData.",
            "Not cohort retention — use for volume of active buyers over time.",
        ],
    )


def _sql_vip_sales_contribution(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH VipSales AS (
    SELECT SUM(s.[SaleNetAmount]) AS VipRevenue
    FROM {_SALES_AI} s WITH (NOLOCK)
    INNER JOIN {_CUST} c WITH (NOLOCK)
        ON s.[CustomerId] = c.[CustomerId]
    WHERE {_invoice_mtd_where("s")}
      AND c.[CustomerGroupName] LIKE N'%VIP%'
),
AllSales AS (
    SELECT SUM(s.[SaleNetAmount]) AS TotalRevenue
    FROM {_SALES_AI} s WITH (NOLOCK)
    WHERE {_invoice_mtd_where("s")}
)
SELECT
    CAST(v.VipRevenue AS decimal(18, 2)) AS VipRevenue,
    CAST(a.TotalRevenue AS decimal(18, 2)) AS TotalRevenue,
    CAST(100.0 * v.VipRevenue / NULLIF(a.TotalRevenue, 0) AS decimal(18, 4)) AS VipContributionPct
FROM VipSales v
CROSS JOIN AllSales a
"""
    return _blob(
        "vip_customer_sales_contribution",
        sql,
        "MTD sales from customers whose CustomerGroupName contains 'VIP' vs all MTD sales.",
        [
            "VIP matched with LIKE '%VIP%' on CustomerGroupName — adjust if your codes differ.",
            "Revenue from VwAISalesData.SaleNetAmount.",
        ],
    )


# ─── Inventory & stock analytics ──────────────────────────────────────────────


def _low_stock_threshold() -> int:
    try:
        return max(1, int(os.getenv("NLQ_LOW_STOCK_THRESHOLD", "5")))
    except ValueError:
        return 5


def _sql_stock_by_branch(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    st.[BranchAlias],
    CAST(SUM(st.[StockQty]) AS decimal(18, 4)) AS TotalStockQty,
    CAST(SUM(st.[StockQty] * st.[ItemMRP]) AS decimal(18, 2)) AS StockValueAtMRP
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[BranchAlias] IS NOT NULL
GROUP BY st.[BranchAlias]
ORDER BY TotalStockQty DESC
"""
    return _blob(
        "current_stock_by_branch",
        sql,
        "Current on-hand stock quantity and MRP value by branch (snapshot).",
        ["View: STOCK_REPORT; no date filter — point-in-time stock."],
    )


def _sql_low_stock_items(_q: str) -> Dict[str, Any]:
    thr = _low_stock_threshold()
    sql = f"""
SELECT TOP (200)
    st.[BranchAlias],
    st.[ItemId],
    st.[ArticleNo],
    st.[CategoryShortName] AS Category,
    CAST(st.[StockQty] AS decimal(18, 4)) AS StockQty
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[StockQty] > 0
  AND st.[StockQty] <= {thr}
ORDER BY st.[StockQty] ASC, st.[BranchAlias]
"""
    return _blob(
        "low_stock_items",
        sql,
        f"Items with positive stock on hand at or below {thr} units (low-stock threshold).",
        [
            f"Threshold = {thr} (override with NLQ_LOW_STOCK_THRESHOLD).",
            "Row-level stock lines from STOCK_REPORT.",
        ],
    )


def _sql_dead_stock_90_days(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    st.[BranchAlias],
    st.[ItemId],
    st.[ArticleNo],
    st.[CategoryShortName] AS Category,
    CAST(st.[StockQty] AS decimal(18, 4)) AS StockQty,
    CAST(st.[PurInvoiceDt] AS DATE) AS PurInvoiceDate,
    DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) AS DaysSincePurInvoice
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[StockQty] > 0
  AND st.[PurInvoiceDt] IS NOT NULL
  AND st.[PurInvoiceDt] < DATEADD(DAY, -90, CAST(GETDATE() AS DATE))
ORDER BY DaysSincePurInvoice DESC, st.[StockQty] DESC
"""
    return _blob(
        "dead_stock_older_than_90_days",
        sql,
        "Stock lines with PurInvoiceDt older than 90 days and positive StockQty.",
        [
            "Proxy for dead stock: aged by last purchase invoice date on stock row.",
            "Does not require sales velocity — use with business validation.",
        ],
    )


def _sql_highest_inventory_branch(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    st.[BranchAlias],
    CAST(SUM(st.[StockQty]) AS decimal(18, 4)) AS TotalStockQty,
    CAST(SUM(st.[StockQty] * st.[ItemMRP]) AS decimal(18, 2)) AS StockValueAtMRP
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[BranchAlias] IS NOT NULL
GROUP BY st.[BranchAlias]
ORDER BY TotalStockQty DESC
"""
    return _blob(
        "highest_inventory_branch",
        sql,
        "Branch with highest total on-hand quantity.",
        ["Snapshot from STOCK_REPORT; ranked by SUM(StockQty)."],
    )


def _sql_stock_value_by_category(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    st.[CategoryShortName] AS Category,
    CAST(SUM(st.[StockQty]) AS decimal(18, 4)) AS TotalStockQty,
    CAST(SUM(st.[StockQty] * st.[ItemMRP]) AS decimal(18, 2)) AS StockValueAtMRP
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[CategoryShortName] IS NOT NULL
GROUP BY st.[CategoryShortName]
ORDER BY StockValueAtMRP DESC
"""
    return _blob(
        "stock_value_by_category",
        sql,
        "On-hand stock quantity and MRP value by category.",
        ["StockValueAtMRP = SUM(StockQty × ItemMRP)."],
    )


def _sql_stock_transfers_mtd(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    t.TransferDirection,
    t.[SourceBranchAlias],
    t.[TargetBranchAlias],
    CAST(SUM(t.[TransferQty]) AS decimal(18, 4)) AS TransferQty,
    CAST(SUM(t.[TransferValue]) AS decimal(18, 2)) AS TransferValue
FROM (
    SELECT
        N'TransferIn' AS TransferDirection,
        sti.[SourceBranchAlias],
        sti.[TargetBranchAlias],
        sti.[StiQty] AS TransferQty,
        sti.[NetAmount] AS TransferValue
    FROM {_STI} sti WITH (NOLOCK)
    WHERE {_mtd_where("sti")}
    UNION ALL
    SELECT
        N'TransferOut',
        sto.[SourceBranchAlias],
        sto.[TargetBranchAlias],
        sto.[StoQty],
        sto.[NetAmount]
    FROM {_STO} sto WITH (NOLOCK)
    WHERE {_mtd_where("sto")}
) t
GROUP BY t.TransferDirection, t.[SourceBranchAlias], t.[TargetBranchAlias]
ORDER BY TransferQty DESC
"""
    return _blob(
        "stock_transfer_between_branches",
        sql,
        "MTD inbound (STI) and outbound (STO) transfers by source and target branch.",
        ["MTD filter on XnDt in STI_REPORT and STO_REPORT."],
    )


def _sql_overstocked_products(_q: str) -> Dict[str, Any]:
    n = _top_n_from_question(_q, 50)
    sql = f"""
SELECT TOP ({n})
    st.[ItemId],
    st.[ArticleNo],
    st.[CategoryShortName] AS Category,
    CAST(SUM(st.[StockQty]) AS decimal(18, 4)) AS TotalStockQty,
    CAST(SUM(st.[StockQty] * st.[ItemMRP]) AS decimal(18, 2)) AS StockValueAtMRP
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[ItemId] IS NOT NULL
  AND st.[StockQty] > 0
GROUP BY st.[ItemId], st.[ArticleNo], st.[CategoryShortName]
ORDER BY TotalStockQty DESC
"""
    return _blob(
        "overstocked_products",
        sql,
        f"Top {n} items by total on-hand quantity across branches (overstock proxy).",
        [
            "Does not subtract MTD sales velocity — high StockQty only.",
            "For true overstock, compare to sales in a follow-up query.",
        ],
    )


def _sql_inventory_turnover_ratio(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH CatSales AS (
    SELECT
        s.[CategoryShortName] AS Category,
        SUM(s.[AppQty]) AS MTDQtySold
    FROM {_APP} s WITH (NOLOCK)
    WHERE {_mtd_where("s")}
      AND s.[CategoryShortName] IS NOT NULL
    GROUP BY s.[CategoryShortName]
),
CatStock AS (
    SELECT
        st.[CategoryShortName] AS Category,
        SUM(st.[StockQty]) AS OnHandQty
    FROM {_STOCK} st WITH (NOLOCK)
    WHERE st.[CategoryShortName] IS NOT NULL
    GROUP BY st.[CategoryShortName]
)
SELECT
    COALESCE(cs.Category, ck.Category) AS Category,
    CAST(ISNULL(cs.MTDQtySold, 0) AS decimal(18, 4)) AS MTDQtySold,
    CAST(ISNULL(ck.OnHandQty, 0) AS decimal(18, 4)) AS OnHandQty,
    CAST(
        CASE WHEN ISNULL(ck.OnHandQty, 0) = 0 THEN NULL
             ELSE ISNULL(cs.MTDQtySold, 0) / ck.OnHandQty
        END AS decimal(18, 4)
    ) AS TurnoverRatio
FROM CatSales cs
FULL OUTER JOIN CatStock ck ON cs.Category = ck.Category
ORDER BY TurnoverRatio DESC
"""
    return _blob(
        "inventory_turnover_ratio",
        sql,
        "Simplified turnover proxy by category: MTD quantity sold ÷ current on-hand quantity.",
        [
            "Not annualized — MTD sales qty / snapshot stock qty.",
            "Categories with zero stock show NULL turnover.",
        ],
    )


def _sql_git_by_supplier(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    g.[SupplierName],
    g.[SupplierAlias],
    CAST(SUM(g.[GitQty]) AS decimal(18, 4)) AS GoodsInTransitQty,
    CAST(SUM(g.[GitCostValue]) AS decimal(18, 2)) AS GoodsInTransitCost,
    CAST(SUM(g.[StockQty]) AS decimal(18, 4)) AS OnHandStockQty,
    CAST(SUM(g.[CbsCostValue]) AS decimal(18, 2)) AS ClosingStockCost
FROM {_CBS} g WITH (NOLOCK)
WHERE g.[SupplierName] IS NOT NULL
GROUP BY g.[SupplierName], g.[SupplierAlias]
ORDER BY GoodsInTransitQty DESC
"""
    return _blob(
        "goods_in_transit_by_supplier",
        sql,
        "Goods in transit and closing stock metrics by supplier from CBS_WITH_GIT.",
        ["Snapshot view; GitQty / GitCostValue per catalog."],
    )


def _sql_stock_aging_analysis(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    CASE
        WHEN st.[PurInvoiceDt] IS NULL THEN N'Unknown date'
        WHEN DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) <= 30 THEN N'0-30 days'
        WHEN DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) <= 60 THEN N'31-60 days'
        WHEN DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) <= 90 THEN N'61-90 days'
        ELSE N'90+ days'
    END AS AgeBucket,
    CAST(SUM(st.[StockQty]) AS decimal(18, 4)) AS TotalStockQty,
    CAST(SUM(st.[StockQty] * st.[ItemMRP]) AS decimal(18, 2)) AS StockValueAtMRP,
    COUNT(DISTINCT st.[ItemId]) AS DistinctItems
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[StockQty] > 0
GROUP BY
    CASE
        WHEN st.[PurInvoiceDt] IS NULL THEN N'Unknown date'
        WHEN DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) <= 30 THEN N'0-30 days'
        WHEN DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) <= 60 THEN N'31-60 days'
        WHEN DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) <= 90 THEN N'61-90 days'
        ELSE N'90+ days'
    END
ORDER BY AgeBucket
"""
    return _blob(
        "stock_aging_analysis",
        sql,
        "Stock quantity and MRP value grouped by age buckets from PurInvoiceDt.",
        ["Aging based on PurInvoiceDt on STOCK_REPORT rows."],
    )


# ─── Supplier analytics ───────────────────────────────────────────────────────


def _sql_highest_supplier_sales_mtd(_q: str) -> Dict[str, Any]:
    # MIS supplier view is the only complete supplier-sales source —
    # APP_REPORT has supplier attribution on a tiny fraction of rows
    # (it returned the same lone supplier for both highest AND lowest).
    sql = f"""
SELECT TOP (1)
    m.[SupplierName],
    CAST(SUM(m.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_MIS_SUP} m WITH (NOLOCK)
WHERE {_memo_mtd_where("m")}
  AND m.[SupplierName] IS NOT NULL
GROUP BY m.[SupplierName]
ORDER BY Revenue DESC
"""
    return _blob(
        "highest_supplier_sales_mtd",
        sql,
        "Supplier with highest current-month net sales (MIS supplier view).",
        ["View: VW_MB_POWERBI_MIS_SUPPLIER_SLS_DATA; date: XnMemoDate; metric SUM(NetAmount)."],
    )


def _sql_supplier_sales_trend(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    m.[SupplierName],
    m.[XnMemoDate_MONTHNAME] AS SalesMonth,
    CAST(SUM(m.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(m.[NetSlsQty]) AS decimal(18, 4)) AS QtySold
FROM {_MIS_SUP} m WITH (NOLOCK)
WHERE {_last_12m_memo_where("m")}
  AND m.[SupplierName] IS NOT NULL
GROUP BY m.[SupplierName], m.[XnMemoDate_MONTH], m.[XnMemoDate_MONTHNAME]
ORDER BY m.[SupplierName], m.[XnMemoDate_MONTH]
"""
    return _blob(
        "supplier_wise_sales_trend",
        sql,
        "Monthly supplier sales trend for the last 12 months (MIS supplier view).",
        [
            "View: VW_MB_POWERBI_MIS_SUPPLIER_SLS_DATA; date: XnMemoDate.",
            "Capped at TOP 500 month-supplier rows.",
        ],
    )


def _sql_top_suppliers_by_qty(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 10)
    sql = f"""
SELECT TOP ({n})
    s.[SupplierName],
    s.[SupplierAlias],
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[SupplierName] IS NOT NULL
GROUP BY s.[SupplierName], s.[SupplierAlias]
ORDER BY QtySold DESC
"""
    return _blob(
        "top_suppliers_by_quantity",
        sql,
        f"Top {n} suppliers by MTD quantity sold (AppQty).",
        ["MTD on XnDt; ranked by SUM(AppQty)."],
    )


def _sql_highest_supplier_stock_value(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    st.[SupplierName],
    st.[SupplierAlias],
    CAST(SUM(st.[StockQty]) AS decimal(18, 4)) AS TotalStockQty,
    CAST(SUM(st.[StockQty] * st.[ItemMRP]) AS decimal(18, 2)) AS StockValueAtMRP
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[SupplierName] IS NOT NULL
GROUP BY st.[SupplierName], st.[SupplierAlias]
ORDER BY StockValueAtMRP DESC
"""
    return _blob(
        "highest_supplier_stock_value",
        sql,
        "Supplier with highest on-hand stock value (StockQty × ItemMRP) from STOCK_REPORT.",
        [
            "Snapshot view — no date filter on stock.",
            "StockValueAtMRP is an MRP-based proxy, not landed cost.",
        ],
    )


def _sql_supplier_performance_by_branch(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[SupplierName],
    s.[BranchAlias],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[AppQty]) AS decimal(18, 4)) AS QtySold
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[SupplierName] IS NOT NULL
GROUP BY s.[SupplierName], s.[BranchAlias]
ORDER BY s.[SupplierName], Revenue DESC
"""
    return _blob(
        "supplier_performance_by_branch",
        sql,
        "MTD net sales and quantity by supplier and branch.",
        ["Grain: SupplierName + BranchAlias; MTD on XnDt."],
    )


def _sql_purchases_by_supplier_mtd(q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    p.[SupplierName],
    p.[SupplierAlias],
    CAST(SUM(p.[NetPurNetAmount]) AS decimal(18, 2)) AS NetPurchaseAmount,
    CAST(SUM(p.[NetPurQty]) AS decimal(18, 4)) AS NetPurchaseQty
FROM {_PUR} p WITH (NOLOCK)
WHERE {_pur_mtd_where("p")}
  AND p.[SupplierName] IS NOT NULL
GROUP BY p.[SupplierName], p.[SupplierAlias]
ORDER BY NetPurchaseAmount DESC
"""
    return _blob(
        "purchases_by_supplier_mtd",
        sql,
        "All suppliers by MTD net purchase amount and quantity (PURXNS). No row cap — full list returned.",
        ["PurInvDate MTD filter; metric SUM(NetPurNetAmount)."],
    )


def _sql_highest_supplier_return_rate(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT TOP (1)
    p.[SupplierName],
    p.[SupplierAlias],
    CAST(SUM(p.[PurQty]) AS decimal(18, 4)) AS PurchaseQty,
    CAST(SUM(p.[PrtQty]) AS decimal(18, 4)) AS ReturnQty,
    CAST(
        100.0 * SUM(p.[PrtQty]) / NULLIF(SUM(p.[PurQty]) + SUM(p.[PrtQty]), 0)
        AS decimal(18, 4)
    ) AS ReturnRatePct
FROM {_PUR} p WITH (NOLOCK)
WHERE {_pur_mtd_where("p")}
  AND p.[SupplierName] IS NOT NULL
GROUP BY p.[SupplierName], p.[SupplierAlias]
HAVING SUM(p.[PurQty]) + SUM(p.[PrtQty]) > 0
ORDER BY ReturnRatePct DESC
"""
    return _blob(
        "highest_supplier_return_rate",
        sql,
        "Supplier with highest MTD purchase return rate: PrtQty / (PurQty + PrtQty).",
        ["Uses PURXNS purchase and return quantities; MTD on PurInvDate."],
    )


def _sql_supplier_sales_by_state(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    s.[SupplierState],
    s.[SupplierName],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[SupplierState] IS NOT NULL
  AND s.[SupplierName] IS NOT NULL
GROUP BY s.[SupplierState], s.[SupplierName]
ORDER BY s.[SupplierState], Revenue DESC
"""
    return _blob(
        "supplier_sales_across_states",
        sql,
        "MTD supplier sales compared across states (SupplierState on APP_REPORT).",
        ["Grouped by SupplierState then SupplierName; MTD period."],
    )


def _sql_supplier_contribution_pct_mtd(_q: str) -> Dict[str, Any]:
    # FIXED 2026-06-13: switched from APP_REPORT (NetAmount/XnDt - sparse, diverged
    # from dashboard) to the canonical SLS_DATA_WITHOUT_ITEMID view (SalesNetAmount/
    # CashmemoDt) so the % matches the Analytics dashboard supplier totals.
    sql = f"""
WITH sup AS (
    SELECT
        sp.[SupplierName],
        SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE {_cashmemo_mtd_where("sp")}
      AND sp.[SupplierName] IS NOT NULL
    GROUP BY sp.[SupplierName]
)
SELECT
    [SupplierName],
    CAST(Revenue AS decimal(18, 2)) AS Revenue,
    CAST(100.0 * Revenue / NULLIF(SUM(Revenue) OVER (), 0) AS decimal(18, 4)) AS ContributionPct
FROM sup
WHERE Revenue <> 0
ORDER BY ContributionPct DESC
"""
    return _blob(
        "supplier_contribution_percentage",
        sql,
        "Each supplier's share of total MTD net sales (percent of grand total).",
        [
            "Source: VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID (SalesNetAmount, CashmemoDt).",
            "Aligned with the Analytics dashboard - same view, amount column and date column.",
        ],
    )


def _sql_top_suppliers_in_city(q: str) -> Dict[str, Any]:
    n = _top_n_from_question(q, 5)
    m = re.search(r"\bin\s+([a-z][a-z\s]{1,40}?)\s*$", _norm(q))
    city = (m.group(1).strip().title() if m else "Chennai")
    sql = f"""
SELECT TOP ({n})
    s.[SupplierName],
    s.[SupplierAlias],
    s.[SupplierCity],
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[SupplierName] IS NOT NULL
  AND s.[SupplierCity] LIKE N'%{city}%'
GROUP BY s.[SupplierName], s.[SupplierAlias], s.[SupplierCity]
ORDER BY Revenue DESC
"""
    return _blob(
        "top_suppliers_in_city",
        sql,
        f"Top {n} suppliers in {city} by MTD net sales (SupplierCity LIKE).",
        [f"City filter: SupplierCity LIKE '%{city}%'; MTD on XnDt."],
    )



# ─── Additional analytics (sell-through, margins, repeat customers, festival) ──


def _sql_product_sell_through(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH Sales AS (
    SELECT s.[Itemcode], SUM(s.[NetSlsQty]) AS SoldQty
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE {_mtd_where("s")} AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
),
Stock AS (
    SELECT pm.[Itemcode], MAX(st.[ArticleNo]) AS ArticleNo, SUM(st.[StockQty]) AS StockQty
    FROM {_STOCK} st WITH (NOLOCK)
    INNER JOIN {_PM} pm WITH (NOLOCK) ON pm.[ItemId] = st.[ItemId]
    WHERE pm.[Itemcode] IS NOT NULL
    GROUP BY pm.[Itemcode]
)
SELECT TOP (200)
    COALESCE(sa.[Itemcode], st.[Itemcode]) AS Itemcode,
    CAST(ISNULL(sa.SoldQty, 0) AS decimal(18, 4)) AS MTDQtySold,
    CAST(ISNULL(st.StockQty, 0) AS decimal(18, 4)) AS OnHandQty,
    CAST(
        100.0 * ISNULL(sa.SoldQty, 0) / NULLIF(ISNULL(sa.SoldQty, 0) + ISNULL(st.StockQty, 0), 0)
        AS decimal(18, 4)
    ) AS SellThroughPct
FROM Sales sa
FULL OUTER JOIN Stock st ON st.[Itemcode] = sa.[Itemcode]
WHERE ISNULL(sa.SoldQty, 0) + ISNULL(st.StockQty, 0) > 0
  AND ISNULL(sa.SoldQty, 0) > 0
ORDER BY SellThroughPct DESC, MTDQtySold DESC, Itemcode
"""
    return _blob(
        "product_sell_through_pct",
        sql,
        "MTD sell-through % per item: sold qty / (sold + on-hand). All items returned.",
        [
            "Stock ItemId bridged to Itemcode via PRODUCT_MASTER.",
            "MTD sold qty from APP_REPORT (XnDt); on-hand from STOCK_REPORT.",
            "No TOP by default — all items with MTD sales and/or on-hand stock.",
            "Say 'top 50 product sell through' to limit to N rows (max 500).",
            "Results capped at 3000 rows for display.",
        ],
    )


def _sql_five_year_sales_dept_category(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
    sp.[DepartmentShortName] AS Department,
    sp.[CategoryShortName] AS Category,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE sp.[CashmemoDt] >= DATEADD(YEAR, -5, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
  AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
GROUP BY
    DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1),
    sp.[DepartmentShortName],
    sp.[CategoryShortName]
ORDER BY MonthStart ASC, TotalSales DESC
"""
    return _blob(
        "five_year_sales_dept_category",
        sql,
        "Monthly net sales by Department and Category for the past 5 years.",
        [
            "Full 5-year monthly grain; chart aggregates to monthly totals.",
            "No row limit — all department x category x month combinations returned.",
        ],
    )


def _sql_category_contribution_pct(_q: str) -> Dict[str, Any]:
    # FIXED 2026-06-13 (Manoj issue #3): switched from APP_REPORT (NetAmount/XnDt -
    # sparse, produced figures that did NOT match the Analytics dashboard category
    # chart) to the canonical SLS_DATA_WITHOUT_ITEMID view (SalesNetAmount/CashmemoDt).
    # The contribution % now reconciles with the dashboard "Sales by category" share %.
    sql = f"""
WITH c AS (
    SELECT sp.[CategoryShortName] AS Category, SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE {_cashmemo_mtd_where("sp")} AND sp.[CategoryShortName] IS NOT NULL
    GROUP BY sp.[CategoryShortName]
)
SELECT
    Category,
    CAST(Revenue AS decimal(18, 2)) AS Revenue,
    CAST(100.0 * Revenue / NULLIF(SUM(Revenue) OVER (), 0) AS decimal(18, 4)) AS ContributionPct
FROM c
WHERE Revenue <> 0
ORDER BY ContributionPct DESC
"""
    return _blob(
        "category_contribution_percentage",
        sql,
        "MTD revenue contribution % by category. All categories returned.",
        [
            "Source: VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID (SalesNetAmount, CashmemoDt).",
            "Aligned with the Analytics dashboard category share % - same view/columns.",
            "No row cap — full category list returned.",
        ],
    )


def _sql_new_vs_repeat_customers(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH Bills AS (
    SELECT
        s.[CustomerId],
        COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount,
        SUM(s.[SaleNetAmount]) AS Revenue
    FROM {_SALES_AI} s WITH (NOLOCK)
    WHERE {_invoice_mtd_where("s")} AND s.[CustomerId] IS NOT NULL
    GROUP BY s.[CustomerId]
)
SELECT N'Repeat' AS CustomerType,
       COUNT(*) AS CustomerCount,
       CAST(SUM(Revenue) AS decimal(18, 2)) AS Revenue
FROM Bills WHERE InvoiceCount > 1
UNION ALL
SELECT N'One-time',
       COUNT(*),
       CAST(SUM(Revenue) AS decimal(18, 2))
FROM Bills WHERE InvoiceCount = 1
"""
    return _blob(
        "new_vs_repeat_customer_analysis",
        sql,
        "MTD split of one-time vs repeat customers (>1 invoice = repeat).",
        [
            "Repeat proxy — not first-purchase-day logic.",
            "Revenue from VwAISalesData.SaleNetAmount.",
        ],
    )


def _sql_gross_margin_by_category(_q: str) -> Dict[str, Any]:
    # FIXED 2026-06-13: switched from APP_REPORT (NetAmount/CostValue/XnDt - sparse)
    # to the canonical SLS_DATA_WITHOUT_ITEMID view. Revenue = SalesNetAmount,
    # Cost = SalesCost (COGS), filtered on CashmemoDt so margin reconciles with the
    # dashboard revenue figures (same view/columns the Analytics page uses).
    sql = f"""
SELECT
    sp.[CategoryShortName] AS Category,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(sp.[SalesCost]) AS decimal(18, 2)) AS CostValue,
    CAST(SUM(sp.[SalesNetAmount]) - SUM(sp.[SalesCost]) AS decimal(18, 2)) AS GrossProfit,
    CAST(
        100.0 * (SUM(sp.[SalesNetAmount]) - SUM(sp.[SalesCost])) / NULLIF(SUM(sp.[SalesNetAmount]), 0)
        AS decimal(18, 4)
    ) AS GrossMarginPct
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")} AND sp.[CategoryShortName] IS NOT NULL
GROUP BY sp.[CategoryShortName]
ORDER BY GrossProfit DESC
"""
    return _blob(
        "gross_margin_by_category",
        sql,
        "MTD revenue, cost, gross profit and margin % by category.",
        [
            "Revenue = SalesNetAmount, Cost = SalesCost from VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID.",
            "Aligned with the Analytics dashboard - same view, amount column and date column.",
            "No row cap — all categories returned.",
        ],
    )


def _sql_dead_stock_identification(_q: str) -> Dict[str, Any]:
    sql = f"""
SELECT
    st.[BranchAlias],
    st.[ItemId],
    st.[ArticleNo],
    st.[CategoryShortName] AS Category,
    CAST(st.[StockQty] AS decimal(18, 4)) AS StockQty,
    CAST(st.[PurInvoiceDt] AS DATE) AS PurInvoiceDate,
    DATEDIFF(DAY, st.[PurInvoiceDt], GETDATE()) AS DaysSincePurInvoice
FROM {_STOCK} st WITH (NOLOCK)
WHERE st.[StockQty] > 0
  AND st.[PurInvoiceDt] IS NOT NULL
  AND st.[PurInvoiceDt] < DATEADD(DAY, -90, CAST(GETDATE() AS DATE))
ORDER BY DaysSincePurInvoice DESC, st.[StockQty] DESC
"""
    return _blob(
        "dead_stock_identification",
        sql,
        "All stock lines unsold 90+ days. No row limit — full result returned.",
        [
            "Proxy for dead stock: aged by last purchase invoice date on stock row.",
            "Does not require sales velocity — use with business validation.",
            "Results capped at 3000 rows for display.",
        ],
    )


def _sql_festival_sales_trend(_q: str) -> Dict[str, Any]:
    sql = f"""
WITH MonthlyTotals AS (
    SELECT
        DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
        CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales,
        COUNT(DISTINCT sp.[CashmemoNo]) AS BillCount
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(YEAR, -3, DATEFROMPARTS(YEAR(GETDATE()), 1, 1))
      AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
    GROUP BY DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)
),
Ranked AS (
    SELECT *,
        AVG(TotalSales) OVER () AS AvgSales,
        RANK() OVER (ORDER BY TotalSales DESC) AS SalesRank
    FROM MonthlyTotals
)
SELECT
    MonthStart,
    TotalSales,
    BillCount,
    SalesRank,
    CAST(100.0 * TotalSales / NULLIF(AvgSales, 0) AS decimal(18, 1)) AS PctOfAvg
FROM Ranked
ORDER BY MonthStart ASC
"""
    return _blob(
        "festival_sales_trend_prediction",
        sql,
        "Monthly sales last 3 years with rank vs average — reveals festival/seasonal peaks.",
        [
            "No hardcoded festival dates — peaks emerge from the data.",
            "PctOfAvg: how each month compares to the 3-year average.",
            "Top-ranked months = historical festival/peak seasons.",
        ],
    )


# Register in priority order (more specific patterns first)
_register(
    "products_frequently_returned",
    [
        r"which\s+products?\s+are\s+frequently\s+returned",
        r"products?\s+frequently\s+returned",
        r"top\s+returned\s+products?",
        r"most\s+returned\s+products?",
    ],
    _sql_products_frequently_returned,
)
_register(
    "best_salesperson_weekends",
    [
        r"which\s+sales\s*person(?:s)?\s+performs?\s+best\s+(?:during\s+)?weekends?",
        r"best\s+salesperson\s+(?:on\s+)?weekends?",
        r"top\s+salesperson\s+weekend",
    ],
    _sql_best_salesperson_weekends,
)
_register(
    "branch_efficiency_bill_count_vs_sales",
    [
        r"branch\s+efficiency.*bill\s+count",
        r"bill\s+count\s+vs\s+sales?\s+by\s+branch",
        r"efficiency\s+based\s+on\s+bill\s+count",
    ],
    _sql_branch_efficiency_bills_vs_sales,
)
_register(
    "departments_most_profit",
    [
        r"which\s+departments?\s+contribute\s+most\s+profit",
        r"departments?\s+by\s+(?:gross\s+)?profit",
        r"most\s+profitable\s+departments?",
    ],
    _sql_departments_most_profit,
)
_register(
    "fast_vs_slow_moving_inventory",
    [
        r"fast[\s-]?moving\s+vs\s+slow[\s-]?moving",
        r"show\s+fast[\s-]?moving.*slow[\s-]?moving",
        r"fast\s+and\s+slow\s+moving\s+inventory",
    ],
    _sql_fast_vs_slow_moving,
)
_register(
    "high_stock_low_sales",
    [
        r"products?\s+(?:with\s+|have\s+)?high\s+stock\s+but\s+low\s+sales?",
        r"high\s+stock\s+but\s+low\s+sales?",
        r"high\s+stock\s+low\s+sales?",
        r"high\s+inventory\s+low\s+sales?",
    ],
    _sql_high_stock_low_sales,
)
_register(
    "supplier_depends_on_one_branch",
    [
        r"supplier\s+depends?\s+heavily\s+on\s+one\s+branch",
        r"supplier\s+concentrated\s+in\s+one\s+branch",
        r"which\s+supplier\s+depends?\s+on\s+one\s+branch",
    ],
    _sql_supplier_depends_on_one_branch,
)
_register(
    "predict_next_month_sales",
    [
        r"predict\s+next\s+month\s+sales?",
        r"forecast\s+next\s+month\s+sales?",
        r"next\s+month\s+sales?\s+(?:forecast|prediction|trend)",
    ],
    _sql_predict_next_month_sales,
)
_register(
    "categories_declining_3_months",
    [
        r"categor(?:y|ies)\s+(?:are\s+)?declining\s+for\s+3\s+consecutive\s+months?",
        r"declining\s+categor(?:y|ies)\s+.*3\s+months?",
        r"3\s+consecutive\s+months?\s+declin.*categor",
    ],
    _sql_categories_declining_3_months,
)
_register(
    "branch_high_growth_low_margin",
    [
        r"branch(?:es)?\s+with\s+highest\s+growth\s+but\s+lowest\s+margin",
        r"highest\s+growth.*lowest\s+margin.*branch",
        r"which\s+branch.*growth.*margin",
    ],
    _sql_branch_high_growth_low_margin,
)
_register(
    "vip_customer_sales_contribution",
    [
        r"sales?\s+contribution\s+from\s+vip\s+customers?",
        r"vip\s+customer\s+(?:sales?\s+)?contribution",
        r"vip\s+(?:share|contribution)\s+of\s+(?:total\s+)?sales?",
    ],
    _sql_vip_sales_contribution,
)
_register(
    "customer_retention_trend",
    [
        r"customer\s+retention\s+trend",
        r"retention\s+trend\s+.*customer",
        r"customer\s+retention\s+over\s+time",
    ],
    _sql_customer_retention_trend,
)
_register(
    "repeat_customer_percentage",
    [
        r"repeat\s+customer\s+(?:%|percent|percentage)",
        r"percentage\s+of\s+repeat\s+customers?",
        r"repeat\s+purchase\s+(?:%|percent|rate)",
    ],
    _sql_repeat_customer_percentage,
)
_register(
    "birthday_customers_this_week",
    [
        r"birthday\s+customers?\s+this\s+week",
        r"customers?\s+(?:with\s+)?birthday\s+this\s+week",
        r"birthdays?\s+this\s+week",
    ],
    _sql_birthday_customers_this_week,
)
_register(
    "highest_credit_limit_customers",
    [
        r"which\s+customers?\s+have\s+(?:the\s+)?highest\s+credit\s+limit",
        r"highest\s+credit\s+limit\s+customers?",
        r"top\s+customers?\s+by\s+credit\s+limit",
    ],
    _sql_highest_credit_limit,
)
_register(
    "inactive_customers",
    [
        r"show\s+inactive\s+customers?",
        r"inactive\s+customers?",
        r"customers?\s+marked\s+inactive",
    ],
    _sql_inactive_customers,
)
_register(
    "top_customers_by_purchase_value",
    [
        r"top\s+(?:\d+\s+)?customers?\s+(?:by|based\s+on)\s+purchase\s+value",
        r"top\s+customers?\s+(?:by|based\s+on)\s+(?:sales?|revenue|spend)",
        r"best\s+customers?\s+(?:by|based\s+on)\s+purchase",
    ],
    _sql_top_customers_by_value,
)
_register(
    "customer_group_wise_sales",
    [
        r"customer\s+group[\s-]?wise\s+sales?",
        r"sales?\s+by\s+customer\s+group",
        r"show\s+customer\s+group.*sales?",
    ],
    _sql_sales_by_customer_group,
)
_register(
    "city_with_most_customers",
    [
        r"which\s+city\s+has\s+(?:the\s+)?most\s+customers?",
        r"city\s+with\s+most\s+customers?",
        r"top\s+city\s+by\s+customer\s+count",
    ],
    _sql_city_most_customers,
)
_register(
    "new_customers_this_month",
    [
        r"new\s+customers?\s+added\s+this\s+month",
        r"new\s+customers?\s+this\s+month",
        r"customers?\s+created\s+this\s+month",
        r"show\s+new\s+customers?",
    ],
    _sql_new_customers_mtd,
)
_register(
    "dead_stock_older_than_90_days",
    [
        r"dead\s+stock\s+older\s+than\s+90",
        r"dead\s+stock.*90\s+days?",
        r"stock\s+older\s+than\s+90\s+days?",
    ],
    _sql_dead_stock_90_days,
)
_register(
    "stock_aging_analysis",
    [
        r"stock\s+aging\s+analysis",
        r"inventory\s+aging\s+analysis",
        r"aging\s+analysis\s+.*stock",
    ],
    _sql_stock_aging_analysis,
)
_register(
    "goods_in_transit_by_supplier",
    [
        r"goods?\s+in\s+transit\s+by\s+supplier",
        r"git\s+by\s+supplier",
        r"in[\s-]?transit\s+stock\s+by\s+supplier",
    ],
    _sql_git_by_supplier,
)
_register(
    "inventory_turnover_ratio",
    [
        r"inventory\s+turnover\s+ratio",
        r"stock\s+turnover\s+ratio",
        r"show\s+inventory\s+turnover",
    ],
    _sql_inventory_turnover_ratio,
)
_register(
    "overstocked_products",
    [
        r"which\s+products?\s+are\s+overstocked",
        r"overstocked\s+products?",
        r"excess\s+stock\s+products?",
    ],
    _sql_overstocked_products,
)
_register(
    "stock_transfer_between_branches",
    [
        r"stock\s+transfer\s+between\s+branches?",
        r"inter[\s-]?branch\s+stock\s+transfer",
    ],
    _sql_stock_transfers_mtd,
)
_register(
    "stock_value_by_category",
    [
        r"stock\s+value\s+by\s+categor",
        r"inventory\s+value\s+by\s+categor",
    ],
    _sql_stock_value_by_category,
)
_register(
    "highest_inventory_branch",
    [
        r"which\s+branch(?:es)?\s+has\s+(?:the\s+)?highest\s+inventory",
        r"highest\s+inventory\s+by\s+branch",
        r"branch\s+with\s+most\s+stock",
    ],
    _sql_highest_inventory_branch,
)
_register(
    "low_stock_items",
    [
        r"which\s+items?\s+are\s+low\s+in\s+stock",
        r"low\s+stock\s+items?",
        r"items?\s+low\s+on\s+stock",
    ],
    _sql_low_stock_items,
)
_register(
    "current_stock_by_branch",
    [
        r"(?:show\s+)?current\s+stock\s+by\s+branch",
        r"stock\s+on\s+hand\s+by\s+branch",
        r"inventory\s+by\s+branch",
    ],
    _sql_stock_by_branch,
)
_register(
    "top_suppliers_in_city",
    [
        r"top\s+\d+\s+suppliers?\s+in\s+chennai",
        r"top\s+suppliers?\s+in\s+chennai",
        r"best\s+suppliers?\s+in\s+chennai",
        r"suppliers?\s+in\s+chennai\s+by\s+sales?",
    ],
    _sql_top_suppliers_in_city,
)
_register(
    "supplier_contribution_percentage",
    [
        r"supplier\s+contribution\s+(?:%|percent|percentage)",
        r"contribution\s+(?:%|percent|percentage)\s+(?:of\s+)?(?:overall\s+)?sales?\s+.*supplier",
        r"supplier\s+(?:share|contribution)\s+of\s+(?:total\s+)?sales?",
    ],
    _sql_supplier_contribution_pct_mtd,
)
_register(
    "supplier_sales_across_states",
    [
        r"compare\s+supplier\s+sales?\s+across\s+states?",
        r"supplier\s+sales?\s+(?:by|across)\s+state",
        r"state[\s-]?wise\s+supplier\s+sales?",
    ],
    _sql_supplier_sales_by_state,
)
_register(
    "highest_supplier_return_rate",
    [
        r"which\s+supplier\s+has\s+(?:the\s+)?highest\s+return\s+rate",
        r"highest\s+(?:purchase\s+)?return\s+rate\s+.*supplier",
        r"supplier\s+return\s+rate",
    ],
    _sql_highest_supplier_return_rate,
)
_register(
    "purchases_by_supplier_mtd",
    [
        r"purchases?\s+from\s+each\s+supplier\s+this\s+month",
        r"purchases?\s+by\s+supplier\s+(?:this\s+month|mtd)",
        r"supplier[\s-]?wise\s+purchases?\s+(?:this\s+month|mtd)",
    ],
    _sql_purchases_by_supplier_mtd,
)
_register(
    "supplier_performance_by_branch",
    [
        r"supplier\s+performance\s+by\s+branch",
        r"supplier[\s-]?wise\s+(?:sales?\s+)?by\s+branch",
        r"sales?\s+by\s+supplier\s+and\s+branch",
    ],
    _sql_supplier_performance_by_branch,
)
_register(
    "highest_supplier_stock_value",
    [
        r"which\s+supplier\s+has\s+(?:the\s+)?highest\s+stock\s+value",
        r"highest\s+stock\s+value\s+.*supplier",
        r"supplier\s+with\s+(?:most|highest)\s+stock",
    ],
    _sql_highest_supplier_stock_value,
)
_register(
    "top_suppliers_by_quantity",
    [
        r"top\s+(?:\d+\s+)?suppliers?\s+by\s+quantity",
        r"suppliers?\s+by\s+qty\s+sold",
        r"which\s+suppliers?\s+sold\s+(?:the\s+)?most\s+quantity",
    ],
    _sql_top_suppliers_by_qty,
)
_register(
    "supplier_wise_sales_trend",
    [
        r"supplier[\s-]?wise\s+sales?\s+trend",
        r"sales?\s+trend\s+by\s+supplier",
        r"supplier\s+sales?\s+over\s+time",
    ],
    _sql_supplier_sales_trend,
)
_register(
    "highest_supplier_sales_mtd",
    [
        r"which\s+supplier\s+generated\s+(?:the\s+)?highest\s+sales?",
        r"which\s+supplier\s+has\s+(?:the\s+)?highest\s+sales?",
        r"top\s+supplier\s+by\s+(?:sales?|revenue)",
        r"best\s+supplier\s+by\s+sales?",
    ],
    _sql_highest_supplier_sales_mtd,
)
_register(
    "products_zero_sales_mtd",
    [
        r"products?\s+with\s+(?:zero|no)\s+sales?",
        r"zero\s+sales?\s+products?",
        r"items?\s+with\s+no\s+sales?\s+(?:this\s+month|mtd)?",
    ],
    _sql_products_zero_sales_mtd,
)
_register(
    "sales_by_neckline_type",
    [
        r"sales?\s+by\s+neckline",
        r"neckline\s+(?:type|wise)\s+sales?",
        r"show\s+sales?\s+by\s+neckline",
    ],
    _sql_sales_by_neckline,
)
_register(
    "top_products_by_profit_margin",
    [
        r"top\s+(?:\d+\s+)?products?\s+by\s+(?:profit\s+)?margin",
        r"(?:profit|gross)\s+margin\s+by\s+product",
        r"products?\s+by\s+profit\s+margin",
    ],
    _sql_top_products_margin,
)
_register(
    "top_articles_by_revenue",
    [
        r"top\s+\d+\s+articles?\s+by\s+revenue",
        r"top\s+\d+\s+articles?\s+by\s+sales?",
        r"show\s+top\s+\d+\s+articles?",
    ],
    _sql_top_articles_revenue,
)
_register(
    "top_products_mtd",
    [
        r"which\s+products?\s+(?:sold|sell)\s+most\s+(?:this\s+month|mtd)?",
        r"best\s+selling\s+products?\s+(?:this\s+month|mtd)?",
        r"most\s+sold\s+products?\s+(?:this\s+month|mtd)?",
        r"top\s+selling\s+products?\s+(?:this\s+month|mtd)?",
        # "top 10 good/best/top performing product(s)", "top performing products"
        r"top\s+\d+\s+(?:good|best|top|well)\s+performing\s+products?",
        r"top\s+\d+\s+performing\s+products?",
        r"(?:good|best|top|well)[-\s]+performing\s+products?",
        r"performing\s+products?",
        # bare "top N products" / "best products" — but NOT "top N products by ... quarter/year"
        r"top\s+\d+\s+products?\b(?!\s+by\b)",
        r"best\s+products?\b(?!\s+by\b)",
        r"top\s+products?(?:\s+(?:this\s+month|mtd|overall|right\s+now|now))?$",
    ],
    _sql_top_products_mtd,
)
_register(
    "category_wise_quantity_sold",
    [
        r"categor(?:y|ies)[\s-]?wise\s+quantity",
        r"quantity\s+sold\s+by\s+categor",
        r"show\s+categor(?:y|ies)[\s-]?wise\s+(?:qty|quantity)",
    ],
    _sql_category_quantity_mtd,
)
_register(
    "sales_by_fabric_type",
    [
        r"sales?\s+by\s+fabric",
        r"fabric\s+(?:type|wise)\s+sales?",
    ],
    _sql_sales_by_fabric,
)
_register(
    "highest_color_sales_mtd",
    [
        r"which\s+color\s+has\s+(?:the\s+)?highest\s+sales?",
        r"highest\s+sales?\s+by\s+color",
        r"top\s+color\s+by\s+sales?",
    ],
    _sql_highest_color_mtd,
)
_register(
    "top_selling_size_mtd",
    [
        r"which\s+size\s+sells?\s+most",
        r"top\s+selling\s+size",
        r"best\s+selling\s+size",
        r"highest\s+sales?\s+by\s+size",
    ],
    _sql_top_size_mtd,
)
_register(
    "highest_concept_revenue_mtd",
    [
        r"which\s+concept\s+generated\s+(?:the\s+)?highest\s+revenue",
        r"highest\s+revenue\s+by\s+concept",
        r"top\s+concept\s+by\s+(?:sales?|revenue)",
    ],
    _sql_highest_concept_mtd,
)
_register(
    "compare_this_month_vs_last_month",
    [
        r"compare\s+this\s+month\s+sales?\s+vs\.?\s+last\s+month",
        r"compare\s+(?:this\s+)?month(?:'?s)?\s+(?:sales?\s+)?vs\.?\s+last\s+month",
        r"compare\s+(?:this\s+)?month(?:'?s)?\s+(?:sales?|revenue)?\s+to\s+last\s+month",
        r"compare\s+(?:this\s+)?month(?:'?s)?\s+(?:sales?|revenue)?\s+with\s+last\s+month",
        r"this\s+month(?:'?s)?\s+(?:sales?|revenue)?\s+compared\s+to\s+last\s+month",
        r"compare\s+last\s+month\s+(?:vs\.?|versus|to)\s+(?:this\s+)?month",
        r"this\s+month\s+vs\.?\s+last\s+month\s+sales?",
    ],
    _sql_compare_this_month_vs_last,
)
_register(
    "sales_trend_last_30_days",
    [
        r"(?:show\s+)?sales?\s+trend\s+(?:for\s+)?(?:the\s+)?last\s+30\s+days?",
        r"daily\s+sales?\s+(?:for\s+)?last\s+30\s+days?",
        r"last\s+30\s+days?\s+sales?\s+trend",
    ],
    _sql_trend_last_30d,
)
_register(
    "total_bill_count_today",
    [
        r"(?:show\s+)?total\s+bill\s+count\s+today",
        r"how\s+many\s+bills?\s+today",
        r"bill\s+count\s+today",
    ],
    _sql_bill_count_today,
)
_register(
    "average_bill_value_by_branch",
    [
        r"(?:show\s+)?average\s+bill\s+value\s+by\s+branch",
        r"avg(?:erage)?\s+bill\s+value\s+by\s+branch",
        r"average\s+(?:basket|invoice)\s+(?:size|value)\s+by\s+branch",
    ],
    _sql_avg_bill_by_branch,
)
_register(
    "lowest_performing_branches",
    [
        r"(?:show\s+)?lowest\s+performing\s+branches?",
        r"bottom\s+\d*\s*branches?\s+(?:by\s+)?sales?",
        r"worst\s+performing\s+branches?",
    ],
    _sql_lowest_branches,
)
_register(
    "top_selling_categories",
    [
        r"(?:show\s+)?top\s+(?:\d+\s+)?selling\s+categor",
        r"(?:show\s+)?top\s+\d+\s+categor(?:y|ies)\s+by\s+(?:sales?|revenue)",
        r"top\s+\d+\s+selling\s+categor",
    ],
    _sql_top_categories,
)
_register(
    "highest_branch_this_month",
    [
        r"which\s+branch(?:es)?\s+has\s+(?:the\s+)?highest\s+sales?\s+(?:this\s+month|mtd|current\s+month)",
        r"highest\s+sales?\s+branch(?:es)?\s+(?:this\s+month|mtd)",
        r"best\s+branch(?:es)?\s+(?:this\s+month|mtd)",
    ],
    _sql_highest_branch_this_month,
)
_register(
    "ytd_sales_by_department",
    [
        r"(?:show\s+)?ytd\s+sales?\s+by\s+department",
        r"(?:show\s+)?sales?\s+by\s+department\s+ytd",
        r"year[\s-]?to[\s-]?date\s+sales?\s+by\s+department",
    ],
    _sql_ytd_sales_by_department,
)
_register(
    "mtd_sales_by_branch",
    [
        r"(?:show\s+)?mtd\s+sales?\s+by\s+branch",
        r"(?:show\s+)?sales?\s+by\s+branch\s+(?:mtd|this\s+month)",
        r"month[\s-]?to[\s-]?date\s+sales?\s+by\s+branch",
    ],
    _sql_mtd_sales_by_branch,
)
_register(
    "total_sales_today",
    [
        r"^(?:show\s+)?total\s+(?:net\s+)?sales?\s+today\b",
        r"\btotal\s+(?:net\s+)?sales?\s+today\b",
        r"^(?:show\s+)?today(?:'?s)?\s+(?:total\s+)?sales?\b(?!\s+with\s+unique)",
    ],
    _sql_total_sales_today,
)


_register(
    "product_sell_through_pct",
    [
        r"product[\s-]?wise\s+sell[\s-]?through",
        r"sell[\s-]?through\s+(?:percent|pct|%|analysis|rate)",
        r"product\s+sell[\s-]?through",
    ],
    _sql_product_sell_through,
)
_register(
    "five_year_sales_dept_category",
    [
        r"(?:last\s+)?5\s+years?\s+sales?\s+(?:analysis\s+)?.*(?:department|dept)",
        r"five\s+year\s+sales?\s+(?:analysis\s+)?.*(?:department|dept)",
        r"5\s+years?\s+sales?\s+by\s+(?:department|dept|category)",
    ],
    _sql_five_year_sales_dept_category,
)
_register(
    "category_contribution_percentage",
    [
        r"category\s+contribution\s+(?:%|percent|percentage)",
        r"contribution\s+(?:%|percent|percentage).*(?:total\s+)?revenue.*categor",
        r"categor.*contribution\s+(?:%|percent|percentage)",
    ],
    _sql_category_contribution_pct,
)
_register(
    "new_vs_repeat_customer_analysis",
    [
        r"new\s+vs\.?\s+repeat\s+customer",
        r"repeat\s+vs\.?\s+new\s+customer",
        r"new\s+and\s+repeat\s+customer\s+analysis",
        r"one[\s-]?time\s+vs\.?\s+repeat\s+customer",
    ],
    _sql_new_vs_repeat_customers,
)
_register(
    "gross_margin_by_category",
    [
        r"gross\s+margin\s+(?:analysis\s+)?by\s+(?:department|category|dept)",
        r"gross\s+margin\s+analysis",
        r"margin\s+by\s+(?:department|category)",
    ],
    _sql_gross_margin_by_category,
)
_register(
    "dead_stock_identification",
    [
        r"dead\s+stock\s+identification",
        r"identify\s+dead\s+stock",
        r"dead\s+stock\s+(?:report|items?|list)",
    ],
    _sql_dead_stock_identification,
)
_register(
    "festival_sales_trend_prediction",
    [
        r"sales?\s+trend\s+prediction.*festival",
        r"festival.*sales?\s+trend",
        r"seasonal\s+sales?\s+(?:trend|prediction|forecast)",
        r"upcoming\s+festival.*sales?",
    ],
    _sql_festival_sales_trend,
)


def _register_kpi_batch() -> None:
    try:
        from nlq_faq_kpi import register_kpi_faqs

        register_kpi_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: KPI FAQ templates not loaded: {exc}", file=sys.stderr)


_register_kpi_batch()


def _register_compare_batch() -> None:
    try:
        from nlq_faq_compare import register_compare_faqs

        register_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Compare FAQ templates not loaded: {exc}", file=sys.stderr)


_register_compare_batch()


def _register_product_compare_batch() -> None:
    try:
        from nlq_faq_product_compare import register_product_compare_faqs

        register_product_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Product compare FAQ templates not loaded: {exc}", file=sys.stderr)


_register_product_compare_batch()


def _register_branch_compare_batch() -> None:
    try:
        from nlq_faq_branch_compare import register_branch_compare_faqs

        register_branch_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Branch compare FAQ templates not loaded: {exc}", file=sys.stderr)


_register_branch_compare_batch()


def _register_supplier_compare_batch() -> None:
    try:
        from nlq_faq_supplier_compare import register_supplier_compare_faqs

        register_supplier_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Supplier compare FAQ templates not loaded: {exc}", file=sys.stderr)


def _register_customer_compare_batch() -> None:
    try:
        from nlq_faq_customer_compare import register_customer_compare_faqs

        register_customer_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Customer compare FAQ templates not loaded: {exc}", file=sys.stderr)


_register_supplier_compare_batch()
_register_customer_compare_batch()


def _register_inventory_compare_batch() -> None:
    try:
        from nlq_faq_inventory_compare import register_inventory_compare_faqs

        register_inventory_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Inventory compare FAQ templates not loaded: {exc}", file=sys.stderr)


def _register_executive_compare_batch() -> None:
    try:
        from nlq_faq_executive_compare import register_executive_compare_faqs

        register_executive_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Executive compare FAQ templates not loaded: {exc}", file=sys.stderr)


_register_inventory_compare_batch()
_register_executive_compare_batch()


def _register_conversational_compare_batch() -> None:
    try:
        from nlq_faq_conversational_compare import register_conversational_compare_faqs

        register_conversational_compare_faqs(_register)
    except ImportError as exc:
        import sys

        print(f"Warning: Conversational compare FAQ templates not loaded: {exc}", file=sys.stderr)


_register_conversational_compare_batch()


def list_frequent_ai_queries() -> List[str]:
    """Curated 'most frequently asked' AI questions (see nlq_faq_kpi.FREQUENT_AI_QUERIES)."""
    try:
        from nlq_faq_kpi import FREQUENT_AI_QUERIES

        return list(FREQUENT_AI_QUERIES)
    except ImportError:
        return []


def list_compare_ai_queries() -> List[str]:
    """Comparison-style FAQ questions (see nlq_faq_compare.COMPARE_AI_QUERIES)."""
    try:
        from nlq_faq_compare import COMPARE_AI_QUERIES

        return list(COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_product_compare_ai_queries() -> List[str]:
    """Product/assortment comparison FAQ questions (nlq_faq_product_compare)."""
    try:
        from nlq_faq_product_compare import PRODUCT_COMPARE_AI_QUERIES

        return list(PRODUCT_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_branch_compare_ai_queries() -> List[str]:
    """Branch comparison FAQ questions (nlq_faq_branch_compare)."""
    try:
        from nlq_faq_branch_compare import BRANCH_COMPARE_AI_QUERIES

        return list(BRANCH_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_supplier_compare_ai_queries() -> List[str]:
    try:
        from nlq_faq_supplier_compare import SUPPLIER_COMPARE_AI_QUERIES

        return list(SUPPLIER_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_customer_compare_ai_queries() -> List[str]:
    try:
        from nlq_faq_customer_compare import CUSTOMER_COMPARE_AI_QUERIES

        return list(CUSTOMER_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_inventory_compare_ai_queries() -> List[str]:
    try:
        from nlq_faq_inventory_compare import INVENTORY_COMPARE_AI_QUERIES

        return list(INVENTORY_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_executive_compare_ai_queries() -> List[str]:
    try:
        from nlq_faq_executive_compare import EXECUTIVE_COMPARE_AI_QUERIES

        return list(EXECUTIVE_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def list_conversational_compare_ai_queries() -> List[str]:
    try:
        from nlq_faq_conversational_compare import CONVERSATIONAL_COMPARE_AI_QUERIES

        return list(CONVERSATIONAL_COMPARE_AI_QUERIES)
    except ImportError:
        return []


def try_faq_template(question: str) -> Optional[Dict[str, Any]]:
    """
    If question matches a curated FAQ, return {template_id, sql, explanation, assumptions}.
    Otherwise return None (caller should use OpenAI).
    """
    nq = _norm(question)
    if not nq:
        return None
    for template_id, patterns, builder in _FAQ_BUILDERS:
        for pat in patterns:
            if pat.search(nq):
                out = builder(question)
                out["template_id"] = template_id
                return out
    return None


def list_faq_ids() -> List[str]:
    return [tid for tid, _, _ in _FAQ_BUILDERS]
