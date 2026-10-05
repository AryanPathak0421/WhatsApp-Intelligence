import jwt from 'jsonwebtoken';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { prisma } from '../src/db';
import { decryptBuffer, decryptField, encryptBuffer, encryptField, maskPhone } from '../src/utils/crypto';
import { bootstrapAdmin, createUser, login, makeCtx, resetDb } from './helpers';

const ctx = makeCtx();
beforeAll(resetDb);
afterAll(async () => { await ctx.queue.close(); await prisma.$disconnect(); });

describe('crypto', () => {
  it('round-trips and detects tampering', () => {
    const blob = encryptBuffer(Buffer.from('secret chat'));
    expect(blob.toString()).not.toContain('secret');
    expect(decryptBuffer(blob).toString()).toBe('secret chat');
    blob[blob.length - 1] ^= 1;
    expect(() => decryptBuffer(blob)).toThrow();
    expect(decryptField(encryptField('+919876543210'))).toBe('+919876543210');
  });
  it('masks phone numbers', () => {
    expect(maskPhone('+919876543210')).toBe('+91••••••3210');
    expect(maskPhone(null)).toBeNull();
  });
});

describe('auth', () => {
  it('first user becomes SUPER_ADMIN; afterwards registration needs an admin', async () => {
    const admin = await bootstrapAdmin(ctx);
    expect(admin.user.role).toBe('SUPER_ADMIN');
    const anon = await request(ctx.app).post('/api/auth/register').send({ email: 'x@example.com', name: 'X', password: 'correct-horse-battery' });
    expect(anon.status).toBe(401);
    const pm = await createUser(ctx, admin, 'PROJECT_MANAGER', 'pm@example.com');
    const denied = await request(ctx.app).post('/api/auth/register').set(pm.auth).send({ email: 'y@example.com', name: 'Y', password: 'correct-horse-battery' });
    expect(denied.status).toBe(403);
  });

  it('rejects weak passwords and duplicate emails', async () => {
    const admin = await login(ctx, 'admin@example.com', 'correct-horse-battery');
    const weak = await request(ctx.app).post('/api/auth/register').set(admin.auth).send({ email: 'w@example.com', name: 'W', password: 'short' });
    expect(weak.status).toBe(422);
    const dup = await request(ctx.app).post('/api/auth/register').set(admin.auth).send({ email: 'pm@example.com', name: 'D', password: 'correct-horse-battery' });
    expect(dup.status).toBe(409);
  });

  it('gives one generic error for unknown user and wrong password', async () => {
    const a = await request(ctx.app).post('/api/auth/login').send({ email: 'nobody@example.com', password: 'whatever-password' });
    const b = await request(ctx.app).post('/api/auth/login').send({ email: 'admin@example.com', password: 'wrong-password-1' });
    expect(a.status).toBe(401);
    expect(b.status).toBe(401);
    expect(a.body.error.message).toBe(b.body.error.message);
  });

  it('rejects forged, unsigned and expired tokens', async () => {
    const admin = await login(ctx, 'admin@example.com', 'correct-horse-battery');
    const forged = jwt.sign({ role: 'SUPER_ADMIN' }, 'wrong-secret-wrong-secret-wrong-secret!!', { subject: admin.user.id });
    expect((await request(ctx.app).get('/api/projects').set('Authorization', `Bearer ${forged}`)).status).toBe(401);
    const none = jwt.sign({ role: 'SUPER_ADMIN' }, '', { algorithm: 'none' as never, subject: admin.user.id });
    expect((await request(ctx.app).get('/api/projects').set('Authorization', `Bearer ${none}`)).status).toBe(401);
    const expired = jwt.sign({ role: 'SUPER_ADMIN' }, process.env.JWT_ACCESS_SECRET!, { subject: admin.user.id, expiresIn: -10 });
    expect((await request(ctx.app).get('/api/projects').set('Authorization', `Bearer ${expired}`)).status).toBe(401);
    expect((await request(ctx.app).get('/api/projects')).status).toBe(401);
  });

  it('rotates refresh tokens and revokes the family on reuse', async () => {
    const s = await login(ctx, 'admin@example.com', 'correct-horse-battery');
    const r1 = await request(ctx.app).post('/api/auth/refresh').send({ refreshToken: s.refresh });
    expect(r1.status).toBe(200);
    const reuse = await request(ctx.app).post('/api/auth/refresh').send({ refreshToken: s.refresh });
    expect(reuse.status).toBe(401);
    const afterTheft = await request(ctx.app).post('/api/auth/refresh').send({ refreshToken: r1.body.refreshToken });
    expect(afterTheft.status).toBe(401); // whole family revoked
  });

  it('deactivated users lose access immediately and role changes apply without re-login', async () => {
    const admin = await login(ctx, 'admin@example.com', 'correct-horse-battery');
    const u = await createUser(ctx, admin, 'TEAM_MEMBER', 'temp@example.com');
    expect((await request(ctx.app).get('/api/auth/me').set(u.auth)).status).toBe(200);
    await prisma.user.update({ where: { id: u.user.id }, data: { role: 'CLIENT_VIEWER' } });
    expect((await request(ctx.app).get('/api/auth/me').set(u.auth)).body.user.role).toBe('CLIENT_VIEWER');
    await prisma.user.update({ where: { id: u.user.id }, data: { isActive: false } });
    expect((await request(ctx.app).get('/api/auth/me').set(u.auth)).status).toBe(401);
    expect((await request(ctx.app).post('/api/auth/login').send({ email: 'temp@example.com', password: 'correct-horse-battery' })).status).toBe(401);
  });

  it('throttles repeated failed logins', async () => {
    let last = 0;
    for (let i = 0; i < 10; i++) last = (await request(ctx.app).post('/api/auth/login').send({ email: 'victim@example.com', password: 'bad-password-123' })).status;
    expect(last).toBe(429);
  });

  it('never leaks stack traces', async () => {
    const r = await request(ctx.app).post('/api/auth/login').set('Content-Type', 'application/json').send('{bad json');
    expect(r.status).toBe(400);
    expect(JSON.stringify(r.body)).not.toMatch(/at .*\.ts|node_modules|stack/i);
    expect((await request(ctx.app).get('/api/nope')).status).toBe(401); // unauthenticated callers learn nothing about routes
    const admin = await login(ctx, 'admin@example.com', 'correct-horse-battery');
    expect((await request(ctx.app).get('/api/nope').set(admin.auth)).status).toBe(404);
  });
});
