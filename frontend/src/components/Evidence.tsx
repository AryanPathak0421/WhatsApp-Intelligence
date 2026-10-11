import { Quote } from 'lucide-react';
import { fmtDateTime } from '../lib/format';
import { useEvidence } from '../lib/queries';
import { Badge, ConfidenceBadge, Drawer, ErrorState, Skeleton, StatusBadge } from './ui';

/** Auditability: every AI result opens the exact chat messages (with surrounding context) it came from. */
export function EvidenceDrawer({ taskId, onClose }: { taskId: string | null; onClose: () => void }) {
  const { data, isLoading, error, refetch } = useEvidence(taskId ?? undefined);
  return (
    <Drawer open={!!taskId} onClose={onClose} title="Source messages" width="max-w-2xl">
      {isLoading && <div className="space-y-3"><Skeleton className="h-16" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div>}
      {error && <ErrorState error={error} onRetry={refetch} />}
      {data && (
        <div className="space-y-5">
          <div className="card p-4">
            <p className="font-medium">{data.task.title}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2"><StatusBadge status={data.task.status} /><ConfidenceBadge value={data.task.confidence} needsReview={data.task.reviewState === 'NEEDS_REVIEW'} />
              {data.task.reviewState.startsWith('HUMAN') && <Badge tone="blue">Human-corrected</Badge>}</div>
            {!!data.task.statusEvidence?.reasons?.length && <ul className="mt-3 list-disc space-y-0.5 pl-4 text-xs text-amber-700 dark:text-amber-300">{data.task.statusEvidence.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
            {!!data.task.statusEvidence?.trace?.length && (
              <ol className="mt-3 space-y-1 text-xs"><li className="muted font-medium">How the status was decided</li>
                {data.task.statusEvidence.trace.map((t, i) => <li key={i} className="flex items-center gap-2"><span className="muted">{i + 1}.</span><span>{t.event.replace(/_/g, ' ')}</span><span className="muted">→</span><StatusBadge status={t.status} /></li>)}</ol>)}
          </div>
          <ol className="space-y-4">
            {data.evidence.map((e) => (
              <li key={e.id}>
                <div className="rounded-xl border-l-4 border-brand-500 bg-brand-500/5 p-3.5">
                  <div className="mb-1 flex items-center gap-2 text-xs"><Quote className="size-3.5 text-brand-500" /><span className="font-semibold">{e.sender ?? 'System'}</span><span className="muted">{fmtDateTime(e.timestamp)}</span></div>
                  <p className="whitespace-pre-wrap text-sm">{e.text}</p>
                </div>
                {e.context.length > 0 && (
                  <div className="muted mt-1.5 space-y-1 pl-4 text-xs">
                    {e.context.map((c) => <p key={c.id}><span className="font-medium">{c.sender}:</span> {c.text}</p>)}
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </Drawer>
  );
}
