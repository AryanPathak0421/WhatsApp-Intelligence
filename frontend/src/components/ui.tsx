import clsx from 'clsx';
import { AlertTriangle, CheckCircle2, Inbox, Info, Loader2, X } from 'lucide-react';
import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { apiError } from '../lib/api';
import { confidenceLevel, titleCase } from '../lib/format';

/* ------------------------------------------------------------------ primitives */
export function Card({ className, children, ...p }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx('card', className)} {...p}>{children}</div>;
}
export const CardHeader = ({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) => (
  <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-2">
    <div><h3 className="text-sm font-semibold">{title}</h3>{sub && <p className="muted text-xs mt-0.5">{sub}</p>}</div>{right}
  </div>
);

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'sm' | 'md'; loading?: boolean };
export function Button({ variant = 'secondary', size = 'md', loading, className, children, disabled, ...p }: BtnProps) {
  const v = { primary: 'bg-brand-600 hover:bg-brand-700 text-white border-transparent', secondary: 'bg-[var(--surface)] hover:bg-[var(--surface-2)] border-[var(--border)]',
    ghost: 'bg-transparent hover:bg-[var(--surface-2)] border-transparent', danger: 'bg-red-600 hover:bg-red-700 text-white border-transparent' }[variant];
  return (
    <button disabled={disabled || loading} className={clsx('inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500',
      size === 'sm' ? 'h-8 px-2.5 text-xs' : 'h-9 px-3.5 text-sm', v, className)} {...p}>
      {loading && <Loader2 className="size-3.5 animate-spin" />}{children}
    </button>
  );
}

export const inputCls = 'h-9 w-full rounded-lg border bg-[var(--surface)] px-3 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 disabled:opacity-60';
export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={clsx(inputCls, p.className)} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={clsx(inputCls, 'pr-8', p.className)} />;
export const Field = ({ label, error, children }: { label: string; error?: string; children: ReactNode }) => (
  <label className="block"><span className="mb-1 block text-xs font-medium muted">{label}</span>{children}{error && <span className="mt-1 block text-xs text-red-500">{error}</span>}</label>
);

/* ------------------------------------------------------------------ badges */
const TONES: Record<string, string> = {
  green: 'bg-emerald-500/12 text-emerald-700 dark:text-emerald-300', amber: 'bg-amber-500/15 text-amber-700 dark:text-amber-300',
  red: 'bg-red-500/12 text-red-700 dark:text-red-300', blue: 'bg-blue-500/12 text-blue-700 dark:text-blue-300',
  gray: 'bg-slate-500/12 text-slate-700 dark:text-slate-300', purple: 'bg-violet-500/12 text-violet-700 dark:text-violet-300',
};
export const Badge = ({ tone = 'gray', children, className, title }: { tone?: keyof typeof TONES; children: ReactNode; className?: string; title?: string }) => (
  <span title={title} className={clsx('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap', TONES[tone], className)}>{children}</span>
);
const STATUS_TONE: Record<string, string> = { COMPLETED: 'green', IN_PROGRESS: 'blue', TODO: 'gray', BLOCKED: 'red', CANCELLED: 'gray', OPEN: 'amber', RESOLVED: 'green',
  HEALTHY: 'green', AT_RISK: 'amber', CRITICAL: 'red', COMPLETED_JOB: 'green', FAILED: 'red', RUNNING: 'blue', QUEUED: 'gray' };
export const StatusBadge = ({ status }: { status: string }) => <Badge tone={STATUS_TONE[status] ?? 'gray'}>{titleCase(status)}</Badge>;
export const SeverityBadge = ({ severity }: { severity: string }) => (
  <Badge tone={({ LOW: 'gray', MEDIUM: 'amber', HIGH: 'red', CRITICAL: 'purple' } as Record<string, string>)[severity] ?? 'gray'}>{titleCase(severity)}</Badge>
);
export function ConfidenceBadge({ value, needsReview }: { value?: number | null; needsReview?: boolean }) {
  if (value === undefined || value === null) return null;
  const lvl = confidenceLevel(value);
  return (
    <span className="inline-flex items-center gap-1">
      <Badge tone={lvl === 'high' ? 'green' : lvl === 'medium' ? 'amber' : 'red'} title="AI confidence">{Math.round(value * 100)}%</Badge>
      {(needsReview || lvl === 'low') && <Badge tone="amber">Needs review</Badge>}
    </span>
  );
}

export function ProgressBar({ value, tone = 'brand', label, height = 8 }: { value: number | null | undefined; tone?: 'brand' | 'green' | 'amber' | 'red'; label?: string; height?: number }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const color = { brand: 'bg-brand-500', green: 'bg-emerald-500', amber: 'bg-amber-500', red: 'bg-red-500' }[tone];
  return (
    <div role="progressbar" aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={100} aria-label={label}
      className="w-full overflow-hidden rounded-full bg-[var(--surface-2)]" style={{ height }}>
      <div className={clsx('h-full rounded-full transition-all duration-500', color)} style={{ width: `${v}%` }} />
    </div>
  );
}

