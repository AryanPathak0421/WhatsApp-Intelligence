import { UserRole } from '@prisma/client';

/** Role -> allowed actions. Anything not listed is denied. Project-level access is checked separately. */
export type Action =
  | 'user:manage' | 'project:create' | 'project:edit' | 'project:delete' | 'member:manage'
  | 'chat:upload' | 'chat:view_raw' | 'task:edit' | 'task:status' | 'task:delete' | 'report:generate' | 'report:view'
  | 'analytics:view' | 'team:view' | 'team:edit' | 'sales:view' | 'risk:view' | 'audit:view' | 'client_facing:view';

const ALL: Action[] = ['user:manage', 'project:create', 'project:edit', 'project:delete', 'member:manage', 'chat:upload',
  'chat:view_raw', 'task:edit', 'task:status', 'task:delete', 'report:generate', 'report:view', 'analytics:view', 'team:view',
  'team:edit', 'sales:view', 'risk:view', 'audit:view', 'client_facing:view'];

export const MATRIX: Record<UserRole, Action[]> = {
  SUPER_ADMIN: ALL,
  ADMIN: ALL, // manage users except SUPER_ADMIN accounts (enforced in controller)
  PROJECT_MANAGER: ['project:create', 'project:edit', 'member:manage', 'chat:upload', 'chat:view_raw', 'task:edit', 'task:status',
    'task:delete', 'report:generate', 'report:view', 'analytics:view', 'team:view', 'team:edit', 'sales:view', 'risk:view', 'client_facing:view'],
  TEAM_MEMBER: ['chat:view_raw', 'task:status', 'report:view', 'analytics:view', 'team:view', 'risk:view', 'client_facing:view'],
  SALES: ['chat:view_raw', 'analytics:view', 'sales:view', 'team:view', 'client_facing:view', 'report:view'],
  CLIENT_VIEWER: ['client_facing:view'],
};

export const can = (role: UserRole, action: Action) => MATRIX[role].includes(action);
export const isAdmin = (role: UserRole) => role === 'SUPER_ADMIN' || role === 'ADMIN';
