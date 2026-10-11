import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { tokens } from './api';

export type LiveState = 'connecting' | 'live' | 'polling';
export interface LiveEvent { type: string; projectId: string; roomId?: string; actorId?: string; jobId?: string; progress?: number; stage?: string; at: string }

/** Parses SSE text blocks ("event:", "data:") from a growing buffer; returns the events and the unconsumed rest. */
export function parseSse(buf: string): { events: { event: string; data: LiveEvent }[]; rest: string } {
  const events: { event: string; data: LiveEvent }[] = [];
  let rest = buf;
  for (let i = rest.indexOf('\n\n'); i >= 0; i = rest.indexOf('\n\n')) {
    const block = rest.slice(0, i);
    rest = rest.slice(i + 2);
    const ev = /^event: (.+)$/m.exec(block)?.[1];
    const data = /^data: (.+)$/m.exec(block)?.[1];
    if (ev && data) { try { events.push({ event: ev, data: JSON.parse(data) }); } catch { /* ignore a malformed frame */ } }
  }
  return { events, rest };
}

/**
 * Live dashboard updates over server-sent events (read with fetch: EventSource cannot send the Authorization header).
 * New results refetch the data on screen without a manual refresh. If the stream cannot be kept open (proxy, network, 3 failures in a row)
 * the hook degrades to polling every 30 s so the dashboard still moves. State is returned for a small "Live / Polling" indicator.
 */
export function useLiveEvents(enabled: boolean): LiveState {
  const qc = useQueryClient();
  const [state, setState] = useState<LiveState>('connecting');

  useEffect(() => {
    if (!enabled) return;
    let stop = false;
    let ctrl: AbortController | null = null;
    let failures = 0;
    let poll: ReturnType<typeof setInterval> | undefined;

    const refresh = (e: { event: string; data: LiveEvent }) => {
      window.dispatchEvent(new CustomEvent('live:event', { detail: e.data }));
      if (e.event === 'analysis.completed' || e.event === 'analysis.failed') void qc.invalidateQueries();
      else if (e.event === 'notification.created') void qc.invalidateQueries({ queryKey: ['notifications'] });
      else if (e.event === 'chat.message' || e.event === 'chat.room') {                       // ids only: refetch what is on screen
        void qc.invalidateQueries({ queryKey: ['rooms'] });
        if (e.data.roomId) { void qc.invalidateQueries({ queryKey: ['room-messages', e.data.roomId] }); void qc.invalidateQueries({ queryKey: ['room', e.data.roomId] }); }
      }
    };

    const run = async () => {
      while (!stop) {
        try {
          ctrl = new AbortController();
          const res = await fetch('/api/events', { headers: { Authorization: `Bearer ${tokens.access ?? ''}` }, signal: ctrl.signal });
          if (!res.ok || !res.body) throw new Error(`status ${res.status}`);
          failures = 0;
          setState('live');
          if (poll) { clearInterval(poll); poll = undefined; }
          const reader = res.body.getReader();
          const dec = new TextDecoder();
          let buf = '';
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            const p = parseSse(buf + dec.decode(value, { stream: true }));
            buf = p.rest;
            p.events.forEach(refresh);
          }
        } catch {
          if (stop) return;
          failures += 1;
        }
        if (failures >= 3) {
          setState('polling');
          poll ??= setInterval(() => void qc.invalidateQueries(), 30_000);
        }
        await new Promise((r) => setTimeout(r, Math.min(30_000, 1000 * 2 ** Math.min(failures, 5))));
      }
    };
    void run();
    return () => { stop = true; ctrl?.abort(); if (poll) clearInterval(poll); };
  }, [enabled, qc]);

  return state;
}
