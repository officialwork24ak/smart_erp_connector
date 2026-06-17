/**
 * Map NLQ API records → chart / KPI cards / table (no mock data).
 */

import { fmtCount, fmtLakhs, fmtLakhsAxis, fmtRupees } from './format';

export interface ChartPoint {
  label: string;
  value: number;
  // Multi-series comparisons carry each period/metric as its own numeric field
  // (e.g. TodaySales, SameDayLastWeekSales) so the chart can plot grouped bars.
  [series: string]: number | string;
}

export interface ChartSeries {
  key: string;
  name: string;
}

export interface KPICard {
  label: string;
  value: string;
  raw?: number;
}

export interface ResultTable {
  columns: string[];
  rows: string[][];
}

export interface NLQVisualization {
  chartType: 'bar' | 'area' | 'line' | 'pie' | 'none';
  chartData: ChartPoint[];
  valueKey: string;
  labelKey: string;
  kpiCards: KPICard[];
  table?: ResultTable;
  // When set (>=2), the chart renders grouped bars — one bar per series per label.
  series?: ChartSeries[];
}

const NUMERIC_HINTS = [
  'sales', 'revenue', 'amount', 'total', 'growth', 'margin', 'qty', 'quantity',
  'count', 'customers', 'invoices', 'ats', 'percent', 'pct', 'contribution',
  'bills', 'value', 'cost', 'profit', 'stock', 'turnover', 'rate',
];

const LABEL_HINTS = [
  'branch', 'store', 'category', 'department', 'supplier', 'product', 'article',
  'color', 'size', 'fabric', 'concept', 'month', 'label', 'name', 'region',
  'city', 'period', 'date', 'day', 'hour', 'season', 'group', 'segment',
];

// NOTE: do NOT include the bare substring 'day' — it false-matches metric columns like
// 'TodaySales' / 'SameDayLastWeekSales'. Real day-named date columns are caught by the
// value-shape check in isDateColumn (their values look like dates).
const DATE_COL_HINTS = ['monthstart', 'monthlabel', 'transactiondate', 'invoicedt', 'xndt', 'date', 'periodlabel', 'latestmonth'];

const SKIP_COLS = new Set(['id', 'rownum', 'rn']);

/** Match backend DB_CHAT_MAX_ROWS — full FAQ / store×category grids must not be truncated in the table. */
const NLQ_TABLE_MAX_ROWS = 3000;

