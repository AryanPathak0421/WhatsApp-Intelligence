import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfidenceBadge, ProgressBar, StatusBadge } from '../components/ui';
import Login from '../pages/Login';
import { api, apiError, tokens } from './api';
import { AuthProvider, can } from './auth';
import { confidenceLevel, fmtDate, fmtDateTime, isOverdue, pct, titleCase } from './format';

describe('format', () => {
  it('renders message wall-clock times without timezone shifts', () => {
    expect(fmtDateTime('2026-10-01T10:00:00.000Z')).toBe('01 Oct 2026 10:00');
    expect(fmtDate('2026-12-31T23:30:00.000Z')).toBe('31 Dec 2026');
  });
  it('formats helpers', () => {
    expect(pct(29.44, 1)).toBe('29.4%');
    expect(pct(null)).toBe('—');
    expect(titleCase('IN_PROGRESS')).toBe('In Progress');
    expect(confidenceLevel(0.9)).toBe('high');
    expect(confidenceLevel(0.75)).toBe('medium');
    expect(confidenceLevel(0.4)).toBe('low');
    expect(isOverdue('2000-01-01T00:00:00Z', 'TODO')).toBe(true);
    expect(isOverdue('2000-01-01T00:00:00Z', 'COMPLETED')).toBe(false);
    expect(isOverdue(null, 'TODO')).toBe(false);
  });
});

describe('permissions mirror', () => {
  it('matches the backend matrix for the cases that gate UI', () => {
    expect(can('SUPER_ADMIN', 'user:manage')).toBe(true);
    expect(can('PROJECT_MANAGER', 'chat:upload')).toBe(true);
    expect(can('PROJECT_MANAGER', 'user:manage')).toBe(false);
    expect(can('TEAM_MEMBER', 'task:edit')).toBe(false);
    expect(can('TEAM_MEMBER', 'task:status')).toBe(true);
    expect(can('SALES', 'sales:view')).toBe(true);
    expect(can('CLIENT_VIEWER', 'chat:view_raw')).toBe(false);
    expect(can('CLIENT_VIEWER', 'analytics:view')).toBe(false);
    expect(can('CLIENT_VIEWER', 'client_facing:view')).toBe(true);
    expect(can(undefined, 'client_facing:view')).toBe(false);
  });
});

describe('ui components', () => {
  it('flags low-confidence AI results for review', () => {
    render(<ConfidenceBadge value={0.55} />);
    expect(screen.getByText('55%')).toBeInTheDocument();
    expect(screen.getByText('Needs review')).toBeInTheDocument();
  });
  it('does not flag high-confidence results', () => {
    render(<ConfidenceBadge value={0.95} />);
    expect(screen.queryByText('Needs review')).not.toBeInTheDocument();
  });
  it('status badge and accessible progress bar', () => {
    render(<><StatusBadge status="IN_PROGRESS" /><ProgressBar value={42} label="Testing" /></>);
    expect(screen.getByText('In Progress')).toBeInTheDocument();
    expect(screen.getByRole('progressbar', { name: 'Testing' })).toHaveAttribute('aria-valuenow', '42');
  });
});

describe('api client', () => {
  beforeEach(() => { sessionStorage.clear(); localStorage.clear(); });

  it('turns server errors into safe messages', () => {
    expect(apiError({ response: { status: 409, data: { error: { code: 'ANALYSIS_IN_PROGRESS', message: 'An analysis is already running for this project' } } } }).message)
      .toBe('An analysis is already running for this project');
    expect(apiError({ code: 'ERR_NETWORK' }).code).toBe('NETWORK');
  });

  it('refreshes once on 401 and retries the request with the new token (concurrent calls share one refresh)', async () => {
    tokens.set('old-access', 'refresh-1');
    const seen: string[] = [];
    let refreshCalls = 0;
    const axios = (await import('axios')).default;
    const post = vi.spyOn(axios, 'post').mockImplementation(async () => { refreshCalls++; await new Promise((r) => setTimeout(r, 20)); return { data: { accessToken: 'new-access', refreshToken: 'refresh-2' } }; });
    api.defaults.adapter = async (cfg) => {
      const auth = String(cfg.headers.Authorization ?? '');
      seen.push(auth);
      if (auth === 'Bearer old-access') throw Object.assign(new Error('401'), { config: cfg, response: { status: 401, data: {} }, isAxiosError: true });
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config: cfg };
    };
    const [a, b] = await Promise.all([api.get('/projects'), api.get('/executive')]);
    expect(a.data.ok && b.data.ok).toBe(true);
    expect(refreshCalls).toBe(1);
    expect(tokens.refresh).toBe('refresh-2');
    expect(seen.filter((s) => s === 'Bearer new-access')).toHaveLength(2);
    post.mockRestore();
  });
});

describe('login page', () => {
  const renderLogin = () => render(
    <QueryClientProvider client={new QueryClient()}><MemoryRouter><AuthProvider><Login /></AuthProvider></MemoryRouter></QueryClientProvider>);

  it('validates the form before calling the API', async () => {
    renderLogin();
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Enter a valid email')).toBeInTheDocument();
    expect(screen.getByText('Enter your password')).toBeInTheDocument();
  });

  it('shows the server error without leaking details', async () => {
    api.defaults.adapter = async (cfg) => { throw Object.assign(new Error('x'), { config: cfg, isAxiosError: true,
      response: { status: 401, data: { error: { code: 'INVALID_CREDENTIALS', message: 'Invalid email or password' } } } }); };
    renderLogin();
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.com');
    await userEvent.type(screen.getByLabelText('Password'), 'whatever');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  });
});

import { parseSse } from './live';

describe('parseSse', () => {
  it('parses complete event blocks and keeps the partial rest', () => {
    const a = 'retry: 5000\n: connected\n\nid: 1\nevent: analysis.completed\ndata: {"type":"analysis.completed","projectId":"p1","at":"x"}\n\nid: 2\nevent: analysis.prog';
    const r = parseSse(a);
    expect(r.events).toHaveLength(1);
    expect(r.events[0].event).toBe('analysis.completed');
    expect(r.events[0].data.projectId).toBe('p1');
    expect(r.rest.startsWith('id: 2')).toBe(true);
  });
  it('ignores heartbeats and malformed frames', () => {
    expect(parseSse(': ping\n\nevent: x\ndata: {not json}\n\n').events).toEqual([]);
  });
});
