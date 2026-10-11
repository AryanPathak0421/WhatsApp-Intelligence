import clsx from 'clsx';
import { Bell, BarChart3, Briefcase, Clock, FileText, Folder, LayoutDashboard, ListChecks, LogOut, Menu, MessageCircle, MessageSquareText, Moon, Settings, ShieldAlert, Sparkles, Sun, Users, UserCheck, Wallet, X } from 'lucide-react';
import { ReactNode, useEffect, useMemo, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Action, useAuth } from '../lib/auth';
import Assistant from './Assistant';
import { useLiveEvents } from '../lib/live';
import { fmtDateTime } from '../lib/format';
import { useNotifications, useProjects, useRooms } from '../lib/queries';
import { api } from '../lib/api';
import { useQueryClient } from '@tanstack/react-query';
import { Badge, Select } from './ui';

export const LAST_PROJECT = 'wa.lastProject';
const NAV: { to: string; label: string; icon: ReactNode; project?: boolean; need?: Action }[] = [
  { to: '/', label: 'Dashboard', icon: <LayoutDashboard className="size-4" />, need: 'analytics:view' },
  { to: '/projects', label: 'Projects', icon: <Folder className="size-4" /> },
  { to: '/chat', label: 'Team chat', icon: <MessageCircle className="size-4" /> },
  { to: 'overview', label: 'Project overview', icon: <Briefcase className="size-4" />, project: true },
  { to: 'chat', label: 'Chat Analysis', icon: <MessageSquareText className="size-4" />, project: true, need: 'chat:view_raw' },
  { to: 'tasks', label: 'Tasks', icon: <ListChecks className="size-4" />, project: true },
  { to: 'team', label: 'Team', icon: <Users className="size-4" />, project: true, need: 'team:view' },
  { to: 'client-pending', label: 'Client Pending', icon: <UserCheck className="size-4" />, project: true },
  { to: 'sales', label: 'Sales', icon: <Wallet className="size-4" />, project: true, need: 'sales:view' },
  { to: 'risks', label: 'Risks', icon: <ShieldAlert className="size-4" />, project: true, need: 'risk:view' },
  { to: 'timeline', label: 'Timeline', icon: <Clock className="size-4" />, project: true },
  { to: 'reports', label: 'Reports', icon: <FileText className="size-4" />, project: true, need: 'report:view' },
  { to: 'analytics', label: 'Analytics', icon: <BarChart3 className="size-4" />, project: true, need: 'analytics:view' },
  { to: 'insights', label: 'Insights', icon: <Sparkles className="size-4" />, project: true, need: 'analytics:view' },
  { to: 'settings', label: 'Settings', icon: <Settings className="size-4" /> },
];

function useDark() {
  const [dark, setDark] = useState(() => localStorage.getItem('wa.theme') ? localStorage.getItem('wa.theme') === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches);
  useEffect(() => { document.documentElement.classList.toggle('dark', dark); localStorage.setItem('wa.theme', dark ? 'dark' : 'light'); }, [dark]);
  return [dark, setDark] as const;
}

