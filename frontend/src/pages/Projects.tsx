import { zodResolver } from '@hookform/resolvers/zod';
import { useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate } from 'react-router-dom';
import { z } from 'zod';
import { Button, Card, Dialog, EmptyState, ErrorState, Field, Input, PageHeader, ProgressBar, StatusBadge, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { fmtDate, pct } from '../lib/format';
import { useProjects } from '../lib/queries';

const schema = z.object({ name: z.string().min(1, 'Name is required').max(150), clientName: z.string().max(150).optional(),
  expectedDelivery: z.string().optional() });

export default function Projects() {
  const { data, isLoading, error, refetch } = useProjects();
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  const toast = useToast();
  const { register, handleSubmit, reset, formState: { errors, isSubmitting } } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });

  return (
    <>
      <PageHeader title="Projects" sub="Each project keeps its own chats, team, tasks and reports — data is never mixed."
        actions={can('project:create') && <Button variant="primary" onClick={() => setOpen(true)}><Plus className="size-4" />New project</Button>} />
      <Card className="overflow-hidden">
        {isLoading ? <TableSkeleton /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? (
          <EmptyState title="No projects yet" hint={can('project:create') ? 'Create your first project, then upload a WhatsApp chat export.' : 'You have not been added to any project yet.'}
            action={can('project:create') && <Button variant="primary" onClick={() => setOpen(true)}>New project</Button>} />
        ) : (
          <div className="overflow-x-auto"><table className="w-full min-w-[700px]"><thead className="border-b bg-[var(--surface-2)]/50"><tr><Th>Project</Th><Th>Client</Th><Th>Status</Th><Th className="w-48">Progress</Th><Th>Health</Th><Th>Delivery</Th></tr></thead>
            <tbody className="divide-y">{data.map((p) => (
              <tr key={p.id} className="hover:bg-[var(--surface-2)]/50">
                <Td><Link className="font-medium text-brand-600 hover:underline" to={`/p/${p.id}/overview`}>{p.name}</Link></Td><Td className="muted">{p.client ?? '—'}</Td><Td><StatusBadge status={p.status} /></Td>
                <Td>{p.progress === null ? <span className="muted text-xs">Upload a chat to analyse</span> : <div className="flex min-w-28 items-center gap-2"><div className="min-w-16 flex-1"><ProgressBar value={p.progress} /></div><span className="w-10 text-xs tabular-nums">{pct(p.progress)}</span></div>}</Td>
                <Td>{p.health ? <StatusBadge status={p.health.status} /> : '—'}</Td><Td className="muted">{fmtDate(p.expectedDelivery)}</Td></tr>))}</tbody></table></div>
        )}
      </Card>
      <Dialog open={open} onClose={() => setOpen(false)} title="New project" footer={<>
        <Button onClick={() => setOpen(false)}>Cancel</Button><Button variant="primary" loading={isSubmitting} onClick={handleSubmit(async (v) => {
          try {
            const r = await api.post('/projects', { name: v.name, clientName: v.clientName || undefined, expectedDelivery: v.expectedDelivery ? new Date(v.expectedDelivery).toISOString() : undefined });
            await qc.invalidateQueries({ queryKey: ['projects'] });
            toast.push('success', 'Project created'); reset(); setOpen(false); nav(`/p/${r.data.id}/chat`);
          } catch (e) { toast.push('error', apiError(e).message); }
        })}>Create</Button></>}>
        <form className="space-y-4" onSubmit={(e) => e.preventDefault()}>
          <Field label="Project name" error={errors.name?.message}><Input autoFocus placeholder="E-Commerce Website" {...register('name')} /></Field>
          <Field label="Client (optional)"><Input placeholder="Sharma Retail" {...register('clientName')} /></Field>
          <Field label="Expected delivery (optional)"><Input type="date" {...register('expectedDelivery')} /></Field>
        </form>
      </Dialog>
    </>
  );
}
