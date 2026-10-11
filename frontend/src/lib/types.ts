export type Role = 'SUPER_ADMIN' | 'ADMIN' | 'PROJECT_MANAGER' | 'TEAM_MEMBER' | 'SALES' | 'CLIENT_VIEWER';
export type TaskStatus = 'TODO' | 'IN_PROGRESS' | 'COMPLETED' | 'BLOCKED' | 'CANCELLED';
export type Severity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type HealthStatus = 'HEALTHY' | 'AT_RISK' | 'CRITICAL' | 'BLOCKED';

export interface User { id: string; email: string; name: string; role: Role }

export interface ProjectRow { id: string; name: string; client: string | null; status: string; startDate: string | null; expectedDelivery: string | null;
  progress: number | null; health: { score: number; status: HealthStatus } | null }

export interface Overview {
  project: { id: string; name: string; description: string | null; status: string; client: string | null; manager: { id: string; name: string } | null; startDate: string | null; expectedDelivery: string | null };
  progress: { overall: number; development: number | null; design: number | null; testing: number | null; deployment: number | null; clientApproval: number | null; documentation: number | null; computedAt: string } | null;
  health: { score: number; status: HealthStatus } | null;
  tasks: Record<TaskStatus, number>; overdue: number; clientPendingOpen: number; messages: number;
  lastAnalysis: { id: string; status: string; stage: string | null; progress: number; finishedAt: string | null } | null;
  openBugs?: number; risksBySeverity?: Record<Severity, number>; needsReview?: number; participants?: number;
  reliability?: { level: ReliabilityLevel; reasons: string[]; tasks?: number; needsReview?: number; messages?: number };
}
export type ReliabilityLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT';
export const isShaky = (l?: ReliabilityLevel) => l === 'LOW' || l === 'INSUFFICIENT';

export interface Task {
  id: string; title: string; description?: string | null; status: TaskStatus; priority?: Severity; domain?: string; weight?: number; deadline: string | null;
  deadlineText?: string | null; completedAt: string | null; confidence?: number; reviewState?: string; needsReview?: boolean; externalDependency?: string | null;
  assignee?: { id: string; name: string } | null; createdBy?: { id: string; name: string } | null; evidenceCount?: number; modelVersion?: string;
}

export interface Job { id: string; status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'; stage: string | null; progress: number; error: string | null; createdAt: string; finishedAt: string | null }

export interface Msg { id: string; seq: number; timestamp: string; sender: { id: string; name: string } | null; text: string; originalText: string; type: string; isMedia: boolean; isDeleted: boolean; urls: string[] }

export interface ClientPending { id: string; title: string; type: string; responsible: string; waitingSince: string; ageDays: number; priority: Severity; impact: Severity; status: 'OPEN' | 'RESOLVED' | 'CANCELLED'; confidence: number; needsReview: boolean; sourceMessageIds: string[]; task: { id: string; title: string } | null }

export interface Evidence { task: { id: string; title: string; status: TaskStatus; confidence: number; reviewState: string; statusEvidence: { trace?: { event: string; status: string; message_id: string }[]; reasons?: string[] } | null };
  evidence: { id: string; timestamp: string; sender: string | null; text: string; isEvidence: boolean; context: { id: string; sender: string | null; text: string; timestamp: string }[] }[] }

// ---- in-app chat ----
export interface RoomRow { id: string; kind: 'GROUP' | 'DIRECT'; name: string; project: { id: string; name: string } | null; memberCount: number; unread: number;
  lastMessage: { text: string; senderName: string; mine?: boolean; at: string } | null; lastActivity: string }
export interface RoomDetail { id: string; kind: 'GROUP' | 'DIRECT'; name: string; project: { id: string; name: string } | null; canManage: boolean; analysed: boolean;
  members: { id: string; name: string; role: Role }[] }
export interface RoomMsg { id: string; senderId: string; senderName: string; mine: boolean; status?: 'sent' | 'read'; text: string; createdAt: string; replyTo: { id: string; senderName: string; text: string } | null }
export interface RoomUser { id: string; name: string; role: Role }
