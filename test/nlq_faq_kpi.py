"""
Frequent AI / dashboard KPI FAQ templates (extends nlq_faq_sql).

Loaded at import-finish of nlq_faq_sql via register_kpi_faqs().
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

# Shown in terminal (`faq` command) and erp_semantic_layer.json — all map to FAQ templates when possible.
FREQUENT_AI_QUERIES: Tuple[str, ...] = (
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
)

# Late import inside register_kpi_faqs to avoid circular import during nlq_faq_sql load.


def _cust_count_subquery(dim_col: str, group_col: str) -> str:
    """Unique customers from salesperson lines aligned to a dimension column."""
    from nlq_faq_sql import _SALESPERSON, _cashmemo_mtd_where

    return f"""
    SELECT
        sp.[{dim_col}] AS DimValue,
        COUNT(DISTINCT sp.[CustomerId]) AS UniqueCustomers
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE {_cashmemo_mtd_where("sp")}
      AND sp.[{dim_col}] IS NOT NULL
      AND sp.[CustomerId] IS NOT NULL
    GROUP BY sp.[{group_col}]
"""


def register_kpi_faqs(register: Callable[..., None]) -> None:
    from nlq_faq_sql import (
        _APP,
        _CUST,
        _PM,
        _SALES_AI,
        _SLSXNS,
        _STOCK,
        _SALESPERSON,
        _blob,
        _mtd_where,
        _today_where,
        _invoice_mtd_where,
        _cashmemo_mtd_where,
        _top_n_from_question,
    )

    def _sql_store_mtd_kpi(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    sp.[BranchAlias] AS Store,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS UniqueInvoices,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT sp.[CustomerId]), 0) AS decimal(18, 2)) AS ATS,
    COUNT(DISTINCT sp.[CustomerId]) AS UniqueCustomers
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[BranchAlias] IS NOT NULL
GROUP BY sp.[BranchAlias]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY MTDSales DESC
"""
        return _blob(
            "store_mtd_sales_customers_ats",
            sql,
            "Store-wise MTD sales, invoice count, ATS (sales per customer), and unique customers.",
            [
                "Single source: SLS_DATA_WITHOUT_ITEMID (CashmemoDt) — aligned with dashboard analytics.",
                "Returns no rows when the current month has no posted sales yet.",
            ],
        )

    def _sql_dept_mtd_kpi(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    sp.[DepartmentShortName] AS Department,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS UniqueInvoices,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT sp.[CustomerId]), 0) AS decimal(18, 2)) AS ATS,
    COUNT(DISTINCT sp.[CustomerId]) AS UniqueCustomers
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[DepartmentShortName] IS NOT NULL
GROUP BY sp.[DepartmentShortName]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY MTDSales DESC
"""
        return _blob(
            "department_mtd_sales_customers_ats",
            sql,
            "Department-wise MTD sales, invoices, ATS, and unique customers.",
            ["Single source: SLS_DATA_WITHOUT_ITEMID on CashmemoDt."],
        )

    def _sql_cat_mtd_kpi(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    sp.[CategoryShortName] AS Category,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS UniqueInvoices,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT sp.[CustomerId]), 0) AS decimal(18, 2)) AS ATS,
    COUNT(DISTINCT sp.[CustomerId]) AS UniqueCustomers
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[CategoryShortName] IS NOT NULL
GROUP BY sp.[CategoryShortName]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY MTDSales DESC
"""
        return _blob(
            "category_mtd_sales_customers_ats",
            sql,
            "Category-wise MTD sales, invoices, ATS, and unique customers.",
            ["Single source: SLS_DATA_WITHOUT_ITEMID on CashmemoDt."],
        )

    def _sql_monthly_since_apr_2024(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
    DATENAME(MONTH, DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1))
        + N' ' + CAST(YEAR(DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)) AS varchar(4)) AS MonthLabel,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE sp.[CashmemoDt] >= DATEFROMPARTS(2024, 4, 1)
  AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
GROUP BY DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)
ORDER BY MonthStart ASC
"""
        return _blob(
            "monthly_sales_since_apr_2024",
            sql,
            "Month-wise total net sales from April 2024 through today.",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt) for fast monthly totals."],
        )

    def _sql_five_year_dept_category(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    DATEFROMPARTS(YEAR(s.[XnDt]), MONTH(s.[XnDt]), 1) AS MonthStart,
    s.[DepartmentShortName] AS Department,
    s.[CategoryShortName] AS Category,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_APP} s WITH (NOLOCK)
WHERE s.[XnDt] >= DATEADD(YEAR, -5, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
  AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
GROUP BY
    DATEFROMPARTS(YEAR(s.[XnDt]), MONTH(s.[XnDt]), 1),
    s.[DepartmentShortName],
    s.[CategoryShortName]
ORDER BY MonthStart ASC, TotalSales DESC
"""
        return _blob(
            "five_year_sales_dept_category",
            sql,
            "Monthly sales for the last 5 years by department and category.",
            ["Full 5-year monthly grain; chart aggregates to monthly totals."],
        )

    def _sql_average_sales_mtd(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDTotalSales,
    COUNT(DISTINCT CAST(sp.[CashmemoDt] AS DATE)) AS TradingDays,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT CAST(sp.[CashmemoDt] AS DATE)), 0) AS decimal(18, 2)) AS AvgDailySales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
"""
        return _blob(
            "average_sales_mtd_level",
            sql,
            "MTD total sales and average daily sales (total / distinct sale days).",
            ["Average = MTD revenue spread across days with at least one transaction."],
        )

    def _sql_today_sales_customers_invoices(_q: str) -> Dict[str, Any]:
        from nlq_faq_sql import _cashmemo_today_where

        sql = f"""
SELECT
    CAST(ISNULL(SUM(sp.[SalesNetAmount]), 0) AS decimal(18, 2)) AS TodaySales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS UniqueInvoices,
    COUNT(DISTINCT sp.[CustomerId]) AS UniqueCustomers
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_today_where("sp")}
"""
        return _blob(
            "today_sales_customers_invoices",
            sql,
            "Today sales, invoice count, and unique customers from cash memo lines.",
            ["Single source: SLS_DATA_WITHOUT_ITEMID on CashmemoDt."],
        )

    def _period_bounds(period: str) -> tuple[str, str]:
        _fy_start = (
            "CASE WHEN MONTH(GETDATE()) >= 4 "
            "THEN DATEFROMPARTS(YEAR(GETDATE()), 4, 1) "
            "ELSE DATEFROMPARTS(YEAR(GETDATE()) - 1, 4, 1) END"
        )
        if period == "ytd":
            cur = (
                f"sp.[CashmemoDt] >= {_fy_start} "
                "AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
            )
            py = (
                f"sp.[CashmemoDt] >= DATEADD(YEAR, -1, {_fy_start}) "
                "AND sp.[CashmemoDt] < DATEADD(YEAR, -1, DATEADD(DAY, 1, CAST(GETDATE() AS DATE)))"
            )
        elif period == "qtd":
            cur = (
                "sp.[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE()), ((MONTH(GETDATE()) - 1) / 3) * 3 + 1, 1) "
                "AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
            )
            py = (
                "sp.[CashmemoDt] >= DATEADD(YEAR, -1, DATEFROMPARTS(YEAR(GETDATE()), ((MONTH(GETDATE()) - 1) / 3) * 3 + 1, 1)) "
                "AND sp.[CashmemoDt] < DATEADD(YEAR, -1, DATEADD(DAY, 1, CAST(GETDATE() AS DATE)))"
            )
        else:  # mtd
            cur = (
                "sp.[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
                "AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
            )
            py = (
                "sp.[CashmemoDt] >= DATEADD(YEAR, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) "
                "AND sp.[CashmemoDt] < DATEADD(YEAR, -1, DATEADD(DAY, 1, CAST(GETDATE() AS DATE)))"
            )
        return cur, py

    def _period_growth_sql(period: str, label_cur: str, label_py: str) -> str:
        cur, py = _period_bounds(period)
        return f"""
