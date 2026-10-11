import { useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { ArrowDown, ArrowLeft, Check, ChevronDown, Clock3, Copy, LogOut, MessageCirclePlus, Reply, Search, Send, Smile, UserPlus, Users, X } from 'lucide-react';
import { Fragment, ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button, Dialog, Input, Select, Skeleton, useToast } from '../components/ui';
import { api, apiError } from '../lib/api';
import { useAuth } from '../lib/auth';
import type { LiveEvent } from '../lib/live';
import { useProjects, useRoom, useRoomMessages, useRoomUsers, useRooms } from '../lib/queries';
import type { RoomMsg, RoomRow } from '../lib/types';

// ---------- chat helpers ----------
const NAME_COLORS = ['#1f7aec', '#e542a3', '#fa6533', '#06cf9c', '#a05fd1', '#ff7a8c', '#53bdeb', '#d4a017', '#2e9e5b', '#c45a2b'];
const colorFor = (s: string) => { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0; return NAME_COLORS[h % NAME_COLORS.length]; };
const initials = (n: string) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?';
const timeOf = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
const daysAgo = (iso: string) => Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 86_400_000);
const dayLabel = (iso: string) => {
  const n = daysAgo(iso);
  if (n <= 0) return 'Today';
  if (n === 1) return 'Yesterday';
  if (n < 7) return new Date(iso).toLocaleDateString([], { weekday: 'long' });
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'long', year: 'numeric' });
};
const listTime = (iso: string) => { const n = daysAgo(iso); return n <= 0 ? timeOf(iso) : n === 1 ? 'Yesterday' : n < 7 ? new Date(iso).toLocaleDateString([], { weekday: 'short' }) : new Date(iso).toLocaleDateString([], { day: '2-digit', month: '2-digit', year: '2-digit' }); };
const roleLabel = (r: string) => r.replace('_', ' ').toLowerCase();
const EMOJIS: Record<string, string[]> = {
  Smileys: ['😀', '😃', '😄', '😁', '😂', '🤣', '😊', '😇', '🙂', '😉', '😍', '😘', '😎', '🤩', '🤔', '🤨', '😐', '😅', '😬', '😢', '😭', '😤', '😡', '🥳', '😴', '🤯'],
  Gestures: ['👍', '👎', '👌', '✌️', '🤞', '🙏', '👏', '🙌', '🤝', '💪', '👀', '👋', '✋', '🫡'],
  Work: ['✅', '❌', '⏳', '⌛', '📌', '📎', '📝', '📅', '📊', '🚀', '⚠️', '🐞', '🔧', '💡', '🔥', '💯', '🎉', '❤️'],
};

