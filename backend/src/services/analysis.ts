/**
 * Analysis job runner: analyze all project messages (written by the in-app chat) -> index -> persist -> notify.
 *
 * Invariants
 *  - ChatMessage rows are write-once (originalText never updated).
 *  - Human-edited rows (reviewState HUMAN_*) are never overwritten by a re-analysis.
 *  - Everything is scoped by projectId; ids coming from the AI engine are prefixed with the project id.
 *  - Errors surfaced to users are sanitized (AiError.safeMessage / generic text).
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { Prisma } from '@prisma/client';
import { config } from '../config';
import { prisma } from '../db';
import { decryptBuffer, decryptField, encryptField } from '../utils/crypto';
import { naive, wall } from '../utils/time';
import { events } from '../events/bus';
import { AiError, AiMessage, ai } from './aiClient';

export const STAGES = {
  TEAM: { label: 'Identifying team', progress: 38 },
  ANALYZING: { label: 'Analyzing project', progress: 45 },
  INDEXING: { label: 'Indexing messages', progress: 75 },
  PERSISTING: { label: 'Calculating progress', progress: 85 },
  REPORT: { label: 'Generating report', progress: 95 },
  DONE: { label: 'Completed', progress: 100 },
} as const;

const scope = (pid: string, id: string) => `${pid}:${id}`;
const unscope = (pid: string, id: string) => (id.startsWith(pid + ':') ? id.slice(pid.length + 1) : id);
const HUMAN = ['HUMAN_CONFIRMED', 'HUMAN_CORRECTED'] as const;
const SEV_SCORE: Record<string, number> = { LOW: 20, MEDIUM: 45, HIGH: 70, CRITICAL: 90 };
const d = wall;

async function setStage(jobId: string, stage: { label: string; progress: number }, extra: Prisma.AnalysisJobUpdateInput = {}) {
  const j = await prisma.analysisJob.update({ where: { id: jobId }, data: { stage: stage.label, progress: stage.progress, ...extra }, select: { projectId: true } });
  events.publish({ type: extra.status === 'COMPLETED' ? 'analysis.completed' : 'analysis.progress', projectId: j.projectId, jobId, progress: stage.progress, stage: stage.label });
}

export async function runAnalysisJob(jobId: string): Promise<void> {
  const job = await prisma.analysisJob.findUnique({ where: { id: jobId }, include: { project: true } });
  if (!job) return;
  const pid = job.projectId;
  try {
    await prisma.analysisJob.update({ where: { id: jobId }, data: { status: 'RUNNING', startedAt: new Date(), stage: 'Starting', progress: 5, error: null } });
    await setStage(jobId, STAGES.TEAM);
    const messages = await prisma.chatMessage.findMany({
      where: { projectId: pid, isSystem: false }, orderBy: [{ timestamp: 'asc' }, { seq: 'asc' }],
      select: { id: true, text: true, timestamp: true, seq: true, sender: { select: { displayName: true } } } });
    if (!messages.length) throw new AiError('INVALID_CHAT', 'This project has no messages yet');
    const roleRows = await prisma.chatParticipant.findMany({ where: { projectId: pid, roleSource: 'admin' } });
    const aiMsgs = messages.map((m, i) => ({ id: unscope(pid, m.id), text: m.text, sender: m.sender?.displayName ?? null, ts: naive(m.timestamp)!, index: i }));

    await setStage(jobId, STAGES.ANALYZING);
    const result = await ai.analyze({
      project_id: pid, messages: aiMsgs, role_overrides: Object.fromEntries(roleRows.map((r) => [r.displayName, r.role])),
      project_start: naive(job.project.startDate), expected_delivery: naive(job.project.expectedDelivery),
      health_weights: undefined,
    });

    await setStage(jobId, STAGES.INDEXING);
    try {
      for (let i = 0; i < aiMsgs.length; i += 2000) await ai.index(pid, aiMsgs.slice(i, i + 2000));
    } catch (e) { console.warn('[analysis] indexing skipped:', (e as Error).message); } // search is optional; analysis still succeeds

    await setStage(jobId, STAGES.PERSISTING);
    const fresh = await persistResult(pid, jobId, result);
    await setStage(jobId, STAGES.REPORT);
    await notifyNew(pid, fresh);
    await setStage(jobId, STAGES.DONE, { status: 'COMPLETED', finishedAt: new Date() });
  } catch (e) {
    const safe = e instanceof AiError ? e.safeMessage : 'Analysis failed. Please try again or contact an administrator.';
    if (!(e instanceof AiError)) console.error('[analysis] job failed', jobId, e);
    await prisma.analysisJob.update({ where: { id: jobId }, data: { status: 'FAILED', error: safe, finishedAt: new Date() } }).catch(() => {});
    events.publish({ type: 'analysis.failed', projectId: pid, jobId });
    if (e instanceof AiError && e.kind === 'UNAVAILABLE') throw e; // lets BullMQ retry transient failures
  }
}

export interface FreshItems { clientPending: any[]; risks: any[]; requirementChanges: any[]; conflicts: any[] }

async function persistResult(pid: string, jobId: string, r: any): Promise<FreshItems> {
  const S = (id: string) => scope(pid, id);
  const SS = (ids: string[] = []) => ids.map(S);
  const people = new Map((await prisma.chatParticipant.findMany({ where: { projectId: pid }, select: { id: true, displayName: true, roleSource: true } })).map((p) => [p.displayName, p]));
  const pId = (n?: string | null) => (n ? people.get(n)?.id ?? null : null);
  const modelVersions = { engine: r.engine_version };

  const prevCp = new Set((await prisma.clientPendingItem.findMany({ where: { projectId: pid }, select: { id: true } })).map((x) => x.id));
  const prevRisk = new Set((await prisma.risk.findMany({ where: { projectId: pid }, select: { title: true } })).map((x) => x.title));
  const prevRc = new Set((await prisma.requirementChange.findMany({ where: { requirement: { projectId: pid } }, select: { sourceMessageIds: true } })).flatMap((x) => x.sourceMessageIds));
  const prevCf = new Set((await prisma.conflict.findMany({ where: { projectId: pid }, select: { messageAId: true, messageBId: true } })).map((x) => x.messageAId + x.messageBId));

  await prisma.$transaction(async (tx) => {
    // roles (admin-set roles are never overwritten)
    for (const [name, role] of Object.entries<any>(r.roles)) {
      const p = people.get(name);
      if (p && p.roleSource !== 'admin') {
        await tx.chatParticipant.update({ where: { id: p.id }, data: { role: role.role, roleConfidence: role.confidence, roleSource: role.source === 'admin' ? 'admin' : role.source } });
      }
    }
    // tasks: upsert, never overwrite human-edited rows; drop stale AI-only rows
    const humanTasks = new Set((await tx.task.findMany({ where: { projectId: pid, reviewState: { in: [...HUMAN] } }, select: { id: true } })).map((t) => t.id));
    const keep = new Set<string>();
    for (const t of r.tasks) {
      const id = S(t.id);
      keep.add(id);
      if (humanTasks.has(id)) continue;
      const data = {
        projectId: pid, title: t.title, assigneeId: pId(t.assigned_to), createdById: pId(t.created_by), priority: t.priority, status: t.status,
        domain: t.domain, weight: t.weight, weightSource: 'rule', deadlineText: t.deadline_text, deadline: d(t.deadline),
        deadlineConfidence: t.deadline_confidence, completedAt: d(t.completed_at), externalDependency: t.external_dependency,
        confidence: t.confidence, reviewState: t.needs_review ? 'NEEDS_REVIEW' as const : 'AUTO_ACCEPTED' as const, modelVersion: t.model_version,
        sourceMessageId: S(t.source_message_id), evidenceMessageIds: SS(t.evidence_message_ids),
        statusEvidence: { trace: t.status_trace.map((x: any) => ({ ...x, message_id: S(x.message_id) })), evidence: t.evidence.map((x: any) => ({ ...x, message_id: S(x.message_id) })), reasons: t.review_reasons } as Prisma.InputJsonValue,
      };
      const old = await tx.task.findUnique({ where: { id } });
      if (!old) await tx.task.create({ data: { id, createdAt: d(t.created_at) ?? undefined, ...data } });
      else {
        if (old.status !== t.status) await tx.taskHistory.create({ data: { taskId: id, field: 'status', oldValue: old.status, newValue: t.status, changedBy: `model:${t.model_version}`, evidenceMessageId: S(t.evidence_message_ids.at(-1) ?? t.source_message_id) } });
        await tx.task.update({ where: { id }, data });
      }
    }
    await tx.task.deleteMany({ where: { projectId: pid, id: { notIn: [...keep, ...humanTasks] }, reviewState: { notIn: [...HUMAN] }, sourceMessageId: { not: null } } });

    // client pending
    const humanCp = new Set((await tx.clientPendingItem.findMany({ where: { projectId: pid, reviewState: { in: [...HUMAN] } }, select: { id: true } })).map((x) => x.id));
    const cpKeep = new Set<string>();
    for (const c of r.client_pending) {
      const id = S(c.id);
      cpKeep.add(id);
      if (humanCp.has(id)) continue;
      const taskId = c.task_id && keep.has(S(c.task_id)) ? S(c.task_id) : null;
      const data = { projectId: pid, taskId, type: c.type, title: c.title, requestedById: pId(c.requested_by), requestedAt: d(c.requested_at), waitingSince: wall(c.waiting_since)!,
        priority: c.priority, impact: c.impact, status: c.status, resolvedAt: d(c.resolved_at), resolutionMessageId: c.resolution_message_id ? S(c.resolution_message_id) : null,
        responsible: c.responsible, confidence: c.confidence, reviewState: c.confidence < 0.7 ? 'NEEDS_REVIEW' as const : 'AUTO_ACCEPTED' as const,
        modelVersion: c.model_version, sourceMessageIds: SS(c.source_message_ids) };
      await tx.clientPendingItem.upsert({ where: { id }, create: { id, ...data }, update: data });
    }
    await tx.clientPendingItem.deleteMany({ where: { projectId: pid, id: { notIn: [...cpKeep, ...humanCp] } } });

    // wholesale-replaced derived tables (no human editing yet)
    await Promise.all([tx.risk.deleteMany({ where: { projectId: pid } }), tx.bug.deleteMany({ where: { projectId: pid } }),
      tx.decision.deleteMany({ where: { projectId: pid } }), tx.meeting.deleteMany({ where: { projectId: pid } }),
      tx.commitment.deleteMany({ where: { projectId: pid } }), tx.conflict.deleteMany({ where: { projectId: pid } }),
      tx.projectEvent.deleteMany({ where: { projectId: pid } }), tx.deadline.deleteMany({ where: { projectId: pid } }),
      tx.requirement.deleteMany({ where: { projectId: pid } }), tx.insight.deleteMany({ where: { projectId: pid } })]);
    const tId = (x?: string | null) => (x && keep.has(S(x)) ? S(x) : null);
    await tx.risk.createMany({ data: r.risk.risks.map((k: any) => ({ projectId: pid, taskId: tId(k.related_task), title: k.title, description: k.description,
      severity: k.severity, score: SEV_SCORE[k.severity] ?? 40, factors: r.risk.factors, recommendedAction: k.recommended_action, detectedAt: wall(k.detected_at)!,
      confidence: k.confidence, modelVersion: k.model_version, sourceMessageIds: SS(k.source_message_ids) })) });
    await tx.bug.createMany({ data: r.bugs.map((b: any) => ({ projectId: pid, taskId: tId(b.task_id), title: b.title, status: b.status, reportedById: pId(b.reported_by),
      assigneeId: pId(b.assignee), reportedAt: wall(b.reported_at)!, fixedAt: d(b.fixed_at), confidence: b.confidence, modelVersion: b.model_version, sourceMessageIds: SS(b.source_message_ids) })) });
    await tx.decision.createMany({ data: r.decisions.map((x: any) => ({ projectId: pid, title: x.title, decidedBy: x.decided_by, impact: x.impact, decidedAt: wall(x.decided_at)!,
      confidence: x.confidence, modelVersion: x.model_version, sourceMessageIds: SS(x.source_message_ids) })) });
    await tx.meeting.createMany({ data: r.meetings.map((x: any) => ({ projectId: pid, title: x.title, scheduledAt: d(x.scheduled_at), confidence: x.confidence,
      modelVersion: x.model_version, sourceMessageIds: SS(x.source_message_ids) })) });
    await tx.commitment.createMany({ data: r.commitments.map((c: any) => ({ projectId: pid, participantId: pId(c.person), action: c.action, deadlineText: c.deadline_text,
      deadline: d(c.deadline), status: c.status, fulfilledAt: d(c.fulfilled_at), confidence: c.confidence, modelVersion: c.model_version, sourceMessageIds: SS(c.source_message_ids) })) });
    await tx.conflict.createMany({ data: r.conflicts.map((c: any) => ({ projectId: pid, topic: c.topic, statementA: c.statement_a.text, statementB: c.statement_b.text,
      messageAId: S(c.statement_a.message_id), messageBId: S(c.statement_b.message_id), severity: c.severity, status: c.status, confidence: c.confidence, modelVersion: c.model_version })) });
    await tx.projectEvent.createMany({ data: r.timeline.map((e: any) => ({ projectId: pid, occurredAt: wall(e.at)!, type: e.type, title: e.title.slice(0, 300),
      sourceMessageIds: SS(e.source_message_ids), confidence: 0.7 })) });
    await tx.deadline.createMany({ data: r.tasks.filter((t: any) => t.deadline_text).map((t: any) => ({ projectId: pid, taskId: tId(t.id), originalText: t.deadline_text,
      normalized: d(t.deadline), timezone: 'Asia/Kolkata', confidence: t.deadline_confidence ?? 0.5, sourceMessageId: S(t.source_message_id) })) });
    for (const q of r.requirements) {
      const last = q.versions.at(-1);
      await tx.requirement.create({ data: { projectId: pid, key: q.key, currentValue: String(last.value).slice(0, 500), requestedBy: q.versions[0].changed_by, confidence: last.confidence,
        modelVersion: r.engine_version, changes: { create: q.versions.map((v: any) => ({ version: v.version, oldValue: v.old_value, newValue: String(v.value).slice(0, 500),
          changedBy: v.changed_by, impact: q.impact, changedAt: wall(v.changed_at)!, confidence: v.confidence, modelVersion: r.engine_version, sourceMessageIds: [S(v.message_id)] })) } } });
    }
    const insights = [
      ...r.summary.claims.map((c: any) => ({ kind: 'SUMMARY', text: c.text, evidence: { taskIds: c.task_ids, messageIds: SS(c.message_ids), facts: c.facts } })),
      ...r.next_actions.map((a: any) => ({ kind: 'NEXT_ACTION', text: a.action, owner: a.owner, priority: a.priority, evidence: { messageIds: SS(a.source_message_ids), reason: a.reason } })),
      ...r.insights.map((i: any) => ({ kind: i.kind, text: i.text, evidence: { messageIds: SS(i.source_message_ids) } })),
    ];
    await tx.insight.createMany({ data: insights.map((i: any) => ({ projectId: pid, kind: i.kind, text: i.text, owner: i.owner ?? null, priority: i.priority ?? null, evidence: i.evidence, modelVersion: r.engine_version })) });

    // snapshots (history kept)
    const P = r.progress;
    await tx.projectProgress.create({ data: { projectId: pid, jobId, overall: P.overall ?? 0, development: P.development, design: P.design, testing: P.testing, deployment: P.deployment,
      clientApproval: P.client_approval, documentation: P.documentation, completedWeight: P.explanation.completed_weight, totalWeight: P.explanation.total_weight, explanation: P.explanation } });
    await tx.projectHealth.create({ data: { projectId: pid, jobId, score: r.health.score, status: r.health.status, components: { components: r.health.components, unavailable: r.health.unavailable, overrides: r.health.overrides, flags: r.health.flags } } });
    const snap = (kind: string, result: unknown) => tx.aIAnalysis.create({ data: { projectId: pid, jobId, kind, result: result as Prisma.InputJsonValue, modelVersions } });
    await snap('CONTRIBUTION', { contribution: r.contribution, sales: r.sales, communication: r.communication });
    await snap('CLIENT_RESPONSE_TIME', r.client_response_time);
    await snap('VELOCITY', { velocity: r.velocity, timeline: r.progress_timeline });
    await snap('RISK_SUMMARY', { score: r.risk.score, level: r.risk.level, factors: r.risk.factors });
    if (r.qa) await snap('QA', r.qa);
    if (r.sentiment) await snap('SENTIMENT', r.sentiment);
    if (r.periodic) await snap('PERIODIC', r.periodic);
  }, { timeout: 120_000, maxWait: 20_000 });

  return {
    clientPending: r.client_pending.filter((c: any) => c.status === 'OPEN' && !prevCp.has(S(c.id))),
    risks: r.risk.risks.filter((k: any) => ['HIGH', 'CRITICAL'].includes(k.severity) && !prevRisk.has(k.title)),
    requirementChanges: r.requirement_changes.filter((c: any) => !prevRc.has(S(c.source_message_ids[0]))),
    conflicts: r.conflicts.filter((c: any) => !prevCf.has(S(c.statement_a.message_id) + S(c.statement_b.message_id))),
  };
}

async function notifyNew(pid: string, f: FreshItems) {
  if (!(f.clientPending.length || f.risks.length || f.requirementChanges.length || f.conflicts.length)) return;
  const members = await prisma.projectMember.findMany({ where: { projectId: pid, user: { role: { in: ['PROJECT_MANAGER', 'SALES', 'ADMIN', 'SUPER_ADMIN'] }, isActive: true } } });
  const rows = members.flatMap((m) => [
    ...f.clientPending.map((c) => ({ type: 'CLIENT_PENDING_NEW', title: `New client pending item: ${c.title}` })),
    ...f.risks.map((k) => ({ type: 'HIGH_RISK', title: `${k.severity} risk: ${k.title}` })),
    ...f.requirementChanges.map((c) => ({ type: 'REQUIREMENT_CHANGE', title: `Requirement changed: ${c.key} ${c.old_value ?? '?'} -> ${c.new_value}` })),
    ...f.conflicts.map((c) => ({ type: 'CONFLICT', title: `Contradictory statements about ${c.topic}` })),
  ].map((n) => ({ userId: m.userId, projectId: pid, link: `/projects/${pid}`, ...n })));
  if (rows.length) await prisma.notification.createMany({ data: rows });
  if (rows.length) events.publish({ type: 'notification.created', projectId: pid });
}

export { decryptField };
