import { prisma } from '../db';

/**
 * How much the headline numbers of a project (progress %, health score) can be trusted.
 *
 * The percentages are arithmetic over the TASKS the analysis extracted. If it found very few tasks for the amount of conversation, or most of them are
 * low-confidence and still waiting for a human, the arithmetic is exact but its input is shaky, and a bold "78% / Critical" would overstate what is known.
 * This is computed on read from the stored tasks, so a person confirming or correcting tasks raises the level immediately, with no re-analysis.
 *
 *   INSUFFICIENT  not analysed yet, or fewer than 3 tasks
 *   LOW           most tasks still need review, or average confidence < 0.65, or very few tasks for the number of messages
 *   MEDIUM        some tasks need review, or average confidence < 0.8, or a thin task count for the conversation
 *   HIGH          none of the above
 */
export type ReliabilityLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'INSUFFICIENT';
export interface Reliability {
  level: ReliabilityLevel;
  reasons: string[];
  tasks: number; needsReview: number; avgConfidence: number | null; messages: number; tasksPer100Messages: number | null;
}

export const isTrusted = (l: ReliabilityLevel) => l === 'HIGH' || l === 'MEDIUM';

export function assess(o: { analysed: boolean; tasks: { confidence: number; needsReview: boolean }[]; messages: number }): Reliability {
  const n = o.tasks.length;
  const needsReview = o.tasks.filter((t) => t.needsReview).length;
  const avg = n ? o.tasks.reduce((s, t) => s + t.confidence, 0) / n : null;
  const rate = o.messages ? (100 * n) / o.messages : null;
  const base = { tasks: n, needsReview, avgConfidence: avg === null ? null : Math.round(avg * 100) / 100, messages: o.messages, tasksPer100Messages: rate === null ? null : Math.round(rate * 10) / 10 };
  if (!o.analysed) return { ...base, level: 'INSUFFICIENT', reasons: ['The chat has not been analysed yet.'] };
  if (n < 3) return { ...base, level: 'INSUFFICIENT', reasons: [`Only ${n} task${n === 1 ? '' : 's'} found${o.messages ? ` in ${o.messages} messages` : ''}; too few to estimate progress.`] };

  const low: string[] = [], mid: string[] = [];
  const share = needsReview / n;
  if (share >= 0.7) low.push(`${needsReview} of ${n} tasks are low-confidence and still need review.`);
  else if (share >= 0.3) mid.push(`${needsReview} of ${n} tasks still need review.`);
  if (avg !== null && avg < 0.65) low.push(`Average extraction confidence is only ${Math.round(avg * 100)}%.`);
  else if (avg !== null && avg < 0.8) mid.push(`Average extraction confidence is ${Math.round(avg * 100)}%.`);
  if (o.messages >= 100 && rate !== null) {
    if (rate < 3) low.push(`Only ${n} tasks were found in ${o.messages} messages (${rate.toFixed(1)} per 100); real work is probably missing.`);
    else if (rate < 5) mid.push(`Few tasks for the amount of conversation (${rate.toFixed(1)} per 100 messages).`);
  }
  if (low.length) return { ...base, level: 'LOW', reasons: [...low, ...mid] };
  if (mid.length) return { ...base, level: 'MEDIUM', reasons: mid };
  return { ...base, level: 'HIGH', reasons: [] };
}

export async function reliabilityFor(projectId: string): Promise<Reliability> {
  const [rows, messages, analysed] = await Promise.all([
    prisma.task.findMany({ where: { projectId, status: { not: 'CANCELLED' } }, select: { confidence: true, reviewState: true } }),
    prisma.chatMessage.count({ where: { projectId, isSystem: false } }),
    prisma.projectProgress.count({ where: { projectId } }),
  ]);
  return assess({ analysed: analysed > 0, messages, tasks: rows.map((t) => ({ confidence: t.confidence, needsReview: t.reviewState === 'NEEDS_REVIEW' })) });
}
