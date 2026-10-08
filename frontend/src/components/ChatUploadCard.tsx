import clsx from 'clsx';
import { CheckCircle2, FileUp, Loader2, XCircle } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useInvalidateProject, useJob, useProjects } from '../lib/queries';
import { Button, Card, CardHeader, Input, ProgressBar, Select, useToast } from './ui';
import { LAST_PROJECT } from './Layout';

const NEW = '__new__';

/** Upload a WhatsApp export from the dashboard: pick a project (or create one), drop the .txt/.zip, watch the analysis finish. */
export default function ChatUploadCard() {
  const { can } = useAuth();
  const { data: projects } = useProjects();
  const toast = useToast();
  const invalidate = useInvalidateProject();
  const input = useRef<HTMLInputElement>(null);
  const [target, setTarget] = useState('');
  const [name, setName] = useState('');
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dup, setDup] = useState('');
  const [job, setJob] = useState<{ id: string; projectId: string } | null>(null);
  const canCreate = can('project:create');

  useEffect(() => {                                     // default to the project you used last, else the first one
    if (target || !projects) return;
    const last = localStorage.getItem(LAST_PROJECT);
    setTarget(projects.some((p) => p.id === last) ? last! : projects[0]?.id ?? (canCreate ? NEW : ''));
  }, [projects, target, canCreate]);

  const { data: status } = useJob(job?.id);
  const finished = status && ['COMPLETED', 'FAILED'].includes(status.status);
  useEffect(() => { if (status?.status === 'COMPLETED' && job) { invalidate(job.projectId); toast.push('success', 'Analysis finished'); } }, [status?.status]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!can('chat:upload')) return null;

  const send = async (file: File) => {
    setDup('');
    if (!/\.(txt|zip)$/i.test(file.name)) { toast.push('error', 'Choose the .txt file (or the .zip) that WhatsApp created'); return; }
    if (target === NEW && !name.trim()) { toast.push('error', 'Give the new project a name first'); return; }
    setBusy(true);
    try {
      let projectId = target;
      if (target === NEW) {
        projectId = (await api.post<{ id: string }>('/projects', { name: name.trim() })).data.id;
        setTarget(projectId); setName('');
        invalidate(projectId);
      }
      const fd = new FormData();
      fd.append('file', file);
      const r = await api.post<{ jobId: string }>(`/projects/${projectId}/chat/upload`, fd);
      localStorage.setItem(LAST_PROJECT, projectId);
      setJob({ id: r.data.jobId, projectId });
    } catch (e) {
      const err = apiError(e);
      if (err.code === 'DUPLICATE_UPLOAD') setDup(err.message); else toast.push('error', err.message);
    } finally { setBusy(false); }
  };

  const projectName = projects?.find((p) => p.id === job?.projectId)?.name;
  return (
    <Card className="mt-5">
      <CardHeader title="Upload a WhatsApp chat" sub="Export the group chat in WhatsApp (without media), choose the project, and drop the file. Only new messages are added if the project already has data." />
      <div className="space-y-4 px-5 pb-5">
        {!job ? (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <label className="text-sm"><span className="muted mb-1 block text-xs">Project</span>
                <Select aria-label="Project to upload into" className="w-72" value={target} onChange={(e) => setTarget(e.target.value)}>
                  {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  {canCreate && <option value={NEW}>+ New project...</option>}
                </Select></label>
              {target === NEW && <label className="text-sm"><span className="muted mb-1 block text-xs">New project name</span>
                <Input aria-label="New project name" className="w-72" value={name} onChange={(e) => setName(e.target.value)} maxLength={150} placeholder="e.g. Acme website" /></label>}
            </div>
            <div role="button" tabIndex={0} aria-label="Upload chat file" onClick={() => !busy && input.current?.click()} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && !busy && input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f && !busy) void send(f); }}
              className={clsx('flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors', over ? 'border-brand-500 bg-brand-500/5' : 'hover:bg-[var(--surface-2)]')}>
              {busy ? <Loader2 className="size-6 animate-spin text-brand-500" /> : <FileUp className="size-6 text-brand-500" />}
              <p className="text-sm font-medium">{busy ? 'Uploading...' : 'Drop the WhatsApp export (.txt or .zip) here, or click to browse'}</p>
              <p className="muted text-xs">Max 200 MB · stored encrypted · analysed on your own server</p>
              <input ref={input} type="file" accept=".txt,.zip,text/plain,application/zip" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void send(f); e.target.value = ''; }} />
            </div>
            {dup && <div role="alert" className="rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300">{dup}</div>}
          </>
        ) : (
          <div className="space-y-3" aria-live="polite">
            <div className="flex items-center justify-between text-sm">
              <span className="flex items-center gap-2 font-medium">
                {status?.status === 'FAILED' ? <XCircle className="size-4 text-red-500" /> : status?.status === 'COMPLETED' ? <CheckCircle2 className="size-4 text-emerald-500" /> : <Loader2 className="size-4 animate-spin text-brand-500" />}
                {status?.status === 'FAILED' ? 'Analysis failed' : status?.status === 'COMPLETED' ? `Done: ${projectName ?? 'project'} is updated` : `${status?.stage ?? 'Queued'}...`}
              </span>
              <span className="tabular-nums muted">{status?.progress ?? 0}%</span>
            </div>
            <ProgressBar value={status?.progress ?? 0} tone={status?.status === 'FAILED' ? 'red' : status?.status === 'COMPLETED' ? 'green' : 'brand'} label="Analysis progress" />
            {status?.status === 'FAILED' && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{status.error}</p>}
            {finished && <div className="flex gap-2">
              {status.status === 'COMPLETED' && <Link to={`/p/${job.projectId}/overview`}><Button variant="primary" size="sm">Open project</Button></Link>}
              <Button size="sm" onClick={() => setJob(null)}>Upload another</Button></div>}
          </div>
        )}
      </div>
    </Card>
  );
}