function toNum(v: unknown): number | null {
  if (v == null || v === '') return null;
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  let s = String(v).replace(/,/g, '').replace(/%/g, '').replace(/₹/g, '').trim();
  // Pre-formatted lakh/crore/K/M (e.g. "39.26 L", "1.2Cr") — backend usually sends raw numbers,
  // but parsing these prevents invisible bars if formatting ever leaks into records.
  const scaled = s.match(/^(-?\d*\.?\d+)\s*([Ll]|Cr|CR|cr|K|k|M|m)?$/);
  if (scaled) {
    let n = Number(scaled[1]);
    const suf = (scaled[2] ?? '').toLowerCase();
    if (suf === 'l') n *= 100_000;
    else if (suf === 'cr') n *= 10_000_000;
    else if (suf === 'k') n *= 1_000;
    else if (suf === 'm') n *= 1_000_000;
    return Number.isFinite(n) ? n : null;
  }
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Numeric-looking columns that must never become chart bar series. */
function isNonMetricColumn(col: string): boolean {
  const l = colLower(col);
  if (l.endsWith('id') && l !== 'grid') return true;
  const bad = [
    'salesrank', 'rank', 'ranking', 'firstname', 'lastname', 'customername', 'suppliername',
    'productname', 'itemname', 'agebucket', 'bucket', 'purinvoicedate', 'invoicedate',
    'monthsin', 'monthsof', 'monthcount', 'dayssince', 'position', 'sno', 'srno', 'detail',
  ];
  return bad.some(k => l.includes(k));
}

/** True when the column has at least one non-zero numeric value in the result set. */
function seriesHasSignal(records: Record<string, unknown>[], col: string): boolean {
  const sample = records.length > 80 ? records.slice(0, 80) : records;
  return sample.some(r => {
    const n = toNum(r[col]);
    return n != null && n !== 0;
  });
}

function isNumericColumn(records: Record<string, unknown>[], col: string): boolean {
  let hits = 0;
  for (const row of records.slice(0, 12)) {
    if (toNum(row[col]) != null) hits += 1;
  }
  return hits > 0;
}

function scoreNumeric(col: string): number {
  const l = col.toLowerCase();
  if (SKIP_COLS.has(l)) return -100;
  let s = 0;
  for (const h of NUMERIC_HINTS) {
    if (l.includes(h)) s += 3;
  }
  if (l.endsWith('id')) s -= 5;
  return s;
}

function scoreLabel(col: string): number {
  const l = col.toLowerCase();
  if (SKIP_COLS.has(l)) return -100;
  let s = 0;
  for (const h of LABEL_HINTS) {
    if (l.includes(h)) s += 3;
  }
  if (l.includes('date') || l.includes('month')) s += 2;
  if (l.endsWith('id')) s -= 4;
  return s;
}

function isDateLikeLabel(label: string): boolean {
  return /^\d{4}-\d{2}-\d{2}/.test(label) || /jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec/i.test(label);
}

function isDateColumn(col: string, records: Record<string, unknown>[]): boolean {
  const l = col.toLowerCase();
  if (DATE_COL_HINTS.some(h => l.includes(h))) return true;
  const samples = records.slice(0, 8).map(r => String(r[col] ?? ''));
  return samples.filter(Boolean).length > 0 && samples.every(s => isDateLikeLabel(s) || /^\d{4}-\d{2}-\d{2}/.test(s));
}

function pickColumns(records: Record<string, unknown>[]): { valueKey: string; labelKey: string; dateKey: string | null; dimKeys: string[] } {
  const cols = Object.keys(records[0] ?? {});
  const numericCols = cols.filter(c => isNumericColumn(records, c));
  const signalCols = numericCols.filter(c => seriesHasSignal(records, c));
  const valueCandidates = signalCols.length ? signalCols : numericCols;
  const dateKey = cols.find(c => isDateColumn(c, records)) ?? null;

  const valueKey =
    [...valueCandidates].sort((a, b) => scoreNumeric(b) - scoreNumeric(a))[0] ??
    cols.find(c => isNumericColumn(records, c)) ??
    cols[0] ??
    'value';

  const dimKeys = cols.filter(c =>
    c !== valueKey &&
    c !== dateKey &&
    !numericCols.includes(c) &&
    !SKIP_COLS.has(c.toLowerCase()),
  );

  // Prefer MonthLabel over MonthStart for display when both exist
  let labelKey = dateKey ?? '';
  if (!labelKey) {
    const preferred = cols.find(c => c.toLowerCase() === 'monthlabel');
    if (preferred) labelKey = preferred;
  }
  if (!labelKey) {
    labelKey =
      [...dimKeys].sort((a, b) => scoreLabel(b) - scoreLabel(a))[0] ??
      cols.find(c => c !== valueKey && !numericCols.includes(c)) ??
      cols.find(c => c !== valueKey) ??
      valueKey;
  }

  return { valueKey, labelKey, dateKey, dimKeys };
}

function aggregateSum(records: Record<string, unknown>[], groupKey: string, valueKey: string): ChartPoint[] {
  const map = new Map<string, number>();
  for (const r of records) {
    const k = String(r[groupKey] ?? '');
    if (!k) continue;
    map.set(k, (map.get(k) ?? 0) + (toNum(r[valueKey]) ?? 0));
  }
  return [...map.entries()].map(([label, value]) => ({
    label: label.slice(0, 28),
    value,
  }));
}

function compositeLabel(row: Record<string, unknown>, dimKeys: string[]): string {
  return dimKeys
    .map(k => String(row[k] ?? '').trim())
    .filter(Boolean)
    .join(' · ');
}

function aggregateComposite(records: Record<string, unknown>[], dimKeys: string[], valueKey: string): ChartPoint[] {
  const map = new Map<string, number>();
  for (const r of records) {
    const k = compositeLabel(r, dimKeys);
    if (!k) continue;
    map.set(k, (map.get(k) ?? 0) + (toNum(r[valueKey]) ?? 0));
  }
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([label, value]) => ({ label: label.slice(0, 28), value }));
}

/**
 * Aggregate a time series by the real date column (chronological ASC),
 * but display a friendly label column (e.g. MonthLabel "April 2024") when present.
 * Sorting always uses the date column value — never the display label — so
 * "since Apr'24" charts start at Apr'24 regardless of label format.
 */
