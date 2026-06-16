import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip as PieTooltip,
  Legend,
} from 'recharts';
import {
  RefreshCw,
  Wifi,
  WifiOff,
  Layers,
  Boxes,
  TrendingUp,
  TrendingDown,
  Search,
  ChevronLeft,
  ChevronRight,
  Package,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { useCategories, fmtRevenue, fmtCount, readCache } from '../hooks/useAnalytics';
import { analytics, TopProductRow, ProductMasterRow, ProductCatalogResponse, TopProductsResponse } from '../lib/api';
import { fmtRupees } from '../lib/format';

const TIME_RANGE_MAP: Record<string, string> = {
  MTD: 'mtd',
  '7D': 'last_7d',
  '30D': 'last_30d',
  YTD: 'ytd',
};

const PIE_COLORS = ['#5882ff', '#a78bfa', '#fb7185', '#34d399', '#fdba74', '#38bdf8', '#f472b6', '#94a3b8'];

const stagger = { animate: { transition: { staggerChildren: 0.06 } } };
const item = {
  initial: { opacity: 0, y: 14 },
  animate: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 280, damping: 28 } },
};

function truncate(s: string, max = 52) {
  if (!s) return '';
  const t = s.replace(/\s+/g, ' ').trim();
  return t.length <= max ? t : `${t.slice(0, max - 1)}…`;
}

