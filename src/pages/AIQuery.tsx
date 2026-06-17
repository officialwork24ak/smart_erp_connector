import { useState, useRef, useEffect, useCallback, useMemo, memo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AreaChart, Area, ResponsiveContainer, XAxis, YAxis, CartesianGrid, BarChart, Bar,
  LineChart, Line, PieChart, Pie, Cell, Tooltip, LabelList, Legend,
} from 'recharts';
import {
  Send, Sparkles, Code2, BarChart2, Loader2,
  Zap, Brain, Terminal, Copy, Check, ArrowRight, Database, ShieldCheck,
  ChevronDown, ThumbsUp, ThumbsDown, BookMarked,
  Search, LayoutTemplate, CheckCircle2, AlertCircle, MessageSquarePlus,
  TrendingUp, Building2, Package, Users, Clock, Hash, History, Trash2,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { ai, NLQResponse, fetchPublicHealth } from '../lib/api';
import {
  buildNLQVisualization,
  formatChartValue,
  formatChartAxisValue,
  type ChartPoint,
  type ChartSeries,
  type KPICard,
} from '../lib/nlqVisualization';
import verifiedQueriesFallback from '../data/verified_nlq_queries.json';
import verifiedAiTemplates from '../data/ai_query_templates.json';
import TableExportButtons, { type ExportNotify } from '../components/export/TableExportButtons';
import { describeSqlPlan } from '../lib/sqlPlan';
import { ScrollableCartesian, PieSideLayout } from '../lib/chartLayout';

const PIE_COLORS = ['#00b8e6', '#00e67a', '#ffb800', '#a78bfa', '#f472b6', '#fb923c', '#38bdf8', '#4ade80'];
// Distinct, high-contrast colours for grouped-bar comparison series (e.g. This period vs Last).
const SERIES_COLORS = ['#00b8e6', '#ffb800', '#00e67a', '#a78bfa'];

/** 10 verified FAQ templates — source: test/verified_ai_templates.py */
const QUERY_TEMPLATES: QueryTemplate[] = verifiedAiTemplates as QueryTemplate[];

function templateTopBadge(label: string): string | null {
  const m = label.match(/\btop\s+(\d+)\b/i);
  return m ? `Top ${m[1]}` : null;
}

// ── Context topic detection ───────────────────────────────────────────────────

type Topic = 'branch' | 'product' | 'trend' | 'salesperson' | 'customer' | 'revenue' | 'department' | null;

function detectTopic(text: string): Topic {
  const q = text.toLowerCase();
  if (/department.*categor|categor.*department|dept.*level|5\s+year.*department/i.test(q)) return 'department';
  if (/branch|store|outlet|location/.test(q)) return 'branch';
  if (/product|item|sku|category|department/.test(q)) return 'product';
  if (/trend|daily|weekly|monthly|over time|last \d+/.test(q)) return 'trend';
  if (/salesperson|staff|sales person|rep/.test(q)) return 'salesperson';
  if (/customer|buyer|client/.test(q)) return 'customer';
  if (/revenue|sales|amount|income/.test(q)) return 'revenue';
  if (/department|dept/.test(q)) return 'department';
  return null;
}

const TOPIC_FOLLOW_UPS: Record<NonNullable<Topic>, string[]> = {
  branch: [
    'What is the trend for the top branch this month?',
    'Which branch had the highest growth vs last year?',
    'Compare top 3 branches side by side',
    'Show daily breakdown for the top performing branch',
  ],
  product: [
    'Which categories are growing fastest this month?',
    'Show top 20 products by revenue this quarter',
    'What is the revenue contribution % by category?',
    'Which products declined vs last month?',
  ],
  trend: [
    'What caused the peaks in this period?',
    'Show the same trend for last year',
    'Break this down by branch over time',
    'Compare weekday vs weekend revenue',
  ],
  salesperson: [
    'How have the top salespersons performed vs last month?',
    'Which salesperson has the highest average order value?',
    'Show salesperson performance by branch',
    'Who are the top 5 salespersons this quarter?',
  ],
  customer: [
    'Which branch has the most unique customers?',
    'How many new customers vs returning customers this month?',
    'What is the average spend per customer?',
    'Show customer count trend over last 6 months',
  ],
  revenue: [
    'Break this down by product category',
    'Which branch is driving the most revenue?',
    'How does this compare to last year?',
    'Show day-by-day revenue this month',
  ],
  department: [
    'Which department has the highest growth?',
    'Show department performance by branch',
    'Compare departments this month vs last month',
    'Top 5 products within the top department',
  ],
};

const STARTER_SUGGESTIONS: string[] = [
  "Today's sales",
  'YTD, QTD and MTD growth vs last year',
  'Which store has the highest sales this month?',
  'Category contribution % in total revenue',
];

function generateFollowUps(userQuestion: string, msg: Message): string[] {
  const topic = detectTopic(userQuestion);
  if (!topic) {
    // Fallback generic follow-ups based on chart type
    if (msg.chartType === 'bar' || msg.chartType === 'pie') {
      return [
        'Show as a trend over the last 30 days',
        'Compare this to last year',
        'Break this down further by branch',
      ];
    }
    if (msg.chartType === 'area' || msg.chartType === 'line') {
      return [
        'Show the same trend for last year',
        'What is the total for this period?',
        'Break down by top category',
      ];
    }
    // Conversational / greeting / help reply (no chart or table) → offer starters.
    if (!msg.chart && !msg.table) return STARTER_SUGGESTIONS;
    return [];
  }
  const pool = TOPIC_FOLLOW_UPS[topic];
  // Pick up to 3, excluding the original question
  return pool.filter(s => !s.toLowerCase().includes(userQuestion.toLowerCase().slice(0, 12))).slice(0, 3);
}

const TOPIC_ICONS: Record<NonNullable<Topic>, React.ElementType> = {
  branch: Building2,
  product: Package,
  trend: TrendingUp,
  salesperson: Users,
  customer: Users,
  revenue: Hash,
  department: Database,
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface QueryTemplate {
  id: string;
  label: string;
  question: string;
  category: string;
  builtin: boolean;
  template_id?: string;
  sql?: string;
}

interface ApprovedQuery {
  id: string;
  question: string;
  sql: string;
  savedAt: string;
}

type Feedback = 'up' | 'down' | null;
type LeftTab = 'suggestions' | 'templates' | 'history';

interface Message {
  id: string;
  role: 'user' | 'ai';
  content: string;
  sql?: string;
  chartType?: 'bar' | 'area' | 'line' | 'pie' | 'none';
  chart?: { data: ChartPoint[]; valueKey: string; series?: ChartSeries[] };
  kpiCards?: KPICard[];
  table?: { columns: string[]; rows: string[][] };
  insights?: Array<{ title?: string; description?: string; severity?: string }>;
  warnings?: string[];
  thinking?: string;
  faqTemplateId?: string | null;
  provider?: 'claude' | 'openai';
  timestamp: string;
  feedback?: Feedback;
  reusedFrom?: string;
  userQuestion?: string;
  followUps?: string[];
  recordCount?: number;
}

// ── Similarity helpers ────────────────────────────────────────────────────────

const STOP_WORDS = new Set([
  'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
  'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
  'should', 'may', 'might', 'can', 'of', 'in', 'on', 'at', 'to', 'for',
  'with', 'by', 'from', 'and', 'or', 'but', 'not', 'this', 'that',
  'what', 'how', 'who', 'me', 'my', 'i', 'show', 'get', 'give',
]);

function tokenize(text: string): Set<string> {
  return new Set(
    text.toLowerCase()
      .replace(/[^a-z0-9\s]/g, ' ')
      .split(/\s+/)
      .filter(t => t.length > 2 && !STOP_WORDS.has(t)),
  );
}

function jaccardSimilarity(a: string, b: string): number {
  const tokA = tokenize(a);
  const tokB = tokenize(b);
  if (!tokA.size && !tokB.size) return 1;
  if (!tokA.size || !tokB.size) return 0;
  const intersection = [...tokA].filter(t => tokB.has(t)).length;
  const union = new Set([...tokA, ...tokB]).size;
  return intersection / union;
}

// ── LocalStorage helpers ──────────────────────────────────────────────────────

const LS_APPROVED = 'smarterp_approved_queries';

function loadApproved(): ApprovedQuery[] {
  try { return JSON.parse(localStorage.getItem(LS_APPROVED) ?? '[]'); } catch { return []; }
}

function saveApproved(list: ApprovedQuery[]) {
  localStorage.setItem(LS_APPROVED, JSON.stringify(list.slice(0, 200)));
}

// ── Chat history (persisted conversations) ────────────────────────────────────

const LS_HISTORY = 'smarterp_chat_history';
const MAX_HISTORY = 40;

interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  conversationId?: string;
  topic: Topic;
  savedAt: string;     // ISO
}

function loadHistory(): ChatSession[] {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_HISTORY) ?? '[]');
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}

