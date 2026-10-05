import { ChildProcess, execSync, spawn } from 'node:child_process';
import path from 'node:path';
import { AI_PORT, TEST_DB, TEST_ENV } from './test-env';

let ai: ChildProcess | undefined;
const root = path.resolve(__dirname, '..', '..');

async function waitFor(url: string, ms = 60_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try { if ((await fetch(url)).ok) return; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`timeout waiting for ${url}`);
}

export async function setup() {
  // dedicated test database (the dev database is never touched)
  // TEST_SKIP_MIGRATE=1: the database already has the schema (e.g. an embedded Postgres without pgvector)
  if (!process.env.TEST_SKIP_MIGRATE) {
    try { execSync('docker exec wa_intel_pg psql -U wa -d postgres -c "CREATE DATABASE wa_intel_test"', { stdio: 'pipe' }); } catch { /* already exists */ }
    execSync('npx prisma migrate deploy', { cwd: path.resolve(__dirname, '..'), env: { ...process.env, DATABASE_URL: TEST_DB }, stdio: 'pipe' });
  }
  const py = process.env.AI_PYTHON ?? (process.platform === 'win32'
    ? path.join(root, 'ai-engine', '.venv', 'Scripts', 'python.exe')
    : path.join(root, 'ai-engine', '.venv', 'bin', 'python'));
  ai = spawn(py, ['-m', 'uvicorn', 'app.api.main:app', '--port', String(AI_PORT), '--log-level', 'warning'], {
    cwd: path.join(root, 'ai-engine'),
    env: { ...process.env, EMBED_MODEL: 'hashing', AI_ENGINE_TOKEN: TEST_ENV.AI_ENGINE_TOKEN, PYTHONPATH: path.join(root, 'ai-engine') },
    stdio: 'ignore',
  });
  await waitFor(`http://127.0.0.1:${AI_PORT}/health`);
}

export async function teardown() { ai?.kill(); }
