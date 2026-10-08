import { useQueryClient } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useOutletContext, useSearchParams } from 'react-router-dom';
import { Badge, Button, Card, CardHeader, ConfirmDialog, EmptyState, ErrorState, PageHeader, Select, TableSkeleton, Td, Th, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { titleCase } from '../lib/format';
import { useAutoImport, useGoogleStatus, useMembers, useUsers } from '../lib/queries';

export default function Settings() {
  const { projectId } = useOutletContext<{ projectId?: string }>();
  const { user, can, logout } = useAuth();
  const members = useMembers(projectId, can('team:view') && !!projectId);
  const users = useUsers(can('user:manage'));
  const autoImport = useAutoImport(can('user:manage'));
  const google = useGoogleStatus(can('user:manage'));
  const [params, setParams] = useSearchParams();
  const [disconnect, setDisconnect] = useState(false);
  const [busy, setBusy] = useState(false);
  const [add, setAdd] = useState('');
  const [canEdit, setCanEdit] = useState(false);
  const [remove, setRemove] = useState<any>(null);
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = () => qc.invalidateQueries({ queryKey: ['members'] });
  useEffect(() => {                                    // Google redirects back here with ?google=connected|error
    const g = params.get('google');
    if (!g) return;
    if (g === 'connected') toast.push('success', 'Google Drive connected');
    else toast.push('error', `Google sign-in failed: ${params.get('reason') ?? 'unknown reason'}`);
    params.delete('google'); params.delete('reason'); setParams(params, { replace: true });
    void qc.invalidateQueries({ queryKey: ['google'] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const connectGoogle = async () => {
    setBusy(true);
    try { const r = await api.post<{ url: string }>('/google/connect'); window.location.href = r.data.url; }
    catch (e) { toast.push('error', apiError(e).message); setBusy(false); }
  };
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
      {can('user:manage') && (
        <Card className="mt-5"><CardHeader title="WhatsApp auto-import" sub="Export a chat on your phone to Google Drive; it is imported from this folder automatically (only new messages are added)." />
          {autoImport.isLoading ? <div className="p-5"><TableSkeleton rows={2} cols={3} /></div> : !autoImport.data?.enabled ? (
            <div className="px-5 pb-5 text-sm"><Badge tone="amber">Off</Badge><p className="muted mt-2">Set <code>AUTO_IMPORT_DIR</code> in the backend environment (for example your Google Drive for desktop folder) and restart the backend.</p></div>
          ) : (
            <div className="space-y-4 px-5 pb-5 text-sm">
              <div className="flex flex-wrap items-center gap-2"><Badge tone="green">Watching</Badge><code className="break-all text-xs">{autoImport.data.root}</code>
                <span className="muted text-xs">{autoImport.data.lastScanAt ? `last check ${new Date(autoImport.data.lastScanAt).toLocaleTimeString()}` : 'not checked yet'}</span>
                <Button size="sm" onClick={async () => { try { await api.post('/auto-import/folders'); await autoImport.refetch(); toast.push('success', 'Project folders are ready'); } catch (e) { toast.push('error', apiError(e).message); } }}>Create project folders</Button></div>
              <ol className="muted list-decimal space-y-1 pl-5 text-xs"><li>On the phone: open the group, tap its name, <b>Export chat</b>, <b>Without media</b>.</li><li>Save it into the Drive folder named like the project.</li><li>It appears here within a minute or two and moves to <code>imported/</code>.</li></ol>
              <div className="overflow-x-auto"><table className="w-full min-w-[420px]"><thead className="border-y bg-[var(--surface-2)]/50"><tr><Th>Folder</Th><Th>Project</Th><Th>Waiting files</Th></tr></thead>
                <tbody className="divide-y">{autoImport.data.folders.map((f) => (
                  <tr key={f.folder}><Td>{f.folder}</Td><Td>{f.status === 'ok' ? f.project : <Badge tone="amber">{f.status === 'ambiguous' ? 'Several projects share this name' : 'No project with this name'}</Badge>}</Td><Td>{f.waitingFiles}</Td></tr>))}</tbody></table></div>
              {autoImport.data.recent.length > 0 && <div><p className="mb-1 text-xs font-medium">Recent</p><ul className="muted space-y-1 text-xs">{autoImport.data.recent.slice(0, 8).map((e, i) => (
                <li key={i}>{new Date(e.at).toLocaleString()} · {e.folder}{e.file ? ` / ${e.file}` : ''} · <b>{e.outcome}</b>{e.detail ? ` (${e.detail})` : ''}</li>))}</ul></div>}
            </div>)}
        </Card>)}
      {can('user:manage') && (
        <Card className="mt-5"><CardHeader title="Google Drive import" sub="Reads WhatsApp exports from a Drive folder with your own Google account (read-only permission). Nothing in Drive is changed." />
          {google.isLoading ? <div className="p-5"><TableSkeleton rows={2} cols={3} /></div> : !google.data?.configured ? (
            <div className="px-5 pb-5 text-sm"><Badge tone="amber">Not set up</Badge><p className="muted mt-2">Add <code>GOOGLE_CLIENT_ID</code> and <code>GOOGLE_CLIENT_SECRET</code> (a Google Cloud OAuth client, Drive API enabled) to the backend environment and restart it.</p></div>
          ) : (
            <div className="space-y-3 px-5 pb-5 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                {google.data.connected ? <Badge tone="green">Connected</Badge> : google.data.needsReauth ? <Badge tone="amber">Sign in again</Badge> : <Badge>Not connected</Badge>}
                {google.data.account && <span>{google.data.account}</span>}
                {google.data.lastSyncAt && <span className="muted text-xs">last check {new Date(google.data.lastSyncAt).toLocaleTimeString()}</span>}
              </div>
              <p className="muted text-xs">Drive folder: <b>{google.data.rootFolder}</b> (in My Drive) with one sub-folder per project, named like the project. On the phone: group, name, Export chat, Without media, save into that sub-folder.</p>
              {google.data.lastError && <p className="text-xs text-red-600 dark:text-red-400">{google.data.lastError}</p>}
              <div className="flex flex-wrap gap-2">
                {!google.data.connected && <Button variant="primary" loading={busy} onClick={connectGoogle}>{google.data.needsReauth ? 'Sign in again' : 'Connect Google Drive'}</Button>}
                {google.data.connected && <Button loading={busy} onClick={async () => { setBusy(true); try { const r = await api.post<{ handled: number }>('/google/sync'); toast.push('success', r.data.handled ? `${r.data.handled} file(s) imported` : 'Nothing new in Drive'); await google.refetch(); } catch (e) { toast.push('error', apiError(e).message); } setBusy(false); }}>Check now</Button>}
                {(google.data.connected || google.data.needsReauth) && <Button variant="ghost" onClick={() => setDisconnect(true)}>Disconnect</Button>}
              </div>
              {google.data.recentImports.length > 0 && <ul className="muted space-y-1 text-xs">{google.data.recentImports.slice(0, 6).map((e, i) => (
                <li key={i}>{new Date(e.importedAt).toLocaleString()} · {e.fileName} · <b>{e.outcome}</b>{e.detail ? ` (${e.detail})` : ''}</li>))}</ul>}
            </div>)}
        </Card>)}
      <ConfirmDialog open={disconnect} danger title="Disconnect Google Drive?" message="The saved permission is deleted and revoked at Google. Files already imported stay. You can connect again at any time." confirmLabel="Disconnect"
        onClose={() => setDisconnect(false)} onConfirm={async () => { try { await api.delete('/google/connection'); await google.refetch(); toast.push('success', 'Google Drive disconnected'); } catch (e) { toast.push('error', apiError(e).message); } setDisconnect(false); }} />
      <ConfirmDialog open={!!remove} danger title="Remove access?" message={`${remove?.user.name} will no longer be able to open this project.`} confirmLabel="Remove" onClose={() => setRemove(null)}
        onConfirm={async () => {
          try { await api.delete(`/projects/${projectId}/members/${remove.userId}`); await refresh(); toast.push('success', 'Access removed'); } catch (e) { toast.push('error', apiError(e).message); }
          setRemove(null);
        }} />
    </>
  );
}
