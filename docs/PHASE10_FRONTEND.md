# Phase 10 - React dashboard

Code: `frontend/` (Vite + React 19 + TypeScript + Tailwind v4 + React Router + TanStack Query + Recharts + Lucide + React Hook Form + Zod + Axios).
Backend additions for it: `GET /api/projects/:id/overview`, `GET /api/executive`, `GET /api/users` (+ 4 tests).

## Pages
| Route | What it shows |
|---|---|
| `/login` | RHF + Zod validated sign-in, generic server error |
| `/` Executive dashboard | totals (projects, at-risk/critical, avg progress, team engaged, client pending, overdue, blockers, high risks), project comparison table, top risks across projects, open-work chart |
| `/projects` | project list with progress/health, create-project dialog |
| `/p/:id/overview` Project dashboard | header, project-health block (overall % + health status + Development / Design / Testing / Deployment / Client approval / Documentation bars; "no data" when there is no evidence), 8 KPI cards, **"Why N%?" drawer** (task-level points, what holds progress back, reliability, warnings), evidence-bound executive summary, next actions, charts (task status, progress over time, velocity, developer contribution, client pending by type, risk distribution, chat activity) |
| `/p/:id/chat` Chat analysis | drag-and-drop upload, live stage stepper (Uploading … Completed) with progress %, duplicate-chat message, import history (messages / new messages), chat explorer (keyword + semantic search, person and date filters, day separators, load more) |
| `/p/:id/tasks` | filterable table, AI-confidence + "Needs review" badges, overdue flags, edit dialog (RHF + Zod; status-only for team members), **click a task -> evidence drawer** with the exact WhatsApp messages, surrounding context and how the status was decided |
| `/p/:id/team` | developer performance table (click -> score breakdown, "message count is not part of the score", low-sample warning), participants with role override (sticks across re-analysis), masked phones |
| `/p/:id/client-pending` | type filter chips (All / Approval / Feedback / Payment / Credentials / Requirements / UAT / Content), age, priority, impact, resolve with confirmation |
| `/p/:id/sales`, `/risks`, `/timeline`, `/reports`, `/analytics`, `/settings` | sales activity, risk score + factor bars + contradictions (always "potential"), evidence timeline, report generation + PDF/Excel/CSV/JSON download, response-time/velocity/volume/workload charts, project access management |

## UX / engineering notes
- Loading skeletons, empty states, error states with retry, confirmation dialogs, toasts, dark mode (follows the system, toggle in the header), responsive (sidebar becomes a drawer on small screens; tables scroll horizontally).
- Role-aware: navigation, buttons and data panels follow the permission matrix (mirrored from the backend for UI gating only; the server enforces). Client viewers see Projects, Overview, Tasks (title/status/deadline), Client pending, Timeline - no messages, assignees, contribution or risks.
- Auth: access token in sessionStorage, refresh token in localStorage; a single in-flight refresh is shared by concurrent 401s (refresh tokens are single use); failure signs the user out.
- WhatsApp wall-clock times are rendered in UTC so nothing shifts with the viewer's timezone.
- Route-level code splitting (initial JS 500 kB, charts 407 kB loaded on demand).
- Accessible basics: labelled inputs, `role=progressbar`, dialog/drawer roles + Escape to close, aria-live job progress.

## Verification done
- `tsc` clean, production build OK, 10 unit tests (formatters, permission mirror, badges, token-refresh de-duplication, login validation/error).
- Driven in a real browser against the real stack (backend + Python engine + PostgreSQL), seeded through the API: login, executive dashboard, project dashboard with charts, task evidence drawer, drag-style upload with live progress, duplicate-upload message, import history, client-viewer navigation and reduced dashboard. Two defects found this way and fixed: progress bars collapsing to a dot inside table cells, and a grammatical error in generated blocker sentences ("blocked of an unresolved dependency").
- Not exercised in the browser: report downloads, Team/Risks/Sales/Analytics/Timeline/Settings pages, task edit dialog, notifications dropdown, light theme, desktop-width layout (the preview pane was ~800 px wide). They compile and use the same tested endpoints, but have had no visual check.

## Gaps
- No end-to-end (Playwright) suite yet. No i18n. Refresh token in localStorage is XSS-exposed; an httpOnly cookie flow is the better production design.
- The executive dashboard has no per-project drill-down charts beyond the table; project comparison is tabular.
- AI assistant chat UI and the annotation tool UI are not in the React app yet (the engine's `/annotate` page exists).
- Stored summary/insight text is only refreshed on re-analysis.