function Notifications() {
  const { data } = useNotifications();
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const nav = useNavigate();
  return (
    <div className="relative">
      <button aria-label={`Notifications (${data?.unread ?? 0} unread)`} onClick={() => setOpen((o) => !o)} className="relative rounded-lg p-2 hover:bg-[var(--surface-2)]">
        <Bell className="size-4" />{!!data?.unread && <span className="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[10px] font-semibold text-white">{data.unread}</span>}
      </button>
      {open && (
        <div className="card absolute right-0 z-40 mt-2 w-80 shadow-xl">
          <div className="flex items-center justify-between border-b px-4 py-2.5"><span className="text-sm font-semibold">Notifications</span>
            <button className="text-xs text-brand-600 hover:underline" onClick={async () => { await api.post('/notifications/read-all'); qc.invalidateQueries({ queryKey: ['notifications'] }); }}>Mark all read</button></div>
          <ul className="max-h-80 overflow-y-auto">
            {!data?.items.length && <li className="muted p-6 text-center text-sm">You’re all caught up.</li>}
            {data?.items.slice(0, 15).map((n) => (
              <li key={n.id}><button onClick={() => { setOpen(false); if (n.link) nav(n.link.replace('/projects/', '/p/')); }}
                className={clsx('block w-full px-4 py-2.5 text-left hover:bg-[var(--surface-2)]', !n.readAt && 'bg-brand-500/5')}>
                <p className="text-sm">{n.title}</p><p className="muted text-xs">{fmtDateTime(n.createdAt)}</p></button></li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { user, logout, can } = useAuth();
  const { projectId: routeId } = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const { data: projects } = useProjects();
  const [dark, setDark] = useDark();
  const [mobile, setMobile] = useState(false);
  const live = useLiveEvents(!!user);
  const unreadChats = useRooms().data?.totalUnread ?? 0;
  const last = localStorage.getItem(LAST_PROJECT) ?? undefined;
  const projectId = routeId ?? (projects?.some((p) => p.id === last) ? last : projects?.[0]?.id);
  useEffect(() => { if (routeId) localStorage.setItem(LAST_PROJECT, routeId); }, [routeId]);
  useEffect(() => setMobile(false), [loc.pathname]);

  const items = useMemo(() => NAV.filter((n) => !n.need || can(n.need)), [can]);
  const sub = loc.pathname.split('/')[3] ?? 'overview';
  const switchProject = (id: string) => nav(routeId ? `/p/${id}/${sub === '' ? 'overview' : sub}` : `/p/${id}/overview`);

  const sidebar = (
    <nav className="flex h-full flex-col" aria-label="Main">
      <div className="flex items-center gap-2 px-5 py-4">
        <div className="grid size-8 place-items-center rounded-lg bg-brand-600 text-sm font-bold text-white">PI</div>
        <div><p className="text-sm font-semibold leading-tight">Project Intelligence</p><p className="muted text-[11px]">Chat → structured insight</p></div>
      </div>
      <ul className="flex-1 space-y-0.5 overflow-y-auto px-3 pb-3">
        {items.map((n) => {
          const to = n.project ? (projectId ? `/p/${projectId}/${n.to}` : '/projects') : n.to;
          return (
            <li key={n.label}>
              <NavLink to={to} end={n.to === '/'} className={({ isActive }) => clsx('flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
                isActive ? 'bg-brand-500/10 font-medium text-brand-700 dark:text-brand-100' : 'muted hover:bg-[var(--surface-2)] hover:text-[var(--text)]')}>
                {n.icon}{n.label}
                {n.to === '/chat' && unreadChats > 0 && <span className="ml-auto grid min-w-5 place-items-center rounded-full bg-brand-600 px-1.5 text-[10px] font-semibold text-white">{unreadChats}</span>}
              </NavLink>
            </li>
          );
        })}
      </ul>
      <div className="border-t p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5">
          <div className="grid size-8 place-items-center rounded-full bg-[var(--surface-2)] text-xs font-semibold">{user?.name.slice(0, 2).toUpperCase()}</div>
          <div className="min-w-0 flex-1"><p className="truncate text-sm font-medium">{user?.name}</p><p className="muted truncate text-[11px]">{user?.role.replace('_', ' ').toLowerCase()}</p></div>
          <button aria-label="Sign out" onClick={logout} className="rounded-md p-1.5 hover:bg-[var(--surface-2)]"><LogOut className="size-4" /></button>
        </div>
      </div>
    </nav>
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r bg-[var(--surface)] lg:block">{sidebar}</aside>
      {mobile && <div className="fixed inset-0 z-40 lg:hidden"><div className="absolute inset-0 bg-black/40" onClick={() => setMobile(false)} /><aside className="relative h-full w-64 bg-[var(--surface)]">{sidebar}</aside></div>}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-[var(--surface)] px-4 lg:px-6">
          <button className="rounded-lg p-2 hover:bg-[var(--surface-2)] lg:hidden" aria-label="Open menu" onClick={() => setMobile(true)}>{mobile ? <X className="size-4" /> : <Menu className="size-4" />}</button>
          <div className="flex items-center gap-2">
            <span className="muted hidden text-xs sm:inline">Project</span>
            <Select aria-label="Select project" className="w-44 sm:w-64" value={projectId ?? ''} onChange={(e) => switchProject(e.target.value)} disabled={!projects?.length}>
              {!projects?.length && <option value="">No projects yet</option>}
              {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </div>
          <div className="ml-auto flex items-center gap-1">
            <span title={live === 'live' ? 'Updates arrive automatically' : live === 'polling' ? 'Live connection unavailable; refreshing every 30 s' : 'Connecting'} className="muted mr-2 hidden items-center gap-1.5 text-[11px] sm:inline-flex"><span className={clsx('size-1.5 rounded-full', live === 'live' ? 'bg-green-500' : live === 'polling' ? 'bg-amber-500' : 'bg-gray-400')} />{live === 'live' ? 'Live' : live === 'polling' ? 'Polling' : '...'}</span>
            {import.meta.env.DEV && <Badge tone="gray" className="mr-2 hidden sm:inline-flex">dev</Badge>}
            <button aria-label="Toggle dark mode" onClick={() => setDark(!dark)} className="rounded-lg p-2 hover:bg-[var(--surface-2)]">{dark ? <Sun className="size-4" /> : <Moon className="size-4" />}</button>
            <Notifications />
          </div>
        </header>
        <main className="flex-1 overflow-y-auto"><div className="mx-auto w-full max-w-[1400px] p-4 lg:p-6"><Outlet context={{ projectId }} /></div></main>
      </div>
      {!loc.pathname.startsWith('/chat') && <Assistant projectId={projectId} />}{/* its floating button would cover the chat's send button */}
    </div>
  );
}
