import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MapPin, TrendingUp, TrendingDown, Activity,
  Zap, RefreshCw, Wifi, WifiOff, Search, BarChart2,
} from 'lucide-react';
import {
  BarChart, Bar, ResponsiveContainer, XAxis, YAxis, Tooltip,
  AreaChart, Area, CartesianGrid, ReferenceLine, Cell,
} from 'recharts';
import { useTheme } from '../context/ThemeContext';
import { useBranches, fmtRevenue, fmtCount, prefetchBranchesChart } from '../hooks/useAnalytics';
import { fmtLakhsAxis } from '../lib/format';
import { analytics, BranchPoint } from '../lib/api';

// ─── Types ─────────────────────────────────────────────────────────────────────
interface BranchDetail {
  branch: string;
  period: string;
  period_label: string;
  total_revenue: number;
  total_transactions: number;
  avg_daily_revenue: number;
  trend: { date: string; revenue: number; transactions: number }[];
}

type BranchPeriod = 'today' | 'last_7d' | 'last_30d' | 'mtd' | 'qtd';

const PERIOD_TABS: { key: BranchPeriod; label: string; detail: string }[] = [
  { key: 'today',    label: 'Today', detail: 'today' },
  { key: 'last_7d',  label: '7D',    detail: 'last_7d' },
  { key: 'last_30d', label: '30D',   detail: 'last_30d' },
  { key: 'mtd',      label: 'MTD',   detail: 'mtd' },
  { key: 'qtd',      label: 'QTD',   detail: 'qtd' },
];

// ─── Design tokens ────────────────────────────────────────────────────────────
const T = {
  cyan:    '#06B6D4',
  green:   '#10B981',
  amber:   '#F59E0B',
  red:     '#EF4444',
  text:    '#F8FAFC',
  muted:   '#94A3B8',
  subtle:  '#64748B',
};

// ─── Custom Tooltip ────────────────────────────────────────────────────────────
function ChartTooltip({ active, payload, label }: any) {
  const { isDark } = useTheme();
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-xl px-3 py-2.5 text-xs shadow-xl"
      style={{
        background: isDark ? '#111827' : '#ffffff',
        border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.1)',
        color: isDark ? T.text : '#0f172a',
      }}>
      <p className="font-semibold mb-1" style={{ color: T.muted }}>{label}</p>
      {payload.map((p: any) => (
        <p key={p.name} className="tabular-nums font-bold" style={{ color: T.cyan }}>
          {fmtRevenue(p.value)}
        </p>
      ))}
    </div>
  );
}

