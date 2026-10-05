import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { ClientPending, Evidence, Job, Msg, Overview, ProjectRow, Task } from './types';

const get = <T,>(url: string, params?: object) => api.get<T>(url, { params }).then((r) => r.data);

export const useProjects = () => useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectRow[] }>('/projects').then((r) => r.items) });
export const useExecutive = () => useQuery({ queryKey: ['executive'], queryFn: () => get<any>('/executive') });
export const useOverview = (id?: string) => useQuery({ queryKey: ['overview', id], enabled: !!id, queryFn: () => get<Overview>(`/projects/${id}/overview`) });
export const useProgress = (id?: string, explain = false) => useQuery({ queryKey: ['progress', id, explain], enabled: !!id, queryFn: () => get<any>(`/projects/${id}/progress`, { explain, history: true }) });
export const useHealth = (id?: string) => useQuery({ queryKey: ['health', id], enabled: !!id, queryFn: () => get<any>(`/projects/${id}/health`) });
export const useSummary = (id?: string) => useQuery({ queryKey: ['summary', id], enabled: !!id, queryFn: () => get<{ text: string; claims?: { text: string; evidence: any }[] }>(`/projects/${id}/summary`) });
export const useInsights = (id?: string, kind?: string, enabled = true) => useQuery({ queryKey: ['insights', id, kind], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/insights`, { kind }).then((r) => r.items) });
export const useTasks = (id?: string, params: Record<string, string> = {}) =>
  useQuery({ queryKey: ['tasks', id, params], enabled: !!id, queryFn: () => get<{ items: Task[]; nextCursor: string | null }>(`/projects/${id}/tasks`, { limit: 200, ...params }) });
export const useClientPending = (id?: string, params: Record<string, string> = {}) =>
  useQuery({ queryKey: ['cp', id, params], enabled: !!id, queryFn: () => get<{ items: ClientPending[] }>(`/projects/${id}/client-pending`, { limit: 200, ...params }).then((r) => r.items) });
export const useTeamPerf = (id?: string, enabled = true) => useQuery({ queryKey: ['team-perf', id], enabled: !!id && enabled, queryFn: () => get<any>(`/projects/${id}/team-performance`) });
export const useTeam = (id?: string, enabled = true) => useQuery({ queryKey: ['team', id], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/team`).then((r) => r.items) });
export const useSales = (id?: string, enabled = true) => useQuery({ queryKey: ['sales', id], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/sales`).then((r) => r.items) });
export const useRisks = (id?: string, enabled = true) => useQuery({ queryKey: ['risks', id], enabled: !!id && enabled, queryFn: () => get<{ summary: any; items: any[] }>(`/projects/${id}/risks`) });
export const useConflicts = (id?: string, enabled = true) => useQuery({ queryKey: ['conflicts', id], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/conflicts`).then((r) => r.items) });
export const useTimeline = (id?: string) => useQuery({ queryKey: ['timeline', id], enabled: !!id, queryFn: () => get<{ items: any[] }>(`/projects/${id}/timeline`).then((r) => r.items) });
export const useVelocity = (id?: string, enabled = true) => useQuery({ queryKey: ['velocity', id], enabled: !!id && enabled, queryFn: () => get<any>(`/projects/${id}/velocity`) });
export const useResponseTime = (id?: string, enabled = true) => useQuery({ queryKey: ['rt', id], enabled: !!id && enabled, queryFn: () => get<any>(`/projects/${id}/client-response-time`) });
export const useReports = (id?: string, enabled = true) => useQuery({ queryKey: ['reports', id], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/reports`).then((r) => r.items) });
export const useUploads = (id?: string, enabled = true) => useQuery({ queryKey: ['uploads', id], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/chat/uploads`).then((r) => r.items) });
export const useEvidence = (taskId?: string) => useQuery({ queryKey: ['evidence', taskId], enabled: !!taskId, queryFn: () => get<Evidence>(`/tasks/${taskId}/evidence`) });
export const useNotifications = () => useQuery({ queryKey: ['notifications'], refetchInterval: 60_000, queryFn: () => get<{ items: any[]; unread: number }>('/notifications') });
export const useMembers = (id?: string, enabled = true) => useQuery({ queryKey: ['members', id], enabled: !!id && enabled, queryFn: () => get<{ items: any[] }>(`/projects/${id}/members`).then((r) => r.items) });
export const useUsers = (enabled: boolean) => useQuery({ queryKey: ['users'], enabled, queryFn: () => get<{ items: any[] }>('/users').then((r) => r.items) });

export const useMessages = (id: string | undefined, params: Record<string, string>) =>
  useQuery({ queryKey: ['messages', id, params], enabled: !!id, queryFn: () => get<{ items: Msg[]; nextCursor: string | null }>(`/projects/${id}/messages`, { limit: 60, ...params }) });

/** Poll a job until it finishes. */
export const useJob = (jobId?: string | null) => useQuery({ queryKey: ['job', jobId], enabled: !!jobId,
  queryFn: () => get<Job>(`/analysis/${jobId}`), refetchInterval: (q) => (q.state.data && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(q.state.data.status) ? false : 1200) });

export function useInvalidateProject() {
  const qc = useQueryClient();
  return (projectId?: string) => {
    for (const k of ['overview', 'progress', 'health', 'summary', 'insights', 'tasks', 'cp', 'team-perf', 'team', 'sales', 'risks', 'conflicts', 'timeline', 'velocity', 'rt', 'uploads', 'messages', 'executive', 'projects', 'notifications'])
      qc.invalidateQueries({ queryKey: [k] });
    void projectId;
  };
}

export const useUpdateTask = () => { const inv = useInvalidateProject(); return useMutation({ mutationFn: ({ id, body }: { id: string; body: object }) => api.put(`/tasks/${id}`, body).then((r) => r.data), onSuccess: () => inv() }); };
export const useUpdateCp = () => { const inv = useInvalidateProject(); return useMutation({ mutationFn: ({ id, body }: { id: string; body: object }) => api.put(`/client-pending/${id}`, body).then((r) => r.data), onSuccess: () => inv() }); };

export const useQa = (id?: string, status?: string, enabled = true) => useQuery({ queryKey: ['qa', id, status], enabled: !!id && enabled, queryFn: () => get<any>(`/projects/${id}/qa`, status ? { status } : {}) });
export const useSentiment = (id?: string, enabled = true) => useQuery({ queryKey: ['sentiment', id], enabled: !!id && enabled, queryFn: () => get<any>(`/projects/${id}/sentiment`) });
export const useSummaries = (id?: string, kind: 'daily' | 'weekly' | 'monthly' = 'weekly', enabled = true) =>
  useQuery({ queryKey: ['summaries', id, kind], enabled: !!id && enabled, queryFn: () => get<any>(`/projects/${id}/summaries`, { kind }) });

export const useAutoImport = (enabled = true) => useQuery({ queryKey: ['auto-import'], enabled, refetchInterval: 15_000, queryFn: () => get<{
  enabled: boolean; root: string | null; lastScanAt: string | null; scans: number; intervalMs: number;
  folders: { folder: string; project: string | null; status: 'ok' | 'unknown' | 'ambiguous'; waitingFiles: number }[];
  recent: { at: string; folder: string; file?: string; outcome: string; detail?: string }[] }>('/auto-import/status') });