function saveHistory(list: ChatSession[]) {
  try { localStorage.setItem(LS_HISTORY, JSON.stringify(list.slice(0, MAX_HISTORY))); } catch { /* quota */ }
}

// ── Sub-components (memoized) ─────────────────────────────────────────────────

const SQLBlock = memo(function SQLBlock({ sql }: { sql: string }) {
  const { isDark } = useTheme();
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="mt-3 rounded-xl overflow-hidden"
      style={{ background: isDark ? 'rgba(0,0,0,0.4)' : 'rgba(0,0,0,0.05)', border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.1)' }}>
      <div className="flex items-center justify-between px-4 py-2"
        style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
        <div className="flex items-center gap-2">
          <Terminal size={11} style={{ color: '#00b8e6' }} />
          <span className="text-xs font-semibold font-mono" style={{ color: '#00b8e6' }}>SQL</span>
        </div>
        <motion.button onClick={copy} whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg"
          style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', color: 'var(--text-muted)' }}>
          {copied ? <Check size={10} /> : <Copy size={10} />}
          {copied ? 'Copied' : 'Copy'}
        </motion.button>
      </div>
      <pre className="p-4 text-xs font-mono overflow-x-auto max-h-48" style={{ color: isDark ? '#a5f3fc' : '#0369a1' }}>{sql}</pre>
    </div>
  );
});

const KPICards = memo(function KPICards({ cards }: { cards: KPICard[] }) {
  const { isDark } = useTheme();
  if (!cards.length) return null;
  return (
    <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
      {cards.map(card => (
        <div key={card.label} className="rounded-xl px-3 py-2.5"
          style={{ background: isDark ? 'rgba(0,184,230,0.08)' : 'rgba(0,184,230,0.06)', border: isDark ? '1px solid rgba(0,184,230,0.15)' : '1px solid rgba(0,184,230,0.12)' }}>
          <p className="text-2xs uppercase tracking-wide truncate" style={{ color: 'var(--text-muted)' }} title={card.label}>{card.label}</p>
          <p className="text-base font-bold mt-0.5 tabular-nums" style={{ color: 'var(--text-primary)' }}>{card.value}</p>
        </div>
      ))}
    </div>
  );
});

/** Min px per bar when chart scrolls horizontally. */
const BAR_SLOT_PX = 52;

function truncateChartLabel(label: string, max = 12): string {
  const s = String(label ?? '').trim();
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}

const ResultChart = memo(function ResultChart({
  type,
  data,
  valueKey,
  series,
  pieGraphicOnly = false,
}: {
  type: 'bar' | 'area' | 'line' | 'pie';
  data: ChartPoint[];
  valueKey: string;
  series?: ChartSeries[];
  pieGraphicOnly?: boolean;
}) {
  const { isDark } = useTheme();
  if (!data.length) return null;
  const multi = (series?.length ?? 0) > 1;

  const plotData = useMemo(
    () => (type === 'bar' || type === 'pie' ? [...data].sort((a, b) => b.value - a.value) : data),
    [data, type],
  );

  const fmtVal = useMemo(
    () => (v: number) => formatChartValue(Number(v), valueKey),
    [valueKey],
  );

  if (pieGraphicOnly && type === 'pie') {
    return (
      <PieChart width={200} height={200}>
        <Pie
          data={plotData}
          dataKey="value"
          nameKey="label"
          cx="50%"
          cy="50%"
          outerRadius={78}
          paddingAngle={1}
          strokeWidth={0}
        >
          {plotData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
        </Pie>
        <Tooltip
          formatter={(v: number) => fmtVal(Number(v))}
          contentStyle={{
            background: isDark ? 'rgba(8,15,26,0.97)' : 'rgba(255,255,255,0.98)',
            border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)',
            borderRadius: 10,
            fontSize: 11,
          }}
        />
      </PieChart>
    );
  }

  // Rankings (bar/pie) sort by value; time series (line/area) must keep the
  // chronological order built by nlqVisualization — never re-sort by value.

  const tick = { fill: 'var(--text-muted)', fontSize: 10 };
  const gridStroke = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const tooltipStyle = {
    background: isDark ? 'rgba(8,15,26,0.97)' : 'rgba(255,255,255,0.98)',
    border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)',
    borderRadius: 10,
    fontSize: 11,
  };
  const barHeight = type === 'bar'
    ? (plotData.length > 30 ? 280 : plotData.length > 15 ? 250 : 220)
    : 176;
  // Each category needs enough horizontal room so the value labels on top of the bars
  // don't collide. Grouped (multi-series) bars need more room per category than single bars.
  // The chart lives inside a horizontal scroller, so wide slots just enable scrolling.
  const seriesCount = multi ? (series?.length ?? 2) : 1;
  const barSlot = multi ? Math.max(78, seriesCount * 46) : BAR_SLOT_PX;
  // Show on-bar value labels while they stay legible; beyond that the tooltip + scroll carry it.
  const showBarLabels = plotData.length <= (multi ? 40 : 150);

  const fmtAxis = useMemo(
    () => (v: number) => formatChartAxisValue(Number(v), valueKey),
    [valueKey],
  );

  return (
    <div className="mt-3 rounded-xl p-4"
      style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)', border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <div className="flex items-center gap-2">
          <BarChart2 size={11} style={{ color: '#00b8e6' }} />
          <span className="text-xs font-semibold" style={{ color: '#00b8e6' }}>{valueKey}</span>
        </div>
        {type === 'bar' && plotData.length * barSlot > 400 && (
          <span className="text-2xs" style={{ color: 'var(--text-muted)' }}>
            Scroll chart horizontally → · {plotData.length}{multi ? ` × ${seriesCount}` : ''} bars
          </span>
        )}
        {type === 'bar' && plotData.length > 0 && (
          <span className="text-2xs hidden sm:inline" style={{ color: 'var(--text-muted)' }}>Values on bars</span>
        )}
      </div>
      {type === 'pie' ? (
        <PieSideLayout
          pie={
            <PieChart width={200} height={200}>
              <Pie
                data={plotData}
                dataKey="value"
                nameKey="label"
                cx="50%"
                cy="50%"
                outerRadius={78}
                paddingAngle={1}
                strokeWidth={0}
              >
                {plotData.map((_, i) => <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
              </Pie>
              <Tooltip formatter={(v: number) => fmtVal(Number(v))} contentStyle={tooltipStyle} />
            </PieChart>
          }
          side={
            <div className="overflow-y-auto max-h-[min(70vh,320px)] space-y-0.5">
              {plotData.map((d, i) => (
                <div key={i} className="flex items-center gap-2 px-1 py-1 rounded-lg text-xs"
                  style={{ background: isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)' }}>
                  <div className="w-2 h-2 rounded-sm shrink-0" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                  <span className="flex-1 truncate" style={{ color: 'var(--text-secondary)' }} title={d.label}>{d.label}</span>
                  <span className="shrink-0 font-semibold tabular-nums" style={{ color: '#00b8e6' }}>{fmtVal(d.value)}</span>
                </div>
              ))}
            </div>
          }
        />
      ) : type === 'bar' ? (
        <ScrollableCartesian itemCount={plotData.length} height={barHeight} slotPx={barSlot}>
          {() => (
            <BarChart
              data={plotData}
              margin={{ top: multi && showBarLabels ? 46 : 24, right: 12, left: 4, bottom: plotData.length > 6 ? 80 : 24 }}
              barCategoryGap="20%"
              barGap={2}
              maxBarSize={multi ? 26 : 40}
            >
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: 'var(--text-muted)', fontSize: 9, textAnchor: 'end' }}
                angle={-45}
                axisLine={false}
                tickLine={false}
                interval={0}
                tickFormatter={(v: string) => truncateChartLabel(v, 14)}
                height={plotData.length > 6 ? 80 : 36}
              />
              <YAxis tick={tick} axisLine={false} tickLine={false} tickFormatter={fmtAxis} width={56} />
              <Tooltip
                formatter={(v: number, name: string) => [fmtVal(Number(v)), multi ? name : valueKey]}
                labelFormatter={(l) => String(l)}
                contentStyle={tooltipStyle}
                cursor={{ fill: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }}
              />
              {multi && <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />}
              {multi ? (
                series!.map((s, i) => (
                  <Bar
                    key={s.key}
                    dataKey={s.key}
                    name={s.name}
                    fill={SERIES_COLORS[i % SERIES_COLORS.length]}
                    radius={[3, 3, 0, 0]}
                    opacity={0.92}
                  >
                    {showBarLabels && (
                      <LabelList
                        dataKey={s.key}
                        position="top"
                        angle={-90}
                        offset={10}
                        formatter={(v: number) => fmtVal(Number(v))}
                        style={{ fontSize: 8, fill: SERIES_COLORS[i % SERIES_COLORS.length], fontWeight: 700 }}
                      />
                    )}
                  </Bar>
                ))
              ) : (
                <Bar dataKey="value" fill="#00b8e6" radius={[4, 4, 0, 0]} opacity={0.9}>
                  {showBarLabels && (
                    <LabelList
                      dataKey="value"
                      position="top"
                      formatter={(v: number) => fmtVal(Number(v))}
                      style={{ fontSize: 9, fill: 'var(--text-primary)', fontWeight: 700 }}
                    />
                  )}
                </Bar>
              )}
            </BarChart>
          )}
        </ScrollableCartesian>
      ) : (
        <div style={{ height: barHeight }}>
        <ResponsiveContainer width="100%" height="100%">
          {type === 'area' ? (
            <AreaChart data={plotData} margin={{ top: 12, right: 12, left: 4, bottom: 4 }}>
              <defs>
                <linearGradient id="aiChartGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00b8e6" stopOpacity={0.35} />
                  <stop offset="95%" stopColor="#00b8e6" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={tick} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={tick} axisLine={false} tickLine={false} tickFormatter={fmtAxis} width={52} />
              <Tooltip
                formatter={(v: number) => [fmtVal(Number(v)), valueKey]}
                labelFormatter={(l) => String(l)}
                contentStyle={tooltipStyle}
              />
              <Area type="monotone" dataKey="value" stroke="#00b8e6" strokeWidth={2} fill="url(#aiChartGrad)" dot={plotData.length <= 24} />
            </AreaChart>
          ) : type === 'line' ? (
            <LineChart data={plotData} margin={{ top: 12, right: 12, left: 4, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} vertical={false} />
              <XAxis dataKey="label" tick={tick} axisLine={false} tickLine={false} interval="preserveStartEnd" />
              <YAxis tick={tick} axisLine={false} tickLine={false} tickFormatter={fmtAxis} width={52} />
              <Tooltip
                formatter={(v: number) => [fmtVal(Number(v)), valueKey]}
                labelFormatter={(l) => String(l)}
                contentStyle={tooltipStyle}
              />
              <Line type="monotone" dataKey="value" stroke="#00e67a" strokeWidth={2} dot={plotData.length <= 20 ? { r: 3 } : false} />
            </LineChart>
          ) : null}
        </ResponsiveContainer>
        </div>
      )}
    </div>
  );
});