function aggregateTimeSeries(
  records: Record<string, unknown>[],
  dateKey: string,
  displayLabelKey: string | null,
  valueKey: string,
): ChartPoint[] {
  const map = new Map<string, { label: string; value: number }>();
  for (const r of records) {
    const dk = String(r[dateKey] ?? '');
    if (!dk) continue;
    const v = toNum(r[valueKey]) ?? 0;
    const existing = map.get(dk);
    if (existing) {
      existing.value += v;
    } else {
      const lbl = displayLabelKey ? String(r[displayLabelKey] ?? dk) : dk;
      map.set(dk, { label: lbl.slice(0, 28), value: v });
    }
  }
  return [...map.entries()]
    .sort(([a], [b]) => {
      const da = Date.parse(a);
      const db = Date.parse(b);
      if (!Number.isNaN(da) && !Number.isNaN(db)) return da - db;
      return a.localeCompare(b);
    })
    .map(([, p]) => p);
}

function buildChartData(
  records: Record<string, unknown>[],
  valueKey: string,
  labelKey: string,
  dateKey: string | null,
  dimKeys: string[],
): { chartData: ChartPoint[]; labelKey: string; valueKey: string } {
  // Friendly label column (e.g. MonthLabel "April 2024") shown on the axis;
  // sorting always uses the real date column.
  const friendlyLabelKey =
    records[0] && 'MonthLabel' in records[0] && dateKey !== 'MonthLabel'
      ? 'MonthLabel'
      : null;

  // Time series with extra dimensions → aggregate to monthly (or daily) totals
  if (dateKey && dimKeys.length > 0) {
    const spaced = valueKey.replace(/([A-Z])/g, ' $1').trim();
    return {
      chartData: aggregateTimeSeries(records, dateKey, friendlyLabelKey, valueKey).slice(-60),
      labelKey: friendlyLabelKey ?? dateKey,
      valueKey: /^total/i.test(spaced) ? spaced : `Total ${spaced}`,
    };
  }

  // Pure time series (one row per period)
  if (dateKey) {
    return {
      chartData: aggregateTimeSeries(records, dateKey, friendlyLabelKey, valueKey).slice(-60),
      labelKey: friendlyLabelKey ?? dateKey,
      valueKey,
    };
  }

  // Ranking / breakdown — aggregate when labels repeat (e.g. same category across months)
  const rawLabels = records.map(r => String(r[labelKey] ?? ''));
  const uniqueLabels = new Set(rawLabels.filter(Boolean));
  if (uniqueLabels.size < records.length) {
    const aggregated = aggregateSum(records, labelKey, valueKey)
      .sort((a, b) => b.value - a.value);
    return { chartData: aggregated, labelKey, valueKey };
  }

  // Multi-dimension ranking without date — composite label
  if (dimKeys.length >= 2) {
    const aggregated = aggregateComposite(records, dimKeys, valueKey);
    return {
      chartData: aggregated,
      labelKey: dimKeys.join(' · '),
      valueKey,
    };
  }

  return {
    chartData: records.map((r, i) => ({
      label: String(r[labelKey] ?? `#${i + 1}`).slice(0, 40),
      value: toNum(r[valueKey]) ?? 0,
    })),
    labelKey,
    valueKey,
  };
}

function formatCompact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
  if (abs >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  if (Number.isInteger(n)) return n.toLocaleString('en-IN');
  return n.toLocaleString('en-IN', { maximumFractionDigits: 2 });
}

const SALES_COL_HINTS = [
  'sales', 'revenue', 'amount', 'netsales', 'mtdsales', 'totalsales', 'turnover', 'margin',
];
const COUNT_COL_HINTS = [
  'count', 'customers', 'customer', 'invoices', 'invoice', 'bills', 'billcount', 'qty', 'quantity', 'units',
];
const RUPEE_AVG_HINTS = ['ats', 'avg', 'average', 'ticket', 'basket', 'billvalue', 'invoicevalue', 'avginvoice'];
const PERCENT_COL_HINTS = ['percent', 'pct', 'growth', 'contribution', 'rate', 'share'];