export default function Product() {
  const { isDark } = useTheme();
  const [timeRange, setTimeRange] = useState('MTD');
  const period = TIME_RANGE_MAP[timeRange] ?? 'mtd';

  const [searchInput, setSearchInput] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 50;

  // Initialise from snapshot cache so the Products page renders instantly.
  // Cache keys match what fetchAndApplySnapshot seeds from the backend snapshot.
  const _cachedCatalog = readCache<ProductCatalogResponse>('product_catalog:50:0');
  const _cachedTop = readCache<TopProductsResponse>('top_products:mtd:15');

  const [catalog, setCatalog] = useState<ProductCatalogResponse | null>(_cachedCatalog);
  const [catalogLoading, setCatalogLoading] = useState(!_cachedCatalog);
  const [catalogError, setCatalogError] = useState<string | null>(null);

  const [topProducts, setTopProducts] = useState<TopProductRow[]>(_cachedTop?.products ?? []);
  const [topLoading, setTopLoading] = useState(!_cachedTop);
  const [topError, setTopError] = useState<string | null>(null);
  const [topSlowQuery, setTopSlowQuery] = useState(false);

  const { categories, loading: catLoading, refetch: refetchCat, fromApi: catFromApi } = useCategories(period, 8);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 400);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    setPage(1);
  }, [debouncedSearch]);

  const loadCatalog = useCallback(async () => {
    const offset = (page - 1) * pageSize;
    const isFirstPageNoSearch = page === 1 && !debouncedSearch;

    // Use snapshot cache for first page load (no search) to avoid a cold SQL Server hit.
    if (isFirstPageNoSearch) {
      const cached = readCache<ProductCatalogResponse>('product_catalog:50:0');
      if (cached?.products?.length) {
        setCatalog(cached);
        setCatalogLoading(false);
        return;
      }
    }

    setCatalogLoading(true);
    setCatalogError(null);
    try {
      const res = await analytics.productCatalog({
        search: debouncedSearch || undefined,
        limit: pageSize,
        offset,
      });
      setCatalog(res);
    } catch (e) {
      setCatalog(null);
      setCatalogError(e instanceof Error ? e.message : 'Failed to load catalog');
    } finally {
      setCatalogLoading(false);
    }
  }, [page, debouncedSearch, pageSize]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const loadTop = useCallback(async () => {
    // Use snapshot cache for MTD top products to avoid a cold SQL Server hit.
    if (period === 'mtd') {
      const cached = readCache<TopProductsResponse>('top_products:mtd:15');
      if (cached?.products?.length) {
        setTopProducts(cached.products);
        setTopLoading(false);
        return;
      }
    }

    // Clear stale rows immediately so we show skeletons rather than old-period products
    setTopProducts([]);
    setTopLoading(true);
    setTopError(null);
    setTopSlowQuery(false);
    // Warn user after 8 seconds that this query is slow (item-master view)
    const slowTimer = setTimeout(() => setTopSlowQuery(true), 8000);
    try {
      const res = await analytics.topProducts(period, 15);
      setTopProducts(res.products ?? []);
    } catch (e) {
      setTopProducts([]);
      setTopError(e instanceof Error ? e.message : 'Top products unavailable');
    } finally {
      clearTimeout(slowTimer);
      setTopLoading(false);
      setTopSlowQuery(false);
    }
  }, [period]);

  useEffect(() => {
    void loadTop();
  }, [loadTop]);

  const totalPages = catalog ? Math.max(1, Math.ceil(catalog.total_count / pageSize)) : 1;

  const pieData = useMemo(() => {
    const total = categories.reduce((s, c) => s + c.revenue, 0) || 1;
    return categories.map((c, i) => ({
      name: c.category || '—',
      value: +(c.percentage ?? (c.revenue / total) * 100).toFixed(1),
      revenue: c.revenue,
      color: PIE_COLORS[i % PIE_COLORS.length],
    }));
  }, [categories]);

  const fromApi = catFromApi && catalog != null;

  const cardStyle = {
    background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.92)',
    border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)',
  } as const;

  const thStyle = { color: 'var(--text-muted)', fontSize: 10, fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.04em' };

  const refreshAll = () => {
    void loadCatalog();
    void loadTop();
    void refetchCat();
  };

  return (
    <motion.div variants={stagger} initial="initial" animate="animate" className="space-y-5">

      <motion.div variants={item} className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{
            background: isDark ? 'linear-gradient(135deg, #f1f5f9 0%, #94a3b8 100%)' : 'linear-gradient(135deg, #0f172a 0%, #334155 100%)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'var(--text-primary)', backgroundClip: 'text',
          }}>Product Analytics</h1>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            Top sellers, category mix, and full item master (same fields as DB product view)
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {fromApi ? (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
              style={{ background: 'rgba(0,230,122,0.1)', border: '1px solid rgba(0,230,122,0.2)', color: '#00e67a' }}>
              <Wifi size={10} /> Live data
            </div>
          ) : !catalogLoading && !catLoading && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold"
              style={{ background: 'rgba(255,184,0,0.1)', border: '1px solid rgba(255,184,0,0.2)', color: '#ffb800' }}>
              <WifiOff size={10} /> Limited / offline
            </div>
          )}
          <div className="flex items-center gap-1 p-1 rounded-xl"
            style={{
              background: isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.04)',
              border: isDark ? '1px solid rgba(255,255,255,0.07)' : '1px solid rgba(0,0,0,0.07)',
            }}>
            {Object.keys(TIME_RANGE_MAP).map((r) => (
              <button key={r} type="button" onClick={() => setTimeRange(r)}
                className="px-2.5 py-1 rounded-lg text-xs font-semibold transition-all"
                style={{
                  background: timeRange === r ? (isDark ? 'rgba(88,130,255,0.2)' : 'rgba(88,130,255,0.12)') : 'transparent',
                  color: timeRange === r ? '#5882ff' : 'var(--text-muted)',
                }}>
                {r}
              </button>
            ))}
          </div>
        </div>
      </motion.div>

      {/* KPI strip — master stats (global, respects search filter for total) */}
      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          {
            label: 'SKUs (filtered)',
            value: catalogLoading ? '—' : fmtCount(catalog?.total_count ?? 0),
            sub: debouncedSearch ? `Search: “${debouncedSearch}”` : 'All rows in master view',
            icon: Boxes,
            color: '#5882ff',
          },
          {
            label: 'Departments',
            value: catalogLoading ? '—' : fmtCount(catalog?.distinct_departments ?? 0),
            sub: 'Distinct dept. short names',
            icon: Layers,
            color: '#a78bfa',
          },
          {
            label: 'Suppliers',
            value: catalogLoading ? '—' : fmtCount(catalog?.distinct_suppliers ?? 0),
            sub: 'Distinct supplier names',
            icon: Package,
            color: '#34d399',
          },
        ].map((k) => {
          const Icon = k.icon;
          return (
            <div key={k.label} className="rounded-2xl p-4 relative overflow-hidden" style={cardStyle}>
              <div className="absolute top-0 left-0 right-0 h-0.5 rounded-t-2xl"
                style={{ background: `linear-gradient(90deg, transparent, ${k.color}, transparent)` }} />
              <div className="flex items-start justify-between mb-2">
                <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{k.label}</p>
                <div className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{ background: `${k.color}18`, border: `1px solid ${k.color}35` }}>
                  <Icon size={15} style={{ color: k.color }} />
                </div>
              </div>
              <p className="text-2xl font-bold metric-value tracking-tight" style={{ color: 'var(--text-primary)' }}>
                {k.value}
              </p>
              <p className="text-2xs mt-1" style={{ color: 'var(--text-muted)' }}>{k.sub}</p>
            </div>
          );
        })}
      </motion.div>

      {/* Top sellers + Category mix */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        <motion.div variants={item} className="lg:col-span-8 rounded-2xl p-5 overflow-hidden" style={cardStyle}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Top products</h2>
              <p className="text-xs flex items-center gap-1" style={{ color: topLoading ? '#5882ff' : 'var(--text-muted)' }}>
                {topLoading && <RefreshCw size={9} className="animate-spin" />}
                {topLoading ? `Loading ${timeRange} data…` : `By revenue · ${timeRange}`}
              </p>
            </div>
            {topError && (
              <span className="text-2xs font-medium px-2 py-1 rounded-lg" style={{ color: '#f87171', background: 'rgba(248,113,113,0.1)' }}>
                {topError}
              </span>
            )}
          </div>
          <div className="overflow-x-auto -mx-1">
            <table className="w-full text-xs min-w-[680px]">
              <thead>
                <tr style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.06)' }}>
                  {['#', 'Product', 'Units', 'Revenue', 'Growth', 'Share'].map((h) => (
                    <th key={h} className={`pb-2.5 pt-1 ${h === 'Product' ? 'text-left pl-2' : 'text-right pr-2'}`} style={thStyle}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {topLoading && topSlowQuery && (
                  <tr>
                    <td colSpan={6} className="py-2 px-2 text-center text-xs" style={{ color: '#f59e0b' }}>
                      ⏳ Querying item-level data… this view is slow. Please wait.
                    </td>
                  </tr>
                )}
                {topLoading && topProducts.length === 0 ? (
                  <>
                    {[...Array(8)].map((_, i) => (
                      <tr key={i}>
                        {[...Array(6)].map((__, j) => (
                          <td key={j} className="py-2 px-2">
                            <div className="h-2.5 rounded animate-pulse" style={{ background: 'rgba(128,128,128,0.12)' }} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </>
                ) : topProducts.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-10 text-center" style={{ color: 'var(--text-muted)' }}>No product sales for this period</td>
                  </tr>
                ) : (
                  topProducts.map((p, i) => {
                    const maxShare = Math.max(...topProducts.map((x) => x.share_pct), 1);
                    const barPct = (p.share_pct / maxShare) * 100;
                    return (
                      <tr key={p.item_id + i}
                        style={{ borderBottom: isDark ? '1px solid rgba(255,255,255,0.04)' : '1px solid rgba(0,0,0,0.05)' }}>
                        <td className="py-2.5 pl-2 font-mono tabular-nums" style={{ color: 'var(--text-muted)', width: 36 }}>{i + 1}</td>
                        <td className="py-2.5 pr-4 max-w-[240px]" style={{ color: 'var(--text-primary)' }}>
                          <span className="font-medium block truncate" title={p.label}>{truncate(p.label, 42)}</span>
                          <span className="text-2xs block truncate font-mono" style={{ color: 'var(--text-muted)' }} title={p.item_id}>{p.item_id}</span>
                        </td>
                        <td className="py-2.5 text-right pr-2 tabular-nums font-semibold" style={{ color: 'var(--text-secondary)' }}>{fmtCount(p.quantity)}</td>
                        <td className="py-2.5 text-right pr-2 tabular-nums font-bold" style={{ color: '#5882ff' }}>{fmtRevenue(p.revenue)}</td>
                        <td className="py-2.5 text-right pr-2">
                          {p.growth_pct == null ? (
                            <span style={{ color: 'var(--text-muted)' }}>—</span>
                          ) : (
                            <span className={`inline-flex items-center justify-end gap-0.5 font-semibold tabular-nums ${p.growth_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                              {p.growth_pct >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                              {p.growth_pct >= 0 ? '+' : ''}{p.growth_pct}%
                            </span>
                          )}
                        </td>
                        <td className="py-2.5 pr-2 w-[140px]">
                          <div className="flex items-center gap-2 justify-end">
                            <span className="tabular-nums font-semibold" style={{ color: 'var(--text-muted)', width: 40 }}>
                              {p.share_pct.toFixed(1)}%
                            </span>
                            <div className="flex-1 h-1.5 rounded-full overflow-hidden max-w-[72px]"
                              style={{ background: isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)' }}>
                              <motion.div className="h-full rounded-full" initial={{ width: 0 }} animate={{ width: `${barPct}%` }}
                                transition={{ duration: 0.35, delay: i * 0.02 }}
                                style={{ background: 'linear-gradient(90deg, #5882ff, #00e67a)' }} />
                            </div>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </motion.div>

        <motion.div variants={item} className="lg:col-span-4 rounded-2xl p-5 flex flex-col" style={cardStyle}>
          <div className="mb-2">
            <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Category mix</h2>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>Share of sales · same period</p>
          </div>
          {catLoading && pieData.length === 0 ? (
            <div className="flex-1 min-h-[220px] flex items-center justify-center">
              <div className="h-40 w-40 rounded-full animate-pulse" style={{ background: 'rgba(128,128,128,0.08)' }} />
            </div>
          ) : pieData.length === 0 ? (
            <p className="text-sm py-16 text-center flex-1 flex items-center justify-center" style={{ color: 'var(--text-muted)' }}>No category data</p>
          ) : (
            <>
              <div className="h-[220px] w-full min-h-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="48%"
                      innerRadius={54}
                      outerRadius={76}
                      paddingAngle={2}
                      strokeWidth={0}
                    >
                      {pieData.map((entry, idx) => (
                        <Cell key={entry.name + idx} fill={entry.color} />
                      ))}
                    </Pie>
                    <PieTooltip
                      formatter={(v: number, _n: string, item: { payload?: { revenue?: number; name?: string } }) => [
                        `${v}% · ${fmtRevenue(item?.payload?.revenue ?? 0)}`,
                        item?.payload?.name ?? '',
                      ]}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} formatter={(value) => <span style={{ color: 'var(--text-secondary)' }}>{value}</span>} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <div className="mt-3 space-y-1.5 text-xs flex-1">
                {pieData.slice(0, 6).map((s) => (
                  <div key={s.name} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: s.color }} />
                    <span className="flex-1 truncate" style={{ color: 'var(--text-secondary)' }}>{s.name}</span>
                    <span className="font-semibold tabular-nums" style={{ color: s.color }}>{s.value}%</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </motion.div>
      </div>

      {/* Full product master — VW_MB_POWERBI_PRODUCT_MASTER columns */}
      <motion.div variants={item} className="rounded-2xl p-5" style={cardStyle}>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Product master</h2>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              ItemId · Itemcode · Dept · Category · Article · Supplier · MRP · Purchase price
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 opacity-45" />
              <input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="Search SKU, article, supplier, category…"
                className="pl-9 pr-3 py-2 rounded-xl text-xs w-full md:w-[280px] outline-none"
                style={{
                  background: isDark ? 'rgba(255,255,255,0.06)' : 'white',
                  border: isDark ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.12)',
                  color: 'var(--text-primary)',
                }}
              />
            </div>
            <div className="flex items-center gap-1 text-xs" style={{ color: 'var(--text-muted)' }}>
              <button type="button" disabled={page <= 1 || catalogLoading} onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="p-1.5 rounded-lg disabled:opacity-35"
                style={{ border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}` }}>
                <ChevronLeft size={16} />
              </button>
              <span className="px-2 tabular-nums">Page {page} / {totalPages}</span>
              <button type="button" disabled={page >= totalPages || catalogLoading} onClick={() => setPage((p) => p + 1)}
                className="p-1.5 rounded-lg disabled:opacity-35"
                style={{ border: `1px solid ${isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)'}` }}>
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        </div>

        {catalogError && (
          <p className="text-xs mb-3 px-3 py-2 rounded-lg" style={{ background: 'rgba(248,113,113,0.08)', color: '#f87171' }}>{catalogError}</p>
        )}

        <div className="overflow-x-auto rounded-xl" style={{
          border: isDark ? '1px solid rgba(255,255,255,0.06)' : '1px solid rgba(0,0,0,0.06)',
        }}>
          <table className="w-full text-xs min-w-[1100px]">
            <thead>
              <tr style={{ background: isDark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.02)' }}>
                {(['ItemId', 'Itemcode', 'Dept', 'Category', 'Article', 'Supplier alias', 'Supplier', 'MRP', 'Pur. price'] as const).map((h) => (
                  <th key={h} className="text-left py-2.5 px-3 whitespace-nowrap" style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {catalogLoading ? (
                [...Array(12)].map((_, i) => (
                  <tr key={i}>
                    {[...Array(9)].map((__, j) => (
                      <td key={j} className="px-3 py-2">
                        <div className="h-2 rounded animate-pulse" style={{ background: 'rgba(128,128,128,0.1)' }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : !(catalog?.products?.length) ? (
                <tr>
                  <td colSpan={9} className="py-14 text-center" style={{ color: 'var(--text-muted)' }}>No rows match this filter</td>
                </tr>
              ) : (
                (catalog.products as ProductMasterRow[]).map((row: ProductMasterRow, ri: number) => (
                  <tr key={`${String(row.ItemId)}-${ri}`}
                    style={{ borderTop: isDark ? '1px solid rgba(255,255,255,0.04)' : '1px solid rgba(0,0,0,0.05)' }}>
                    <td className="py-2 px-3 font-mono align-top max-w-[120px]" style={{ color: 'var(--text-secondary)' }}>
                      <span className="block truncate" title={String(row.ItemId ?? '')}>{row.ItemId ?? '—'}</span>
                    </td>
                    <td className="py-2 px-3 align-top max-w-[100px]" style={{ color: 'var(--text-primary)' }}>
                      <span className="block truncate font-mono" title={String(row.Itemcode ?? '')}>{row.Itemcode ?? '—'}</span>
                    </td>
                    <td className="py-2 px-3 align-top" style={{ color: 'var(--text-secondary)' }}>{row.DepartmentShortName || '—'}</td>
                    <td className="py-2 px-3 align-top" style={{ color: 'var(--text-secondary)' }}>{row.CategoryShortName || '—'}</td>
                    <td className="py-2 px-3 align-top max-w-[200px]">
                      <span className="line-clamp-2" style={{ color: 'var(--text-primary)' }} title={String(row.ArticleNo ?? '')}>
                        {truncate(String(row.ArticleNo ?? '—'), 64)}
                      </span>
                    </td>
                    <td className="py-2 px-3 align-top text-2xs" style={{ color: 'var(--text-muted)' }}>{row.SupplierAlias || '—'}</td>
                    <td className="py-2 px-3 align-top max-w-[180px]" style={{ color: 'var(--text-secondary)' }}>
                      <span className="line-clamp-2" title={String(row.SupplierName ?? '')}>{truncate(String(row.SupplierName ?? '—'), 40)}</span>
                    </td>
                    <td className="py-2 px-3 align-top tabular-nums font-medium" style={{ color: '#38bdf8' }}>
                      {row.ItemMRP != null ? fmtRupees(row.ItemMRP) : '—'}
                    </td>
                    <td className="py-2 px-3 align-top tabular-nums" style={{ color: 'var(--text-muted)' }}>
                      {row.PurchasePrice != null ? fmtRupees(row.PurchasePrice) : '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </motion.div>

    </motion.div>
  );
}