// ─── Stat Card ────────────────────────────────────────────────────────────────
function StatCard({ icon: Icon, label, value, color, loading }: {
  icon: any; label: string; value: string; color: string; loading?: boolean;
}) {
  const { isDark } = useTheme();
  return (
    <div className="rounded-2xl p-5 flex flex-col gap-3"
      style={{
        background: isDark ? '#111827' : '#ffffff',
        border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(15,23,42,0.08)',
        boxShadow: isDark ? undefined : '0 1px 3px rgba(15,23,42,0.06)',
      }}>
      <div className="w-9 h-9 rounded-xl flex items-center justify-center"
        style={{ background: `${color}18`, border: `1px solid ${color}30` }}>
        <Icon size={16} style={{ color }} />
      </div>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-widest mb-1.5"
          style={{ color: T.muted }}>{label}</p>
        {loading ? (
          <div className="h-7 w-20 rounded-lg animate-pulse"
            style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }} />
        ) : (
          <p className="text-2xl font-bold tabular-nums"
            style={{ color: isDark ? T.text : '#0f172a' }}>{value}</p>
        )}
      </div>
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────
export default function Branch() {
  const { isDark } = useTheme();
  const [period, setPeriod] = useState<BranchPeriod>('mtd');
  const [search, setSearch] = useState('');
  const { branches, loading, error, refetch, fromApi } = useBranches(period);
  const [selectedBranch, setSelectedBranch] = useState<BranchPoint | null>(null);
  const [detail, setDetail] = useState<BranchDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const listSkeleton = loading && branches.length === 0;
  const detailPeriod = PERIOD_TABS.find(t => t.key === period)?.detail ?? 'last_30d';

  useEffect(() => {
    void prefetchBranchesChart('mtd');
    void prefetchBranchesChart('last_7d');
    void prefetchBranchesChart('last_30d');
  }, []);

  useEffect(() => {
    if (branches.length > 0) setSelectedBranch(branches[0]);
    else if (!loading) setSelectedBranch(null);
  }, [branches, period]); // eslint-disable-line

  useEffect(() => {
    if (!selectedBranch) return;
    let ignore = false;
    setDetailLoading(true);
    setDetail(null);
    analytics.branchDetail(selectedBranch.branch, detailPeriod)
      .then(d => { if (!ignore) setDetail(d as BranchDetail); })
      .catch(() => { if (!ignore) setDetail(null); })
      .finally(() => { if (!ignore) setDetailLoading(false); });
    return () => { ignore = true; };
  }, [selectedBranch, detailPeriod]);

  const maxRevenue = branches.length > 0 ? Math.max(...branches.map(b => b.revenue)) : 1;
  const avgRevenue = branches.length > 0 ? branches.reduce((s, b) => s + b.revenue, 0) / branches.length : 0;

  const filteredBranches = useMemo(() =>
    search.trim()
      ? branches.filter(b => b.branch.toLowerCase().includes(search.toLowerCase()))
      : branches,
    [branches, search],
  );

  const rank = selectedBranch ? branches.findIndex(b => b.branch === selectedBranch.branch) + 1 : 0;
  const avgTicket = detail && detail.total_transactions > 0
    ? detail.total_revenue / detail.total_transactions : 0;
  const trendAvg = detail?.trend?.length
    ? detail.trend.reduce((s, d) => s + d.revenue, 0) / detail.trend.length : 0;

  const card = {
    bg: isDark ? '#111827' : '#ffffff',
    border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.08)',
  };

  return (
    <div className="flex flex-col gap-6 max-w-[1600px] mx-auto" style={{ color: T.text }}>

      {/* ── Page header ── */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-[1.75rem] font-bold tracking-tight" style={{ color: isDark ? T.text : '#0F172A' }}>
            Branch Intelligence
          </h1>
          <p className="text-sm mt-0.5" style={{ color: T.muted }}>
            {PERIOD_TABS.find(t => t.key === period)?.key === 'mtd'
              ? 'Month-to-date branch performance'
              : `${PERIOD_TABS.find(t => t.key === period)?.label} branch performance`}
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Period tabs */}
          <div className="flex items-center rounded-xl p-1 gap-0.5"
            style={{ background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.05)', border: card.border }}>
            {PERIOD_TABS.map(tab => (
              <button key={tab.key} type="button"
                onClick={() => { if (tab.key !== period) { setPeriod(tab.key); } }}
                onMouseEnter={() => prefetchBranchesChart(tab.key)}
                className="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all"
                style={{
                  background: period === tab.key ? `${T.cyan}22` : 'transparent',
                  color: period === tab.key ? T.cyan : T.muted,
                  border: period === tab.key ? `1px solid ${T.cyan}44` : '1px solid transparent',
                }}>
                {tab.label}
              </button>
            ))}
          </div>

          {fromApi ? (
            <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
              style={{ background: `${T.green}15`, border: `1px solid ${T.green}30`, color: T.green }}>
              <Wifi size={10} />
              {listSkeleton ? 'Loading…' : loading ? 'Updating…' : `${branches.length} Branches`}
            </span>
          ) : !loading && (
            <span className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
              style={{ background: `${T.amber}15`, border: `1px solid ${T.amber}30`, color: T.amber }}>
              <WifiOff size={10} /> Demo
            </span>
          )}
        </div>
      </div>

      {/* ── Main layout: sidebar + content ── */}
      <div className="grid grid-cols-12 gap-5">

        {/* ── LEFT SIDEBAR: Branch List (3 cols) ── */}
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3 }}
          className="col-span-12 md:col-span-3 flex flex-col gap-0 rounded-2xl overflow-hidden md:sticky md:top-6"
          style={{ background: card.bg, border: card.border, height: 'fit-content' }}
        >
          {/* Sidebar header */}
          <div className="px-4 pt-4 pb-3 flex-shrink-0"
            style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-[11px] font-bold uppercase tracking-widest" style={{ color: T.muted }}>
                All Branches
              </span>
              <span className="text-[10px] tabular-nums px-2 py-0.5 rounded-full font-semibold"
                style={{ background: `${T.cyan}15`, color: T.cyan }}>
                {branches.length || '—'}
              </span>
            </div>
            {/* Search */}
            <div className="relative">
              <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none"
                style={{ color: T.subtle }} />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search branch…"
                className="w-full pl-8 pr-3 py-2 text-xs rounded-lg outline-none"
                style={{
                  background: isDark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.04)',
                  border: '1px solid rgba(255,255,255,0.07)',
                  color: isDark ? T.text : '#0F172A',
                }}
              />
            </div>
          </div>

          {/* Scrollable list */}
          <div className="overflow-y-auto py-2"
            style={{ maxHeight: '72vh', scrollbarWidth: 'thin', scrollbarColor: `${T.cyan}30 transparent` }}>
            {listSkeleton ? (
              <div className="px-3 flex flex-col gap-1">
                {[...Array(6)].map((_, i) => (
                  <div key={i} className="rounded-xl p-3 animate-pulse"
                    style={{ background: 'rgba(255,255,255,0.03)' }}>
                    <div className="flex items-center gap-2.5">
                      <div className="w-7 h-7 rounded-lg" style={{ background: 'rgba(255,255,255,0.05)' }} />
                      <div className="flex-1 space-y-1.5">
                        <div className="h-2.5 rounded" style={{ background: 'rgba(255,255,255,0.06)', width: '55%' }} />
                        <div className="h-1.5 rounded" style={{ background: 'rgba(255,255,255,0.03)', width: '40%' }} />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : filteredBranches.length === 0 ? (
              <div className="py-10 text-center text-xs" style={{ color: T.muted }}>
                {error ? 'Could not load branches' : search ? 'No match' : 'No data'}
              </div>
            ) : (
              <div className="px-2 flex flex-col gap-0.5">
                {filteredBranches.map((branch, i) => {
                  const isSelected = selectedBranch?.branch === branch.branch;
                  const globalRank = branches.findIndex(b => b.branch === branch.branch) + 1;
                  const pct = (branch.revenue / maxRevenue) * 100;
                  return (
                    <motion.button
                      key={branch.branch}
                      type="button"
                      onClick={() => setSelectedBranch(branch)}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      transition={{ delay: Math.min(i * 0.015, 0.2) }}
                      className="w-full text-left rounded-xl px-3 py-2.5 relative overflow-hidden"
                      style={{
                        background: isSelected
                          ? isDark ? `${T.cyan}14` : `${T.cyan}0f`
                          : 'transparent',
                        border: isSelected ? `1px solid ${T.cyan}40` : '1px solid transparent',
                      }}
                      whileHover={{ background: isSelected ? `${T.cyan}18` : 'rgba(255,255,255,0.04)' }}
                    >
                      {/* Left accent bar on selected */}
                      {isSelected && (
                        <div className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r"
                          style={{ background: T.cyan }} />
                      )}
                      <div className="flex items-center gap-2 mb-1.5">
                        {/* Rank */}
                        <span className="text-[10px] font-bold tabular-nums w-5 shrink-0 text-right"
                          style={{ color: globalRank <= 3 ? T.cyan : T.subtle }}>
                          #{globalRank}
                        </span>
                        {/* Name */}
                        <span className="text-xs font-semibold flex-1 truncate"
                          style={{ color: isSelected ? T.cyan : isDark ? T.text : '#0F172A' }}>
                          {branch.branch}
                        </span>
                        {/* Revenue */}
                        <span className="text-[11px] font-bold tabular-nums shrink-0"
                          style={{ color: isSelected ? T.cyan : T.muted }}>
                          {fmtRevenue(branch.revenue)}
                        </span>
                      </div>
                      {/* Progress bar */}
                      <div className="ml-7 h-1 rounded-full overflow-hidden"
                        style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                        <motion.div className="h-full rounded-full"
                          initial={{ width: 0 }}
                          animate={{ width: `${pct}%` }}
                          transition={{ duration: 0.5, delay: Math.min(i * 0.015, 0.2) }}
                          style={{ background: isSelected ? T.cyan : `${T.cyan}55` }} />
                      </div>
                    </motion.button>
                  );
                })}
              </div>
            )}
          </div>
        </motion.div>

        {/* ── RIGHT CONTENT (9 cols) ── */}
        <div className="col-span-12 md:col-span-9 flex flex-col gap-5">

          <AnimatePresence mode="wait">
            {selectedBranch ? (
              <motion.div key={selectedBranch.branch + period}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.2 }}
                className="flex flex-col gap-5">

                {/* ── Branch header card ── */}
                <div className="rounded-2xl p-6"
                  style={{ background: card.bg, border: card.border }}>
                  <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="flex items-start gap-4">
                      {/* Icon */}
                      <div className="w-12 h-12 rounded-2xl flex items-center justify-center shrink-0"
                        style={{ background: `${T.cyan}18`, border: `1px solid ${T.cyan}30` }}>
                        <MapPin size={20} style={{ color: T.cyan }} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <h2 className="text-2xl font-bold" style={{ color: isDark ? T.text : '#0F172A' }}>
                            {selectedBranch.branch}
                          </h2>
                          <span className="px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                            style={{ background: `${T.green}18`, color: T.green, border: `1px solid ${T.green}30` }}>
                            Active
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-xs" style={{ color: T.muted }}>
                          <span>Rank <span style={{ color: T.cyan, fontWeight: 700 }}>#{rank}</span> of {branches.length}</span>
                          <span>·</span>
                          <span>{PERIOD_TABS.find(t => t.key === period)?.label} performance</span>
                        </div>
                      </div>
                    </div>
                    {/* Total revenue */}
                    <div className="text-right">
                      <p className="text-[11px] font-semibold uppercase tracking-widest mb-1" style={{ color: T.muted }}>
                        Total Revenue
                      </p>
                      {detailLoading ? (
                        <div className="h-9 w-32 rounded-lg animate-pulse"
                          style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }} />
                      ) : (
                        <p className="text-3xl font-bold tabular-nums" style={{ color: T.cyan }}>
                          {fmtRevenue(detail?.total_revenue ?? selectedBranch.revenue)}
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                {/* ── KPI cards row ── */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <StatCard icon={Activity} label="Transactions"
                    value={fmtCount(detail?.total_transactions ?? selectedBranch.transactions)}
                    color={T.cyan} loading={detailLoading} />
                  <StatCard icon={TrendingUp} label="Avg Daily Revenue"
                    value={fmtRevenue(detail?.avg_daily_revenue ?? 0)}
                    color={T.green} loading={detailLoading} />
                  <StatCard icon={Zap} label="Avg Ticket"
                    value={avgTicket > 0 ? fmtRevenue(avgTicket) : '—'}
                    color={T.amber} loading={detailLoading} />
                </div>

                {/* ── Revenue trend chart ── */}
                <div className="rounded-2xl p-6" style={{ background: card.bg, border: card.border }}>
                  <div className="flex items-center justify-between mb-5">
                    <div>
                      <h3 className="text-sm font-semibold" style={{ color: isDark ? T.text : '#0F172A' }}>
                        Revenue Trend
                      </h3>
                      <p className="text-xs mt-0.5" style={{ color: T.muted }}>
                        Daily revenue for {selectedBranch.branch}
                      </p>
                    </div>
                    {!detailLoading && trendAvg > 0 && (
                      <span className="text-xs px-2.5 py-1 rounded-lg font-semibold"
                        style={{ background: `${T.cyan}15`, color: T.cyan }}>
                        Avg {fmtRevenue(trendAvg)}/day
                      </span>
                    )}
                  </div>
                  <div style={{ height: 260 }}>
                    {detailLoading ? (
                      <div className="h-full flex items-end gap-1.5">
                        {[...Array(18)].map((_, i) => (
                          <div key={i} className="flex-1 rounded-t animate-pulse"
                            style={{ height: `${20 + (i % 6) * 12}%`, background: 'rgba(6,182,212,0.08)' }} />
                        ))}
                      </div>
                    ) : detail && detail.trend.length > 0 ? (
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={detail.trend.map(d => ({ ...d, label: d.date?.slice(5) }))}
                          margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                          <defs>
                            <linearGradient id="brGrad" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor={T.cyan} stopOpacity={0.2} />
                              <stop offset="95%" stopColor={T.cyan} stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3"
                            stroke={isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)'} vertical={false} />
                          <XAxis dataKey="label"
                            tick={{ fill: T.subtle, fontSize: 10 }}
                            axisLine={false} tickLine={false} interval={2} />
                          <YAxis
                            tick={{ fill: T.subtle, fontSize: 10 }}
                            axisLine={false} tickLine={false}
                            tickFormatter={v => fmtLakhsAxis(v)} width={46} />
                          {trendAvg > 0 && (
                            <ReferenceLine y={trendAvg} stroke={`${T.amber}60`} strokeDasharray="4 3"
                              label={{ value: 'Avg', position: 'right', fill: T.amber, fontSize: 10 }} />
                          )}
                          <Tooltip content={<ChartTooltip />} />
                          <Area type="monotone" dataKey="revenue" stroke={T.cyan} strokeWidth={2.5}
                            fill="url(#brGrad)" dot={false} activeDot={{ r: 4, fill: T.cyan, stroke: '#111827', strokeWidth: 2 }} />
                        </AreaChart>
                      </ResponsiveContainer>
                    ) : (
                      <div className="h-full flex items-center justify-center text-sm" style={{ color: T.muted }}>
                        No trend data for this period
                      </div>
                    )}
                  </div>
                </div>

              </motion.div>
            ) : (
              <motion.div key="empty"
                className="rounded-2xl p-16 flex flex-col items-center justify-center gap-3"
                style={{ background: card.bg, border: card.border }}>
                <BarChart2 size={28} style={{ color: T.subtle }} />
                <p className="text-sm" style={{ color: T.muted }}>Select a branch to view analytics</p>
              </motion.div>
            )}
          </AnimatePresence>

          {/* ── Revenue Ranking — All Branches ── */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 }}
            className="rounded-2xl p-6"
            style={{ background: card.bg, border: card.border }}>
            <div className="flex items-center justify-between mb-5">
              <div>
                <h3 className="text-sm font-semibold" style={{ color: isDark ? T.text : '#0F172A' }}>
                  Revenue Ranking
                </h3>
                <p className="text-xs mt-0.5" style={{ color: T.muted }}>
                  Top 10 branches · {PERIOD_TABS.find(t => t.key === period)?.label} revenue
                </p>
              </div>
            </div>

            {/* Horizontal bar list */}
            {listSkeleton ? (
              <div className="flex flex-col gap-2.5">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className="w-6 h-3 rounded animate-pulse" style={{ background: 'rgba(255,255,255,0.05)' }} />
                    <div className="flex-1 h-8 rounded-xl animate-pulse" style={{ background: 'rgba(255,255,255,0.04)' }} />
                    <div className="w-16 h-4 rounded animate-pulse" style={{ background: 'rgba(255,255,255,0.05)' }} />
                  </div>
                ))}
              </div>
            ) : branches.length > 0 ? (
              <div className="flex flex-col gap-2">
                {branches.slice(0, 10).map((b, i) => {
                  const isSelected = selectedBranch?.branch === b.branch;
                  const pct = (b.revenue / maxRevenue) * 100;
                  const isAboveAvg = b.revenue >= avgRevenue;
                  return (
                    <motion.button key={b.branch} type="button"
                      onClick={() => setSelectedBranch(b)}
                      initial={{ opacity: 0, x: 8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.04 }}
                      className="w-full flex items-center gap-3 rounded-xl px-3 py-2 text-left"
                      style={{
                        background: isSelected ? `${T.cyan}10` : 'transparent',
                        border: isSelected ? `1px solid ${T.cyan}30` : '1px solid transparent',
                      }}
                      whileHover={{ background: isSelected ? `${T.cyan}15` : 'rgba(255,255,255,0.03)' }}>
                      {/* Rank */}
                      <span className="text-[11px] font-bold tabular-nums w-6 shrink-0 text-right"
                        style={{ color: i < 3 ? T.cyan : T.subtle }}>
                        #{i + 1}
                      </span>
                      {/* Bar + name */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-xs font-semibold"
                            style={{ color: isSelected ? T.cyan : isDark ? T.text : '#1E293B' }}>
                            {b.branch}
                          </span>
                          <div className="flex items-center gap-1.5">
                            {isAboveAvg
                              ? <TrendingUp size={11} style={{ color: T.green }} />
                              : <TrendingDown size={11} style={{ color: T.subtle }} />}
                            <span className="text-[11px] font-bold tabular-nums" style={{ color: isSelected ? T.cyan : T.muted }}>
                              {fmtRevenue(b.revenue)}
                            </span>
                          </div>
                        </div>
                        <div className="h-1.5 rounded-full overflow-hidden"
                          style={{ background: 'rgba(255,255,255,0.06)' }}>
                          <motion.div className="h-full rounded-full"
                            initial={{ width: 0 }}
                            animate={{ width: `${pct}%` }}
                            transition={{ duration: 0.6, delay: i * 0.04 }}
                            style={{ background: isSelected ? T.cyan : i < 3 ? `${T.cyan}bb` : `${T.cyan}55` }} />
                        </div>
                      </div>
                    </motion.button>
                  );
                })}
              </div>
            ) : (
              <div className="py-10 text-center text-sm" style={{ color: T.muted }}>No branch data</div>
            )}
          </motion.div>

        </div>{/* end right content */}
      </div>{/* end grid */}
    </div>
  );
}