function colLower(col?: string): string {
  return (col ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function isSalesColumn(col?: string): boolean {
  const l = colLower(col);
  if (!l) return false;
  if (RUPEE_AVG_HINTS.some(h => l.includes(h))) return false;
  if (COUNT_COL_HINTS.some(h => l.includes(h)) && !l.includes('sales')) return false;
  return SALES_COL_HINTS.some(h => l.includes(h));
}

function isCountColumn(col?: string): boolean {
  const l = colLower(col);
  return COUNT_COL_HINTS.some(h => l.includes(h)) && !l.includes('sales');
}

function isRupeeAvgColumn(col?: string): boolean {
  const l = colLower(col);
  return RUPEE_AVG_HINTS.some(h => l.includes(h));
}

function isPercentColumn(col?: string): boolean {
  const l = colLower(col);
  return PERCENT_COL_HINTS.some(h => l.includes(h));
}

/** Unit/scale family of a numeric column — only same-family columns may share grouped bars. */
function numericCategory(col?: string): 'sales' | 'count' | 'rupeeAvg' | 'percent' | 'other' {
  if (isPercentColumn(col)) return 'percent';
  if (isRupeeAvgColumn(col)) return 'rupeeAvg';
  if (isCountColumn(col)) return 'count';
  if (isSalesColumn(col)) return 'sales';
  return 'other';
}

function formatNumeric(n: number, col?: string, opts?: { axis?: boolean }): string {
  if (isPercentColumn(col)) return `${n.toFixed(2)}%`;
  if (isCountColumn(col)) return fmtCount(n);
  if (isRupeeAvgColumn(col)) return fmtRupees(n);
  if (isSalesColumn(col) || Math.abs(n) >= 100_000) {
    return opts?.axis ? fmtLakhsAxis(n) : fmtLakhs(n);
  }
  return formatCompact(n);
}

function formatCell(v: unknown, col?: string, maxTextLen = 28): string {
  if (v == null) return '—';
  const n = toNum(v);
  if (n != null) return formatNumeric(n, col);
  if (v instanceof Date) return v.toISOString().slice(0, 19).replace('T', ' ');
  const s = String(v);
  return s.length > maxTextLen ? `${s.slice(0, maxTextLen - 2)}…` : s;
}

/** Detect key-value metric tables like (Metric | Value | Detail) — show as KPI cards, not a chart */
function isMetricKeyValueTable(records: Record<string, unknown>[]): boolean {
  if (records.length < 2 || records.length > 20) return false;
  const cols = Object.keys(records[0]);
  if (cols.length < 2 || cols.length > 3) return false;
  const firstColLower = cols[0].toLowerCase();
  const secondColLower = cols[1].toLowerCase();
  // First column must be a text "Metric/Label" column, second must be numeric
  const firstIsLabel = ['metric', 'label', 'kpi', 'indicator', 'name'].some(h => firstColLower.includes(h));
  const secondIsNum = records.every(r => toNum(r[cols[1]]) != null || r[cols[1]] == null);
  // All values in first column must be distinct strings
  const vals = records.map(r => String(r[cols[0]] ?? ''));
  const allDistinct = new Set(vals).size === vals.length;
  return firstIsLabel && secondIsNum && allDistinct;
}

export function buildNLQVisualization(
  records: Record<string, unknown>[],
  chartTypeHint?: string,
): NLQVisualization {
  if (!records.length) {
    return { chartType: 'none', chartData: [], valueKey: '', labelKey: '', kpiCards: [] };
  }

  const { valueKey, labelKey, dateKey, dimKeys } = pickColumns(records);
  const rowCount = records.length;

  // Key-value metric table → KPI cards (e.g. AI insights: Metric | Value | Detail)
  if (isMetricKeyValueTable(records)) {
    const cols = Object.keys(records[0]);
    const metricCol = cols[0];
    const valueCol = cols[1];
    const detailCol = cols[2] ?? null;
    const cards: KPICard[] = records.map(r => {
      const n = toNum(r[valueCol]);
      const detail = detailCol ? String(r[detailCol] ?? '').trim() : '';
      const labelBase = String(r[metricCol] ?? '');
      return {
        label: detail ? `${labelBase} — ${detail}` : labelBase,
        value: n != null ? formatNumeric(n, valueCol) : '—',
        raw: n ?? undefined,
      };
    });
    const table: ResultTable = {
      columns: cols,
      rows: records.map(r => cols.map(c => formatCell(r[c], c))),
    };
    return { chartType: 'none', chartData: [], valueKey: valueCol, labelKey: metricCol, kpiCards: cards, table };
  }

  // Single scalar row → KPI cards from numeric columns, plus any
  // identifying text columns (e.g. SupplierName, CustomerName) so
  // "which X has the highest Y" results show *who* X is, not just Y.
  if (rowCount === 1) {
    const cards: KPICard[] = [];
    for (const col of Object.keys(records[0])) {
      const raw = records[0][col];
      const n = toNum(raw);
      if (n != null) {
        cards.push({
          label: col.replace(/([A-Z])/g, ' $1').trim(),
          value: formatNumeric(n, col),
          raw: n,
        });
        continue;
      }
      const text = raw == null ? '' : String(raw).trim();
      if (!text) continue;
      cards.push({
        label: col.replace(/([A-Z])/g, ' $1').trim(),
        value: text.length > 32 ? `${text.slice(0, 31)}…` : text,
      });
    }
    return {
      chartType: 'none',
      chartData: [],
      valueKey,
      labelKey,
      kpiCards: cards.slice(0, 8),
    };
  }

  // Multi-series comparison: one dimension + 2+ numeric columns of the SAME unit family
  // (e.g. TodaySales vs SameDayLastWeekSales, or This/Last/LastYear revenue). Render every
  // period as its own bar so the comparison is visible — not just the first column.
  if (!dateKey && rowCount > 1 && rowCount <= 200 && dimKeys.length >= 1) {
    const numericCols = Object.keys(records[0]).filter(
      c =>
        isNumericColumn(records, c) &&
        !SKIP_COLS.has(c.toLowerCase()) &&
        !isDateColumn(c, records) &&
        !isNonMetricColumn(c),
    );
    if (numericCols.length >= 2) {
      const byCat = new Map<string, string[]>();
      for (const c of numericCols) {
        const cat = numericCategory(c);
        byCat.set(cat, [...(byCat.get(cat) ?? []), c]);
      }
      // Prefer money/count/avg series; fall back to percent so "contribution % this vs last
      // quarter" groups both % columns. A lone growth-% next to a money column won't group
      // (its category only has 1 member), so mixed-scale bars are still avoided.
      const chosen = ['sales', 'count', 'rupeeAvg', 'percent', 'other'].find(cat => (byCat.get(cat)?.length ?? 0) >= 2);
      if (chosen) {
        const seriesCols = (byCat.get(chosen) as string[])
          .filter(c => seriesHasSignal(records, c))
          .slice(0, 4);
        if (seriesCols.length < 2) {
          // e.g. stock-out rows where OnHandQty is 0 but QtyNeeded7Days has signal — fall through
          // to single-series bar instead of a grouped chart with a flat invisible series.
        } else {
        const points: ChartPoint[] = records
          .map((r, i) => {
            const p: ChartPoint = { label: String(r[labelKey] ?? `#${i + 1}`).slice(0, 28), value: toNum(r[seriesCols[0]]) ?? 0 };
            for (const c of seriesCols) p[c] = toNum(r[c]) ?? 0;
            return p;
          })
          .sort((a, b) => (b.value as number) - (a.value as number));
        const series: ChartSeries[] = seriesCols.map(c => ({ key: c, name: c.replace(/([A-Z])/g, ' $1').trim() }));
        const cols0 = Object.keys(records[0]).slice(0, 8);
        const tbl: ResultTable = {
          columns: cols0,
          rows: records.slice(0, NLQ_TABLE_MAX_ROWS).map(r => cols0.map(c => formatCell(r[c], c))),
        };
        return { chartType: 'bar', chartData: points, valueKey: seriesCols[0], labelKey, kpiCards: [], series, table: tbl };
        }
      }
    }
  }

  const { chartData, labelKey: chartLabelKey, valueKey: chartValueKey } = buildChartData(
    records, valueKey, labelKey, dateKey, dimKeys,
  );

  const firstLabel = chartData[0]?.label ?? '';
  const hint = (chartTypeHint ?? '').toLowerCase();

  let chartType: NLQVisualization['chartType'] = 'bar';
  if (hint === 'line' || hint === 'area') {
    chartType = hint === 'line' ? 'line' : 'area';
  } else if (hint === 'pie' || hint === 'donut') {
    chartType = 'pie';
  } else if (dateKey || isDateLikeLabel(firstLabel) || /trend|daily|month/i.test(chartLabelKey)) {
    chartType = chartData.length > 14 ? 'area' : 'line';
  } else if (chartData.length <= 6) {
    chartType = 'pie';
  } else if (chartData.length > 20) {
    chartType = 'bar';
  }

  const cols = Object.keys(records[0]).slice(0, 8);
  const table: ResultTable = {
    columns: cols,
    rows: records.slice(0, NLQ_TABLE_MAX_ROWS).map(r =>
      cols.map(c => formatCell(r[c], c)),
    ),
  };

  return {
    chartType,
    chartData,
    valueKey: chartValueKey,
    labelKey: chartLabelKey,
    kpiCards: [],
    table: rowCount > 1 ? table : undefined,
  };
}

export function formatTableCell(v: unknown, col?: string, maxTextLen = 28): string {
  return formatCell(v, col, maxTextLen);
}

export function formatChartValue(n: number, valueKey?: string): string {
  return formatNumeric(n, valueKey);
}

export function formatChartAxisValue(n: number, valueKey?: string): string {
  return formatNumeric(n, valueKey, { axis: true });
}