const ResultTable = memo(function ResultTable({
  columns,
  rows,
  exportName,
  onExportNotify,
  totalRows,
  embedded = false,
}: {
  columns: string[];
  rows: string[][];
  exportName?: string;
  onExportNotify?: (n: ExportNotify) => void;
  /** When API returned more rows than displayed (should match rows.length after fix). */
  totalRows?: number;
  embedded?: boolean;
}) {
  const { isDark } = useTheme();
  const total = totalRows ?? rows.length;
  return (
    <div className={embedded ? 'rounded-xl overflow-hidden' : 'mt-3 rounded-xl overflow-hidden'}
      style={{ border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)' }}>
      {exportName && onExportNotify && (
        <div className="flex items-center justify-between px-3 py-2"
          style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
          <span className="text-2xs font-medium" style={{ color: 'var(--text-muted)' }}>
            {rows.length === total
              ? `${total} row(s) — full result`
              : `Showing ${rows.length} of ${total} row(s)`}
          </span>
          <TableExportButtons
            columns={columns}
            rows={rows}
            fileBaseName={exportName}
            compact
            onNotify={onExportNotify}
          />
        </div>
      )}
      <div className="overflow-x-auto overflow-y-auto max-h-[min(70vh,520px)]">
        <table className="w-full text-xs min-w-[280px]">
          <thead>
            <tr style={{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }}>
              {columns.map(col => <th key={col} className="px-3 py-2 text-left font-semibold whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{col}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} style={{ borderTop: isDark ? '1px solid rgba(255,255,255,0.04)' : '1px solid rgba(0,0,0,0.04)' }}>
                {row.map((cell, j) => <td key={j} className="px-3 py-2 whitespace-nowrap" style={{ color: j === 0 ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});

const ThinkingBubble = memo(function ThinkingBubble({ text }: { text: string }) {
  const { isDark } = useTheme();
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
      className="mt-2 px-3 py-2 rounded-lg text-xs font-mono flex items-start gap-2"
      style={{ background: isDark ? 'rgba(0,184,230,0.06)' : 'rgba(0,184,230,0.04)', border: isDark ? '1px solid rgba(0,184,230,0.12)' : '1px solid rgba(0,184,230,0.1)', color: '#00b8e6' }}>
      <Brain size={10} className="flex-shrink-0 mt-0.5" />
      <span style={{ opacity: 0.8 }}>{text}</span>
    </motion.div>
  );
});

// ── Adaptive follow-up chips ──────────────────────────────────────────────────

const AdaptiveChips = memo(function AdaptiveChips({
  followUps, onSelect, disabled,
}: { followUps: string[]; onSelect: (q: string) => void; disabled: boolean }) {
  const { isDark } = useTheme();
  if (!followUps.length) return null;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.25 }}
      className="mt-3 flex flex-wrap gap-1.5"
    >
      <span className="text-2xs self-center mr-0.5" style={{ color: 'var(--text-muted)' }}>Ask next:</span>
      {followUps.map((q, i) => (
        <motion.button
          key={i}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(q)}
          className="flex items-center gap-1 px-2.5 py-1 rounded-full text-2xs font-medium disabled:opacity-40"
          style={{
            background: isDark ? 'rgba(0,184,230,0.08)' : 'rgba(0,184,230,0.06)',
            border: isDark ? '1px solid rgba(0,184,230,0.2)' : '1px solid rgba(0,184,230,0.15)',
            color: '#00b8e6',
          }}
          whileHover={{ scale: 1.03, background: isDark ? 'rgba(0,184,230,0.15)' : 'rgba(0,184,230,0.1)' }}
          whileTap={{ scale: 0.97 }}
        >
          <ArrowRight size={9} />
          {q.length > 52 ? q.slice(0, 52) + '…' : q}
        </motion.button>
      ))}
    </motion.div>
  );
});

// ── Topic context pill ────────────────────────────────────────────────────────

const TopicPill = memo(function TopicPill({ topic }: { topic: NonNullable<Topic> }) {
  const Icon = TOPIC_ICONS[topic];
  const labels: Record<NonNullable<Topic>, string> = {
    branch: 'Branch context',
    product: 'Product context',
    trend: 'Trend context',
    salesperson: 'Sales staff context',
    customer: 'Customer context',
    revenue: 'Revenue context',
    department: 'Department context',
  };
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-2xs font-semibold"
      style={{ background: 'rgba(0,184,230,0.1)', color: '#00b8e6', border: '1px solid rgba(0,184,230,0.2)' }}
    >
      <Icon size={10} />
      {labels[topic]}
    </motion.div>
  );
});

// ── Toast notification ────────────────────────────────────────────────────────

const Toast = memo(function Toast({ message, type, visible }: { message: string; type: 'success' | 'error'; visible: boolean }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 10, scale: 0.95 }}
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2.5 rounded-2xl text-sm font-semibold text-white shadow-lg"
          style={{ background: type === 'success' ? 'linear-gradient(135deg, #00b8e6, #00e67a)' : 'linear-gradient(135deg, #ef4444, #f97316)' }}
        >
          {type === 'success' ? <CheckCircle2 size={14} /> : <AlertCircle size={14} />}
          {message}
        </motion.div>
      )}
    </AnimatePresence>
  );
});

// ── NLQ → Message converter ───────────────────────────────────────────────────

