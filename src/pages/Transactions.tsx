import { useState, useEffect, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search,
  Download,
  RefreshCw,
  Wifi,
  WifiOff,
  ChevronLeft,
  ChevronRight,
  ArrowDownCircle,
  CheckCircle2,
  Clock,
  XCircle,
  ArrowUpDown,
  Calendar,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { useTransactionSummary, useTransactions, fmtCount, fmtSmart, fetchAndApplySnapshot, prefetchTransactionsSnapshots } from '../hooks/useAnalytics';
import type { TransactionRecord } from '../lib/api';
import { fmtLakhs } from '../lib/format';

const stagger = { animate: { transition: { staggerChildren: 0.05 } } };
const row = {
  initial: { opacity: 0, x: -8 },
  animate: { opacity: 1, x: 0, transition: { type: 'spring', stiffness: 300, damping: 28 } },
};

const TIME_PERIOD_MAP: Record<string, string> = {
  Today: 'today',
  MTD: 'mtd',
  '7D': 'last_7d',
  '30D': 'last_30d',
  YTD: 'ytd',
};

type SortKey = 'invoice' | 'customer' | 'branch' | 'product' | 'amount' | 'date' | 'status';
type RowStatus = TransactionRecord['status'] | 'refunded';

function fmtDateLong(iso: string) {
  if (!iso) return '—';
  const d = new Date(iso.includes('T') ? iso : `${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleDateString('en-IN', { month: 'long', day: 'numeric', year: 'numeric' });
}

function invoiceLabel(txn: TransactionRecord) {
  const n = txn.xn_no?.trim();
  if (n) return n;
  const id = txn.id?.trim();
  if (id && id.length > 14) return `${id.slice(0, 12)}…`;
  return id || '—';
}

function customerLabel(txn: TransactionRecord) {
  const s = txn.salesperson?.trim();
  return s || '—';
}

function escapeCsvCell(s: string) {
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function downloadPageCsv(period: string, rows: TransactionRecord[]) {
  const headers = ['Invoice', 'Customer', 'Branch', 'Product', 'Amount', 'Date', 'Status'];
  const body = rows.map((r) =>
    [
      invoiceLabel(r),
      customerLabel(r),
      r.branch ?? '',
      r.itemcode ?? '',
      String(r.amount ?? ''),
      r.date ?? '',
      normalizeStatus(r.status),
    ].map(escapeCsvCell).join(','),
  );
  const csv = [headers.join(','), ...body].join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `transactions-${period}-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function normalizeStatus(s: TransactionRecord['status']): RowStatus {
  return s;
}

function StatusPill({ status }: { status: RowStatus }) {
  const styles: Record<RowStatus, { bg: string; fg: string; label: string }> = {
    completed: { bg: 'rgba(34,197,94,0.14)', fg: '#4ade80', label: 'Completed' },
    pending: { bg: 'rgba(234,88,12,0.18)', fg: '#fb923c', label: 'Pending' },
    failed: { bg: 'rgba(239,68,68,0.16)', fg: '#f87171', label: 'Failed' },
    refunded: { bg: 'rgba(59,130,246,0.18)', fg: '#60a5fa', label: 'Refunded' },
  };
  const x = styles[status] ?? styles.completed;
  return (
    <span
      className="inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold capitalize"
      style={{ background: x.bg, color: x.fg }}
    >
      {x.label}
    </span>
  );
}

export default function Transactions() {
  const { isDark } = useTheme();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedPeriod, setSelectedPeriod] = useState('MTD');
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 12;
  const [sortKey, setSortKey] = useState<SortKey>('date');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [search]);

  const period = TIME_PERIOD_MAP[selectedPeriod] ?? 'mtd';

  // Hydrate SWR cache from server snapshot on mount so data is already in cache
  // when useTransactions/useTransactionSummary initialise — no loading flash.
  useEffect(() => {
    void fetchAndApplySnapshot();
    // Also kick off a background prefetch for any period not in snapshot (today, etc.)
    prefetchTransactionsSnapshots();
  }, []);

  const { summary, loading: summaryLoading, fromApi: summaryFromApi, refetch: refetchSummary } = useTransactionSummary(period);
  const { transactions, totalCount, totalPages, dataPeriod, loading: txnLoading, refetch, fromApi: txnFromApi } =
    useTransactions({
      period,
      page,
      page_size: PAGE_SIZE,
      search: debouncedSearch || undefined,
    });

  // True while we're waiting for data that actually belongs to the current period.
  // This fires when the user switches periods and there is NO cache for the new period yet —
  // the hook keeps old-period rows visible (stale-while-revalidate) but we should show
  // skeletons in the table body so "Today" doesn't display MTD rows.
  const tableLoading = txnLoading || (!!dataPeriod && dataPeriod !== period);

  const fromApi = summaryFromApi || txnFromApi;

  const refreshAll = () => {
    void refetch();
    void refetchSummary();
  };

  /**
   * Header pending/failed: only reflect rows on the **current page** unless the backend adds aggregate status counts.
   * Today the ERP projection marks lines completed — expect 0 here.
   */
  const pageStatusCounts = useMemo(() => {
    let pending = 0;
    let failed = 0;
    for (const t of transactions as TransactionRecord[]) {
      if (t.status === 'pending') pending += 1;
      else if (t.status === 'failed') failed += 1;
    }
    return { pending, failed };
  }, [transactions]);

  // Use list totalCount as fallback for "completed" when the fast-view summary
  // disagrees (CashmemoDt vs XnDt date-column mismatch across ERP views).
  const effectiveTotalTxns = (!summaryLoading && summary.total_transactions > 0)
    ? summary.total_transactions
    : (!txnLoading && totalCount > 0 ? totalCount : summary.total_transactions);
  const completedDisplay = (summaryLoading && txnLoading) ? '…' : fmtCount(effectiveTotalTxns);
  const pendingDisplay = txnLoading ? '…' : fmtCount(pageStatusCounts.pending);
  const failedDisplay = txnLoading ? '…' : fmtCount(pageStatusCounts.failed);

  const volumeDisplay = summaryLoading ? '…' : fmtLakhs(summary.total_revenue);

  const toggleSort = useCallback((key: SortKey) => {
    setSortKey((prev) => {
      if (prev === key) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
        return prev;
      }
      setSortDir(key === 'date' || key === 'amount' ? 'desc' : 'asc');
      return key;
    });
  }, []);

  const sortedRows = useMemo(() => {
    const rows = [...(transactions as TransactionRecord[])];
    const dir = sortDir === 'asc' ? 1 : -1;
    rows.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'invoice':
          cmp = invoiceLabel(a).localeCompare(invoiceLabel(b), undefined, { sensitivity: 'base' });
          break;
        case 'customer':
          cmp = customerLabel(a).localeCompare(customerLabel(b), undefined, { sensitivity: 'base' });
          break;
        case 'branch':
          cmp = (a.branch || '').localeCompare(b.branch || '', undefined, { sensitivity: 'base' });
          break;
        case 'product':
          cmp = (a.itemcode || '').localeCompare(b.itemcode || '', undefined, { sensitivity: 'base' });
          break;
        case 'amount':
          cmp = (a.amount ?? 0) - (b.amount ?? 0);
          break;
        case 'date':
          cmp = (a.date || '').localeCompare(b.date || '');
          break;
        case 'status':
          cmp = normalizeStatus(a.status).localeCompare(normalizeStatus(b.status));
          break;
        default:
          break;
      }
      return cmp * dir;
    });
    return rows;
  }, [transactions, sortKey, sortDir]);

  const surface = {
    card: isDark ? '#161b22' : '#ffffff',
    border: isDark ? '1px solid rgba(240,246,252,0.08)' : '1px solid rgba(27,31,36,0.09)',
    borderSoft: isDark ? '1px solid rgba(240,246,252,0.06)' : '1px solid rgba(27,31,36,0.06)',
  } as const;

  const SortHead = ({ k, label, align = 'left' }: { k: SortKey; label: string; align?: 'left' | 'right' }) => (
    <th className={align === 'right' ? 'text-right' : 'text-left'}>
      <button
        type="button"
        onClick={() => toggleSort(k)}
        className={`inline-flex items-center gap-1 py-2.5 px-3 text-[11px] font-semibold uppercase tracking-wider whitespace-nowrap rounded-lg hover:brightness-125 transition-colors w-full ${
          align === 'right' ? 'justify-end' : 'justify-start'
        }`}
        style={{ color: isDark ? '#8b949e' : '#57606a' }}
      >
        {label}
        <ArrowUpDown size={11} style={{ opacity: sortKey === k ? 1 : 0.35 }} />
      </button>
    </th>
  );

  return (
    <motion.div
      variants={stagger}
      initial="initial"
      animate="animate"
      className="space-y-6 max-w-[1600px] mx-auto"
      style={{ color: 'var(--text-primary)' }}
    >
      {/* Page header */}
      <motion.div variants={row} className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1
            className="text-[1.65rem] sm:text-[1.85rem] font-bold tracking-tight"
            style={{ color: isDark ? '#f0f6fc' : '#1f2328' }}
          >
            Transactions
          </h1>
          <p className="text-sm mt-1" style={{ color: isDark ? '#8b949e' : '#57606a' }}>
            A complete log of business activity
          </p>
        </div>

        <div id="transactions-export-anchor" className="flex flex-wrap items-center gap-2">
          {fromApi ? (
            <span
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
              style={{
                background: 'rgba(34,197,94,0.12)',
                border: '1px solid rgba(34,197,94,0.22)',
                color: '#4ade80',
              }}
            >
              <Wifi size={10} /> Live ERP
            </span>
          ) : (
            !txnLoading &&
            !summaryLoading && (
              <span
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
                style={{
                  background: 'rgba(234,179,8,0.12)',
                  border: '1px solid rgba(234,179,8,0.22)',
                  color: '#eab308',
                }}
              >
                <WifiOff size={10} /> Offline
              </span>
            )
          )}

          <div
            className="flex items-center gap-0.5 p-1 rounded-xl"
            style={{
              background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.03)',
              border: surface.borderSoft,
            }}
          >
            {Object.keys(TIME_PERIOD_MAP).map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => {
                  setSelectedPeriod(p);
                  setPage(1);
                }}
                className="px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all flex items-center gap-1"
                style={{
                  background:
                    selectedPeriod === p
                      ? isDark
                        ? 'rgba(88,130,255,0.18)'
                        : 'rgba(88,130,255,0.12)'
                      : 'transparent',
                  color: selectedPeriod === p ? '#a5b4fc' : isDark ? '#8b949e' : '#57606a',
                }}
              >
                {p === 'MTD' && <Calendar size={12} />}
                {p}
              </button>
            ))}
          </div>

          <motion.button
            type="button"
            onClick={() => downloadPageCsv(period, sortedRows)}
            disabled={!sortedRows.length || txnLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white disabled:opacity-40 disabled:pointer-events-none"
            style={{
              background: 'linear-gradient(135deg, #8957e5 0%, #a371f7 100%)',
              boxShadow: '0 2px 12px rgba(137,87,229,0.35)',
            }}
            whileHover={{ scale: sortedRows.length ? 1.02 : 1 }}
            whileTap={{ scale: sortedRows.length ? 0.98 : 1 }}
          >
            <Download size={14} />
            Export
          </motion.button>
        </div>
      </motion.div>

      {/* Summary metric cards */}
      <motion.div variants={row} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          {
            label: 'Total Volume',
            value: volumeDisplay,
            icon: <ArrowDownCircle size={18} style={{ color: '#58a6ff' }} />,
            iconBg: 'rgba(88,166,255,0.12)',
            iconBorder: 'rgba(88,166,255,0.22)',
          },
          {
            label: 'Completed',
            value: completedDisplay,
            icon: <CheckCircle2 size={18} style={{ color: '#3fb950' }} />,
            iconBg: 'rgba(63,185,80,0.12)',
            iconBorder: 'rgba(63,185,80,0.22)',
          },
          {
            label: 'Pending',
            value: pendingDisplay,
            icon: <Clock size={18} style={{ color: '#d29922' }} />,
            iconBg: 'rgba(210,153,34,0.12)',
            iconBorder: 'rgba(210,153,34,0.22)',
          },
          {
            label: 'Failed',
            value: failedDisplay,
            icon: <XCircle size={18} style={{ color: '#f85149' }} />,
            iconBg: 'rgba(248,81,73,0.12)',
            iconBorder: 'rgba(248,81,73,0.22)',
          },
        ].map((card) => (
          <div
            key={card.label}
            className="rounded-2xl p-5"
            style={{
              background: surface.card,
              border: surface.border,
              boxShadow: isDark ? '0 8px 24px rgba(0,0,0,0.35)' : '0 1px 3px rgba(0,0,0,0.06)',
            }}
          >
            <div className="flex items-center gap-3 mb-3">
              <div
                className="w-10 h-10 rounded-full flex items-center justify-center"
                style={{ background: card.iconBg, border: `1px solid ${card.iconBorder}` }}
              >
                {card.icon}
              </div>
            </div>
            <p
              className="text-[10px] font-bold uppercase tracking-widest mb-1"
              style={{ color: isDark ? '#8b949e' : '#57606a' }}
            >
              {card.label}
            </p>
            {summaryLoading && (card.label === 'Total Volume' || card.label === 'Completed') ? (
              <div className="h-8 w-24 rounded animate-pulse" style={{ background: isDark ? '#21262d' : '#eaeef2' }} />
            ) : tableLoading && (card.label === 'Pending' || card.label === 'Failed') ? (
              <div className="h-8 w-10 rounded animate-pulse" style={{ background: isDark ? '#21262d' : '#eaeef2' }} />
            ) : (
              <p
                className="text-2xl font-bold tabular-nums tracking-tight"
                style={{ color: isDark ? '#f0f6fc' : '#1f2328' }}
              >
                {card.value}
              </p>
            )}
          </div>
        ))}
      </motion.div>

      {/* Recent transactions card */}
      <motion.div
        variants={row}
        className="rounded-2xl overflow-hidden"
        style={{
          background: surface.card,
          border: surface.border,
          boxShadow: isDark ? '0 8px 32px rgba(0,0,0,0.45)' : '0 1px 3px rgba(0,0,0,0.08)',
        }}
      >
        <div
          className="flex flex-col gap-3 p-4 md:p-5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
          style={{ borderBottom: surface.borderSoft }}
        >
          <div>
            <h2 className="text-base font-semibold" style={{ color: isDark ? '#f0f6fc' : '#1f2328' }}>
              Recent Transactions
            </h2>
            <p className="text-xs mt-0.5" style={{ color: isDark ? '#8b949e' : '#57606a' }}>
              {tableLoading ? 'Loading…' : `${totalCount.toLocaleString('en-IN')} records`}
            </p>
          </div>
          <div className="relative w-full sm:max-w-xs">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
              style={{ color: isDark ? '#8b949e' : '#57606a' }}
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search invoice, customer…"
              className="w-full pl-9 pr-3 py-2.5 text-xs rounded-xl outline-none"
              style={{
                background: isDark ? '#0d1117' : '#f6f8fa',
                border: surface.border,
                color: isDark ? '#e6edf3' : '#1f2328',
              }}
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-xs min-w-[920px]">
            <thead>
              <tr style={{ borderBottom: surface.border }}>
                <SortHead k="invoice" label="Invoice" />
                <SortHead k="customer" label="Customer" />
                <SortHead k="branch" label="Branch" />
                <SortHead k="product" label="Product" />
                <SortHead k="amount" label="Amount" align="right" />
                <SortHead k="date" label="Date" />
                <SortHead k="status" label="Status" />
              </tr>
            </thead>
            <tbody>
              {tableLoading ? (
                [...Array(8)].map((_, i) => (
                  <tr key={i} style={{ borderBottom: surface.borderSoft }}>
                    {[...Array(7)].map((__, j) => (
                      <td key={j} className="px-3 py-3">
                        <div
                          className="h-2.5 rounded animate-pulse"
                          style={{ background: isDark ? '#21262d' : '#eaeef2', width: j === 0 ? '72%' : '88%' }}
                        />
                      </td>
                    ))}
                  </tr>
                ))
              ) : sortedRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-16 text-center text-sm" style={{ color: isDark ? '#8b949e' : '#57606a' }}>
                    {fromApi ? 'No transactions in this period' : 'Sign in and connect the backend to load transactions'}
                  </td>
                </tr>
              ) : (
                <AnimatePresence>
                  {sortedRows.map((txn, i) => (
                    <motion.tr
                      key={`${txn.id}-${txn.itemcode}-${i}`}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: Math.min(i * 0.02, 0.2) }}
                      style={{
                        borderBottom: surface.borderSoft,
                        background: i % 2 === 0 ? (isDark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.015)') : 'transparent',
                      }}
                      className="group"
                    >
                      <td className="py-3 px-3 align-middle">
                        <span
                          className="font-semibold text-[13px] font-mono"
                          style={{ color: isDark ? '#f0f6fc' : '#1f2328' }}
                          title={invoiceLabel(txn)}
                        >
                          {invoiceLabel(txn)}
                        </span>
                      </td>
                      <td className="py-3 px-3 align-middle max-w-[140px]">
                        <span className="text-[13px] truncate block" style={{ color: isDark ? '#e6edf3' : '#24292f' }} title={customerLabel(txn)}>
                          {customerLabel(txn)}
                        </span>
                      </td>
                      <td className="py-3 px-3 align-middle text-[13px]" style={{ color: isDark ? '#c9d1d9' : '#57606a' }}>
                        {txn.branch || '—'}
                      </td>
                      <td className="py-3 px-3 align-middle max-w-[200px]">
                        <span className="text-[13px] line-clamp-2" style={{ color: isDark ? '#c9d1d9' : '#57606a' }} title={txn.itemcode ?? ''}>
                          {txn.itemcode?.trim() || '—'}
                        </span>
                      </td>
                      <td className="py-3 px-3 align-middle text-right">
                        <span
                          className="text-[13px] font-semibold tabular-nums"
                          style={{ color: isDark ? '#f0f6fc' : '#1f2328' }}
                        >
                          {fmtSmart(txn.amount ?? 0)}
                        </span>
                      </td>
                      <td className="py-3 px-3 align-middle text-[13px] whitespace-nowrap" style={{ color: isDark ? '#8b949e' : '#57606a' }}>
                        {fmtDateLong(txn.date)}
                      </td>
                      <td className="py-3 px-3 align-middle">
                        <StatusPill status={normalizeStatus(txn.status)} />
                      </td>
                    </motion.tr>
                  ))}
                </AnimatePresence>
              )}
            </tbody>
          </table>
        </div>

        <div
          className="flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between px-5 py-4"
          style={{ borderTop: surface.borderSoft }}
        >
          <span className="text-xs tabular-nums" style={{ color: isDark ? '#8b949e' : '#57606a' }}>
            Page {page} of {totalPages}
          </span>
          <div className="flex items-center gap-2">
            <motion.button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-4 py-2 rounded-xl text-xs font-semibold disabled:opacity-35"
              style={{
                background: isDark ? 'rgba(255,255,255,0.05)' : '#f6f8fa',
                border: surface.border,
                color: isDark ? '#e6edf3' : '#24292f',
              }}
              whileHover={{ scale: page === 1 ? 1 : 1.02 }}
              whileTap={{ scale: page === 1 ? 1 : 0.98 }}
            >
              <span className="inline-flex items-center gap-1.5">
                <ChevronLeft size={14} /> Previous
              </span>
            </motion.button>
            <motion.button
              type="button"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-4 py-2 rounded-xl text-xs font-semibold text-white disabled:opacity-35 disabled:pointer-events-none"
              style={{
                background: 'linear-gradient(135deg, #8957e5 0%, #6366f1 100%)',
                boxShadow: '0 2px 14px rgba(99,102,241,0.35)',
              }}
              whileHover={{ scale: page >= totalPages ? 1 : 1.02 }}
              whileTap={{ scale: page >= totalPages ? 1 : 0.98 }}
            >
              <span className="inline-flex items-center gap-1.5">
                Next <ChevronRight size={14} />
              </span>
            </motion.button>
          </div>
        </div>
      </motion.div>

      <motion.p variants={row} className="text-[11px] text-center pb-2" style={{ color: isDark ? '#6e7681' : '#656d76' }}>
        Source: line-level ERP view (branch · category · item).{' '}
        <Link to="/ai-query" className="underline font-medium" style={{ color: '#a371f7' }}>
          Ask AI
        </Link>{' '}
        for ad-hoc analysis.
      </motion.p>
    </motion.div>
  );
}
