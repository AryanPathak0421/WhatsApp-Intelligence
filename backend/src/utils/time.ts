/**
 * Message times are wall-clock times in the project's timezone, stored as "wall-clock-as-UTC" so that
 * what people saw in the chat is what the API returns (no accidental shifts by the server's TZ), and we send the
 * AI engine naive timestamps (it also treats them as wall-clock).
 */
export const wall = (s?: string | null): Date | null => (s ? new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(s) ? s : s + 'Z') : null);
export const naive = (d?: Date | null): string | undefined => (d ? d.toISOString().replace('Z', '') : undefined);
