import clsx from 'clsx';
import { AlertTriangle, Bot, Check, Loader2, Send, ThumbsDown, ThumbsUp, X } from 'lucide-react';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, apiError } from '../lib/api';

/** Chat panel for the policy-governed assistant (service on /assistant). The model proposes; sensitive actions are confirmed HERE, by a button. */
interface Pending { id: string; tool: string; preview: string; tainted: boolean; reason?: string }
interface Citation { citation: string; title: string; authors: string[]; year?: number; page?: number; doi?: string }
interface Turn {
  turn_id: string; session_id: string; reply: string; actions: { tool: string; status: string }[]; pending: Pending[];
  ui_events: { type: string; page?: string; project_id?: string; days?: number; status?: string }[]; citations: Citation[]; sources: string[]; issues: string[];
}
interface Msg { role: 'user' | 'assistant'; text: string; turn?: Turn; resolved?: Record<string, string>; rating?: number }

const SOURCE_LABEL: Record<string, string> = {
  application_data: 'live application data', documents: 'cited documents', model_general_knowledge_unverified: 'general knowledge (unverified)',
};

const call = <T,>(method: 'get' | 'post', url: string, data?: unknown) => api.request<T>({ method, url, data, baseURL: '/', timeout: 600_000 }).then((r) => r.data);

