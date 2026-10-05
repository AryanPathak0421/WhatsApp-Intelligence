import { PrismaClient } from '@prisma/client';

export const prisma = new PrismaClient();
/** Chats contain emoji and Devanagari: a non-UTF8 database silently breaks imports mid-job, so refuse to start instead. */
export async function assertUtf8(): Promise<void> {
  const rows = await prisma.$queryRaw<{ server_encoding: string }[]>`SHOW server_encoding`;
  const enc = rows[0]?.server_encoding;
  if (enc !== 'UTF8') throw new Error(`Database encoding is ${enc}; it must be UTF8 (create the database with ENCODING 'UTF8')`);
}

export type Tx = Parameters<Parameters<typeof prisma.$transaction>[0]>[0];
