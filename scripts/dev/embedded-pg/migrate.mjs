// Applies pending backend/prisma/migrations to the RUNNING dev Postgres (same bookkeeping as start.mjs, which only runs at server start).
//   cd scripts/dev/embedded-pg && node migrate.mjs
import fs from 'node:fs';
import path from 'node:path';
import pg from 'pg';

const root = path.resolve(import.meta.dirname, '..', '..', '..');
const migDir = path.join(root, 'backend', 'prisma', 'migrations');
const migrations = fs.readdirSync(migDir).filter((x) => /^\d/.test(x)).sort();
for (const name of ['wa_intel_dev', 'wa_intel_test']) {
  const c = new pg.Client({ connectionString: `postgresql://wa:wa_dev_pw@localhost:15433/${name}` });
  await c.connect();
  await c.query('create table if not exists _dev_migrations (name text primary key)');
  const done = new Set((await c.query('select name from _dev_migrations')).rows.map((r) => r.name));
  for (const m of migrations.filter((x) => !done.has(x))) {
    const sql = fs.readFileSync(path.join(migDir, m, 'migration.sql'), 'utf8').replace(/CREATE EXTENSION[^;]*;/g, '').replace(/"embedding" vector\(384\)/g, '"embedding" TEXT');
    await c.query(sql);
    await c.query('insert into _dev_migrations values ($1)', [m]);
    console.log(`${name}: applied ${m}`);
  }
  await c.end();
}
console.log('up to date');