/** Plain text -> text with clickable links and an optional search highlight. React escapes everything; no HTML is injected. */
function richText(text: string, highlight: string): ReactNode[] {
  const out: ReactNode[] = [];
  text.split(/(https?:\/\/[^\s<]+)/g).forEach((part, i) => {
    if (/^https?:\/\//.test(part)) { out.push(<a key={i} href={part} target="_blank" rel="noopener noreferrer">{part}</a>); return; }
    const q = highlight.trim();
    if (!q) { out.push(<Fragment key={i}>{part}</Fragment>); return; }
    const low = part.toLowerCase(), ql = q.toLowerCase();
    let at = 0, k = 0;
    for (let j = low.indexOf(ql); j >= 0; j = low.indexOf(ql, at)) {
      out.push(<Fragment key={`${i}-${k++}`}>{part.slice(at, j)}</Fragment>, <mark key={`${i}-${k++}`}>{part.slice(j, j + q.length)}</mark>);
      at = j + q.length;
    }
    out.push(<Fragment key={`${i}-${k}`}>{part.slice(at)}</Fragment>);
  });
  return out;
}

function Avatar({ name, group, size = 40 }: { name: string; group?: boolean; size?: number }) {
  const c = colorFor(name);
  return (
    <div className="grid shrink-0 select-none place-items-center rounded-full font-medium text-white" aria-hidden
      style={{ width: size, height: size, fontSize: size * 0.38, background: group ? `linear-gradient(135deg, ${c}, color-mix(in srgb, ${c} 55%, #111b21))` : c }}>
      {group ? <Users style={{ width: size * 0.48, height: size * 0.48 }} /> : initials(name)}
    </div>
  );
}

function Ticks({ status }: { status?: 'sent' | 'read' | 'pending' }) {
  if (status === 'pending') return <Clock3 className="size-3" aria-label="Sending" style={{ color: 'var(--wa-sub)' }} />;
  const read = status === 'read';
  const c = read ? 'var(--wa-tick)' : 'var(--wa-sub)';
  return (
    <svg viewBox="0 0 16 11" width="16" height="11" aria-label={read ? 'Read' : 'Sent'} className="inline-block">
      {read ? (<><path d="M1 6l3 3L11 1" fill="none" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M6 8.5l1 .9L15 1" fill="none" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></>)
        : <path d="M3 6l3 3L13 1" fill="none" stroke={c} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />}
    </svg>
  );
}

const IconBtn = ({ label, onClick, children, active }: { label: string; onClick: () => void; children: ReactNode; active?: boolean }) => (
  <button aria-label={label} title={label} onClick={onClick} className="grid size-10 place-items-center rounded-full transition-colors hover:bg-black/5 dark:hover:bg-white/5"
    style={{ color: active ? 'var(--wa-green)' : 'var(--wa-sub)' }}>{children}</button>
);

// ---------- chat list ----------
function RoomList({ rooms, activeId, onPick, loading }: { rooms: RoomRow[]; activeId?: string; onPick: (id: string) => void; loading: boolean }) {
  const [q, setQ] = useState('');
  const [tab, setTab] = useState<'all' | 'unread' | 'groups' | 'direct'>('all');
  const needle = q.trim().toLowerCase();
  const shown = rooms.filter((r) => (tab === 'all' || (tab === 'unread' ? r.unread > 0 : tab === 'groups' ? r.kind === 'GROUP' : r.kind === 'DIRECT'))
    && (!needle || r.name.toLowerCase().includes(needle) || (r.lastMessage?.text ?? '').toLowerCase().includes(needle) || (r.project?.name ?? '').toLowerCase().includes(needle)));
  const counts = { unread: rooms.filter((r) => r.unread > 0).length };
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="space-y-2.5 px-3 pb-2 pt-2.5">
        <label className="flex items-center gap-3 rounded-xl px-3 py-2 transition-shadow focus-within:shadow-[0_0_0_2px_var(--wa-green)]" style={{ background: 'var(--wa-header)' }}>
          <Search className="size-4 shrink-0" style={{ color: 'var(--wa-sub)' }} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chats, messages or projects" aria-label="Search chats"
            className="w-full bg-transparent text-sm outline-none placeholder:opacity-70" style={{ color: 'var(--wa-text)' }} />
          {q && <button aria-label="Clear search" onClick={() => setQ('')}><X className="size-4" style={{ color: 'var(--wa-sub)' }} /></button>}
        </label>
        <div className="flex gap-2 overflow-x-auto pb-0.5">
          {([['all', 'All'], ['unread', `Unread${counts.unread ? ` ${counts.unread}` : ''}`], ['groups', 'Groups'], ['direct', 'Direct']] as const).map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} className="shrink-0 rounded-full px-3 py-1 text-[13px] transition-colors"
              style={tab === k ? { background: 'color-mix(in srgb, var(--wa-green) 20%, transparent)', color: 'var(--wa-green)', fontWeight: 600 } : { background: 'var(--wa-header)', color: 'var(--wa-sub)' }}>{label}</button>))}
        </div>
      </div>
      <div className="wa-scroll min-h-0 flex-1 overflow-y-auto">
        {loading && <div className="space-y-2 p-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-16" />)}</div>}
        {!loading && !shown.length && <p className="p-8 text-center text-sm" style={{ color: 'var(--wa-sub)' }}>{rooms.length ? 'No chats match.' : 'No chats yet. Start one with the new chat button above.'}</p>}
        {shown.map((r) => {
          const active = r.id === activeId;
          const preview = r.lastMessage ? `${r.lastMessage.mine ? 'You: ' : r.kind === 'GROUP' ? `${r.lastMessage.senderName.split(' ')[0]}: ` : ''}${r.lastMessage.text}` : r.project ? `Project · ${r.project.name}` : 'No messages yet';
          return (
            <button key={r.id} onClick={() => onPick(r.id)} className={clsx('group flex w-full items-center gap-3 px-3 text-left transition-colors', !active && 'hover:bg-[var(--wa-hover)]')}
              style={{ background: active ? 'var(--wa-active)' : undefined }}>
              <Avatar name={r.name} group={r.kind === 'GROUP'} size={49} />
              <div className="min-w-0 flex-1 border-b py-3.5" style={{ borderColor: 'var(--wa-line)' }}>
                <div className="flex items-baseline gap-2">
                  <span className={clsx('truncate text-[16px]', r.unread > 0 && 'font-semibold')}>{r.name}</span>
                  {r.lastMessage && <span className="ml-auto shrink-0 text-[12px]" style={{ color: r.unread ? 'var(--wa-green)' : 'var(--wa-sub)', fontWeight: r.unread ? 600 : 400 }}>{listTime(r.lastMessage.at)}</span>}
                </div>
                <div className="mt-0.5 flex items-center gap-2">
                  <p className="truncate text-[14px]" style={{ color: r.unread ? 'var(--wa-text)' : 'var(--wa-sub)' }}>{preview}</p>
                  {r.project && !r.lastMessage && null}
                  {r.unread > 0 && <span className="ml-auto grid h-5 min-w-5 shrink-0 place-items-center rounded-full px-1.5 text-[11px] font-bold" style={{ background: 'var(--wa-green)', color: 'var(--wa-panel)' }}>{r.unread > 99 ? '99+' : r.unread}</span>}
                </div>
              </div>
            </button>);
        })}
      </div>
    </div>
  );
}

