// Read-only: how each project currently receives WhatsApp data (dev database). Prints counts only, no message text.
const { PrismaClient } = require('@prisma/client');
const prisma = new PrismaClient();
(async () => {
  const sources = await prisma.whatsappSource.count();
  const uploads = await prisma.chatUpload.groupBy({ by: ['projectId'], _count: { _all: true }, _max: { createdAt: true }, where: { storageKey: { not: 'webhook' } } });
  const projects = await prisma.project.findMany({ select: { id: true, name: true, _count: { select: { messages: true } } }, orderBy: { createdAt: 'asc' } });
  console.log('webhook sources connected:', sources);
  for (const p of projects) {
    const u = uploads.find((x) => x.projectId === p.id);
    console.log(`${p.name.padEnd(46)} messages=${String(p._count.messages).padStart(4)}  export uploads=${u?._count._all ?? 0}${u ? '  last=' + u._max.createdAt.toISOString().slice(0, 16) : ''}`);
  }
})().finally(() => prisma.$disconnect());