/** Never show raw {"sql":...} JSON in the chat bubble. */
function formatAiContent(resp: NLQResponse): string {
  const raw = (resp.summary || resp.description || '').trim();
  if (!raw) {
    return resp.record_count > 0
      ? `Returned ${resp.record_count} row(s). See chart and table below.`
      : 'Query completed — no rows for this period.';
  }
  if (raw.startsWith('{') || raw.startsWith('[')) {
    if (/"(sql|explanation)"\s*:/.test(raw)) {
      if (resp.record_count > 0) {
        const desc = resp.description?.trim();
        return desc && !desc.startsWith('{')
          ? desc
          : `Returned ${resp.record_count} row(s). See chart and table below.`;
      }
      return 'SQL was generated but could not be run to completion. Open View SQL below, or use FAQ templates on the left (e.g. the same festival/season question).';
    }
    try {
      JSON.parse(raw);
      return resp.record_count > 0
        ? `Returned ${resp.record_count} row(s).`
        : 'Query completed.';
    } catch { /* partial JSON — fall through */ }
  }
  return raw;
}

function nlqToMessage(
  resp: NLQResponse,
  id: string,
  usedProvider: 'claude' | 'openai',
  userQuestion: string,
  reusedFrom?: string,
): Message {
  const viz = buildNLQVisualization(resp.records ?? [], resp.chart_type);
  const providerLabel = usedProvider === 'openai' ? 'ChatGPT' : 'Claude';
  const thinkingParts = [
    reusedFrom ? '♻️ Approved SQL reused' : resp.faq_template_id ? `Verified FAQ · ${resp.faq_template_id}` : resp.from_template ? 'Template SQL' : 'Generated SQL',
    `${resp.record_count} rows`,
    resp.period_label || resp.period,
    `${resp.duration_ms}ms`,
    providerLabel,
  ];
  const msg: Message = {
    id,
    role: 'ai',
    content: formatAiContent(resp),
    sql: resp.sql,
    chartType: viz.chartType,
    chart: viz.chartType !== 'none' && viz.chartData.length ? { data: viz.chartData, valueKey: viz.valueKey, series: viz.series } : undefined,
    kpiCards: viz.kpiCards.length ? viz.kpiCards : undefined,
    table: viz.table,
    insights: (resp.insights ?? []) as Message['insights'],
    warnings: resp.warnings?.length ? resp.warnings : undefined,
    thinking: thinkingParts.filter(Boolean).join(' · '),
    faqTemplateId: resp.faq_template_id,
    provider: usedProvider,
    timestamp: new Date().toLocaleTimeString(),
    feedback: null,
    reusedFrom,
    userQuestion,
    recordCount: resp.record_count,
  };
  // Attach adaptive follow-up suggestions
  msg.followUps = generateFollowUps(userQuestion, msg);
  return msg;
}

// ── Auto-resize textarea hook ─────────────────────────────────────────────────