// ---------- right-hand info panel ----------
function InfoPanel({ roomId, onClose, onLeft, onAdd }: { roomId: string; onClose: () => void; onLeft: () => void; onAdd: () => void }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: room } = useRoom(roomId);
  const invites = useQuery({ queryKey: ['room-invites', roomId], enabled: !!room?.canManage, queryFn: () => api.get<{ items: { id: string; email: string; name: string | null; expiresAt: string }[] }>(`/rooms/${roomId}/invites`).then((r) => r.data.items) });
  if (!room) return null;
  const isGroup = room.kind === 'GROUP';
  const remove = async (id: string) => {
    try {
      await api.delete(`/rooms/${roomId}/members/${id}`);
      await qc.invalidateQueries({ queryKey: ['rooms'] });
      if (id === user?.id) onLeft(); else await qc.invalidateQueries({ queryKey: ['room', roomId] });
    } catch (e) { toast.push('error', apiError(e).message); }
  };
  return (
    <aside className="wa-slide absolute inset-0 z-20 flex flex-col md:static md:w-[360px] md:shrink-0 md:border-l" style={{ background: 'var(--wa-wall)', borderColor: 'var(--wa-line)' }}>
      <div className="flex h-[60px] items-center gap-4 px-4" style={{ background: 'var(--wa-header)' }}>
        <IconBtn label="Close info" onClick={onClose}><X className="size-5" /></IconBtn>
        <span className="text-[16px] font-medium">{isGroup ? 'Group info' : 'Contact info'}</span>
      </div>
      <div className="wa-scroll min-h-0 flex-1 space-y-2 overflow-y-auto">
        <div className="flex flex-col items-center px-6 py-7 text-center" style={{ background: 'var(--wa-panel)' }}>
          <Avatar name={room.name} group={isGroup} size={120} />
          <p className="mt-4 text-[22px]">{room.name}</p>
          <p className="text-sm" style={{ color: 'var(--wa-sub)' }}>{isGroup ? `Group · ${room.members.length} members` : roleLabel(room.members.find((m) => m.id !== user?.id)?.role ?? '')}</p>
        </div>
        {room.project && (
          <div className="px-6 py-4" style={{ background: 'var(--wa-panel)' }}>
            <p className="text-sm" style={{ color: 'var(--wa-sub)' }}>Project</p>
            <p className="mt-1 text-[15px]">{room.project.name}</p>
            {room.analysed && <p className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ background: 'color-mix(in srgb, var(--wa-green) 12%, transparent)', color: 'var(--wa-text)' }}>
              Messages in this group are analysed like an imported chat: tasks, progress and health update from the conversation.</p>}
          </div>)}
        {isGroup && (
          <div className="py-2" style={{ background: 'var(--wa-panel)' }}>
            <p className="px-6 pb-1 pt-2 text-sm" style={{ color: 'var(--wa-sub)' }}>{room.members.length} members</p>
            {room.canManage && (
              <button onClick={onAdd} className="flex w-full items-center gap-4 px-6 py-2.5 text-left hover:bg-[var(--wa-hover)]">
                <span className="grid size-10 place-items-center rounded-full text-white" style={{ background: 'var(--wa-green)' }}><UserPlus className="size-5" /></span>
                <span className="text-[15px]">Add people or invite by e-mail</span>
              </button>)}
            {room.members.map((m) => (
              <div key={m.id} className="group flex items-center gap-4 px-6 py-2.5 hover:bg-[var(--wa-hover)]">
                <Avatar name={m.name} size={40} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[15px]">{m.id === user?.id ? 'You' : m.name}</p>
                  <p className="truncate text-xs" style={{ color: 'var(--wa-sub)' }}>{roleLabel(m.role)}</p>
                </div>
                {room.canManage && m.id !== user?.id && <button className="rounded-full px-2 py-1 text-xs opacity-0 group-hover:opacity-100" style={{ color: '#ea0038' }} onClick={() => void remove(m.id)}>Remove</button>}
              </div>))}
          </div>)}
        {!!invites.data?.length && (
          <div className="py-2" style={{ background: 'var(--wa-panel)' }}>
            <p className="px-6 pb-1 pt-2 text-sm" style={{ color: 'var(--wa-sub)' }}>Pending invitations</p>
            {invites.data.map((i) => (
              <div key={i.id} className="flex items-center gap-4 px-6 py-2">
                <span className="grid size-10 place-items-center rounded-full" style={{ background: 'var(--wa-header)', color: 'var(--wa-sub)' }}><Clock3 className="size-4" /></span>
                <div className="min-w-0 flex-1"><p className="truncate text-sm">{i.name || i.email}</p><p className="truncate text-xs" style={{ color: 'var(--wa-sub)' }}>{i.name ? i.email : ''} expires {new Date(i.expiresAt).toLocaleDateString()}</p></div>
                <button className="text-xs underline" style={{ color: 'var(--wa-sub)' }} onClick={async () => { await api.delete(`/rooms/${roomId}/invites/${i.id}`); await invites.refetch(); }}>Revoke</button>
              </div>))}
          </div>)}
        {isGroup && (
          <button onClick={() => void remove(user!.id)} className="flex w-full items-center gap-4 px-6 py-4 text-left hover:bg-[var(--wa-hover)]" style={{ background: 'var(--wa-panel)', color: '#ea0038' }}>
            <LogOut className="size-5" /><span className="text-[15px]">Exit group</span>
          </button>)}
      </div>
    </aside>
  );
}

// ---------- one conversation ----------
type Shown = RoomMsg & { pending?: boolean };

