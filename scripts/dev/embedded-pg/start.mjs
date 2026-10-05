// Development-only PostgreSQL (no Docker): an embedded server on :15433 with the application schema applied.
//   cd scripts/dev/embedded-pg && npm install && node start.mjs      (leave it running; see scripts/dev/dev-up.ps1)
// It creates wa_intel_dev (the app) and wa_intel_test (the backend tests), applies backend/prisma/migrations in order (pgvector is replaced by a TEXT column,
// because this build has no extension), and remembers what it applied in the _dev_migrations table so restarts and new migrations are safe.
// NOT for production: the real database is the pgvector Postgres container in docker-compose.yml.
import EmbeddedPostgres from 'embedded-postgres';
import fs from 'node:fs';
import path from 'node:path';
import pg from 'pg';

const root = path.resolve(import.meta.dirname, '..', '..', '..');
const dir = path.join(root, 'private-data', 'pgdata');
const migDir = path.join(root, 'backend', 'prisma', 'migrations');
const PORT = 15433;
const conn = (db) => `postgresql://wa:wa_dev_pw@localhost:${PORT}/${db}`;

const fresh = !fs.existsSync(path.join(dir, 'PG_VERSION'));
const server = new EmbeddedPostgres({ databaseDir: dir, user: 'wa', password: 'wa_dev_pw', port: PORT, persistent: true });
if (fresh) await server.initialise();
await server.start();

const admin = new pg.Client({ connectionString: conn('postgres') });
await admin.connect();
for (const name of ['wa_intel_dev', 'wa_intel_test']) {
  if (!(await admin.query('select 1 from pg_database where datname=$1', [name])).rowCount) {
    await admin.query(`CREATE DATABASE ${name} ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'`);
  }
}
await admin.end();

const migrations = fs.readdirSync(migDir).filter((x) => /^\d/.test(x)).sort();
for (const name of ['wa_intel_dev', 'wa_intel_test']) {
  const c = new pg.Client({ connectionString: conn(name) });
  await c.connect();
  const hadTable = (await c.query(`select to_regclass('public._dev_migrations') as t`)).rows[0].t;
  await c.query('create table if not exists _dev_migrations (name text primary key)');
  if (!hadTable && (await c.query(`select to_regclass('public."User"') as t`)).rows[0].t) {
    // a database created before this table existed: the migrations that were present then are already applied
    for (const m of migrations.filter((x) => x <= '20261006010000_project_retention')) await c.query('insert into _dev_migrations values ($1) on conflict do nothing', [m]);
  }
  const done = new Set((await c.query('select name from _dev_migrations')).rows.map((r) => r.name));
  for (const m of migrations.filter((x) => !done.has(x))) {
    const sql = fs.readFileSync(path.join(migDir, m, 'migration.sql'), 'utf8').replace(/CREATE EXTENSION[^;]*;/g, '').replace(/"embedding" vector\(384\)/g, '"embedding" TEXT');
    await c.query(sql);
    await c.query('insert into _dev_migrations values ($1)', [m]);
    console.log(`${name}: applied ${m}`);
  }
  await c.end();
}
console.log('READY');
setInterval(() => {}, 1 << 30);