/* ------------------------------------------------------------------ states */
export const Skeleton = ({ className }: { className?: string }) => <div className={clsx('skeleton', className)} />;
export function EmptyState({ icon, title, hint, action }: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      <div className="grid size-11 place-items-center rounded-full bg-[var(--surface-2)] muted">{icon ?? <Inbox className="size-5" />}</div>
      <p className="text-sm font-medium">{title}</p>{hint && <p className="muted max-w-sm text-xs">{hint}</p>}{action}
    </div>
  );
}
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = apiError(error);
  return (
    <div role="alert" className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <AlertTriangle className="size-6 text-red-500" /><p className="text-sm font-medium">Couldn’t load this</p><p className="muted text-xs">{e.message}</p>
      {onRetry && <Button size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

/* ------------------------------------------------------------------ overlays */
export function Drawer({ open, onClose, title, children, width = 'max-w-xl' }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    ref.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <aside ref={ref} tabIndex={-1} role="dialog" aria-modal aria-label={typeof title === 'string' ? title : 'Details'}
        className={clsx('relative flex h-full w-full flex-col bg-[var(--surface)] shadow-2xl outline-none', width)}>
        <header className="flex items-center justify-between border-b px-5 py-3.5"><h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 hover:bg-[var(--surface-2)]"><X className="size-4" /></button></header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

export function Dialog({ open, onClose, title, children, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal aria-label={title} className="card relative w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between border-b px-5 py-3.5"><h2 className="text-sm font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-md p-1 hover:bg-[var(--surface-2)]"><X className="size-4" /></button></div>
        <div className="p-5">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', danger, onConfirm, onClose, loading }:
  { open: boolean; title: string; message: string; confirmLabel?: string; danger?: boolean; onConfirm: () => void; onClose: () => void; loading?: boolean }) {
  return (
    <Dialog open={open} onClose={onClose} title={title} footer={<>
      <Button onClick={onClose}>Cancel</Button><Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></>}>
      <p className="text-sm">{message}</p>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ toasts */
type Toast = { id: number; kind: 'success' | 'error' | 'info'; text: string };
const ToastCtx = createContext<{ push: (kind: Toast['kind'], text: string) => void }>({ push: () => {} });
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast['kind'], text: string) => {
    const id = Date.now() + Math.random();
    setItems((t) => [...t, { id, kind, text }]);
    setTimeout(() => setItems((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="card pointer-events-auto flex max-w-sm items-start gap-2 px-4 py-3 text-sm shadow-lg">
            {t.kind === 'success' ? <CheckCircle2 className="mt-0.5 size-4 text-emerald-500" /> : t.kind === 'error' ? <AlertTriangle className="mt-0.5 size-4 text-red-500" /> : <Info className="mt-0.5 size-4 text-blue-500" />}
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ------------------------------------------------------------------ KPI + table helpers */
export function Kpi({ label, value, sub, tone, icon }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'ok' | 'warn' | 'bad'; icon?: ReactNode }) {
  const c = tone === 'bad' ? 'text-red-600 dark:text-red-400' : tone === 'warn' ? 'text-amber-600 dark:text-amber-400' : tone === 'ok' ? 'text-emerald-600 dark:text-emerald-400' : '';
  return (
    <Card className="px-4 py-3.5">
      <div className="flex items-center justify-between"><span className="muted text-xs font-medium">{label}</span>{icon && <span className="muted">{icon}</span>}</div>
      <div className={clsx('mt-1 text-2xl font-semibold tabular-nums', c)}>{value}</div>{sub && <div className="muted mt-0.5 text-xs">{sub}</div>}
    </Card>
  );
}
export const Th = ({ children, className }: { children?: ReactNode; className?: string }) => <th className={clsx('whitespace-nowrap px-4 py-2.5 text-left text-xs font-medium muted', className)}>{children}</th>;
export const Td = ({ children, className, ...p }: { children?: ReactNode; className?: string } & React.TdHTMLAttributes<HTMLTableCellElement>) => <td className={clsx('px-4 py-3 align-middle text-sm', className)} {...p}>{children}</td>;
export const TableSkeleton = ({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) => (
  <div className="space-y-2 p-4">{Array.from({ length: rows }, (_, i) => <div key={i} className="flex gap-4">{Array.from({ length: cols }, (_, j) => <Skeleton key={j} className="h-5 flex-1" />)}</div>)}</div>
);
export function PageHeader({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-xl font-semibold tracking-tight">{title}</h1>{sub && <p className="muted mt-0.5 text-sm">{sub}</p>}</div>{actions}
    </div>
  );
}