function Conversation({ roomId, onBack, unreadAtOpen }: { roomId: string; onBack: () => void; unreadAtOpen: number }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: room, error: roomError } = useRoom(roomId);
  const { data, isLoading } = useRoomMessages(roomId);
  const [text, setText] = useState('');
  const [reply, setReply] = useState<RoomMsg | null>(null);
  const [info, setInfo] = useState(false);
  const [adding, setAdding] = useState(false);
  const [emoji, setEmoji] = useState(false);
  const [emojiTab, setEmojiTab] = useState<keyof typeof EMOJIS>('Smileys');
  const [atBottom, setAtBottom] = useState(true);
  const [newBelow, setNewBelow] = useState(0);
  const [searching, setSearching] = useState(false);
  const [find, setFind] = useState('');
  const [menu, setMenu] = useState<string | null>(null);
  const [pending, setPending] = useState<Shown[]>([]);
  const [typing, setTyping] = useState<Record<string, number>>({});
  const [divider, setDivider] = useState(unreadAtOpen);
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const lastTypingSent = useRef(0);
  const items: Shown[] = useMemo(() => [...(data?.items ?? []), ...pending], [data, pending]);
  const lastId = items.at(-1)?.id;
  const lastMine = items.at(-1)?.mine;

  // reset per room
  useEffect(() => { setReply(null); setText(''); setInfo(false); setEmoji(false); setSearching(false); setFind(''); setPending([]); setTyping({}); setDivider(unreadAtOpen); setNewBelow(0); }, [roomId]); // eslint-disable-line react-hooks/exhaustive-deps
  // follow the conversation unless the reader scrolled up to read history
  useEffect(() => {
    if (atBottom || lastMine) { end.current?.scrollIntoView({ block: 'end' }); setNewBelow(0); }
    else setNewBelow((n) => n + 1);
  }, [lastId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [roomId, isLoading]);
  // opening the room, or a new message while it is open, marks it read
  useEffect(() => {
    if (!data?.items.length) return;
    api.post(`/rooms/${roomId}/read`).then(() => qc.invalidateQueries({ queryKey: ['rooms'] })).catch(() => undefined);
  }, [roomId, data?.items.at(-1)?.id, qc]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const t = box.current; if (t) { t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 140) + 'px'; } }, [text]);
  // "typing..." from other members (ephemeral live events)
  useEffect(() => {
    const on = (ev: Event) => {
      const e = (ev as CustomEvent<LiveEvent>).detail;
      if (e.type === 'chat.typing' && e.roomId === roomId && e.actorId && e.actorId !== user?.id) setTyping((t) => ({ ...t, [e.actorId!]: Date.now() + 4500 }));
      if (e.type === 'chat.message' && e.roomId === roomId) setTyping({});
    };
    window.addEventListener('live:event', on);
    const tick = setInterval(() => setTyping((t) => { const now = Date.now(); const k = Object.entries(t).filter(([, v]) => v > now); return k.length === Object.keys(t).length ? t : Object.fromEntries(k); }), 1000);
    return () => { window.removeEventListener('live:event', on); clearInterval(tick); };
  }, [roomId, user?.id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { if (menu) setMenu(null); else if (emoji) setEmoji(false); else if (reply) setReply(null); else if (searching) { setSearching(false); setFind(''); } } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [menu, emoji, reply, searching]);

  const onType = (v: string) => {
    setText(v);
    if (v.trim() && Date.now() - lastTypingSent.current > 2500) { lastTypingSent.current = Date.now(); api.post(`/rooms/${roomId}/typing`).catch(() => undefined); }
  };

  const send = async () => {
    const t = text.trim();
    if (!t) return;
    const tmp: Shown = { id: `tmp-${Date.now()}`, senderId: user!.id, senderName: user!.name, mine: true, status: undefined, pending: true, text: t, createdAt: new Date().toISOString(),
      replyTo: reply ? { id: reply.id, senderName: reply.senderName, text: reply.text.slice(0, 120) } : null };
    const replyId = reply?.id;
    setPending((p) => [...p, tmp]); setText(''); setReply(null); setEmoji(false); setDivider(0);
    box.current?.focus();
    try {
      await api.post(`/rooms/${roomId}/messages`, { text: t, replyToId: replyId });
      await qc.invalidateQueries({ queryKey: ['room-messages', roomId] });
      void qc.invalidateQueries({ queryKey: ['rooms'] });
    } catch (e) { toast.push('error', apiError(e).message); setText(t); }
    finally { setPending((p) => p.filter((x) => x.id !== tmp.id)); }
  };

  const shown = useMemo(() => (find.trim() ? items.filter((m) => m.text.toLowerCase().includes(find.trim().toLowerCase())) : items), [items, find]);
  const dividerBefore = useMemo(() => {
    if (!divider || find) return null;
    let n = 0;
    for (let i = items.length - 1; i >= 0; i--) { if (!items[i].mine) n++; if (n === divider) return items[i].id; }
    return items[0]?.id ?? null;
  }, [divider, items, find]);

  if (roomError) return (
    <div className="wa-wall grid h-full place-items-center p-6 text-center">
      <div className="rounded-xl px-6 py-5" style={{ background: 'var(--wa-panel)' }}><p className="text-sm">This chat is not available. You may have been removed from it.</p><Button className="mt-3" onClick={onBack}>Back to chats</Button></div>
    </div>);

  const isGroup = room?.kind === 'GROUP';
  const typers = Object.keys(typing).map((id) => room?.members.find((m) => m.id === id)?.name.split(' ')[0]).filter(Boolean) as string[];
  const subtitle = typers.length ? `${typers.join(', ')} ${typers.length > 1 ? 'are' : 'is'} typing…`
    : !room ? '' : isGroup ? room.members.map((m) => (m.id === user?.id ? 'You' : m.name.split(' ')[0])).join(', ') : room.project ? room.project.name : 'Direct message';

  return (
    <div className="relative flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* header */}
        <div className="flex h-[60px] shrink-0 items-center gap-2 px-2 md:px-4" style={{ background: 'var(--wa-header)' }}>
          <button className="grid size-10 place-items-center rounded-full md:hidden" aria-label="Back to chats" onClick={onBack}><ArrowLeft className="size-5" /></button>
          <button className="flex min-w-0 flex-1 items-center gap-3 rounded-lg py-1 text-left" onClick={() => setInfo((s) => !s)} aria-label="Open chat info">
            <Avatar name={room?.name ?? '?'} group={isGroup} size={40} />
            <div className="min-w-0">
              <p className="truncate text-[16px] font-medium">{room?.name ?? '…'}</p>
              <p className="truncate text-[13px]" style={{ color: typers.length ? 'var(--wa-green)' : 'var(--wa-sub)' }}>{subtitle}</p>
            </div>
          </button>
          {room?.analysed && <span className="mr-1 hidden items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium lg:inline-flex" style={{ background: 'color-mix(in srgb, var(--wa-green) 16%, transparent)', color: 'var(--wa-green)' }}
            title="Messages in this group are analysed like an imported chat: tasks, progress and health update from them"><Check className="size-3" />Analysed</span>}
          {room?.canManage && (
            <button className="mr-1 hidden items-center gap-1.5 rounded-full px-3.5 py-2 text-sm font-medium text-white transition-transform active:scale-95 sm:flex" style={{ background: 'var(--wa-green)' }} onClick={() => setAdding(true)}>
              <UserPlus className="size-4" />Add people
            </button>)}
          <IconBtn label="Search messages" active={searching} onClick={() => { setSearching((s) => !s); setFind(''); }}><Search className="size-5" /></IconBtn>
        </div>
        {searching && (
          <div className="flex items-center gap-2 px-4 py-2" style={{ background: 'var(--wa-panel)', borderBottom: '1px solid var(--wa-line)' }}>
            <Search className="size-4" style={{ color: 'var(--wa-sub)' }} />
            <input autoFocus value={find} onChange={(e) => setFind(e.target.value)} placeholder="Search in this chat" aria-label="Search in this chat" className="flex-1 bg-transparent text-sm outline-none" style={{ color: 'var(--wa-text)' }} />
            {find && <span className="text-xs" style={{ color: 'var(--wa-sub)' }}>{shown.length} found</span>}
            <button aria-label="Close search" onClick={() => { setSearching(false); setFind(''); }}><X className="size-4" style={{ color: 'var(--wa-sub)' }} /></button>
          </div>)}

        {/* messages */}
        <div className="relative min-h-0 flex-1" onClick={() => setMenu(null)}>
          <div className="wa-wall wa-scroll h-full overflow-y-auto px-3 pb-2 pt-3 md:px-[6%]"
            onScroll={(e) => { const el = e.currentTarget; const b = el.scrollHeight - el.scrollTop - el.clientHeight < 80; setAtBottom(b); if (b) setNewBelow(0); }}>
            {isLoading && <div className="space-y-3 pt-4">{[0, 1, 2].map((i) => <Skeleton key={i} className={clsx('h-10 w-56', i % 2 && 'ml-auto')} />)}</div>}
            {!isLoading && room && (
              <div className="mx-auto mb-3 mt-1 max-w-md rounded-lg px-3 py-2 text-center text-[12.5px] shadow-sm" style={{ background: 'var(--wa-note)', color: 'var(--wa-note-text)' }}>
                🔒 Messages stay inside this application{room.analysed ? '. This group is analysed for project tasks and progress.' : '. Not analysed.'}
              </div>)}
            {!isLoading && !items.length && <p className="mx-auto mt-6 w-fit rounded-lg px-3 py-1.5 text-xs shadow-sm" style={{ background: 'var(--wa-in)', color: 'var(--wa-sub)' }}>No messages yet. Say hello 👋</p>}
            {find && !shown.length && <p className="mx-auto mt-6 w-fit rounded-lg px-3 py-1.5 text-xs shadow-sm" style={{ background: 'var(--wa-in)', color: 'var(--wa-sub)' }}>No messages match “{find}”.</p>}
            {shown.map((m, i) => {
              const prev = shown[i - 1];
              const newDay = !prev || daysAgo(prev.createdAt) !== daysAgo(m.createdAt);
              const first = newDay || prev.senderId !== m.senderId || m.id === dividerBefore;
              const showAvatar = isGroup && !m.mine;
              return (
                <Fragment key={m.id}>
                  {newDay && <div className="sticky top-1 z-10 my-3 flex justify-center"><span className="rounded-lg px-3 py-1 text-[12.5px] shadow-sm" style={{ background: 'var(--wa-in)', color: 'var(--wa-sub)' }}>{dayLabel(m.createdAt)}</span></div>}
                  {m.id === dividerBefore && (
                    <div className="my-3 flex justify-center"><span className="rounded-full px-4 py-1 text-[12.5px] font-medium shadow-sm" style={{ background: 'color-mix(in srgb, var(--wa-panel) 90%, transparent)', color: 'var(--wa-green)' }}>
                      {divider} unread message{divider === 1 ? '' : 's'}</span></div>)}
                  <div className={clsx('group flex items-end gap-2', m.mine ? 'justify-end' : 'justify-start', first ? 'mt-2.5' : 'mt-[3px]', (m.pending || i === shown.length - 1) && 'wa-pop')}>
                    {showAvatar && (first ? <div className="mb-0.5 self-start"><Avatar name={m.senderName} size={28} /></div> : <div className="w-7 shrink-0" />)}
                    <div className={clsx('wa-bubble max-w-[85%] px-2 pb-1.5 pt-1.5 text-[14.2px] leading-[19px] md:max-w-[62%]', m.mine ? 'out' : 'in', first && 'tail')}>
                      {!m.pending && (
                        <button aria-label="Message options" onClick={(e) => { e.stopPropagation(); setMenu(menu === m.id ? null : m.id); }}
                          className="absolute right-1 top-1 z-10 grid size-6 place-items-center rounded-full opacity-0 transition-opacity focus:opacity-100 group-hover:opacity-100"
                          style={{ background: m.mine ? 'var(--wa-out)' : 'var(--wa-in)', color: 'var(--wa-sub)' }}><ChevronDown className="size-4" /></button>)}
                      {menu === m.id && (
                        <div className={clsx('wa-pop absolute top-7 z-30 w-40 overflow-hidden rounded-lg py-1.5 shadow-xl', m.mine ? 'right-0' : 'left-0')} style={{ background: 'var(--wa-panel)' }} onClick={(e) => e.stopPropagation()}>
                          <button className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm hover:bg-[var(--wa-hover)]" onClick={() => { setReply(m); setMenu(null); box.current?.focus(); }}><Reply className="size-4" />Reply</button>
                          <button className="flex w-full items-center gap-3 px-4 py-2 text-left text-sm hover:bg-[var(--wa-hover)]" onClick={() => { void navigator.clipboard?.writeText(m.text); setMenu(null); toast.push('success', 'Message copied'); }}><Copy className="size-4" />Copy</button>
                        </div>)}
                      {first && !m.mine && isGroup && <p className="mb-0.5 pr-6 text-[12.8px] font-medium" style={{ color: colorFor(m.senderName) }}>{m.senderName}</p>}
                      {m.replyTo && (
                        <div className="mb-1 overflow-hidden rounded-md border-l-4 px-2 py-1 text-[12.8px]" style={{ borderColor: colorFor(m.replyTo.senderName), background: 'color-mix(in srgb, var(--wa-text) 6%, transparent)' }}>
                          <p className="font-medium" style={{ color: colorFor(m.replyTo.senderName) }}>{m.replyTo.senderName === user?.name ? 'You' : m.replyTo.senderName}</p>
                          <p className="line-clamp-2" style={{ color: 'var(--wa-sub)' }}>{m.replyTo.text}</p>
                        </div>)}
                      <span className="whitespace-pre-wrap break-words px-0.5">{richText(m.text, find)}</span>
                      <span className="float-right ml-3 mt-1.5 inline-flex translate-y-[3px] items-center gap-1 text-[11px]" style={{ color: 'var(--wa-sub)' }}>
                        {timeOf(m.createdAt)}{m.mine && <Ticks status={m.pending ? 'pending' : m.status} />}
                      </span>
                    </div>
                  </div>
                </Fragment>);
            })}
            {typers.length > 0 && !find && (
              <div className="wa-pop mt-2 flex items-end gap-2">
                {isGroup && <div className="w-7 shrink-0" />}
                <div className="wa-bubble in tail px-3 py-2.5"><span className="wa-dots" aria-label={`${typers.join(', ')} typing`}><span /><span /><span /></span></div>
              </div>)}
            <div ref={end} className="h-1" />
          </div>
          {!atBottom && (
            <button aria-label="Scroll to latest" onClick={() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); setNewBelow(0); }}
              className="wa-pop absolute bottom-4 right-5 grid size-11 place-items-center rounded-full shadow-lg" style={{ background: 'var(--wa-panel)', color: 'var(--wa-sub)' }}>
              <ArrowDown className="size-5" />
              {newBelow > 0 && <span className="absolute -top-1.5 -right-1 grid h-5 min-w-5 place-items-center rounded-full px-1 text-[11px] font-bold" style={{ background: 'var(--wa-green)', color: 'var(--wa-panel)' }}>{newBelow}</span>}
            </button>)}
        </div>

        {/* composer */}
        <div className="shrink-0" style={{ background: 'var(--wa-header)' }}>
          {reply && (
            <div className="wa-pop flex items-start gap-3 px-4 pt-2.5">
              <div className="min-w-0 flex-1 overflow-hidden rounded-lg border-l-4 px-3 py-2 text-[13px]" style={{ borderColor: colorFor(reply.senderName), background: 'var(--wa-pill)' }}>
                <p className="font-medium" style={{ color: colorFor(reply.senderName) }}>{reply.mine ? 'You' : reply.senderName}</p>
                <p className="truncate" style={{ color: 'var(--wa-sub)' }}>{reply.text}</p>
              </div>
              <IconBtn label="Cancel reply" onClick={() => setReply(null)}><X className="size-5" /></IconBtn>
            </div>)}
          {emoji && (
            <div className="wa-pop px-3 pt-2">
              <div className="flex gap-1 pb-1.5">
                {(Object.keys(EMOJIS) as (keyof typeof EMOJIS)[]).map((k) => (
                  <button key={k} onClick={() => setEmojiTab(k)} className="rounded-full px-3 py-1 text-xs" style={emojiTab === k ? { background: 'color-mix(in srgb, var(--wa-green) 20%, transparent)', color: 'var(--wa-green)', fontWeight: 600 } : { color: 'var(--wa-sub)' }}>{k}</button>))}
              </div>
              <div className="grid max-h-40 grid-cols-9 gap-0.5 overflow-y-auto sm:grid-cols-12 md:grid-cols-14">
                {EMOJIS[emojiTab].map((e) => <button key={e} className="rounded-lg p-1.5 text-[22px] transition-transform hover:scale-125" onClick={() => { setText((t) => t + e); box.current?.focus(); }}>{e}</button>)}
              </div>
            </div>)}
          <div className="flex items-end gap-1.5 px-2 py-2.5 md:px-4">
            <IconBtn label="Emoji" active={emoji} onClick={() => setEmoji((s) => !s)}><Smile className="size-6" /></IconBtn>
            <textarea ref={box} value={text} onChange={(e) => onType(e.target.value)} rows={1} maxLength={4000} placeholder="Type a message" aria-label="Message"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void send(); } }}
              className="wa-scroll max-h-[140px] min-h-[44px] flex-1 resize-none rounded-xl px-4 py-[11px] text-[15px] leading-[22px] outline-none" style={{ background: 'var(--wa-input)', color: 'var(--wa-text)' }} />
            <button aria-label="Send" onClick={() => void send()} disabled={!text.trim()}
              className="grid size-11 shrink-0 place-items-center rounded-full text-white shadow-sm transition-all active:scale-90 disabled:opacity-40" style={{ background: 'var(--wa-green)' }}><Send className="size-5 translate-x-[1px]" /></button>
          </div>
        </div>
      </div>
      {info && <InfoPanel roomId={roomId} onClose={() => setInfo(false)} onLeft={onBack} onAdd={() => setAdding(true)} />}
      <AddMember open={adding} onClose={() => setAdding(false)} roomId={roomId} projectId={room?.project?.id} existing={room?.members.map((m) => m.id) ?? []} />
    </div>
  );
}

