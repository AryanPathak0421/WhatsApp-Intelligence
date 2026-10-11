/** Message times are wall-clock values (project timezone) stored as UTC: always render them in UTC so nothing shifts. */
const opt = (o: Intl.DateTimeFormatOptions): Intl.DateTimeFormatOptions => ({ ...o, timeZone: 'UTC' });
export const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleDateString('en-GB', opt({ day: '2-digit', month: 'short', year: 'numeric' })) : '—');
export const fmtShort = (s?: string | null) => (s ? new Date(s).toLocaleDateString('en-GB', opt({ day: '2-digit', month: 'short' })) : '—');
export const fmtTime = (s?: string | null) => (s ? new Date(s).toLocaleTimeString('en-GB', opt({ hour: '2-digit', minute: '2-digit' })) : '');
export const fmtDateTime = (s?: string | null) => (s ? `${fmtDate(s)} ${fmtTime(s)}` : '—');
export const pct = (n?: number | null, digits = 0) => (n === null || n === undefined ? '—' : `${n.toFixed(digits)}%`);
export const titleCase = (s: string) => s.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
export const isOverdue = (deadline: string | null | undefined, status: string) =>
  !!deadline && !['COMPLETED', 'CANCELLED'].includes(status) && new Date(deadline).getTime() < Date.now();
export const confidenceLevel = (c?: number | null): 'high' | 'medium' | 'low' => (c === undefined || c === null ? 'low' : c >= 0.85 ? 'high' : c >= 0.7 ? 'medium' : 'low');
export function dayLabel(iso: string) { return fmtShort(iso); }
