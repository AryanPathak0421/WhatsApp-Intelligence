import { useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { useState } from 'react';
import { useOutletContext } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, ErrorState, PageHeader, Select, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { titleCase } from '../lib/format';
import { useMembers, useUsers } from '../lib/queries';

export default function Settings() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { user, can, logout } = useAuth();
  const members = useMembers(projectId, can('team:view') && !!projectId);
  const users = useUsers(can('user:manage'));
  const [add, setAdd] = useState('');
  const [canEdit, setCanEdit] = useState(false);
  const [remove, setRemove] = useState<any>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = () => qc.invalidateQueries({ queryKey: ['members'] });
  const candidates = users.data?.filter((u) => u.isActive && !members.data?.some((m) => m.userId === u.id)) ?? [];
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card><CardHeader title="Your account" />
          <dl className="space-y-3 px-5 pb-5 text-sm">
            <div><dt className="muted text-xs">Name</dt><dd>{user?.name}</dd></div>
            <div><dt className="muted text-xs">Email</dt><dd>{user?.email}</dd></div>
            <div><dt className="muted text-xs">Role</dt><dd><Badge>{titleCase(user?.role ?? '')}</Badge></dd></div>
            <Button onClick={logout}>Sign out</Button>
          </dl></Card>
        <Card className="overflow-hidden lg:col-span-2"><CardHeader title="Project access" sub="People who can open this project. Data from other projects is never visible to them." />
          {!projectId ? <EmptyState title="Select a project" /> : members.isLoading ? <TableSkeleton rows={3} cols={4} /> : members.error ? <ErrorState error={members.error} onRetry={members.refetch} /> : (<>
            <div className="overflow-x-auto"><table className="w-full min-w-[480px]"><thead className="border-y bg-[var(--surface-2)]/50"><tr><Th>Name</Th><Th>Role</Th><Th>Access</Th><Th /></tr></thead>
              <tbody className="divide-y">{members.data?.map((m) => (
                <tr key={m.id}><Td><p className="font-medium">{m.user.name}</p><p className="muted text-xs">{m.user.email}</p></Td><Td>{titleCase(m.user.role)}</Td>
                  <Td>{m.canEdit ? <Badge tone="blue">Can edit</Badge> : <Badge>Read only</Badge>}</Td>
                  <Td>{can('member:manage') && <Button size="sm" variant="ghost" aria-label={`Remove ${m.user.name}`} onClick={() => setRemove(m)}><Trash2 className="size-3.5" /></Button>}</Td></tr>))}</tbody></table></div>
            {can('user:manage') && (
              <div className="flex flex-wrap items-end gap-2 border-t p-4">
                <Select aria-label="User to add" className="w-64" value={add} onChange={(e) => setAdd(e.target.value)}><option value="">Add a user…</option>{candidates.map((u) => <option key={u.id} value={u.id}>{u.name} ({titleCase(u.role)})</option>)}</Select>
                <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={canEdit} onChange={(e) => setCanEdit(e.target.checked)} className="size-4" />Can edit</label>
                <Button variant="primary" disabled={!add} onClick={async () => {
                  try { await api.post(`/projects/${projectId}/members`, { userId: add, canEdit }); setAdd(''); await refresh(); toast.push('success', 'Member added'); }
                  catch (e) { toast.push('error', apiError(e).message); }
                }}>Add</Button>
              </div>)}</>)}
        </Card>
      </div>
      <ConfirmDialog open={!!remove} danger title="Remove access?" message={`${remove?.user.name} will no longer be able to open this project.`} confirmLabel="Remove" onClose={() => setRemove(null)}
        onConfirm={async () => {
          try { await api.delete(`/projects/${projectId}/members/${remove.userId}`); await refresh(); toast.push('success', 'Access removed'); } catch (e) { toast.push('error', apiError(e).message); }
          setRemove(null);
        }} />
    </>
  );
}