// ---------- dialogs ----------
function AddMember({ open, onClose, roomId, projectId, existing }: { open: boolean; onClose: () => void; roomId: string; projectId?: string; existing: string[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: users } = useRoomUsers(open, projectId);
  const [tab, setTab] = useState<'people' | 'email'>('people');
  const [uid, setUid] = useState('');
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useQuery({ queryKey: ['room-invites', roomId], enabled: open && !!projectId, queryFn: () => api.get<{ items: { id: string; email: string; name: string | null; expiresAt: string }[] }>(`/rooms/${roomId}/invites`).then((r) => r.data.items) });
  const options = (users ?? []).filter((u) => !existing.includes(u.id));
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ['room', roomId] }); await qc.invalidateQueries({ queryKey: ['rooms'] }); await qc.invalidateQueries({ queryKey: ['room-invites', roomId] }); };

  const submit = async () => {
    setBusy(true);
    try {
      if (tab === 'people') {
        await api.post(`/rooms/${roomId}/members`, { userId: uid });
        toast.push('success', 'Added. They will get an e-mail.');
        setUid(''); onClose();
      } else {
        const r = await api.post(`/rooms/${roomId}/invite`, { email: email.trim(), name: name.trim() || undefined });
        const s = r.data.status;
        toast.push(s === 'invited' && !r.data.emailSent ? 'error' : 'success',
          s === 'invited' ? (r.data.emailSent ? `Invitation e-mailed to ${email.trim()}` : 'Invitation created, but the e-mail could not be sent (check SMTP settings)')
            : s === 'added' ? 'They already had an account and were added. They will get an e-mail.' : 'Already in this group');
        setEmail(''); setName('');
      }
      await refresh();
    } catch (e) { toast.push('error', apiError(e).message); } finally { setBusy(false); }
  };
  const ready = tab === 'people' ? !!uid : /^\S+@\S+\.\S+$/.test(email.trim());

  return (
    <Dialog open={open} onClose={onClose} title="Add people" footer={<><Button onClick={onClose}>Close</Button>
      <Button variant="primary" loading={busy} disabled={!ready} onClick={() => void submit()}>{tab === 'people' ? 'Add' : 'Send invitation'}</Button></>}>
      <div className="space-y-3">
        {(
          <div className="flex gap-1 rounded-lg bg-[var(--surface-2)] p-1 text-sm">
            {([['people', 'From the team'], ['email', 'Invite by e-mail']] as const).map(([k, l]) => (
              <button key={k} onClick={() => setTab(k)} className={clsx('flex-1 rounded-md px-3 py-1.5', tab === k ? 'bg-[var(--surface)] font-medium shadow-sm' : 'muted')}>{l}</button>))}
          </div>)}
        {tab === 'people' ? (
          <>
            <Select aria-label="Person" value={uid} onChange={(e) => setUid(e.target.value)}>
              <option value="">{options.length ? 'Choose a person' : 'No one else available'}</option>
              {options.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </Select>
            {projectId && <p className="muted text-xs">Only people with access to the project are listed. They get an e-mail when added.</p>}
          </>
        ) : (
          <>
            <Input aria-label="E-mail" type="email" placeholder="client@company.com" value={email} onChange={(e) => setEmail(e.target.value)} />
            <Input aria-label="Name (optional)" placeholder="Name (optional)" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
            {projectId
              ? <p className="muted text-xs">They receive an e-mail with a link. Opening it creates a client account with view access to this project and joins this group. The link works once.</p>
              : <p className="muted text-xs">They receive an e-mail with a link. Opening it creates a client account that can use <b>only this group</b> (this group is not linked to a project, so no project data is shared). The link works once.</p>}
            {!!pending.data?.length && (
              <div>
                <p className="mb-1 text-xs font-medium">Pending invitations</p>
                <ul className="space-y-1">
                  {pending.data.map((i) => (
                    <li key={i.id} className="flex items-center gap-2 rounded-md bg-[var(--surface-2)] px-2 py-1 text-xs">
                      <span className="flex-1 truncate">{i.name ? `${i.name} · ` : ''}{i.email}</span>
                      <button className="underline" onClick={async () => { await api.delete(`/rooms/${roomId}/invites/${i.id}`); await refresh(); }}>Revoke</button>
                    </li>))}
                </ul>
              </div>)}
          </>
        )}
      </div>
    </Dialog>
  );
}

