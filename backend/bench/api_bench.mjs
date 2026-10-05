// End-to-end API benchmark: import a large chat through the real HTTP API, then measure read latencies.
//   node bench/api_bench.mjs <chat.txt> [baseUrl]
// Requires a running backend + AI engine + database (see README). Uses a throwaway project; data is synthetic.
import fs from 'node:fs';

const file = process.argv[2];
const API = (process.argv[3] ?? 'http://localhost:4010') + '/api';
const pw = 'correct-horse-battery-bench';
const call = async (method, url, body, token, form) => {
  const r = await fetch(API + url, { method, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body && !form ? { 'Content-Type': 'application/json' } : {}) }, body: form ?? (body ? JSON.stringify(body) : undefined) });
  const t = await r.text();
  if (!r.ok) throw new Error(`${method} ${url} -> ${r.status} ${t.slice(0, 200)}`);
  return JSON.parse(t);
};
const pct = (a, p) => a.slice().sort((x, y) => x - y)[Math.min(a.length - 1, Math.floor(a.length * p))];

await call('POST', '/auth/register', { email: 'bench@example.com', name: 'Bench', password: pw }).catch(() => {});
const me = await call('POST', '/auth/login', { email: 'bench@example.com', password: pw });
const token = me.accessToken;
const project = await call('POST', '/projects', { name: 'Bench ' + Date.now() }, token);

const buf = fs.readFileSync(file);
const fd = new FormData();
fd.append('file', new Blob([buf]), 'bench.txt');
let t0 = performance.now();
const up = await call('POST', `/projects/${project.id}/chat/upload`, null, token, fd);
const uploadMs = performance.now() - t0;
const stages = [];
t0 = performance.now();
let job;
for (;;) {
  job = await call('GET', `/analysis/${up.jobId}`, null, token);
  if (!stages.length || stages.at(-1).stage !== job.stage) stages.push({ stage: job.stage, atSec: +((performance.now() - t0) / 1000).toFixed(1) });
  if (['COMPLETED', 'FAILED'].includes(job.status)) break;
  await new Promise((r) => setTimeout(r, 250));
}
const totalSec = (performance.now() - t0) / 1000;
console.log(`file ${(buf.length / 1e6).toFixed(2)} MB | upload request ${uploadMs.toFixed(0)} ms (returns 202) | job ${job.status} in ${totalSec.toFixed(1)} s`);
console.log('stages:', stages.map((s) => `${s.stage}@${s.atSec}s`).join(' > '));
if (job.status !== 'COMPLETED') { console.log('error:', job.error); process.exit(1); }

const endpoints = [`/projects/${project.id}/overview`, `/projects/${project.id}/progress`, `/projects/${project.id}/health`, `/projects/${project.id}/tasks?limit=50`,
  `/projects/${project.id}/messages?limit=60`, `/projects/${project.id}/messages?limit=60&q=razorpay`, `/projects/${project.id}/client-pending?limit=50`,
  `/projects/${project.id}/team-performance`, `/projects/${project.id}/risks`, `/projects/${project.id}/timeline`, `/projects/${project.id}/search?q=payment%20gateway&mode=lexical`, '/executive'];
const CONC = 10, N = 40;
console.log(`\nread latency (${CONC} concurrent clients x ${N} requests each endpoint, ms)`);
console.log('endpoint'.padEnd(52), 'p50'.padStart(6), 'p95'.padStart(6), 'max'.padStart(6));
for (const e of endpoints) {
  const lat = [];
  const worker = async () => { for (let i = 0; i < N / CONC; i++) { const s = performance.now(); await call('GET', e, null, token); lat.push(performance.now() - s); } };
  await Promise.all(Array.from({ length: CONC }, worker));
  console.log(e.replace(project.id, '<id>').padEnd(52), pct(lat, 0.5).toFixed(0).padStart(6), pct(lat, 0.95).toFixed(0).padStart(6), Math.max(...lat).toFixed(0).padStart(6));
}
// incremental re-import of the same chat must be rejected instantly (duplicate)
const fd2 = new FormData(); fd2.append('file', new Blob([buf]), 'bench.txt');
t0 = performance.now();
const dup = await fetch(API + `/projects/${project.id}/chat/upload`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd2 });
console.log(`\nduplicate upload -> HTTP ${dup.status} in ${(performance.now() - t0).toFixed(0)} ms`);