function useAutoResize(value: string) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [value]);
  return ref;
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AIQuery() {
  const { isDark } = useTheme();

  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [showSQL, setShowSQL] = useState<Record<string, boolean>>({});
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [dbConnected, setDbConnected] = useState<boolean | null>(null);
  const [queryCount, setQueryCount] = useState(0);
  const [lastDurationMs, setLastDurationMs] = useState<number | null>(null);
  const [provider, setProvider] = useState<'claude' | 'openai'>('openai');
  const [showProviderMenu, setShowProviderMenu] = useState(false);

  // Conversation context
  const [activeTopic, setActiveTopic] = useState<Topic>(null);

  // Suggestions state
  const [suggestions, setSuggestions] = useState<string[]>(verifiedQueriesFallback as string[]);
  const [suggestionFilter, setSuggestionFilter] = useState('');

  // Left panel tabs
  const [leftTab, setLeftTab] = useState<LeftTab>('suggestions');
  // Chat-first on phones: the side panel starts collapsed on small screens so the
  // conversation is front-and-centre; it's open by default on tablets/desktops.
  const [leftOpen, setLeftOpen] = useState(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true,
  );

  const [templateFilter, setTemplateFilter] = useState('');

  // Approved queries
  const [approvedQueries, setApprovedQueries] = useState<ApprovedQuery[]>(() => loadApproved());

  // Chat history (persisted past conversations)
  const [history, setHistory] = useState<ChatSession[]>(() => loadHistory());
  const sessionIdRef = useRef<string>(`sess_${Date.now()}`);

  // Toast
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useAutoResize(input);

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, loading]);

  useEffect(() => {
    ai.verifiedSuggestions(50)
      .then(r => {
        if (r.queries?.length) {
          setSuggestions([...new Set(r.queries)]);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchPublicHealth().then(h => setDbConnected(h?.mssql?.connected ?? false));
  }, []);

  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const handleExportNotify = useCallback((n: ExportNotify) => {
    if (n.type === 'error') {
      showToast(n.message, 'error');
      return;
    }
    if (n.link) {
      window.open(n.link, '_blank', 'noopener,noreferrer');
    }
    showToast(n.message, 'success');
  }, [showToast]);

  // ── Semantic match ─────────────────────────────────────────────────────────
  const SIMILARITY_THRESHOLD = 0.65;

  const findApprovedMatch = useCallback((query: string): ApprovedQuery | null => {
    let best: ApprovedQuery | null = null;
    let bestScore = SIMILARITY_THRESHOLD;
    for (const aq of approvedQueries) {
      const score = jaccardSimilarity(query, aq.question);
      if (score > bestScore) { bestScore = score; best = aq; }
    }
    return best;
  }, [approvedQueries]);

  // ── Persist the current conversation into history (upsert by session id) ─────
  useEffect(() => {
    const firstUser = messages.find(m => m.role === 'user');
    if (!firstUser) return;  // nothing meaningful to save yet
    const sid = sessionIdRef.current;
    const session: ChatSession = {
      id: sid,
      title: (firstUser.content || 'Conversation').slice(0, 80),
      messages,
      conversationId,
      topic: activeTopic,
      savedAt: new Date().toISOString(),
    };
    setHistory(prev => {
      const without = prev.filter(s => s.id !== sid);
      const next = [session, ...without].slice(0, MAX_HISTORY);
      saveHistory(next);
      return next;
    });
  }, [messages, conversationId, activeTopic]);

  // ── New chat ───────────────────────────────────────────────────────────────
  // Current chat is already saved by the effect above, so starting fresh never
  // loses anything — it just opens a new session id.
  const newChat = useCallback(() => {
    setMessages([]);
    setConversationId(undefined);
    setActiveTopic(null);
    setShowSQL({});
    sessionIdRef.current = `sess_${Date.now()}`;
  }, []);

  // ── Load / delete / clear history ────────────────────────────────────────────
  const loadSession = useCallback((s: ChatSession) => {
    setMessages(s.messages);
    setConversationId(s.conversationId);
    setActiveTopic(s.topic);
    setShowSQL({});
    sessionIdRef.current = s.id;
    setLeftTab('suggestions');
  }, []);

  const deleteSession = useCallback((id: string) => {
    setHistory(prev => {
      const next = prev.filter(s => s.id !== id);
      saveHistory(next);
      return next;
    });
    if (sessionIdRef.current === id) {
      setMessages([]);
      setConversationId(undefined);
      setActiveTopic(null);
      sessionIdRef.current = `sess_${Date.now()}`;
    }
  }, []);

  const clearHistory = useCallback(() => {
    setHistory([]);
    saveHistory([]);
  }, []);

  // ── Feedback ──────────────────────────────────────────────────────────────
  const handleFeedback = useCallback((msgId: string, fb: Feedback) => {
    setMessages(prev => prev.map(m => {
      if (m.id !== msgId) return m;
      if (fb === 'up' && m.sql && m.userQuestion) {
        const newApproved: ApprovedQuery = {
          id: `aq_${Date.now()}`,
          question: m.userQuestion,
          sql: m.sql,
          savedAt: new Date().toISOString(),
        };
        setApprovedQueries(prev2 => {
          const deduped = prev2.filter(q => jaccardSimilarity(q.question, m.userQuestion!) < 0.9);
          const updated = [newApproved, ...deduped];
          saveApproved(updated);
          return updated;
        });
        showToast('SQL approved and saved for reuse ✓');
      } else if (fb === 'down') {
        showToast('Feedback noted — SQL not saved', 'error');
      }
      return { ...m, feedback: m.feedback === fb ? null : fb };
    }));
  }, [showToast]);

  const filteredTemplates = useMemo(() => {
    const q = templateFilter.trim().toLowerCase();
    if (!q) return QUERY_TEMPLATES;
    return QUERY_TEMPLATES.filter(t =>
      t.label.toLowerCase().includes(q) ||
      t.question.toLowerCase().includes(q) ||
      t.category.toLowerCase().includes(q),
    );
  }, [templateFilter]);

  // ── Send message ───────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text?: string) => {
    const msg = text ?? input.trim();
    if (!msg || loading) return;
    setInput('');
    // On phones, collapse the side panel after sending so the answer is in view.
    if (typeof window !== 'undefined' && window.innerWidth < 768) setLeftOpen(false);

    // Track conversation topic
    const topic = detectTopic(msg);
    if (topic) setActiveTopic(topic);

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: msg,
      timestamp: new Date().toLocaleTimeString(),
    };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    const approvedMatch = findApprovedMatch(msg);
    const queryText = approvedMatch ? approvedMatch.question : msg;

    try {
      const resp = await ai.query({ query: queryText, conversation_id: conversationId, provider });
      if (resp.conversation_id) setConversationId(resp.conversation_id);
      setQueryCount(c => c + 1);
      setLastDurationMs(resp.duration_ms);
      const aiMsg = nlqToMessage(resp, (Date.now() + 1).toString(), provider, msg, approvedMatch?.question);
      setMessages(prev => [...prev, aiMsg]);
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Unknown error';
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'ai',
        content: `Query failed: ${detail}. Check ERP connection and try again, or pick a **FAQ template** for a verified SQL path.`,
        timestamp: new Date().toLocaleTimeString(),
        userQuestion: msg,
        warnings: [detail],
      }]);
    } finally {
      setLoading(false);
    }
  }, [input, loading, conversationId, provider, findApprovedMatch]);

  // ── Filter suggestions (topic-aware) ──────────────────────────────────────
  const filteredSuggestions = useMemo(() => {
    const base = suggestions.filter(s =>
      !suggestionFilter.trim() || s.toLowerCase().includes(suggestionFilter.toLowerCase()),
    );
    // Bubble topic-relevant suggestions to the top if we have an active topic
    if (!activeTopic || suggestionFilter.trim()) return base;
    const topicKeywords: Record<NonNullable<Topic>, string[]> = {
      branch: ['branch', 'store', 'location'],
      product: ['product', 'item', 'category', 'sku'],
      trend: ['trend', 'daily', 'monthly', 'over time'],
      salesperson: ['salesperson', 'sales person', 'staff'],
      customer: ['customer', 'buyer', 'client'],
      revenue: ['revenue', 'sales', 'amount'],
      department: ['department', 'dept'],
    };
    const kw = topicKeywords[activeTopic];
    const relevant = base.filter(s => kw.some(k => s.toLowerCase().includes(k)));
    const rest = base.filter(s => !kw.some(k => s.toLowerCase().includes(k)));
    return [...relevant, ...rest];
  }, [suggestions, suggestionFilter, activeTopic]);

  // ── Render AI message extras ───────────────────────────────────────────────
  const renderAiResults = useCallback((msg: Message) => (
    <div className="w-full mt-1 space-y-0">
      {msg.thinking && <ThinkingBubble text={msg.thinking} />}

      {msg.reusedFrom && (
        <div className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-2xs font-medium"
          style={{ background: 'rgba(167,139,250,0.12)', color: '#a78bfa', border: '1px solid rgba(167,139,250,0.25)' }}>
          <CheckCircle2 size={10} />
          Matched approved SQL
        </div>
      )}

      {msg.faqTemplateId && !msg.reusedFrom && (
        <div className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-2xs font-medium"
          style={{ background: 'rgba(0,230,122,0.1)', color: '#00e67a', border: '1px solid rgba(0,230,122,0.25)' }}>
          <ShieldCheck size={10} />
          Verified FAQ SQL
        </div>
      )}

      {/* Timeline + Logic — derived from the SQL that actually ran, so users see exactly
          which date window and calculation produced this answer (templates AND dynamic).
          Responsive: stacks on mobile, side-by-side on larger screens. */}
      {(() => {
        const plan = describeSqlPlan(msg.sql);
        if (!plan) return null;
        return (
          <div
            className="mt-2 flex flex-col gap-2 rounded-xl px-3 py-2 sm:flex-row sm:items-start sm:gap-3"
            style={{
              background: isDark ? 'rgba(0,184,230,0.06)' : 'rgba(0,184,230,0.05)',
              border: isDark ? '1px solid rgba(0,184,230,0.18)' : '1px solid rgba(0,184,230,0.2)',
            }}
          >
            <div className="flex items-center gap-1.5 shrink-0">
              <Clock size={11} style={{ color: '#00b8e6' }} />
              <span className="text-2xs font-semibold uppercase tracking-wide" style={{ color: '#00b8e6' }}>Timeline</span>
              <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>{plan.timeline}</span>
            </div>
            <div
              className="flex flex-wrap items-start gap-1.5 min-w-0 sm:border-l sm:pl-3"
              style={{ borderColor: isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)' }}
            >
              <span className="flex items-center gap-1.5 shrink-0">
                <BarChart2 size={11} style={{ color: '#00e67a' }} />
                <span className="text-2xs font-semibold uppercase tracking-wide" style={{ color: '#00e67a' }}>Logic</span>
              </span>
              <div className="flex flex-wrap gap-1">
                {plan.logic.map((l, i) => (
                  <span
                    key={i}
                    className="text-2xs px-1.5 py-0.5 rounded-md"
                    style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)', color: 'var(--text-secondary)' }}
                  >
                    {l}
                  </span>
                ))}
              </div>
            </div>
          </div>
        );
      })()}

      {msg.kpiCards && <KPICards cards={msg.kpiCards} />}
      {msg.warnings && msg.warnings.length > 0 && (
        <div className="mt-2 space-y-1">
          {msg.warnings.map((w, i) => (
            <p key={i} className="text-xs px-2 py-1 rounded-lg flex items-start gap-1.5"
              style={{ background: 'rgba(255,184,0,0.08)', color: '#ffb800', border: '1px solid rgba(255,184,0,0.2)' }}>
              <AlertCircle size={11} className="flex-shrink-0 mt-0.5" />
              {w}
            </p>
          ))}
        </div>
      )}
      {msg.chart && msg.chartType === 'pie' && msg.table ? (
        <div className="mt-3 rounded-xl p-4"
          style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)', border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
          <PieSideLayout
            pie={<ResultChart type="pie" data={msg.chart.data} valueKey={msg.chart.valueKey} pieGraphicOnly />}
            side={
              <ResultTable
                columns={msg.table.columns}
                rows={msg.table.rows}
                totalRows={msg.recordCount}
                exportName={`ai_query_${msg.id.slice(0, 8)}`}
                onExportNotify={handleExportNotify}
                embedded
              />
            }
          />
        </div>
      ) : (
        <>
          {msg.chart && msg.chartType && msg.chartType !== 'none' && (
            <ResultChart type={msg.chartType as 'bar' | 'area' | 'line' | 'pie'} data={msg.chart.data} valueKey={msg.chart.valueKey} series={msg.chart.series} />
          )}
          {msg.table && (
            <ResultTable
              columns={msg.table.columns}
              rows={msg.table.rows}
              totalRows={msg.recordCount}
              exportName={`ai_query_${msg.id.slice(0, 8)}`}
              onExportNotify={handleExportNotify}
            />
          )}
        </>
      )}
      {msg.insights && msg.insights.length > 0 && (
        <div className="mt-2 space-y-1">
          {msg.insights.slice(0, 3).map((ins, i) => (
            <p key={i} className="text-xs px-2 py-1 rounded-lg"
              style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)', color: 'var(--text-secondary)' }}>
              {ins.title ? <span className="font-semibold">{ins.title}: </span> : null}
              {ins.description}
            </p>
          ))}
        </div>
      )}

      {/* SQL toggle */}
      {msg.sql && (
        <div>
          <button onClick={() => setShowSQL(prev => ({ ...prev, [msg.id]: !prev[msg.id] }))}
            className="flex items-center gap-1.5 mt-2 text-xs px-2 py-1 rounded-lg"
            style={{ color: '#00b8e6', background: 'rgba(0,184,230,0.08)' }}>
            <Code2 size={10} />
            {showSQL[msg.id] ? 'Hide SQL' : 'View SQL'}
          </button>
          <AnimatePresence>
            {showSQL[msg.id] && (
              <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                <SQLBlock sql={msg.sql} />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Adaptive follow-up chips */}
      {msg.followUps && msg.followUps.length > 0 && (
        <AdaptiveChips followUps={msg.followUps} onSelect={sendMessage} disabled={loading} />
      )}

      {/* Feedback row */}
      <div className="flex items-center gap-2 mt-3 pt-2.5"
        style={{ borderTop: isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.05)' }}>
        <span className="text-2xs" style={{ color: 'var(--text-muted)' }}>Was this helpful?</span>
        <motion.button type="button" onClick={() => handleFeedback(msg.id, 'up')}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-2xs font-semibold"
          style={{
            background: msg.feedback === 'up' ? 'rgba(0,230,122,0.15)' : isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
            color: msg.feedback === 'up' ? '#00e67a' : 'var(--text-muted)',
            border: msg.feedback === 'up' ? '1px solid rgba(0,230,122,0.3)' : isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)',
          }}
          whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}>
          <ThumbsUp size={10} />
          {msg.feedback === 'up' ? 'Approved' : 'Approve'}
        </motion.button>
        <motion.button type="button" onClick={() => handleFeedback(msg.id, 'down')}
          className="flex items-center gap-1 px-2 py-1 rounded-lg text-2xs font-semibold"
          style={{
            background: msg.feedback === 'down' ? 'rgba(239,68,68,0.12)' : isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
            color: msg.feedback === 'down' ? '#f87171' : 'var(--text-muted)',
            border: msg.feedback === 'down' ? '1px solid rgba(239,68,68,0.25)' : isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)',
          }}
          whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}>
          <ThumbsDown size={10} />
          Not helpful
        </motion.button>
      </div>
    </div>
  ), [isDark, showSQL, loading, sendMessage, handleFeedback, handleExportNotify]);

  // ── Category color ─────────────────────────────────────────────────────────
  const categoryColor: Record<string, string> = {
    Revenue: '#00b8e6', Trends: '#00e67a', Trend: '#00e67a', Products: '#ffb800',
    Product: '#ffb800', Purchase: '#a78bfa',
    Sales: '#a78bfa', Customers: '#f472b6', Customer: '#f472b6',
    Departments: '#fb923c', Department: '#fb923c', Store: '#38bdf8',
    Category: '#ffb800', Growth: '#4ade80', Today: '#f472b6',
  };

  // ── Placeholder adapts to context ──────────────────────────────────────────
  const placeholder = useMemo(() => {
    if (activeTopic === 'branch') return 'Ask about branches… e.g. "Which branch grew the most this month?"';
    if (activeTopic === 'product') return 'Ask about products… e.g. "Top 10 items by revenue QTD"';
    if (activeTopic === 'trend') return 'Ask about trends… e.g. "Show weekly revenue for last 3 months"';
    if (activeTopic === 'salesperson') return 'Ask about sales staff… e.g. "Top salesperson by avg order value"';
    return 'Ask anything about your ERP data… Approve answers to reuse SQL.';
  }, [activeTopic]);

  return (
    <div className="flex flex-col md:flex-row gap-4 h-[calc(100dvh-96px)] md:h-[calc(100vh-108px)]">

      <Toast message={toast?.message ?? ''} type={toast?.type ?? 'success'} visible={!!toast} />

      {/* ── Left panel toggle (mobile) — chat-first; tap to reveal the panel ─── */}
      <button
        type="button"
        onClick={() => setLeftOpen(o => !o)}
        className="md:hidden flex items-center justify-between gap-2 w-full px-3 py-2 rounded-xl text-xs font-semibold flex-shrink-0"
        style={{
          background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
          border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)',
          color: 'var(--text-secondary)',
        }}
      >
        <span className="flex items-center gap-1.5">
          <ShieldCheck size={13} style={{ color: '#00b8e6' }} />
          Suggestions · Templates · History
        </span>
        <ChevronDown size={13} style={{ transform: leftOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>

      {/* ── Left panel toggle (desktop) ─────────────────────────────────────── */}
      <button
        type="button"
        onClick={() => setLeftOpen(o => !o)}
        className="hidden md:flex items-center justify-center flex-shrink-0 self-start mt-1"
        style={{
          width: 22, height: 48, borderRadius: 6,
          background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)',
          border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)',
          color: 'var(--text-muted)', cursor: 'pointer',
        }}
        title={leftOpen ? 'Collapse panel' : 'Expand panel'}
      >
        <ChevronDown size={11} style={{ transform: leftOpen ? 'rotate(90deg)' : 'rotate(-90deg)', transition: 'transform 0.2s' }} />
      </button>

      {/* ── Left panel ──────────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.25 }}
        className={`w-full flex-shrink-0 flex flex-col gap-3 min-h-0 overflow-hidden transition-all duration-300 md:max-h-full ${leftOpen ? 'max-h-80 md:w-56' : 'max-h-0 md:w-0 pointer-events-none opacity-0'}`}
      >
        {/* Stats card */}
        <div className="rounded-2xl p-4 flex-shrink-0"
          style={{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.85)', backdropFilter: 'blur(20px)', border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)' }}>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, rgba(0,184,230,0.2), rgba(0,230,122,0.2))', border: '1px solid rgba(0,184,230,0.2)' }}>
                <Brain size={16} className="text-primary-400" />
              </div>
              <div>
                <p className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>AI Analyst</p>
                <div className="flex items-center gap-1">
                  <div className={`w-1.5 h-1.5 rounded-full ${dbConnected ? 'bg-accent-400 animate-pulse' : 'bg-amber-400'}`} />
                  <p className="text-2xs" style={{ color: dbConnected ? '#00e67a' : '#ffb800' }}>
                    {dbConnected === null ? 'Checking…' : dbConnected ? 'SQL Server connected' : 'DB offline'}
                  </p>
                </div>
              </div>
            </div>
            {/* New Chat button */}
            {messages.length > 0 && (
              <motion.button
                type="button"
                onClick={newChat}
                className="flex items-center gap-1 px-2 py-1 rounded-lg text-2xs font-semibold"
                style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)', color: 'var(--text-muted)', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)' }}
                whileHover={{ scale: 1.05, color: '#00b8e6' }}
                whileTap={{ scale: 0.95 }}
                title="Start a new conversation"
              >
                <MessageSquarePlus size={11} />
                New
              </motion.button>
            )}
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Queries this session</span>
              <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>{queryCount}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Last response</span>
              <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                {lastDurationMs != null ? `${(lastDurationMs / 1000).toFixed(1)}s` : '—'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Approved SQLs</span>
              <span className="text-xs font-bold" style={{ color: '#00e67a' }}>{approvedQueries.length}</span>
            </div>
            {/* Active topic display */}
            <AnimatePresence>
              {activeTopic && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="pt-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Context</span>
                    <TopicPill topic={activeTopic} />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* Tabs + panel */}
        <div className="rounded-2xl flex-1 flex flex-col min-h-0 overflow-hidden"
          style={{ background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.85)', backdropFilter: 'blur(20px)', border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)' }}>

          <div className="flex flex-shrink-0" style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
            {([
              { id: 'suggestions' as LeftTab, label: 'Suggestions', icon: ShieldCheck },
              { id: 'templates' as LeftTab, label: 'Templates', icon: LayoutTemplate },
              { id: 'history' as LeftTab, label: 'History', icon: History },
            ] as const).map(tab => {
              const Icon = tab.icon;
              const isActive = leftTab === tab.id;
              return (
                <button key={tab.id} type="button" onClick={() => setLeftTab(tab.id)}
                  className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-semibold"
                  style={{ color: isActive ? '#00b8e6' : 'var(--text-muted)', borderBottom: isActive ? '2px solid #00b8e6' : '2px solid transparent' }}>
                  <Icon size={11} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Suggestions tab */}
          {leftTab === 'suggestions' && (
            <div className="flex flex-col flex-1 min-h-0 p-3">
              <div className="flex items-center gap-1.5 mb-2 flex-shrink-0">
                <ShieldCheck size={12} style={{ color: '#00e67a' }} />
                <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
                  {suggestions.length} verified queries
                </p>
                {activeTopic && (
                  <span className="text-2xs px-1.5 py-0.5 rounded-full ml-auto"
                    style={{ background: 'rgba(0,184,230,0.1)', color: '#00b8e6' }}>
                    sorted by context
                  </span>
                )}
              </div>
              <div className="relative mb-2 flex-shrink-0">
                <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-muted)' }} />
                <input type="search" placeholder="Filter suggestions…" value={suggestionFilter}
                  onChange={e => setSuggestionFilter(e.target.value)}
                  className="w-full pl-7 pr-3 py-1.5 rounded-lg text-xs outline-none"
                  style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)', color: 'var(--text-primary)' }} />
              </div>
              <div className="space-y-1.5 overflow-y-auto flex-1 scrollbar-none pr-0.5">
                {filteredSuggestions.map((s, i) => (
                  <motion.button key={`${i}-${s.slice(0, 24)}`} onClick={() => sendMessage(s)} disabled={loading}
                    className="w-full text-left px-3 py-2 rounded-xl text-xs flex items-start gap-2 disabled:opacity-50"
                    style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)', border: isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.05)' }}
                    whileHover={{ borderColor: 'rgba(0,184,230,0.3)', background: isDark ? 'rgba(0,184,230,0.06)' : 'rgba(0,184,230,0.04)' }}
                    whileTap={{ scale: 0.98 }}>
                    <Zap size={10} className="flex-shrink-0 mt-0.5" style={{ color: '#00b8e6' }} />
                    <span style={{ color: 'var(--text-secondary)' }}>{s}</span>
                  </motion.button>
                ))}
              </div>
            </div>
          )}

          {/* Templates tab */}
          {leftTab === 'templates' && (
            <div className="flex flex-col flex-1 min-h-0 p-3">
              <div className="flex items-center justify-between mb-2 flex-shrink-0">
                <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
                  {QUERY_TEMPLATES.length} verified templates
                </p>
                <ShieldCheck size={12} style={{ color: '#00e67a' }} />
              </div>

              <div className="relative mb-2 flex-shrink-0">
                <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-muted)' }} />
                <input type="search" placeholder="Search templates…" value={templateFilter} onChange={e => setTemplateFilter(e.target.value)}
                  className="w-full pl-7 pr-3 py-1.5 rounded-lg text-xs outline-none"
                  style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)', color: 'var(--text-primary)' }} />
              </div>

              <div className="space-y-1.5 overflow-y-auto flex-1 scrollbar-none pr-0.5">
                {filteredTemplates.length === 0 && (
                  <p className="text-xs text-center py-6" style={{ color: 'var(--text-muted)' }}>No templates match your search.</p>
                )}
                {filteredTemplates.map(tpl => {
                  const color = categoryColor[tpl.category] ?? '#94a3b8';
                  const topBadge = templateTopBadge(tpl.label);
                  return (
                    <motion.div key={tpl.id} className="group relative px-3 py-2 rounded-xl text-xs"
                      style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)', border: isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.05)' }}
                      whileHover={{ borderColor: `${color}50` }}>
                      <div className="flex items-start gap-2">
                        <div className="w-1.5 h-1.5 rounded-full flex-shrink-0 mt-1" style={{ background: color }} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <p className="font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{tpl.label}</p>
                            {topBadge && (
                              <span className="flex-shrink-0 px-1.5 py-0.5 rounded text-2xs font-bold"
                                style={{ background: `${color}20`, color }}>
                                {topBadge}
                              </span>
                            )}
                          </div>
                          <p className="text-2xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{tpl.category}</p>
                          <p className="text-2xs mt-1 line-clamp-2 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>{tpl.question}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1 mt-1.5">
                        <motion.button type="button" onClick={() => sendMessage(tpl.question)} disabled={loading}
                          className="flex items-center gap-1 px-2 py-0.5 rounded-md text-2xs font-semibold disabled:opacity-50"
                          style={{ background: `${color}18`, color }} whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}>
                          <ArrowRight size={9} /> Run
                        </motion.button>
                        <motion.button type="button" onClick={() => setInput(tpl.question)}
                          className="flex items-center gap-1 px-2 py-0.5 rounded-md text-2xs font-semibold"
                          style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.05)', color: 'var(--text-muted)' }}
                          whileHover={{ scale: 1.04 }} whileTap={{ scale: 0.96 }}>
                          Edit
                        </motion.button>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            </div>
          )}

          {/* History tab */}
          {leftTab === 'history' && (
            <div className="flex flex-col flex-1 min-h-0 p-3">
              <div className="flex items-center justify-between mb-2 flex-shrink-0">
                <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
                  {history.length} saved {history.length === 1 ? 'chat' : 'chats'}
                </p>
                {history.length > 0 && (
                  <button type="button" onClick={clearHistory}
                    className="flex items-center gap-1 text-2xs font-semibold px-2 py-1 rounded-md"
                    style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}>
                    <Trash2 size={10} /> Clear all
                  </button>
                )}
              </div>

              {history.length === 0 ? (
                <div className="flex flex-col items-center justify-center flex-1 text-center px-4">
                  <History size={26} style={{ color: 'var(--text-muted)' }} />
                  <p className="text-xs mt-2 font-semibold" style={{ color: 'var(--text-secondary)' }}>No history yet</p>
                  <p className="text-2xs mt-1 leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                    Your conversations are saved here automatically. Click any to reopen it.
                  </p>
                </div>
              ) : (
                <div className="space-y-1.5 overflow-y-auto flex-1 scrollbar-none pr-0.5">
                  {history.map(s => {
                    const isCurrent = s.id === sessionIdRef.current;
                    const turns = s.messages.filter(m => m.role === 'user').length;
                    let when = '';
                    try {
                      when = new Date(s.savedAt).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
                    } catch { when = ''; }
                    return (
                      <div key={s.id}
                        className="group relative px-3 py-2 rounded-xl text-xs cursor-pointer"
                        onClick={() => loadSession(s)}
                        style={{
                          background: isCurrent ? (isDark ? 'rgba(0,184,230,0.10)' : 'rgba(0,184,230,0.07)') : (isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)'),
                          border: isCurrent ? '1px solid rgba(0,184,230,0.35)' : (isDark ? '1px solid rgba(255,255,255,0.05)' : '1px solid rgba(0,0,0,0.05)'),
                        }}>
                        <div className="flex items-start gap-2">
                          <MessageSquarePlus size={11} className="flex-shrink-0 mt-0.5" style={{ color: '#00b8e6' }} />
                          <div className="flex-1 min-w-0">
                            <p className="font-semibold truncate" style={{ color: 'var(--text-primary)' }}>{s.title}</p>
                            <div className="flex items-center gap-1.5 mt-0.5" style={{ color: 'var(--text-muted)' }}>
                              <Clock size={9} />
                              <span className="text-2xs">{when}</span>
                              <span className="text-2xs">· {turns} {turns === 1 ? 'query' : 'queries'}</span>
                              {isCurrent && <span className="text-2xs font-bold" style={{ color: '#00b8e6' }}>· current</span>}
                            </div>
                          </div>
                          <button type="button"
                            onClick={(e) => { e.stopPropagation(); deleteSession(s.id); }}
                            aria-label="Delete conversation"
                            className="flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md"
                            style={{ color: '#ef4444', background: isDark ? 'rgba(239,68,68,0.1)' : 'rgba(239,68,68,0.08)' }}>
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </motion.div>

      {/* ── Main chat ────────────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="flex-1 flex flex-col rounded-2xl overflow-hidden min-w-0 min-h-0"
        style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(255,255,255,0.85)', backdropFilter: 'blur(20px)', border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)' }}
      >
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 md:px-5 py-3 md:py-3.5 flex-shrink-0"
          style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, #00b8e6, #00e67a)', boxShadow: '0 0 16px rgba(0,184,230,0.3)' }}>
              <Sparkles size={14} className="text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>AI Query Workspace</h2>
              <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                Approve answers to reuse SQL · Templates for saved queries
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {approvedQueries.length > 0 && (
              <div className="flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold"
                style={{ background: 'rgba(167,139,250,0.12)', color: '#a78bfa', border: '1px solid rgba(167,139,250,0.25)' }}>
                <BookMarked size={10} />
                {approvedQueries.length} approved
              </div>
            )}

            {/* Context pill in header */}
            <AnimatePresence>
              {activeTopic && <TopicPill topic={activeTopic} />}
            </AnimatePresence>

            {/* Provider toggle */}
            <div className="relative">
              <motion.button type="button" onClick={() => setShowProviderMenu(v => !v)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold"
                style={{
                  background: provider === 'claude'
                    ? 'linear-gradient(135deg, rgba(88,130,255,0.15), rgba(139,92,246,0.15))'
                    : 'linear-gradient(135deg, rgba(16,163,127,0.15), rgba(0,184,230,0.15))',
                  border: provider === 'claude' ? '1px solid rgba(88,130,255,0.35)' : '1px solid rgba(16,163,127,0.35)',
                  color: provider === 'claude' ? '#818cf8' : '#10a37f',
                }}
                whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
                <span className="text-base leading-none">{provider === 'claude' ? '⬡' : '⬢'}</span>
                {provider === 'claude' ? 'Claude' : 'ChatGPT'}
                <ChevronDown size={11} />
              </motion.button>
              <AnimatePresence>
                {showProviderMenu && (
                  <motion.div
                    initial={{ opacity: 0, y: -6, scale: 0.96 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -6, scale: 0.96 }}
                    transition={{ duration: 0.12 }}
                    className="absolute right-0 top-full mt-1.5 rounded-xl overflow-hidden z-50 min-w-[160px]"
                    style={{ background: isDark ? '#141929' : 'white', border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)', boxShadow: '0 8px 24px rgba(0,0,0,0.2)' }}
                    onMouseLeave={() => setShowProviderMenu(false)}>
                    {([
                      { key: 'claude', label: 'Claude', sub: 'Anthropic API', icon: '⬡', color: '#818cf8' },
                      { key: 'openai', label: 'ChatGPT', sub: 'OpenAI API', icon: '⬢', color: '#10a37f' },
                    ] as const).map(opt => (
                      <button key={opt.key} type="button" onClick={() => { setProvider(opt.key); setShowProviderMenu(false); }}
                        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left"
                        style={{ background: provider === opt.key ? isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)' : 'transparent' }}>
                        <span className="text-base">{opt.icon}</span>
                        <div>
                          <p className="text-xs font-semibold" style={{ color: provider === opt.key ? opt.color : 'var(--text-primary)' }}>{opt.label}</p>
                          <p className="text-2xs" style={{ color: 'var(--text-muted)' }}>{opt.sub}</p>
                        </div>
                        {provider === opt.key && <div className="ml-auto w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: opt.color }} />}
                      </button>
                    ))}
                    <div className="px-3.5 py-2 border-t" style={{ borderColor: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                      <p className="text-2xs" style={{ color: 'var(--text-muted)' }}>Affects AI summary &amp; insights. SQL runs against your ERP.</p>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* New chat button (in header, only when messages exist) */}
            {messages.length > 0 && (
              <motion.button type="button" onClick={newChat}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold"
                style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)', color: 'var(--text-muted)' }}
                whileHover={{ scale: 1.02, color: '#00b8e6' }} whileTap={{ scale: 0.97 }}>
                <MessageSquarePlus size={12} />
                New chat
              </motion.button>
            )}

            <div className="px-2.5 py-1 rounded-full text-xs font-semibold flex items-center gap-1"
              style={{ background: 'rgba(0,230,122,0.1)', color: '#00e67a', border: '1px solid rgba(0,230,122,0.2)' }}>
              <Database size={10} />
              FAQ templates
            </div>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5 scrollbar-none">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-5 py-8">
              <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                className="w-20 h-20 rounded-3xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, rgba(0,184,230,0.15), rgba(0,230,122,0.15))', border: '1px solid rgba(0,184,230,0.2)' }}>
                <Brain size={36} style={{ color: '#00b8e6' }} />
              </motion.div>
              <div className="text-center max-w-lg">
                <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--text-primary)' }}>Ask your ERP anything</h3>
                <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
                  Pick from the {suggestions.length} verified prompts on the left, use a template, or type your own question.
                  Approve answers with 👍 to save SQL for instant reuse on similar questions.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 justify-center max-w-2xl">
                {suggestions.slice(0, 6).map((s, i) => (
                  <motion.button key={i} onClick={() => sendMessage(s)} disabled={loading}
                    className="px-3 py-2 rounded-xl text-xs flex items-center gap-1.5 max-w-xs text-left disabled:opacity-50"
                    style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)', color: 'var(--text-secondary)' }}
                    whileHover={{ borderColor: 'rgba(0,184,230,0.3)', color: '#00b8e6' }}>
                    <ArrowRight size={10} className="flex-shrink-0" />
                    <span className="line-clamp-2">{s}</span>
                  </motion.button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <motion.div key={msg.id}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
            >
              <div className="w-7 h-7 rounded-xl flex items-center justify-center flex-shrink-0"
                style={msg.role === 'ai'
                  ? { background: 'linear-gradient(135deg, #00b8e6, #00e67a)', boxShadow: '0 0 12px rgba(0,184,230,0.3)' }
                  : { background: 'rgba(0,184,230,0.15)' }}>
                {msg.role === 'ai'
                  ? <Sparkles size={13} className="text-white" />
                  : <span className="text-xs font-bold" style={{ color: '#00b8e6' }}>You</span>}
              </div>
              <div className={`w-full min-w-0 flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                <div className={`rounded-2xl px-4 py-3 ${msg.role === 'user' ? 'rounded-tr-sm max-w-xl' : 'rounded-tl-sm w-full'}`}
                  style={{
                    background: msg.role === 'user'
                      ? 'linear-gradient(135deg, #00b8e6, #0092b8)'
                      : isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
                    border: msg.role === 'user' ? 'none' : isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)',
                  }}>
                  <p className="text-sm leading-relaxed whitespace-pre-line" style={{ color: msg.role === 'user' ? 'white' : 'var(--text-primary)' }}>
                    {msg.content}
                  </p>
                </div>
                {msg.role === 'ai' && renderAiResults(msg)}
                <span className="text-2xs mt-1.5 px-1" style={{ color: 'var(--text-muted)' }}>{msg.timestamp}</span>
              </div>
            </motion.div>
          ))}

          {loading && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
              <div className="w-7 h-7 rounded-xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, #00b8e6, #00e67a)' }}>
                <Sparkles size={13} className="text-white" />
              </div>
              <div className="px-4 py-3 rounded-2xl rounded-tl-sm"
                style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)', border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)' }}>
                <div className="flex items-center gap-2">
                  <Loader2 size={13} className="animate-spin" style={{ color: '#00b8e6' }} />
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    {activeTopic === 'branch' ? 'Analysing branch data…'
                      : activeTopic === 'trend' ? 'Building trend query…'
                      : activeTopic === 'product' ? 'Querying product catalogue…'
                      : 'Running verified SQL on warehouse…'}
                  </span>
                </div>
              </div>
            </motion.div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div className="p-4 flex-shrink-0"
          style={{ borderTop: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)' }}>
          {/* Context hint strip */}
          <AnimatePresence>
            {activeTopic && messages.length > 0 && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="mb-2.5 flex items-center gap-2"
              >
                <Clock size={10} style={{ color: 'var(--text-muted)' }} />
                <span className="text-2xs" style={{ color: 'var(--text-muted)' }}>
                  Conversation context: <span style={{ color: '#00b8e6' }}>{activeTopic}</span>
                  {' '}— follow-up questions will be scoped to this topic
                </span>
                <button
                  type="button"
                  onClick={() => setActiveTopic(null)}
                  className="ml-auto text-2xs px-1.5 py-0.5 rounded"
                  style={{ color: 'var(--text-muted)', background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)' }}
                >
                  Clear
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          <div className="flex gap-3 items-end">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void sendMessage(); } }}
              placeholder={placeholder}
              rows={1}
              className="flex-1 px-4 py-3 rounded-2xl text-sm resize-none outline-none scrollbar-none"
              style={{
                background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)',
                border: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.08)',
                color: 'var(--text-primary)',
                maxHeight: 120,
                minHeight: 44,
                overflowY: 'auto',
              }}
            />
            <motion.button
              onClick={() => void sendMessage()}
              disabled={!input.trim() || loading}
              className="w-11 h-11 rounded-2xl flex items-center justify-center flex-shrink-0"
              style={{ background: input.trim() && !loading ? 'linear-gradient(135deg, #00b8e6, #00e67a)' : isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}
              whileTap={input.trim() && !loading ? { scale: 0.95 } : {}}>
              <Send size={15} className="text-white" />
            </motion.button>
          </div>
          <p className="text-2xs mt-2 text-center" style={{ color: 'var(--text-muted)', opacity: 0.6 }}>
            Enter to send · Shift+Enter for new line · SQL runs read-only against your ERP
          </p>
        </div>
      </motion.div>
    </div>
  );
}