function NewChat({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { can } = useAuth();
  const canGroup = can('member:manage');
  const qc = useQueryClient();
  const toast = useToast();
  const { data: projects } = useProjects();
  const [mode, setMode] = useState<'direct' | 'group'>(canGroup ? 'group' : 'direct');
  const [name, setName] = useState('');
  const [projectId, setProjectId] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [direct, setDirect] = useState('');
  const [busy, setBusy] = useState(false);
  const { data: users } = useRoomUsers(open, mode === 'group' && projectId ? projectId : undefined);
  useEffect(() => { setPicked([]); }, [projectId, mode]);

  const submit = async () => {
    setBusy(true);
    try {
      const r = mode === 'direct' ? await api.post('/rooms/direct', { userId: direct }) : await api.post('/rooms', { name: name.trim(), projectId: projectId || undefined, memberIds: picked });
      await qc.invalidateQueries({ queryKey: ['rooms'] });
      setName(''); setPicked([]); setDirect(''); onClose(); onCreated(r.data.id);
    } catch (e) { toast.push('error', apiError(e).message); } finally { setBusy(false); }
  };
  const ready = mode === 'direct' ? !!direct : name.trim().length > 0;

  return (
    <Dialog open={open} onClose={onClose} title="New chat" footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} disabled={!ready} onClick={() => void submit()}>{mode === 'direct' ? 'Open chat' : 'Create group'}</Button></>}>
      <div className="space-y-3">
        {canGroup && (
          <div className="flex gap-1 rounded-lg bg-[var(--surface-2)] p-1 text-sm">
            {(['group', 'direct'] as const).map((m) => <button key={m} onClick={() => setMode(m)} className={clsx('flex-1 rounded-md px-3 py-1.5', mode === m ? 'bg-[var(--surface)] font-medium shadow-sm' : 'muted')}>{m === 'group' ? 'New group' : 'New chat'}</button>)}
          </div>)}
        {mode === 'direct' ? (
          <Select aria-label="Person" value={direct} onChange={(e) => setDirect(e.target.value)}>
            <option value="">Choose a person</option>
            {(users ?? []).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </Select>
        ) : (
          <>
            <Input aria-label="Group name" placeholder="Group name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
            <Select aria-label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">No project (not analysed)</option>
              {projects?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
            {projectId && <p className="muted text-xs">Messages in a project group are analysed: tasks, progress and health update from the conversation.</p>}
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-lg border p-2">
              {!users?.length && <p className="muted p-2 text-xs">No one available to add.</p>}
              {users?.map((u) => (
                <label key={u.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-[var(--surface-2)]">
                  <input type="checkbox" checked={picked.includes(u.id)} onChange={(e) => setPicked((p) => (e.target.checked ? [...p, u.id] : p.filter((x) => x !== u.id)))} />
                  {u.name}<span className="muted ml-auto text-[11px]">{u.role.replace('_', ' ').toLowerCase()}</span>
                </label>))}
            </div>
          </>
        )}
      </div>
    </Dialog>
  );
}

// ---------- page ----------
export default function Chat() {
  const { roomId } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const { data, isLoading } = useRooms();
  const [creating, setCreating] = useState(false);
  const rooms = data?.items ?? [];
  const open = (id?: string) => nav(id ? `/chat/${id}` : '/chat');
  // unread count at the moment a room is opened: drives the "N unread messages" divider
  const unreadAtOpen = useMemo(() => rooms.find((r) => r.id === roomId)?.unread ?? 0, [roomId, isLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="wa-chat -m-4 flex h-[calc(100vh-3.5rem)] min-h-[460px] overflow-hidden lg:-m-6" style={{ background: 'var(--wa-panel)' }}>
      <aside className={clsx('w-full shrink-0 flex-col border-r md:flex md:w-[400px]', roomId ? 'hidden' : 'flex')} style={{ borderColor: 'var(--wa-line)', background: 'var(--wa-panel)' }}>
        <div className="flex h-[60px] shrink-0 items-center gap-3 px-4" style={{ background: 'var(--wa-header)' }}>
          <Avatar name={user?.name ?? '?'} size={40} />
          <div className="min-w-0 flex-1">
            <h1 className="text-[19px] font-semibold leading-tight">Chats</h1>
            {!!data?.totalUnread && <p className="text-[12px]" style={{ color: 'var(--wa-green)' }}>{data.totalUnread} unread</p>}
          </div>
          <button className="flex items-center gap-1.5 rounded-full px-3 py-2 text-sm font-medium text-white transition-transform active:scale-95" style={{ background: 'var(--wa-green)' }} onClick={() => setCreating(true)}>
            <MessageCirclePlus className="size-4" />New
          </button>
        </div>
        <RoomList rooms={rooms} activeId={roomId} onPick={open} loading={isLoading} />
      </aside>
      <section className={clsx('min-w-0 flex-1', roomId ? 'block' : 'hidden md:block')}>
        {roomId ? <Conversation key={roomId} roomId={roomId} onBack={() => open()} unreadAtOpen={unreadAtOpen} /> : (
          <div className="grid h-full place-items-center p-8 text-center" style={{ background: 'var(--wa-header)', borderBottom: '6px solid var(--wa-green)' }}>
            <div className="max-w-md">
              <div className="mx-auto mb-6 grid size-28 place-items-center rounded-full" style={{ background: 'color-mix(in srgb, var(--wa-green) 14%, transparent)' }}>
                <MessageCirclePlus className="size-12" style={{ color: 'var(--wa-green)' }} />
              </div>
              <h2 className="text-[30px] font-light">Team chat</h2>
              <p className="mt-3 text-sm leading-6" style={{ color: 'var(--wa-sub)' }}>Talk with your team and clients in project groups. Project groups feed the project&apos;s analysis automatically, so tasks and progress stay up to date.</p>
              <button className="mt-6 inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium text-white" style={{ background: 'var(--wa-green)' }} onClick={() => setCreating(true)}>
                <MessageCirclePlus className="size-4" />Start a chat
              </button>
              <p className="mt-10 text-xs" style={{ color: 'var(--wa-sub)' }}>🔒 Everything stays inside this application. No external service is involved.</p>
            </div>
          </div>)}
      </section>
      <NewChat open={creating} onClose={() => setCreating(false)} onCreated={(id) => open(id)} />
    </div>
  );
}
