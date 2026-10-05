import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, setLogoutHandler, tokens } from './api';
import type { Role, User } from './types';

/** Mirrors backend/src/utils/permissions.ts. UI gating only; the server enforces everything. */
const ALL = ['project:create', 'project:edit', 'member:manage', 'chat:upload', 'chat:view_raw', 'task:edit', 'task:status', 'task:delete', 'report:generate',
  'report:view', 'analytics:view', 'team:view', 'team:edit', 'sales:view', 'risk:view', 'audit:view', 'user:manage', 'client_facing:view'] as const;
export type Action = (typeof ALL)[number];
const MATRIX: Record<Role, readonly Action[]> = {
  SUPER_ADMIN: ALL, ADMIN: ALL,
  PROJECT_MANAGER: ['project:create', 'project:edit', 'member:manage', 'chat:upload', 'chat:view_raw', 'task:edit', 'task:status', 'task:delete', 'report:generate', 'report:view', 'analytics:view', 'team:view', 'team:edit', 'sales:view', 'risk:view', 'client_facing:view'],
  TEAM_MEMBER: ['chat:view_raw', 'task:status', 'report:view', 'analytics:view', 'team:view', 'risk:view', 'client_facing:view'],
  SALES: ['chat:view_raw', 'analytics:view', 'sales:view', 'team:view', 'client_facing:view', 'report:view'],
  CLIENT_VIEWER: ['client_facing:view'],
};
export const can = (role: Role | undefined, a: Action) => !!role && MATRIX[role].includes(a);

interface AuthCtx { user: User | null; loading: boolean; login: (email: string, password: string) => Promise<void>; logout: () => void; can: (a: Action) => boolean }
const Ctx = createContext<AuthCtx>(null as never);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!(tokens.refresh || tokens.access));
  const qc = useQueryClient();

  const logout = useCallback(() => {
    const refreshToken = tokens.refresh;
    if (refreshToken) api.post('/auth/logout', { refreshToken }).catch(() => {});
    tokens.clear(); setUser(null); qc.clear();
  }, [qc]);

  useEffect(() => { setLogoutHandler(() => { setUser(null); qc.clear(); }); }, [qc]);
  useEffect(() => {
    if (!(tokens.refresh || tokens.access)) return;
    api.get('/auth/me').then((r) => setUser(r.data.user)).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.post('/auth/login', { email, password });
    tokens.set(r.data.accessToken, r.data.refreshToken);
    setUser(r.data.user);
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout, can: (a: Action) => can(user?.role, a) }), [user, loading, login, logout]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
