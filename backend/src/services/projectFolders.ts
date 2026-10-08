import { prisma } from '../db';

/** Windows-safe folder name for a project (the characters \ / : * ? " < > | are not allowed in file names). */
export const folderNameFor = (projectName: string) => projectName.replace(/[\\/:*?"<>|]/g, '_').replace(/[. ]+$/, '').trim() || 'project';

export interface ProjectRef { id: string; name: string; managerId: string | null }

/** Projects indexed by their folder name (lower case). A name shared by several projects is "ambiguous" and is never imported into. */
export async function listProjects() {
  const projects: ProjectRef[] = await prisma.project.findMany({ select: { id: true, name: true, managerId: true }, orderBy: { createdAt: 'asc' } });
  const byFolder = new Map<string, ProjectRef[]>();
  for (const p of projects) { const k = folderNameFor(p.name).toLowerCase(); byFolder.set(k, [...(byFolder.get(k) ?? []), p]); }
  return { projects, byFolder };
}

/** Who an automatic import is attributed to: the project manager, else the first active admin. */
export async function uploaderFor(managerId: string | null): Promise<string | null> {
  if (managerId) return managerId;
  return (await prisma.user.findFirst({ where: { role: { in: ['SUPER_ADMIN', 'ADMIN'] }, isActive: true }, orderBy: { createdAt: 'asc' }, select: { id: true } }))?.id ?? null;
}