export default function Assistant({ projectId }: { projectId?: string }) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [session, setSession] = useState<string | undefined>();
  const end = useRef<HTMLDivElement>(null);
  const loc = useLocation();
  const nav = useNavigate();
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [msgs, busy, open]);

  const applyEvents = (t: Turn) => {
    for (const e of t.ui_events) {
      if (e.type === 'navigate' && e.page) {
        const id = e.project_id ?? projectId;
        const map: Record<string, string> = { dashboard: '/', projects: '/projects', settings: '/settings' };
        const sub: Record<string, string> = { project: 'overview', tasks: 'tasks', risks: 'risks', reports: 'reports', analytics: 'analytics', team: 'team', timeline: 'timeline', client_pending: 'client-pending' };
        if (map[e.page]) nav(map[e.page]);
        else if (sub[e.page] && id) nav(`/p/${id}/${sub[e.page]}`);
      }
      if (e.type === 'set_dashboard_filter') window.dispatchEvent(new CustomEvent('assistant:filter', { detail: { days: e.days, status: e.status } }));
    }
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setText('');
    setMsgs((m) => [...m, { role: 'user', text: q }]);
    setBusy(true);
    try {
      const t = await call<Turn>('post', '/assistant/chat', { message: q, session_id: session, app_state: { page: loc.pathname, project_id: projectId } });
      setSession(t.session_id);
      setMsgs((m) => [...m, { role: 'assistant', text: t.reply, turn: t }]);
      applyEvents(t);
    } catch (err) {
      setMsgs((m) => [...m, { role: 'assistant', text: apiError(err).message || 'The assistant is not available.' }]);
    } finally { setBusy(false); }
  };

  const decide = async (idx: number, p: Pending, what: 'confirm' | 'cancel') => {
    setBusy(true);
    try {
      const t = await call<Turn>('post', `/assistant/${what}`, { session_id: session, pending_id: p.id });
      setMsgs((m) => m.map((x, i) => (i === idx ? { ...x, resolved: { ...x.resolved, [p.id]: what } } : x)).concat({ role: 'assistant', text: t.reply, turn: t }));
      applyEvents(t);
    } catch (err) {
      setMsgs((m) => m.concat({ role: 'assistant', text: apiError(err).message }));
    } finally { setBusy(false); }
  };

  const rate = async (idx: number, rating: number) => {
    const t = msgs[idx].turn;
    if (!t) return;
    setMsgs((m) => m.map((x, i) => (i === idx ? { ...x, rating } : x)));
    await call('post', '/assistant/feedback', { turn_id: t.turn_id, rating }).catch(() => undefined);
  };

  return (
    <>
      <button aria-label="Open assistant" onClick={() => setOpen((o) => !o)}
        className="fixed bottom-5 right-5 z-30 grid size-12 place-items-center rounded-full bg-brand-600 text-white shadow-lg hover:bg-brand-700">
        {open ? <X className="size-5" /> : <Bot className="size-5" />}
      </button>
      {open && (
        <section aria-label="Assistant" className="fixed bottom-20 right-5 z-30 flex h-[32rem] max-h-[80vh] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-xl border bg-[var(--surface)] shadow-xl sm:w-[26rem]">
          <header className="border-b px-4 py-3"><p className="text-sm font-semibold">Assistant</p>
            <p className="muted text-[11px]">Acts as you, with your permissions. Sensitive changes need your confirmation.</p></header>
          <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3" aria-live="polite">
            {!msgs.length && <p className="muted text-sm">Ask about your projects, tasks or documents, or tell me what to do. Try: &ldquo;Which tasks are overdue?&rdquo;</p>}
            {msgs.map((m, i) => (
              <div key={i} className={clsx('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
                <div className={clsx('max-w-[90%] rounded-lg px-3 py-2 text-sm', m.role === 'user' ? 'bg-brand-600 text-white' : 'bg-[var(--surface-2)]')}>
                  <p className="whitespace-pre-wrap">{m.text}</p>
                  {m.turn?.pending.map((p) => (
                    <div key={p.id} className="mt-2 rounded-md border border-amber-400/50 bg-amber-500/10 p-2">
                      <p className="flex items-start gap-1.5 text-xs font-medium"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{p.preview}</p>
                      {p.tainted && <p className="muted mt-1 text-[11px]">This follows text from a document or chat. Check it is what you asked for.</p>}
                      {m.resolved?.[p.id] ? <p className="muted mt-1 text-[11px]">{m.resolved[p.id] === 'confirm' ? 'Confirmed' : 'Cancelled'}</p> : (
                        <div className="mt-2 flex gap-2">
                          <button disabled={busy} onClick={() => decide(i, p, 'confirm')} className="inline-flex items-center gap-1 rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-700 disabled:opacity-50"><Check className="size-3" />Confirm</button>
                          <button disabled={busy} onClick={() => decide(i, p, 'cancel')} className="rounded-md border px-2.5 py-1 text-xs hover:bg-[var(--surface)] disabled:opacity-50">Cancel</button>
                        </div>
                      )}
                    </div>
                  ))}
                  {m.turn && m.turn.sources.length > 0 && <p className="muted mt-2 text-[11px]">Based on: {m.turn.sources.map((s) => SOURCE_LABEL[s] ?? s).join(', ')}</p>}
                  {m.turn && m.turn.issues.length > 0 && <p className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">Checked: {m.turn.issues.join('; ')}</p>}
                  {m.turn && m.role === 'assistant' && (
                    <div className="mt-1 flex gap-1">
                      <button aria-label="Helpful" onClick={() => rate(i, 1)} className={clsx('rounded p-1 hover:bg-[var(--surface)]', m.rating === 1 && 'text-green-600')}><ThumbsUp className="size-3" /></button>
                      <button aria-label="Not helpful" onClick={() => rate(i, -1)} className={clsx('rounded p-1 hover:bg-[var(--surface)]', m.rating === -1 && 'text-red-600')}><ThumbsDown className="size-3" /></button>
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <p className="muted flex items-center gap-2 text-xs"><Loader2 className="size-3.5 animate-spin" />Working...</p>}
            <div ref={end} />
          </div>
          <form onSubmit={send} className="flex gap-2 border-t p-3">
            <input value={text} onChange={(e) => setText(e.target.value)} maxLength={4000} placeholder="Ask or instruct..." aria-label="Message"
              className="min-w-0 flex-1 rounded-lg border bg-[var(--surface)] px-3 py-2 text-sm" />
            <button type="submit" disabled={busy || !text.trim()} aria-label="Send" className="grid size-9 place-items-center rounded-lg bg-brand-600 text-white disabled:opacity-50"><Send className="size-4" /></button>
          </form>
        </section>
      )}
    </>
  );
}