SELECT
    N'{label_cur}' AS PeriodLabel,
    CAST(ISNULL(SUM(sp.[SalesNetAmount]), 0) AS decimal(18, 2)) AS TotalSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {cur}
UNION ALL
SELECT
    N'{label_py}',
    CAST(ISNULL(SUM(sp.[SalesNetAmount]), 0) AS decimal(18, 2))
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {py}
"""

    def _sql_all_period_growth(_q: str) -> Dict[str, Any]:
        parts = [
            _period_growth_sql("ytd", "CurrentYTD", "LastYearYTD"),
            _period_growth_sql("qtd", "CurrentQTD", "LastYearQTD"),
            _period_growth_sql("mtd", "CurrentMTD", "LastYearMTD"),
        ]
        sql = "\nUNION ALL\n".join(p.strip() for p in parts)
        return _blob(
            "all_period_growth_vs_last_year",
            sql,
            "FY YTD, calendar QTD, and MTD each compared to the same window last year (6 rows).",
            [
                "YTD uses Indian FY (Apr 1 → today); QTD/MTD use calendar quarter/month.",
                "Replaces three separate suggestion entries with one combined view.",
            ],
        )

    def _sql_ytd_growth(_q: str) -> Dict[str, Any]:
        return _blob(
            "ytd_growth_vs_last_year",
            _period_growth_sql("ytd", "CurrentYTD", "LastYearYTD"),
            "Current FY YTD sales (Apr 1 → today) vs same day-range last FY.",
            ["Indian financial year starts 1 April — aligned with Analytics dashboard."],
        )

    def _sql_qtd_growth(_q: str) -> Dict[str, Any]:
        return _blob(
            "qtd_growth_vs_last_year",
            _period_growth_sql("qtd", "CurrentQTD", "LastYearQTD"),
            "Current quarter QTD vs same quarter last year.",
            ["Calendar quarter based on GETDATE()."],
        )

    def _sql_mtd_growth(_q: str) -> Dict[str, Any]:
        return _blob(
            "mtd_growth_vs_last_year",
            _period_growth_sql("mtd", "CurrentMTD", "LastYearMTD"),
            "Current month MTD vs same MTD dates last year.",
            ["Aligned day-for-day MTD windows using DATEADD(YEAR,-1)."],
        )

    def _sql_highest_department_mtd(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT TOP (1)
    sp.[DepartmentShortName] AS Department,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[DepartmentShortName] IS NOT NULL
GROUP BY sp.[DepartmentShortName]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY MTDSales DESC
"""
        return _blob(
            "highest_department_sales_mtd",
            sql,
            "Department with highest MTD net sales.",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt) — aligned with dashboard."],
        )

    def _sql_highest_category_mtd(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT TOP (1)
    sp.[CategoryShortName] AS Category,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[CategoryShortName] IS NOT NULL
GROUP BY sp.[CategoryShortName]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY MTDSales DESC
"""
        return _blob(
            "highest_category_sales_mtd",
            sql,
            "Category with highest MTD net sales.",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt) — aligned with dashboard."],
        )

    def _sql_least_product_mtd(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT TOP (20)
    s.[Itemcode],
    MAX(s.[ArticleNo]) AS ArticleNo,
    CAST(SUM(s.[NetSlsNetAmount]) AS decimal(18, 2)) AS MTDSales,
    CAST(SUM(s.[NetSlsQty]) AS decimal(18, 4)) AS MTDQty
FROM {_SLSXNS} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Itemcode] IS NOT NULL
GROUP BY s.[Itemcode]
HAVING SUM(s.[NetSlsNetAmount]) > 0
ORDER BY MTDSales ASC
"""
        return _blob(
            "least_selling_product_mtd",
            sql,
            "Bottom 20 products by MTD revenue (among items with sales > 0).",
            ["Use YTD by rephrasing with 'year' if needed — template defaults to MTD."],
        )

    def _sql_lowest_supplier_mtd(_q: str) -> Dict[str, Any]:
        from nlq_faq_sql import _MIS_SUP, _memo_mtd_where

        sql = f"""
SELECT TOP (1)
    m.[SupplierName],
    CAST(SUM(m.[NetAmount]) AS decimal(18, 2)) AS MTDSales
FROM {_MIS_SUP} m WITH (NOLOCK)
WHERE {_memo_mtd_where("m")}
  AND m.[SupplierName] IS NOT NULL
GROUP BY m.[SupplierName]
HAVING SUM(m.[NetAmount]) > 0
ORDER BY MTDSales ASC
"""
        return _blob(
            "lowest_supplier_sales_mtd",
            sql,
            "Supplier with lowest current-month sales among suppliers with positive sales (MIS supplier view).",
            ["View: VW_MB_POWERBI_MIS_SUPPLIER_SLS_DATA; date: XnMemoDate."],
        )

    def _sql_top_stores_growth(_q: str) -> Dict[str, Any]:
        n = _top_n_from_question(_q, 10)
        sql = f"""
WITH Bounds AS (
    SELECT
        DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) AS CurrStart,
        CAST(GETDATE() AS DATE) AS AsOf,
        DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) AS PrevStart
),
B AS (
    SELECT
        sp.[BranchAlias],
        SUM(CASE WHEN sp.[CashmemoDt] >= b.CurrStart AND sp.[CashmemoDt] < DATEADD(DAY, 1, b.AsOf)
            THEN sp.[SalesNetAmount] ELSE 0 END) AS Curr,
        SUM(CASE WHEN sp.[CashmemoDt] >= b.PrevStart
                 AND sp.[CashmemoDt] < DATEADD(MONTH, -1, DATEADD(DAY, 1, b.AsOf))
            THEN sp.[SalesNetAmount] ELSE 0 END) AS Prev
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    CROSS JOIN Bounds b
    WHERE sp.[BranchAlias] IS NOT NULL
    GROUP BY sp.[BranchAlias]
)
SELECT TOP ({n})
    [BranchAlias] AS Store,
    CAST(Curr AS decimal(18, 2)) AS MTDSales,
    CAST(Prev AS decimal(18, 2)) AS PriorPeriodSales,
    CAST(CASE WHEN Prev = 0 THEN NULL ELSE 100.0 * (Curr - Prev) / Prev END AS decimal(18, 4)) AS GrowthPct
FROM B
WHERE Curr > 0 AND Prev > 0
ORDER BY GrowthPct DESC
"""
        return _blob(
            "top_stores_by_growth_pct",
            sql,
            f"Top {n} stores by % growth: MTD vs same elapsed days last month.",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt)."],
        )

    def _sql_bottom_stores_decline(_q: str) -> Dict[str, Any]:
        n = _top_n_from_question(_q, 10)
        sql = f"""
WITH Bounds AS (
    SELECT
        DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) AS CurrStart,
        CAST(GETDATE() AS DATE) AS AsOf,
        DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)) AS PrevStart
),
B AS (
    SELECT
        sp.[BranchAlias],
        SUM(CASE WHEN sp.[CashmemoDt] >= b.CurrStart AND sp.[CashmemoDt] < DATEADD(DAY, 1, b.AsOf)
            THEN sp.[SalesNetAmount] ELSE 0 END) AS Curr,
        SUM(CASE WHEN sp.[CashmemoDt] >= b.PrevStart
                 AND sp.[CashmemoDt] < DATEADD(MONTH, -1, DATEADD(DAY, 1, b.AsOf))
            THEN sp.[SalesNetAmount] ELSE 0 END) AS Prev
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    CROSS JOIN Bounds b
    WHERE sp.[BranchAlias] IS NOT NULL
    GROUP BY sp.[BranchAlias]
)
SELECT TOP ({n})
    [BranchAlias] AS Store,
    CAST(Curr AS decimal(18, 2)) AS MTDSales,
    CAST(Prev AS decimal(18, 2)) AS PriorPeriodSales,
    CAST(Curr - Prev AS decimal(18, 2)) AS SalesDecline,
    CAST(CASE WHEN Prev = 0 THEN NULL ELSE 100.0 * (Curr - Prev) / Prev END AS decimal(18, 4)) AS DeclinePct
FROM B
WHERE Prev > 0 AND Curr > 0 AND Curr < Prev
ORDER BY SalesDecline ASC
"""
        return _blob(
            "bottom_stores_sales_decline",
            sql,
            f"Bottom {n} stores by sales decline: current MTD vs same elapsed days last month.",
            [
                "Only stores with sales in both periods where current MTD declined.",
                "Prior period = same day-count in previous calendar month (not full month).",
            ],
        )

    def _sql_products_mom_growth(_q: str) -> Dict[str, Any]:
        sql = f"""
-- OPTIMISED 2026-06-13: single 2-month scan with conditional sums instead of a
-- 6-month scan + ROW_NUMBER window + self-join (which timed out at 300s on SLSXNS).
-- LatestRevenue = last complete month; PriorMonthRevenue = the month before it.
WITH M AS (
    SELECT
        s.[Itemcode],
        SUM(CASE WHEN s.[XnDt] >= DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
                 THEN s.[NetSlsNetAmount] ELSE 0 END) AS LatestRevenue,
        SUM(CASE WHEN s.[XnDt] <  DATEADD(MONTH, -1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
                 THEN s.[NetSlsNetAmount] ELSE 0 END) AS PriorMonthRevenue
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE s.[XnDt] >= DATEADD(MONTH, -2, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
      AND s.[XnDt] <  DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
)
SELECT TOP (50)
    [Itemcode],
    CAST(LatestRevenue AS decimal(18, 2)) AS LatestRevenue,
    CAST(PriorMonthRevenue AS decimal(18, 2)) AS PriorMonthRevenue,
    CAST(
        100.0 * (LatestRevenue - PriorMonthRevenue) / NULLIF(PriorMonthRevenue, 0)
        AS decimal(18, 4)
    ) AS MoMGrowthPct
FROM M
WHERE PriorMonthRevenue > 0 AND LatestRevenue > PriorMonthRevenue
ORDER BY MoMGrowthPct DESC
"""
        return _blob(
            "products_fastest_mom_growth",
            sql,
            "Products with highest month-over-month revenue growth (latest complete month vs prior).",
            [
                "Compares the last complete month vs the month before it, per Itemcode (SLSXNS).",
                "TOP 50 fastest growers; requires sales in both months; current partial month excluded.",
            ],
        )

    def _sql_categories_negative_growth(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH M AS (
    SELECT
        sp.[CategoryShortName] AS Category,
        DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
        SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(MONTH, -4, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
      AND sp.[CashmemoDt] < DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
      AND sp.[CategoryShortName] IS NOT NULL
    GROUP BY sp.[CategoryShortName], DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)
),
L AS (
    SELECT *,
        LAG(Revenue, 1) OVER (PARTITION BY Category ORDER BY MonthStart) AS PrevRev
    FROM M
)
SELECT
    Category,
    MonthStart AS LatestMonth,
    CAST(Revenue AS decimal(18, 2)) AS LatestRevenue,
    CAST(PrevRev AS decimal(18, 2)) AS PriorMonthRevenue,
    CAST(100.0 * (Revenue - PrevRev) / NULLIF(PrevRev, 0) AS decimal(18, 4)) AS MoMGrowthPct
FROM L
WHERE PrevRev IS NOT NULL AND Revenue < PrevRev
ORDER BY MoMGrowthPct ASC
"""
        return _blob(
            "categories_negative_growth_trends",
            sql,
            "Categories with negative month-over-month revenue (latest complete month vs prior).",
            ["Broader than 3-month consecutive decline template."],
        )

    def _sql_stock_requirement_30d(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH DailySales AS (
    SELECT
        s.[Itemcode],
        SUM(s.[NetSlsQty]) / 30.0 AS AvgDailyQty
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE s.[XnDt] >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE))
      AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
)
SELECT
    d.[Itemcode],
    CAST(d.AvgDailyQty AS decimal(18, 4)) AS AvgDailyQtySold,
    CAST(d.AvgDailyQty * 30 AS decimal(18, 4)) AS ExpectedQtyNext30Days
FROM DailySales d
ORDER BY ExpectedQtyNext30Days DESC
"""
        return _blob(
            "expected_stock_requirement_30_days",
            sql,
            "Expected stock need next 30 days = avg daily qty sold (last 30d) × 30 per item.",
            ["Heuristic demand plan — not on-hand stock adjusted."],
        )

    def _sql_stockout_risk(_q: str) -> Dict[str, Any]:
        from nlq_faq_sql import _stock_by_itemcode_cte

        sql = f"""
WITH DailySales AS (
    SELECT s.[Itemcode], SUM(s.[NetSlsQty]) / 14.0 AS AvgDailyQty
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE s.[XnDt] >= DATEADD(DAY, -14, CAST(GETDATE() AS DATE))
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
),
{_stock_by_itemcode_cte("Stock")}
SELECT
    d.[Itemcode],
    CAST(ISNULL(st.StockQty, 0) AS decimal(18, 4)) AS OnHandQty,
    CAST(d.AvgDailyQty AS decimal(18, 4)) AS AvgDailyQty,
    CAST(d.AvgDailyQty * 7 AS decimal(18, 4)) AS QtyNeeded7Days
FROM DailySales d
LEFT JOIN Stock st ON st.[Itemcode] = d.[Itemcode]
WHERE ISNULL(st.StockQty, 0) < d.AvgDailyQty * 7
ORDER BY OnHandQty ASC
"""
        return _blob(
            "potential_stockout_prediction",
            sql,
            "Items where on-hand stock is less than 7 days of average daily sales (last 14d).",
            ["Simple stock-out risk proxy."],
        )

    def _sql_peak_sales_hours(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    DATEPART(HOUR, sp.[CreatedOn]) AS SaleHour,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS Bills
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[CreatedOn] IS NOT NULL
GROUP BY DATEPART(HOUR, sp.[CreatedOn])
ORDER BY MTDSales DESC
"""
        return _blob(
            "peak_sales_hours_not_supported",
            sql,
            "MTD sales and bill count by hour of day from CreatedOn on salesperson lines.",
            [
                "Uses VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID; CashmemoDt is date-only.",
                "Hour bucket = DATEPART(HOUR, CreatedOn) at bill creation time.",
            ],
        )

    def _sql_festival_sales(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH M AS (
    SELECT
        MONTH(sp.[CashmemoDt]) AS Mo,
        SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(YEAR, -3, DATEFROMPARTS(YEAR(GETDATE()), 1, 1))
      AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
    GROUP BY MONTH(sp.[CashmemoDt])
)
SELECT
    Mo AS CalendarMonth,
    CASE WHEN Mo IN (10, 11) THEN N'Festive (Oct-Nov proxy)'
         WHEN Mo IN (3, 4, 5) THEN N'Summer'
         ELSE N'Non-festive / regular' END AS SeasonTag,
    CAST(Revenue AS decimal(18, 2)) AS AvgMonthlyRevenue
FROM M
ORDER BY Mo
"""
        return _blob(
            "festival_vs_non_festival_sales",
            sql,
            "Average monthly revenue by calendar month with festive season tags (heuristic).",
            ["No festival calendar table — Oct/Nov tagged as festive proxy."],
        )

    def _sql_region_sales(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    sp.[BranchRegion] AS Region,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS Bills
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[BranchRegion] IS NOT NULL
GROUP BY sp.[BranchRegion]
ORDER BY MTDSales DESC
"""
        return _blob(
            "region_wise_sales_performance",
            sql,
            "MTD sales by BranchRegion from salesperson lines view.",
            ["Region = BranchRegion on VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID."],
        )

    def _sql_invoice_value_trend(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT TOP (24)
    DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT sp.[CashmemoNo]), 0) AS decimal(18, 2)) AS AvgInvoiceValue,
    COUNT(DISTINCT sp.[CashmemoNo]) AS InvoiceCount
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE sp.[CashmemoDt] >= DATEADD(MONTH, -24, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
  AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
GROUP BY DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)
ORDER BY MonthStart ASC
"""
        return _blob(
            "average_invoice_value_trend",
            sql,
            "Monthly average invoice value (ATS) over the last 24 months.",
            ["AvgInvoiceValue = SUM(NetAmount) / COUNT(DISTINCT XnNo)."],
        )

    def _sql_new_vs_repeat(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH Bills AS (
    SELECT
        s.[CustomerId],
        COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount,
        SUM(s.[SaleNetAmount]) AS Revenue
    FROM {_SALES_AI} s WITH (NOLOCK)
    WHERE {_invoice_mtd_where("s")}
      AND s.[CustomerId] IS NOT NULL
    GROUP BY s.[CustomerId]
)
SELECT N'Repeat' AS CustomerType, COUNT(*) AS CustomerCount, CAST(SUM(Revenue) AS decimal(18, 2)) AS Revenue
FROM Bills WHERE InvoiceCount > 1
UNION ALL
SELECT N'One-time', COUNT(*), CAST(SUM(Revenue) AS decimal(18, 2))
FROM Bills WHERE InvoiceCount = 1
"""
        return _blob(
            "new_vs_repeat_customer_analysis",
            sql,
            "MTD customers split: repeat (>1 invoice) vs one-time (single invoice).",
            ["Repeat proxy — not first-purchase-day logic."],
        )

    def _sql_category_contribution(_q: str) -> Dict[str, Any]:
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
            "Each category's % of total MTD net sales.",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt, SalesNetAmount)."],
        )

    def _sql_gross_margin_category(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    s.[CategoryShortName] AS Category,
    CAST(SUM(s.[NetAmount]) AS decimal(18, 2)) AS Revenue,
    CAST(SUM(s.[CostValue]) AS decimal(18, 2)) AS CostValue,
    CAST(SUM(s.[NetAmount]) - SUM(s.[CostValue]) AS decimal(18, 2)) AS GrossProfit,
    CAST(100.0 * (SUM(s.[NetAmount]) - SUM(s.[CostValue])) / NULLIF(SUM(s.[NetAmount]), 0) AS decimal(18, 4)) AS GrossMarginPct
FROM {_APP} s WITH (NOLOCK)
WHERE {_mtd_where("s")} AND s.[CategoryShortName] IS NOT NULL
GROUP BY s.[CategoryShortName]
ORDER BY GrossProfit DESC
"""
        return _blob(
            "gross_margin_by_category",
            sql,
            "MTD gross margin by category (NetAmount - CostValue).",
            ["Department variant: ask 'gross margin by department'."],
        )

    def _sql_sell_through(q: str) -> Dict[str, Any]:
        import re

        from nlq_faq_sql import _stock_by_itemcode_cte

        m = re.search(r"\btop\s+(\d+)\b", q, re.I)
        top_prefix = (
            f"TOP ({max(1, min(500, int(m.group(1))))}) " if m else ""
        )
        sql = f"""
WITH Sales AS (
    SELECT s.[Itemcode], SUM(s.[AppQty]) AS SoldQty
    FROM {_APP} s WITH (NOLOCK)
    WHERE {_mtd_where("s")} AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
),
{_stock_by_itemcode_cte("Stock")}
SELECT {top_prefix}
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
ORDER BY SellThroughPct DESC, MTDQtySold DESC, Itemcode
"""
        assumptions = [
            "Stock ItemId bridged to Itemcode via PRODUCT_MASTER.",
            "MTD sold qty from APP_REPORT (XnDt); on-hand from STOCK_REPORT.",
            "No TOP by default — all items with MTD sales and/or on-hand stock.",
            "Say 'top 50 product sell through' to limit to N rows (max 500).",
        ]
        return _blob(
            "product_sell_through_pct",
            sql,
            "Sell-through % = MTD sold qty / (MTD sold + on-hand) by item.",
            assumptions,
        )

    def _sql_sales_spike_alert(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH Daily AS (
    SELECT CAST(sp.[CashmemoDt] AS DATE) AS SaleDate, SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(DAY, -14, CAST(GETDATE() AS DATE))
      AND sp.[CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
    GROUP BY CAST(sp.[CashmemoDt] AS DATE)
),
Stats AS (
    SELECT
        AVG(CASE WHEN SaleDate >= DATEADD(DAY, -7, CAST(GETDATE() AS DATE)) THEN Revenue END) AS AvgLast7,
        AVG(CASE WHEN SaleDate < DATEADD(DAY, -7, CAST(GETDATE() AS DATE)) THEN Revenue END) AS AvgPrev7
    FROM Daily
)
SELECT
    CAST(AvgLast7 AS decimal(18, 2)) AS AvgDailySalesLast7Days,
    CAST(AvgPrev7 AS decimal(18, 2)) AS AvgDailySalesPrior7Days,
    CAST(100.0 * (AvgLast7 - AvgPrev7) / NULLIF(AvgPrev7, 0) AS decimal(18, 4)) AS ChangePct,
    CASE
        WHEN AvgPrev7 IS NULL OR AvgPrev7 = 0 THEN N'Insufficient history'
        WHEN AvgLast7 > AvgPrev7 * 1.25 THEN N'Possible sales spike'
        WHEN AvgLast7 < AvgPrev7 * 0.75 THEN N'Possible sales drop'
        ELSE N'Within normal range'
    END AS AlertFlag
FROM Stats
"""
        return _blob(
            "sales_spike_drop_alert",
            sql,
            "Compares average daily sales last 7 days vs prior 7 days with alert flag.",
            ["Simple 25% threshold — not ML alerting."],
        )

    def _sql_demand_forecast_store_category(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH Monthly AS (
    SELECT
        sp.[BranchAlias] AS Store,
        sp.[CategoryShortName] AS Category,
        DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1) AS MonthStart,
        SUM(sp.[SalesNetAmount]) AS Revenue
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEADD(MONTH, -3, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
      AND sp.[CashmemoDt] < DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)
      AND sp.[BranchAlias] IS NOT NULL
      AND sp.[CategoryShortName] IS NOT NULL
    GROUP BY sp.[BranchAlias], sp.[CategoryShortName],
        DATEFROMPARTS(YEAR(sp.[CashmemoDt]), MONTH(sp.[CashmemoDt]), 1)
),
Avg3 AS (
    SELECT
        Store,
        Category,
        COUNT(*) AS MonthsInAverage,
        AVG(Revenue) AS AvgMonthlyRevenue
    FROM Monthly
    GROUP BY Store, Category
    HAVING AVG(Revenue) > 0
)
SELECT
    Store,
    Category,
    MonthsInAverage,
    CAST(AvgMonthlyRevenue AS decimal(18, 2)) AS AvgMonthlyRevenueLast3Mo,
    CAST(AvgMonthlyRevenue AS decimal(18, 2)) AS ForecastNextMonthRevenue
FROM Avg3
ORDER BY ForecastNextMonthRevenue DESC
"""
        return _blob(
            "demand_forecast_store_category",
            sql,
            "Next-month demand forecast = average monthly revenue per store×category over the last 3 complete months.",
            [
                "Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt, SalesNetAmount).",
                "No TOP — all store×category pairs with history in the window.",
            ],
        )

    def _sql_discount_impact(_q: str) -> Dict[str, Any]:
        sql = f"""
SELECT
    sp.[CategoryShortName] AS Category,
    CAST(SUM(sp.[ItemMRP] * sp.[SalesQuantity]) AS decimal(18, 2)) AS TotalMRP,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS NetSales,
    CAST(SUM(sp.[ItemMRP] * sp.[SalesQuantity]) - SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS ImpliedDiscountValue,
    CAST(
        100.0 * (SUM(sp.[ItemMRP] * sp.[SalesQuantity]) - SUM(sp.[SalesNetAmount])) / NULLIF(SUM(sp.[ItemMRP] * sp.[SalesQuantity]), 0)
        AS decimal(18, 4)
    ) AS ImpliedDiscountPct
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[CategoryShortName] IS NOT NULL
GROUP BY sp.[CategoryShortName]
HAVING SUM(sp.[ItemMRP] * sp.[SalesQuantity]) > 0
ORDER BY ImpliedDiscountPct DESC
"""
        return _blob(
            "discount_impact_sales",
            sql,
            "MTD implied discount by category: MRP value minus net sales (proxy for discount impact).",
            [
                "No dedicated discount column — uses MrpValue − NetAmount on APP_REPORT.",
                "Higher ImpliedDiscountPct = more MRP given up vs net collected.",
            ],
        )

    def _sql_product_recommendation(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH RepeatCust AS (
    SELECT s.[CustomerId]
    FROM {_SALES_AI} s WITH (NOLOCK)
    WHERE {_invoice_mtd_where("s")}
      AND s.[CustomerId] IS NOT NULL
    GROUP BY s.[CustomerId]
    HAVING COUNT(DISTINCT s.[InvoiceId]) >= 2
),
ItemPop AS (
    SELECT
        pm.[Itemcode],
        MAX(pm.[ArticleNo]) AS ArticleNo,
        MAX(pm.[CategoryShortName]) AS Category,
        COUNT(DISTINCT s.[CustomerId]) AS RepeatBuyerCount,
        CAST(SUM(s.[SaleNetAmount]) AS decimal(18, 2)) AS RevenueFromRepeatBuyers
    FROM {_SALES_AI} s WITH (NOLOCK)
    INNER JOIN RepeatCust r ON r.[CustomerId] = s.[CustomerId]
    INNER JOIN {_PM} pm WITH (NOLOCK) ON pm.[ItemId] = s.[ItemId]
    WHERE {_invoice_mtd_where("s")}
      AND pm.[Itemcode] IS NOT NULL
    GROUP BY pm.[Itemcode]
)
SELECT
    [Itemcode],
    [ArticleNo],
    [Category],
    [RepeatBuyerCount],
    [RevenueFromRepeatBuyers]
FROM ItemPop
ORDER BY [RepeatBuyerCount] DESC, [RevenueFromRepeatBuyers] DESC
"""
        return _blob(
            "product_recommendation_customer",
            sql,
            "Top products bought by repeat customers MTD (proxy for buying-pattern recommendations).",
            [
                "Repeat = customer with 2+ distinct invoices in MTD on VwAISalesData.",
                "Itemcode from PRODUCT_MASTER via ItemId; ranked by repeat-buyer count.",
            ],
        )

    def _sql_daily_target_achievement(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH Daily AS (
    SELECT
        CAST(sp.[CashmemoDt] AS DATE) AS SaleDate,
        CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS DaySales
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE {_cashmemo_mtd_where("sp")}
    GROUP BY CAST(sp.[CashmemoDt] AS DATE)
),
Benchmark AS (
    SELECT AVG(DaySales) AS AvgDailyBenchmark
    FROM Daily
)
SELECT
    d.[SaleDate],
    d.[DaySales],
    CAST(b.[AvgDailyBenchmark] AS decimal(18, 2)) AS DailyBenchmarkTarget,
    CAST(100.0 * d.[DaySales] / NULLIF(b.[AvgDailyBenchmark], 0) AS decimal(18, 4)) AS AchievementPct
FROM Daily d
CROSS JOIN Benchmark b
ORDER BY d.[SaleDate] ASC
"""
        return _blob(
            "daily_sales_target_achievement",
            sql,
            "Daily MTD sales vs MTD average daily sales (benchmark target proxy).",
            [
                "No ERP targets table — DailyBenchmarkTarget = average daily sales so far this month.",
                "AchievementPct > 100 means above the MTD daily average.",
            ],
        )

    def _sql_ai_business_insights_snapshot(_q: str) -> Dict[str, Any]:
        # Uses VW_MB_POWERBI_SLS_DATA_WITHOUT_ITEMID (CashmemoDt) — same view as analytics dashboard
        curr_filter = (
            "[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1) "
            "AND [CashmemoDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))"
        )
        # Compare same days last year (e.g. June 1-4 2025 vs June 1-4 2026), not full month
        ly_filter = (
            "[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE())-1, MONTH(GETDATE()), 1) "
            "AND [CashmemoDt] < DATEADD(DAY, 1, CAST(DATEADD(YEAR,-1,GETDATE()) AS DATE))"
        )
        sql = f"""
WITH Base AS (
    SELECT
        sp.[BranchAlias],
        sp.[CategoryShortName],
        sp.[SalesNetAmount] AS Amt,
        sp.[CashmemoNo],
        sp.[CashmemoDt]
    FROM {_SALESPERSON} sp WITH (NOLOCK)
    WHERE sp.[CashmemoDt] >= DATEFROMPARTS(YEAR(GETDATE())-1, MONTH(GETDATE()), 1)
      AND sp.[CashmemoDt] < DATEADD(MONTH, 1, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1))
),
MTD AS (
    SELECT
        SUM(CASE WHEN {curr_filter} THEN Amt ELSE 0 END) AS CurrSales,
        SUM(CASE WHEN {ly_filter}   THEN Amt ELSE 0 END) AS LYSales,
        COUNT(DISTINCT CASE WHEN {curr_filter} THEN CashmemoNo END) AS Bills
    FROM Base
),
TopBranch AS (
    SELECT TOP 1 BranchAlias, SUM(Amt) AS BranchSales
    FROM Base WHERE {curr_filter}
    GROUP BY BranchAlias ORDER BY BranchSales DESC
),
TopCat AS (
    SELECT TOP 1 CategoryShortName, SUM(Amt) AS CatSales
    FROM Base WHERE {curr_filter} AND CategoryShortName IS NOT NULL
    GROUP BY CategoryShortName ORDER BY CatSales DESC
),
BranchGrowth AS (
    SELECT TOP 1
        BranchAlias,
        CAST(ROUND(100.0 *
            (SUM(CASE WHEN {curr_filter} THEN Amt ELSE 0 END)
           - SUM(CASE WHEN {ly_filter}   THEN Amt ELSE 0 END))
          / NULLIF(SUM(CASE WHEN {ly_filter} THEN Amt ELSE 0 END), 0)
        , 1) AS DECIMAL(18,1)) AS GrowthPct
    FROM Base
    GROUP BY BranchAlias
    HAVING SUM(CASE WHEN {ly_filter} THEN Amt ELSE 0 END) > 0
    ORDER BY GrowthPct DESC
)
SELECT N'MTD Sales (Lakhs)'            AS Metric,
       CAST(ROUND(CurrSales/100000.0,2) AS DECIMAL(18,2)) AS Value,
       NULL AS Detail FROM MTD
UNION ALL
SELECT N'MTD Bills (Unique Invoices)', CAST(Bills AS DECIMAL(18,0)), NULL FROM MTD
UNION ALL
SELECT N'MTD YoY Growth %',
       CAST(ROUND(100.0*(CurrSales-LYSales)/NULLIF(LYSales,0),2) AS DECIMAL(18,2)),
       NULL FROM MTD
UNION ALL
SELECT N'Top Branch MTD', CAST(ROUND(BranchSales/100000.0,2) AS DECIMAL(18,2)), BranchAlias FROM TopBranch
UNION ALL
SELECT N'Top Category MTD', CAST(ROUND(CatSales/100000.0,2) AS DECIMAL(18,2)), CategoryShortName FROM TopCat
UNION ALL
SELECT N'Fastest Growing Branch (vs LY)', GrowthPct, BranchAlias FROM BranchGrowth
"""
        return _blob(
            "ai_business_insights_snapshot",
            sql,
            "Live MTD KPI snapshot using sales dashboard view — Claude narrates as business insights.",
            ["Values in Lakhs (₹L). Growth % vs same calendar month last year."],
        )

    def _sql_high_return_low_sales(_q: str) -> Dict[str, Any]:
        sql = f"""
WITH Ret AS (
    SELECT [Itemcode], SUM([SlrQty]) AS ReturnQty
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE {_mtd_where("s")} AND [SlrQty] > 0 AND [Itemcode] IS NOT NULL
    GROUP BY [Itemcode]
),
Sales AS (
    SELECT [Itemcode], SUM([NetSlsQty]) AS SoldQty
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE {_mtd_where("s")} AND [Itemcode] IS NOT NULL
    GROUP BY [Itemcode]
)
SELECT
    r.[Itemcode],
    CAST(r.ReturnQty AS decimal(18, 4)) AS ReturnQty,
    CAST(ISNULL(sa.SoldQty, 0) AS decimal(18, 4)) AS MTDQtySold,
    CAST(100.0 * r.ReturnQty / NULLIF(ISNULL(sa.SoldQty, 0), 0) AS decimal(18, 4)) AS ReturnRatePct
FROM Ret r
LEFT JOIN Sales sa ON sa.[Itemcode] = r.[Itemcode]
WHERE r.ReturnQty > 0
ORDER BY ReturnRatePct DESC, ReturnQty DESC
"""
        return _blob(
            "high_return_low_conversion_products",
            sql,
            "Items with MTD returns ranked by return qty vs sold qty (conversion proxy).",
            [
                "Returns from SLSXNS SlrQty; sold qty from APP_REPORT AppQty."
            ],
        )

    # ── Additional SQL builders ───────────────────────────────────────────────

    def _sql_highest_store_current_month(_q):
        sql = f"""
SELECT TOP (1)
    sp.[BranchAlias] AS Store,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS TotalSales
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[BranchAlias] IS NOT NULL
GROUP BY sp.[BranchAlias]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY TotalSales DESC
"""
        return _blob(
            "highest_store_current_month",
            sql,
            "Store with highest MTD net sales (current month).",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt). Single row."],
        )

    def _sql_most_selling_product_mtd(_q):
        sql = f"""
SELECT TOP (1)
    s.[Itemcode],
    MAX(s.[ArticleNo]) AS ArticleNo,
    CAST(SUM(s.[NetSlsNetAmount]) AS decimal(18, 2)) AS MTDSales,
    CAST(SUM(s.[NetSlsQty]) AS decimal(18, 4)) AS MTDQtySold
FROM {_SLSXNS} s WITH (NOLOCK)
WHERE {_mtd_where("s")}
  AND s.[Itemcode] IS NOT NULL
GROUP BY s.[Itemcode]
HAVING SUM(s.[NetSlsNetAmount]) > 0
ORDER BY MTDQtySold DESC
"""
        return _blob(
            "most_selling_product_mtd",
            sql,
            "Single product with highest quantity sold in the current month.",
            ["Sorted by qty sold. Use SLSXNS_REPORT NetSlsQty for quantity."],
        )

    def _sql_slow_moving_inventory(_q):
        from nlq_faq_sql import _stock_by_itemcode_cte
        sql = f"""
WITH SalesLast30 AS (
    SELECT s.[Itemcode], SUM(s.[NetSlsQty]) AS SoldQty30d
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE s.[XnDt] >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE))
      AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
),
{_stock_by_itemcode_cte("StockNow")}
SELECT
    sn.[Itemcode],
    CAST(ISNULL(sl.SoldQty30d, 0) AS decimal(18, 4)) AS SoldQty30d,
    CAST(sn.StockQty AS decimal(18, 4)) AS OnHandQty,
    CAST(
        CASE WHEN ISNULL(sl.SoldQty30d, 0) = 0 THEN NULL
             ELSE sn.StockQty / (sl.SoldQty30d / 30.0)
        END AS decimal(18, 1)
    ) AS DaysOfStockLeft
FROM StockNow sn
LEFT JOIN SalesLast30 sl ON sl.[Itemcode] = sn.[Itemcode]
WHERE sn.StockQty > 0
  AND ISNULL(sl.SoldQty30d, 0) < sn.StockQty * 0.1
ORDER BY OnHandQty DESC, SoldQty30d ASC
"""
        return _blob(
            "slow_moving_inventory_identification",
            sql,
            "Items where 30-day sales < 10% of on-hand qty (slow-moving proxy).",
            ["Stock via STOCK_REPORT+PRODUCT_MASTER; sales from APP_REPORT."],
        )

    def _sql_fast_moving_inventory(_q):
        from nlq_faq_sql import _stock_by_itemcode_cte
        sql = f"""
WITH SalesLast30 AS (
    SELECT s.[Itemcode], SUM(s.[NetSlsQty]) AS SoldQty30d
    FROM {_SLSXNS} s WITH (NOLOCK)
    WHERE s.[XnDt] >= DATEADD(DAY, -30, CAST(GETDATE() AS DATE))
      AND s.[XnDt] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
      AND s.[Itemcode] IS NOT NULL
    GROUP BY s.[Itemcode]
),
{_stock_by_itemcode_cte("StockNow")}
SELECT
    sl.[Itemcode],
    CAST(sl.SoldQty30d AS decimal(18, 4)) AS SoldQty30d,
    CAST(ISNULL(sn.StockQty, 0) AS decimal(18, 4)) AS OnHandQty,
    CAST(
        CASE WHEN ISNULL(sn.StockQty, 0) = 0 THEN NULL
             ELSE sn.StockQty / (sl.SoldQty30d / 30.0)
        END AS decimal(18, 1)
    ) AS DaysOfStockLeft
FROM SalesLast30 sl
LEFT JOIN StockNow sn ON sn.[Itemcode] = sl.[Itemcode]
WHERE sl.SoldQty30d > 0
  AND ISNULL(sn.StockQty, 0) < sl.SoldQty30d * 0.5
ORDER BY sl.SoldQty30d DESC
"""
        return _blob(
            "fast_moving_inventory_identification",
            sql,
            "Items with high 30-day sales but on-hand stock < 50% of monthly demand.",
            ["DaysOfStockLeft < 15 = high replenishment urgency."],
        )

    def _sql_customer_repeat_purchase(_q):
        sql = f"""
WITH CustPurchases AS (
    SELECT
        s.[CustomerId],
        COUNT(DISTINCT s.[InvoiceId]) AS InvoiceCount,
        CAST(SUM(s.[SaleNetAmount]) AS decimal(18, 2)) AS TotalSpend
    FROM {_SALES_AI} s WITH (NOLOCK)
    WHERE {_invoice_mtd_where("s")}
      AND s.[CustomerId] IS NOT NULL
    GROUP BY s.[CustomerId]
)
SELECT
    InvoiceCount AS VisitCount,
    COUNT(*) AS CustomerCount,
    CAST(AVG(TotalSpend) AS decimal(18, 2)) AS AvgSpendPerCustomer
FROM CustPurchases
GROUP BY InvoiceCount
ORDER BY InvoiceCount ASC
"""
        return _blob(
            "customer_repeat_purchase_analysis",
            sql,
            "MTD customer distribution by visit count — shows repeat purchase behaviour.",
            ["InvoiceCount = distinct invoices per customer this month."],
        )

    def _sql_avg_basket_by_store(_q):
        sql = f"""
SELECT
    sp.[BranchAlias] AS Store,
    CAST(SUM(sp.[SalesNetAmount]) AS decimal(18, 2)) AS MTDSales,
    COUNT(DISTINCT sp.[CashmemoNo]) AS UniqueInvoices,
    CAST(SUM(sp.[SalesNetAmount]) / NULLIF(COUNT(DISTINCT sp.[CustomerId]), 0) AS decimal(18, 2)) AS ATS,
    COUNT(DISTINCT sp.[CustomerId]) AS UniqueCustomers
FROM {_SALESPERSON} sp WITH (NOLOCK)
WHERE {_cashmemo_mtd_where("sp")}
  AND sp.[BranchAlias] IS NOT NULL
GROUP BY sp.[BranchAlias]
HAVING SUM(sp.[SalesNetAmount]) <> 0
ORDER BY ATS DESC
"""
        return _blob(
            "average_basket_size_by_store",
            sql,
            "MTD average basket size (ATS) per store, sorted highest to lowest.",
            ["Uses SLS_DATA_WITHOUT_ITEMID (CashmemoDt, SalesNetAmount). No row limit."],
        )

    # ── Register all KPI patterns ─────────────────────────────────────────────

    register("store_mtd_sales_customers_ats", [
        r"store[\s-]?wise\s+mtd\s+sales?",
        r"store[\s-]?wise.*(?:unique\s+customer|ats)",
        r"mtd\s+sales?\s+(?:by\s+)?store",
    ], _sql_store_mtd_kpi)

    register("store_ranking_sales_ats_customers", [
        r"store\s+rank(?:ing)?\s+based\s+on\s+sales?",
        r"rank\s+stores?\s+by\s+(?:sales?|ats|customer)",
        r"store\s+rank(?:ing)?.*(?:ats|customer\s+count)",
    ], _sql_store_mtd_kpi)

    register("department_mtd_sales_customers_ats", [
        r"department[\s-]?wise\s+mtd\s+sales?",
        r"dept[\s-]?wise\s+mtd\s+sales?",
        r"department[\s-]?wise.*(?:unique\s+customer|ats)",
        r"mtd\s+sales?\s+by\s+department",
    ], _sql_dept_mtd_kpi)

    register("category_mtd_sales_customers_ats", [
        r"categor(?:y|ies)[\s-]?wise\s+mtd\s+sales?",
        r"category[\s-]?wise.*(?:unique\s+customer|ats)",
        r"mtd\s+sales?\s+by\s+categor",
    ], _sql_cat_mtd_kpi)

    register("monthly_sales_since_apr_2024", [
        r"month[\s-]?wise\s+sales?\s+comparison\s+since\s+apr",
        r"monthly\s+sales?\s+since\s+(?:apr(?:il)?[\s\']?24|april\s+2024)",
        r"month[\s-]?wise\s+sales?\s+comparison.*2024",
        r"sales?\s+comparison\s+since\s+apr(?:il)?",
    ], _sql_monthly_since_apr_2024)

    register("average_sales_mtd_level", [
        r"average\s+(?:daily\s+)?sales?\s+(?:at\s+)?mtd",
        r"avg(?:erage)?\s+(?:daily\s+)?sales?\s+this\s+month",
        r"average\s+sales?\s+(?:level|per\s+day).*(?:this\s+month|mtd)",
    ], _sql_average_sales_mtd)

    register("today_sales_customers_invoices", [
        r"today(?:'?s)?\s+sales?\s+with\s+unique\s+customer",
        r"today(?:'?s)?\s+sales?\s+.*unique.*invoices?\s+billed",
        r"today(?:'?s)?\s+sales?\s+unique\s+customer\s+count",
        r"sales?\s+today\s+with\s+(?:unique\s+)?customer\s+count",
    ], _sql_today_sales_customers_invoices)

    register("all_period_growth_vs_last_year", [
        r"ytd.*qtd.*mtd.*growth.*last\s+year",
        r"(?:ytd|qtd|mtd).*(?:and|&|,).*growth.*last\s+year",
        r"all\s+period\s+growth.*last\s+year",
        r"growth\s+(?:vs|versus|compared\s+to)\s+last\s+year.*(?:ytd|qtd|mtd)",
    ], _sql_all_period_growth)

    register("ytd_growth_vs_last_year", [
        r"(?:current\s+year\s+)?ytd\s+growth\s+vs\.?\s+last\s+year",
        r"ytd\s+growth.*last\s+year\s+ytd",
        r"year[\s-]?to[\s-]?date\s+growth\s+(?:vs|versus|compared\s+to)\s+last\s+year",
    ], _sql_ytd_growth)

    register("qtd_growth_vs_last_year", [
        r"(?:current\s+year\s+)?qtd\s+growth\s+vs\.?\s+last\s+year",
        r"qtd\s+growth.*last\s+year\s+qtd",
        r"quarter[\s-]?to[\s-]?date\s+growth\s+(?:vs|versus|compared\s+to)\s+last\s+year",
    ], _sql_qtd_growth)

    register("mtd_growth_vs_last_year", [
        r"(?:current\s+year\s+)?mtd\s+growth\s+vs\.?\s+last\s+year",
        r"mtd\s+growth.*last\s+year\s+mtd",
        r"month[\s-]?to[\s-]?date\s+growth\s+(?:vs|versus|compared\s+to)\s+last\s+year",
        r"current.*mtd.*growth.*last\s+year",
    ], _sql_mtd_growth)

    register("highest_store_current_month", [
        r"which\s+store\s+has\s+(?:the\s+)?highest\s+sales?\s+(?:in\s+the\s+)?(?:current\s+month|this\s+month|mtd)",
        r"top\s+store\s+(?:by\s+sales?|this\s+month|current\s+month)",
        r"best\s+store\s+(?:this\s+month|current\s+month|mtd)",
        r"which\s+store.*highest\s+sales?.*(?:current|this)\s+month",
    ], _sql_highest_store_current_month)

    register("highest_department_sales_mtd", [
        r"which\s+department\s+has\s+(?:the\s+)?highest\s+sales?\s+(?:in\s+the\s+)?(?:current\s+month|this\s+month|mtd)",
        r"top\s+department\s+(?:by\s+sales?|this\s+month)",
        r"best\s+department\s+(?:this\s+month|current\s+month|mtd)",
    ], _sql_highest_department_mtd)

    register("highest_category_sales_mtd", [
        r"which\s+categor(?:y|ies)\s+has\s+(?:the\s+)?highest\s+sales?\s+(?:in\s+the\s+)?(?:current\s+month|this\s+month|mtd)",
        r"top\s+categor(?:y|ies)\s+(?:by\s+sales?|this\s+month)",
        r"best\s+categor(?:y|ies)\s+(?:this\s+month|current\s+month|mtd)",
    ], _sql_highest_category_mtd)

    register("most_selling_product_mtd", [
        r"most\s+selling\s+product\s+(?:in\s+the\s+)?(?:current\s+month|this\s+month|year|ytd|mtd)?",
        r"which\s+product\s+(?:sold|sells?)\s+(?:the\s+)?most\s+(?:this\s+month|this\s+year|mtd|ytd)?",
    ], _sql_most_selling_product_mtd)

    register("least_selling_product_mtd", [
        r"least\s+selling\s+product",
        r"which\s+product\s+(?:sold|sells?)\s+(?:the\s+)?least",
        r"bottom\s+(?:product|item)s?\s+by\s+(?:sales?|qty)",
        r"worst\s+selling\s+product",
    ], _sql_least_product_mtd)

    register("lowest_supplier_sales_mtd", [
        r"which\s+supplier\s+has\s+(?:the\s+)?lowest\s+sales?",
        r"lowest\s+supplier\s+by\s+sales?",
        r"which\s+supplier.*lowest\s+sales?.*(?:current|this)\s+month",
    ], _sql_lowest_supplier_mtd)

    register("top_stores_by_growth_pct", [
        r"top\s+\d*\s*(?:performing\s+)?stores?\s+based\s+on\s+growth",
        r"stores?\s+(?:with\s+)?highest\s+growth\s+(?:percent|pct|%)?",
        r"top\s+\d+\s+stores?\s+growth\s+(?:percent|pct|%)?",
        r"best\s+performing\s+stores?\s+(?:by\s+)?growth",
    ], _sql_top_stores_growth)

    register("bottom_stores_sales_decline", [
        r"bottom\s+\d*\s*(?:performing\s+)?stores?\s+based\s+on\s+(?:sales?\s+)?decline",
        r"stores?\s+(?:with\s+)?biggest\s+(?:sales?\s+)?decline",
        r"worst\s+performing\s+stores?\s+(?:by\s+)?(?:sales?\s+)?decline",
    ], _sql_bottom_stores_decline)

    register("products_fastest_mom_growth", [
        r"which\s+products?\s+are\s+growing\s+fastest\s+month[\s-]?over[\s-]?month",
        r"products?\s+growing\s+fastest\s+(?:mom|month[\s-]?over[\s-]?month)",
        r"fastest\s+growing\s+products?\s+(?:mom|month[\s-]?over[\s-]?month|monthly)",
    ], _sql_products_mom_growth)

    register("categories_negative_growth_trends", [
        r"which\s+categor(?:y|ies)\s+are\s+showing\s+negative\s+growth",
        r"categor(?:y|ies)\s+(?:with\s+)?negative\s+growth\s+trends?",
        r"declining\s+categor(?:y|ies)\s+trend",
    ], _sql_categories_negative_growth)

    register("expected_stock_requirement_30_days", [
        r"expected\s+stock\s+requirement\s+(?:for\s+)?next\s+30\s+days?",
        r"stock\s+(?:needed|required)\s+(?:for\s+)?next\s+30\s+days?",
    ], _sql_stock_requirement_30d)

    register("potential_stockout_prediction", [
        r"potential\s+stock[\s-]?out\s+(?:products?\s+)?prediction",
        r"predict\s+stock[\s-]?out",
        r"items?\s+at\s+risk\s+of\s+stock[\s-]?out",
    ], _sql_stockout_risk)

    register("slow_moving_inventory_identification", [
        r"slow[\s-]?moving\s+inventory\s+(?:identification|identify|report)?",
        r"identify\s+slow[\s-]?moving\s+(?:inventory|items?|products?|stock)",
        r"which\s+(?:items?|products?)\s+are\s+slow[\s-]?moving",
    ], _sql_slow_moving_inventory)

    register("fast_moving_inventory_identification", [
        r"fast[\s-]?moving\s+inventory\s+(?:identification|identify|report)?",
        r"identify\s+fast[\s-]?moving\s+(?:inventory|items?|products?|stock)",
        r"which\s+(?:items?|products?)\s+are\s+fast[\s-]?moving",
    ], _sql_fast_moving_inventory)

    register("customer_repeat_purchase_analysis", [
        r"customer\s+repeat\s+purchase\s+(?:analysis|report)?",
        r"repeat\s+purchase\s+(?:analysis|behaviour|behavior)",
        r"how\s+many\s+times\s+customers?\s+(?:purchase|buy|visit)",
    ], _sql_customer_repeat_purchase)

    register("peak_sales_hours_billing_time", [
        r"peak\s+sales?\s+hours?",
        r"peak\s+billing\s+time",
        r"best\s+(?:sales?\s+)?hours?\s+of\s+(?:the\s+)?day",
        r"hourly\s+sales?\s+(?:analysis|breakdown|distribution)",
    ], _sql_peak_sales_hours)

    register("festival_vs_non_festival_sales", [
        r"festival\s+vs\.?\s+non[\s-]?festival\s+sales?",
        r"non[\s-]?festival\s+vs\.?\s+festival\s+sales?",
        r"festive\s+vs\.?\s+non[\s-]?festive\s+sales?\s+comparison",
    ], _sql_festival_sales)

    register("weather_festival_impact_sales", [
        r"weather.*festival.*impact.*sales?",
        r"festival.*impact.*sales?\s+trend",
        r"impact\s+of\s+(?:weather|festival)\s+on\s+sales?",
        r"how\s+(?:weather|festivals?)\s+(?:affect|impact)\s+sales?",
    ], _sql_festival_sales)

    register("region_wise_sales_performance", [
        r"region[\s-]?wise\s+sales?\s+(?:performance|comparison|report)?",
        r"sales?\s+by\s+region",
        r"regional\s+sales?\s+(?:performance|comparison|analysis)",
    ], _sql_region_sales)

    register("average_basket_size_by_store", [
        r"average\s+basket\s+size\s+by\s+store",
        r"basket\s+size\s+(?:by\s+store|store[\s-]?wise)",
        r"avg(?:erage)?\s+basket\s+(?:size|value)\s+(?:by\s+)?store",
        r"store[\s-]?wise\s+(?:average\s+)?basket\s+(?:size|value)",
    ], _sql_avg_basket_by_store)

    register("average_invoice_value_trend", [
        r"average\s+invoice\s+value\s+trend",
        r"avg(?:erage)?\s+invoice\s+value\s+(?:trend|over\s+time|analysis)",
        r"invoice\s+value\s+trend\s+(?:analysis|over\s+time)?",
        r"ats\s+trend\s+(?:analysis|over\s+time|last\s+\d+\s+months?)?",
    ], _sql_invoice_value_trend)

    register("discount_impact_sales", [
        r"discount\s+impact\s+on\s+sales?\s+(?:performance)?",
        r"impact\s+of\s+discount\s+on\s+sales?",
        r"discount\s+(?:analysis|effect)\s+(?:on\s+)?sales?",
    ], _sql_discount_impact)

    register("product_recommendation_customer", [
        r"product\s+recommendation\s+based\s+on\s+customer\s+buying\s+pattern",
        r"recommend\s+products?\s+based\s+on\s+(?:customer\s+)?buying\s+pattern",
        r"customer\s+buying\s+pattern\s+(?:product\s+)?recommendation",
    ], _sql_product_recommendation)

    register("demand_forecast_store_category", [
        r"ai[\s-]?based\s+demand\s+forecast(?:ing)?\s+by\s+store\s+and\s+categor",
        r"demand\s+forecast(?:ing)?\s+(?:by\s+)?(?:store|branch).*categor",
        r"forecast\s+(?:demand|sales?)\s+(?:by\s+)?store\s+(?:and\s+)?categor",
    ], _sql_demand_forecast_store_category)

    register("daily_sales_target_achievement", [
        r"daily\s+sales?\s+target\s+(?:vs\.?\s+)?achievement",
        r"sales?\s+target\s+(?:vs\.?\s+)?achievement\s+(?:tracking|daily)?",
        r"track\s+daily\s+sales?\s+target",
    ], _sql_daily_target_achievement)

    register("high_return_low_conversion_products", [
        r"high\s+return.*low\s+conversion\s+product",
        r"products?\s+with\s+high\s+return\s+(?:rate|ratio|percentage)",
        r"which\s+products?\s+(?:have\s+)?(?:high\s+)?return\s+(?:rate|frequently)",
    ], _sql_high_return_low_sales)

    register("ai_based_alerts_sales_drop_spike", [
        r"ai[\s-]?based\s+alerts?\s+(?:for\s+)?(?:sudden\s+)?sales?\s+(?:drop|spike)",
        r"alerts?\s+(?:for\s+)?(?:sudden\s+)?sales?\s+(?:drop|spike|change)",
        r"detect\s+(?:sales?\s+)?(?:drop|spike|anomal)",
        r"(?:sudden\s+)?sales?\s+(?:drop|spike)\s+alert",
    ], _sql_sales_spike_alert)

    register("ai_business_insights_snapshot", [
        r"ai[\s-]?(?:generated|based)\s+business\s+insights?\s+(?:and\s+recommendations?)?",
        r"business\s+insights?\s+(?:and\s+)?recommendations?",
        r"ai\s+insights?\s+(?:for\s+)?(?:this\s+month|mtd|current\s+period)?",
        r"generate\s+(?:business\s+)?insights?\s+(?:and\s+)?recommendations?",
    ], _sql_ai_business_insights_snapshot)

    register("sales_trend_prediction_festivals", [
        r"sales?\s+trend\s+prediction\s+(?:for\s+)?upcoming\s+festivals?",
        r"predict\s+sales?\s+(?:for\s+)?upcoming\s+(?:festivals?|seasons?)",
        r"upcoming\s+(?:festival|season)\s+sales?\s+(?:trend|prediction|forecast)",
    ], _sql_festival_sales)
