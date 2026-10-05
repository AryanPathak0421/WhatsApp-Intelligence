import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Button, Card, ConfidenceBadge, ConfirmDialog, EmptyState, ErrorState, PageHeader, SeverityBadge, StatusBadge, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fmtDate, titleCase } from '../lib/format';
import { useClientPending, useUpdateCp } from '../lib/queries';
import type { ClientPending as CP } from '../lib/types';

const FILTERS: [string, string][] = [['', 'All'], ['APPROVAL', 'Approval'], ['FEEDBACK', 'Feedback'], ['PAYMENT', 'Payment'], ['CREDENTIALS', 'Credentials'], ['REQUIREMENT', 'Requirements'], ['UAT', 'UAT'], ['CONTENT', 'Content']];

export default function ClientPending() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { can } = useAuth();
  const [type, setType] = useState(''); const [status, setStatus] = useState('OPEN');
  const params: Record<string, string> = {}; if (type) params.type = type; if (status) params.status = status;
  const { data, isLoading, error, refetch } = useClientPending(projectId, params);
  const update = useUpdateCp();
  const [target, setTarget] = useState<CP | null>(null);
  const toast = useToast();
  const editable = can('task:edit') || can('sales:view');
  if (!projectId) return <EmptyState title="Select a project first" />;
  const resolve = async () => {
    try { await update.mutateAsync({ id: target!.id, body: { status: 'RESOLVED' } }); toast.push('success', 'Marked as resolved'); setTarget(null); } catch (e) { toast.push('error', apiError(e).message); }
  };
  return (
    <>
      <PageHeader title="Client pending" sub="Everything the team is waiting on from the client — and for how long." />
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by type">{FILTERS.map(([v, l]) => (
            <button key={l} role="tab" aria-selected={type === v} onClick={() => setType(v)} className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${type === v ? 'bg-brand-600 text-white' : 'bg-[var(--surface-2)] hover:bg-[var(--border)]'}`}>{l}</button>))}</div>
          <div className="ml-auto flex gap-1.5">{[['OPEN', 'Open'], ['RESOLVED', 'Resolved'], ['', 'All']].map(([v, l]) => (
            <button key={l} aria-pressed={status === v} onClick={() => setStatus(v)} className={`rounded-lg border px-2.5 py-1 text-xs ${status === v ? 'border-brand-500 bg-brand-500/10 font-medium' : ''}`}>{l}</button>))}</div>
        </div>
        {isLoading ? <TableSkeleton rows={5} cols={7} /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? <EmptyState title={status === 'OPEN' ? 'Nothing is waiting on the client' : 'No items'} hint="Items appear when the chat says things like “waiting for client approval”." /> : (
          <div className="overflow-x-auto"><table className="w-full min-w-[900px]"><thead className="border-b bg-[var(--surface-2)]/50"><tr><Th>Item</Th><Th>Type</Th><Th>Responsible</Th><Th>Waiting since</Th><Th>Age</Th><Th>Priority</Th><Th>Impact</Th><Th>Status</Th><Th>AI</Th><Th /></tr></thead>
            <tbody className="divide-y">{data.map((c) => (
              <tr key={c.id} className="hover:bg-[var(--surface-2)]/50"><Td className="max-w-xs"><p className="font-medium">{c.title}</p>{c.task && <p className="muted text-xs">Blocks: {c.task.title}</p>}</Td><Td><Badge>{titleCase(c.type)}</Badge></Td>
                <Td>{titleCase(c.responsible)}</Td><Td>{fmtDate(c.waitingSince)}</Td><Td className={c.status === 'OPEN' && c.ageDays >= 5 ? 'font-semibold text-red-600 dark:text-red-400' : ''}>{c.ageDays} d</Td>
                <Td><SeverityBadge severity={c.priority} /></Td><Td><SeverityBadge severity={c.impact} /></Td><Td><StatusBadge status={c.status} /></Td><Td><ConfidenceBadge value={c.confidence} needsReview={c.needsReview} /></Td>
                <Td>{editable && c.status === 'OPEN' && <Button size="sm" onClick={() => setTarget(c)}>Resolve</Button>}</Td></tr>))}</tbody></table></div>)}
      </Card>
      <ConfirmDialog open={!!target} title="Mark as resolved?" message={`“${target?.title}” will be marked resolved. This is a manual correction and will be kept when the chat is re-analysed.`}
        confirmLabel="Mark resolved" loading={update.isPending} onConfirm={resolve} onClose={() => setTarget(null)} />
    </>
  );
}
