/**
 * Derive a plain-language "Timeline" + "Logic" summary from the SQL that actually ran,
 * so users can see exactly which date window and which calculation produced an answer.
 * Works for both verified-template SQL and dynamically generated SQL — it only reads the SQL.
 */

export interface SqlPlan {
  timeline: string;
  logic: string[];
}

function squash(sql: string): string {
  return sql.replace(/\s+/g, '').toLowerCase();
}

/** Plain-language date window detected in the SQL. */
function detectTimeline(sql: string): string {
  const s = squash(sql);
  const raw = sql.toLowerCase();

  // Financial-year YTD (April 1 start)
  if (s.includes('month(getdate())>=4') || s.includes('datefromparts(year(getdate()),4,1)')) {
    return 'Financial year to date (1 Apr → today)';
  }
  // This vs last (two windows present)
  const hasThisMonth = s.includes('datefromparts(year(getdate()),month(getdate()),1)');
  const hasLastMonth = s.includes('dateadd(month,-1') || s.includes('dateadd(month,-1,');
  if (hasThisMonth && hasLastMonth) return 'This month vs last month';
  if (s.includes('dateadd(day,-7')) return 'Today vs the same day last week';
  if (s.includes('dateadd(year,-1') || s.includes('year(getdate())-1')) return 'This year vs last year';
  // Quarter to date
  if (s.includes('((month(getdate())-1)/3)')) return 'Quarter to date (1st of quarter → today)';
  // Last N days / months
  const lastDays = raw.match(/dateadd\(\s*day\s*,\s*-(\d+)/);
  if (lastDays && Number(lastDays[1]) >= 2) return `Last ${lastDays[1]} days`;
  const lastMonths = raw.match(/dateadd\(\s*month\s*,\s*-(\d+)/);
  if (lastMonths && Number(lastMonths[1]) >= 2) return `Last ${lastMonths[1]} months`;
  // Aged stock
  if (s.includes('dateadd(day,-90')) return 'Items aged more than 90 days';
  // Plain MTD
  if (hasThisMonth) return 'This month to date (1st → today)';
  // Today only
  if (/cast\(\s*getdate\(\)\s*as\s*date\s*\)/i.test(sql) && !s.includes('dateadd')) return 'Today only';
  // No date filter
  if (!s.includes('getdate(')) return 'All-time (no date filter)';
  return 'Custom date range';
}

/** Plain-language list of what the query computes. */
function detectLogic(sql: string): string[] {
  const s = squash(sql);
  const out: string[] = [];

  if (s.includes('salesnetamount')) out.push('Revenue = SalesNetAmount');
  else if (s.includes('netslsnetamount')) out.push('Revenue = NetSlsNetAmount');
  else if (s.includes('salenetamount')) out.push('Revenue = SaleNetAmount');

  if (s.includes('count(distinct') && s.includes('cashmemono')) out.push('Bills = COUNT(DISTINCT CashmemoNo)');
  if (s.includes('count(distinct') && s.includes('customerid')) out.push('Customers = COUNT(DISTINCT CustomerId)');
  if (s.includes('sum([salesquantity])') || s.includes('sum(s.[salesquantity])') || s.includes('netslsqty')) out.push('Units = SUM(quantity)');
  if (s.includes('stockqty')) out.push('Stock quantity on hand');
  if (s.includes('itemmrp')) out.push('MRP value = SUM(ItemMRP × qty)');
  if (/\*\s*100\.0\s*\//.test(sql)) out.push('Percentage / share calculation');
  if (/nullif\(/i.test(sql) && /\/\s*nullif/i.test(sql.replace(/\s+/g, ''))) out.push('Per-bill average (AOV/ATS)');

  // dimension grouped by
  const grp = sql.match(/group\s+by\s+([^\n]+)/i);
  if (grp) {
    const dims = grp[1]
      .replace(/option\s*\(.+$/i, '')
      .split(',')
      .map(d => d.replace(/[[\]]/g, '').replace(/^\w+\./, '').trim())
      .filter(d => d && !/^\d+$/.test(d) && !/cast|datepart|datefromparts/i.test(d))
      .slice(0, 3);
    if (dims.length) out.push(`Grouped by ${dims.join(', ')}`);
  }

  const top = sql.match(/top\s*\(?\s*(\d+)/i);
  if (top) out.push(`Top ${top[1]} only`);

  if (!out.length) out.push('See SQL for full calculation');
  return out;
}

export function describeSqlPlan(sql?: string | null): SqlPlan | null {
  if (!sql || sql.trim().length < 10) return null;
  return { timeline: detectTimeline(sql), logic: detectLogic(sql) };
}
