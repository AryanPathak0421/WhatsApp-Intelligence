// Development helper: set a user's password directly in the dev database (bypasses the register-time length rules, so it is for LOCAL DEV ONLY).
//   node set-dev-password.cjs <email> <new password>
const bcrypt = require('bcryptjs');
const { PrismaClient } = require('@prisma/client');

const [email, password] = process.argv.slice(2);
if (!email || !password) { console.error('usage: node set-dev-password.cjs <email> <new password>'); process.exit(1); }
if (!/localhost|127\.0\.0\.1/.test(process.env.DATABASE_URL || '')) { console.error('refusing: DATABASE_URL is not a local database'); process.exit(1); }

const prisma = new PrismaClient();
(async () => {
  const u = await prisma.user.findUnique({ where: { email } });
  if (!u) { console.error('no such user'); process.exit(1); }
  await prisma.user.update({ where: { id: u.id }, data: { passwordHash: await bcrypt.hash(password, 12) } });
  await prisma.refreshToken.deleteMany({ where: { userId: u.id } });          // sign out existing sessions
  console.log('password updated for', email);
})().finally(() => prisma.$disconnect());
