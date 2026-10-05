"""Builds docx/00-overview/WhatsApp_Platform_Architecture.pdf (10 pages, A4) with reportlab.
   python docx/00-overview/build_architecture_pdf.py        (uses the ai-engine virtualenv: it has reportlab)
Facts in this file come from the repository (see docx/ for the detailed documents); change them here when the system changes."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, KeepInFrame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

OUT = Path(__file__).with_name("WhatsApp_Platform_Architecture.pdf")
W, H = A4
M = 34
CW = W - 2 * M                      # content width
INK, MUTED, LINE = colors.HexColor("#1b2033"), colors.HexColor("#5d6480"), colors.HexColor("#d5d9e6")
BRAND, BRAND_D = colors.HexColor("#4f5fe0"), colors.HexColor("#2f3aa8")
C_USER, C_FE, C_BE, C_AI, C_AS, C_DB, C_EXT, C_SEC, C_OK = (colors.HexColor(x) for x in ("#e8ecff", "#dff4ee", "#e4ecff", "#fff0d9", "#f3e6ff", "#e6efe0", "#f1f1f4", "#ffe4e4", "#dff5e3"))

S = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK, spaceAfter=3),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=9.2, leading=12.4, textColor=MUTED, spaceAfter=7),
    "p": ParagraphStyle("p", fontName="Helvetica", fontSize=8.7, leading=11.6, textColor=INK, spaceAfter=4, alignment=TA_LEFT),
    "b": ParagraphStyle("b", fontName="Helvetica", fontSize=8.5, leading=11.2, textColor=INK, leftIndent=9, bulletIndent=0, spaceAfter=1.6),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.6, leading=13, textColor=BRAND_D, spaceBefore=6, spaceAfter=3),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=7.9, leading=9.8, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=7.9, leading=9.8, textColor=INK),
    "head": ParagraphStyle("head", fontName="Helvetica-Bold", fontSize=7.9, leading=9.8, textColor=colors.white),
    "small": ParagraphStyle("small", fontName="Helvetica-Oblique", fontSize=7.4, leading=9.4, textColor=MUTED),
}


def P(t, s="p"): return Paragraph(t, S[s])
def bullets(items, s="b"): return [Paragraph(i, S[s], bulletText="•") for i in items]


def table(rows, widths, head=True, zebra=True, extra=()):
    data = [[Paragraph(str(c), S["head" if (head and r == 0) else "cell"]) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 2.6),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE)]
    if head:
        st += [("BACKGROUND", (0, 0), (-1, 0), BRAND_D)]
    if zebra:
        st += [("ROWBACKGROUNDS", (0, 1 if head else 0), (-1, -1), [colors.white, colors.HexColor("#f6f7fb")])]
    t.setStyle(TableStyle(st + list(extra)))
    return t


class Draw(Flowable):
    """A diagram: fn(canvas, width, height) draws in a box of the given height."""
    def __init__(self, height, fn, width=CW):
        super().__init__()
        self.width, self.height, self.fn = width, height, fn

    def wrap(self, aw, ah): return self.width, self.height

    def draw(self): self.fn(self.canv, self.width, self.height)


def wrap_text(text, font, size, maxw):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word).strip()
            if stringWidth(t, font, size) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def box(c, x, y, w, h, text, fill=C_BE, stroke=BRAND_D, size=7.6, bold_first=True, color=INK, r=4, dash=False):
    c.saveState()
    c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(0.7)
    if dash: c.setDash(2, 2)
    c.roundRect(x, y, w, h, r, fill=1, stroke=1)
    c.setDash()
    lines = wrap_text(text, "Helvetica-Bold", size, w - 10)
    lead = size + 1.5
    total = lead * len(lines)
    ty = y + h / 2 + total / 2 - size + 0.5
    for i, ln in enumerate(lines):
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if (i == 0 and bold_first) else "Helvetica", size)
        c.drawCentredString(x + w / 2, ty - i * lead, ln)
    c.restoreState()


def region(c, x, y, w, h, title, fill=colors.HexColor("#f7f8fc"), stroke=LINE):
    c.saveState()
    c.setFillColor(fill); c.setStrokeColor(stroke); c.setLineWidth(0.8); c.setDash(3, 2)
    c.roundRect(x, y, w, h, 6, fill=1, stroke=1)
    c.setDash(); c.setFillColor(MUTED); c.setFont("Helvetica-Bold", 7.2)
    c.drawString(x + 6, y + h - 10, title)
    c.restoreState()


def arrow(c, x1, y1, x2, y2, label=None, color=BRAND_D, w=0.9, lx=0, ly=0, both=False):
    import math
    c.saveState()
    c.setStrokeColor(color); c.setFillColor(color); c.setLineWidth(w)
    c.line(x1, y1, x2, y2)
    for (ax, ay, bx, by) in ([(x1, y1, x2, y2)] + ([(x2, y2, x1, y1)] if both else [])):
        ang = math.atan2(by - ay, bx - ax)
        p = c.beginPath()
        p.moveTo(bx, by)
        p.lineTo(bx - 5 * math.cos(ang - 0.4), by - 5 * math.sin(ang - 0.4))
        p.lineTo(bx - 5 * math.cos(ang + 0.4), by - 5 * math.sin(ang + 0.4))
        p.close()
        c.drawPath(p, fill=1, stroke=0)
    if label:
        c.setFillColor(MUTED); c.setFont("Helvetica", 6.4)
        c.drawCentredString((x1 + x2) / 2 + lx, (y1 + y2) / 2 + 3 + ly, label)
    c.restoreState()


def page_deco(canv, doc):
    canv.saveState()
    canv.setFillColor(BRAND_D); canv.rect(0, H - 14, W, 14, fill=1, stroke=0)
    canv.setFillColor(colors.white); canv.setFont("Helvetica-Bold", 7.4)
    canv.drawString(M, H - 10, "WhatsApp Project Intelligence Platform")
    canv.setFont("Helvetica", 7.4); canv.drawRightString(W - M, H - 10, "End-to-end architecture  |  2026-10-06")
    canv.setStrokeColor(LINE); canv.line(M, 26, W - M, 26)
    canv.setFillColor(MUTED); canv.setFont("Helvetica", 7)
    canv.drawString(M, 15, "Self-hosted, single-company deployment. Facts from the repository; unmeasured items are marked as such.")
    canv.drawRightString(W - M, 15, f"Page {doc.page} of 10")
    canv.restoreState()


def fit(content, h=H - 2 * M - 14):
    """Each page is a KeepInFrame that shrinks slightly instead of spilling onto an eleventh page."""
    return KeepInFrame(CW, h, content, mode="shrink", vAlign="TOP")


def title(t, sub=None):
    return [P(t, "h1")] + ([P(sub, "sub")] if sub else [])


# ============================================================ page 1: summary
def layer_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    layers = [("Sources", [("Phone export -> Google Drive", C_EXT), ("Manual upload", C_EXT), ("Cloud API webhook (business groups, 1:1)", C_EXT)]),
              ("Experience", [("Dashboard + live updates", C_FE), ("Assistant panel", C_FE), ("Annotation tool", C_FE)]),
              ("Application", [("Backend API + RBAC", C_BE), ("Worker + queue", C_BE), ("Assistant service + policy engine", C_AS)]),
              ("Intelligence", [("AI engine: rules + ML analysis", C_AI), ("Search + RAG", C_AI), ("LLM (llama.cpp, local)", C_AS)]),
              ("Data", [("PostgreSQL (+pgvector)", C_DB), ("Redis (optional)", C_DB), ("Files, model registry, audit", C_DB)])]
    rh = (h - 24) / len(layers)
    for li, (name, items) in enumerate(layers):
        y = h - 14 - (li + 1) * rh + 3
        c.setFillColor(BRAND_D); c.setFont("Helvetica-Bold", 7.4)
        c.drawString(14, y + rh / 2 - 6, name)
        bw = (w - 110 - 2 * 8) / 3
        for i, (t, f) in enumerate(items):
            box(c, 96 + i * (bw + 8), y, bw, rh - 8, t, f, BRAND_D, size=7.2, bold_first=False)


def page1():
    c = title("WhatsApp Project Intelligence Platform",
              "A self-hosted platform that turns WhatsApp project chats into structured, evidence-linked project intelligence, a live dashboard, search, and a permission-bound assistant. No external AI service is used.")
    c.append(P("What it does, end to end", "h2"))
    c += bullets([
        "<b>Ingests</b> chats: phone export saved to Google Drive and imported from a watched folder, manual upload, or (for business-created groups and 1:1 chats) the official WhatsApp Cloud API webhook.",
        "<b>Analyses</b> every message with deterministic rules and small models (English, Hinglish, Hindi): tasks, assignees, deadlines, decisions, requirements and changes, bugs, commitments, client-pending items, conflicts, risks, questions and answers, tone, progress and health, daily/weekly/monthly summaries.",
        "<b>Shows</b> it in a role-aware dashboard that updates live; every number links to the messages it came from (evidence ids).",
        "<b>Answers and acts</b> through an assistant: a self-hosted LLM proposes, a deterministic policy engine decides, actions run with the user's own permissions and are verified by reading back.",
        "<b>Protects</b> data: RBAC with project membership, encrypted uploads and phone numbers, signed webhooks, audit trail, per-project retention and erasure.",
    ])
    c.append(P("Design principles", "h2"))
    c.append(table([["Principle", "How it shows up"],
                    ["Evidence over assertion", "Every derived item carries source message ids and a confidence or review flag; raw text is never modified."],
                    ["Deterministic where possible", "Counts, dates, rates and response times are plain code; models only classify or generate text."],
                    ["LLM proposes, code disposes", "Permissions, risk tiers, confirmations, id checks and rate limits are ordinary code, outside the model."],
                    ["Honest degradation", "Live events fall back to polling, the app serves stored data if the AI engine is down, the assistant abstains instead of guessing."],
                    ["Self-hosted, single company", "Models run locally (Qwen2.5-7B via llama.cpp); isolation unit is the project, not a tenant (ADR-002)."],
                    ["Additive change", "Schema changes are migrations that only add; existing roles, APIs and data keep working."]],
                   [118, CW - 118]))
    c.append(Spacer(1, 6))
    c.append(P("At a glance", "h2"))
    c.append(table([["Services", "Languages", "Data model", "Automated tests (all passing)", "Not yet measured"],
                    ["Frontend, Backend API + worker, AI engine, Assistant, LLM server, PostgreSQL, Redis (optional), edge proxy",
                     "TypeScript (backend, frontend), Python (AI engine, assistant)",
                     "38 Prisma models; derived outputs also stored as JSON snapshots",
                     "AI engine 175, backend 83, assistant 57, frontend 12 + typecheck",
                     "Real-LLM tool-calling quality (bake-off running), speech accuracy, load tests, independent accuracy of Q&A / tone"]],
                   [118, 90, 90, 112, CW - 410]))
    c.append(Spacer(1, 5))
    c.append(P("The system in five layers", "h2"))
    c.append(Draw(176, layer_diagram))
    c.append(Spacer(1, 3))
    c.append(P("Status legend used in this document: <b>Built and tested</b> | <b>Built, not exercised against the real counterpart</b> (Meta, Google Drive, a speech model) | <b>Planned / out of scope</b> (multi-tenancy, RabbitMQ).", "small"))
    return [fit(c)]


# ============================================================ page 2: system context
def ctx_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    # actors (left)
    box(c, 12, h - 62, 110, 44, "Phone: normal WhatsApp\nExport chat (without media)", C_EXT, MUTED)
    box(c, 12, h - 128, 110, 44, "Google Drive\n(phone account) -> Drive for desktop", C_EXT, MUTED)
    box(c, 12, h - 194, 110, 44, "Meta WhatsApp Cloud API\nbusiness groups (<=8), 1:1", C_EXT, MUTED)
    box(c, 12, 18, 110, 50, "Users: admin, project manager, team member, sales, client viewer", C_USER, BRAND)
    # system boundary
    region(c, 150, 10, w - 160, h - 22, "PLATFORM (self-hosted, one company)")
    box(c, 170, h - 70, 150, 44, "Ingestion\nwatched folder | upload | signed webhook", C_BE)
    box(c, 340, h - 70, 150, 44, "Job queue + analysis\nBullMQ (or inline) -> AI engine", C_BE)
    box(c, 170, h - 140, 150, 44, "PostgreSQL\nmessages, derived data, snapshots, audit", C_DB)
    box(c, 340, h - 140, 150, 44, "AI engine (Python)\nrules + ML, search index, summaries", C_AI)
    box(c, 170, h - 210, 150, 44, "Backend API (Node)\nauth, RBAC, analytics, SSE, retention", C_BE)
    box(c, 340, h - 210, 150, 44, "Assistant (Python)\npolicy engine, tools, document RAG", C_AS)
    box(c, 170, 24, 150, 44, "Frontend (React)\ndashboard, assistant panel, live updates", C_FE)
    box(c, 340, 24, 150, 44, "LLM server (llama.cpp)\nQwen2.5-7B Q4_K_M, CPU, local only", C_AS)
    arrow(c, 122, h - 40, 170, h - 48, "export file")
    arrow(c, 67, h - 62, 67, h - 84, "save")
    arrow(c, 122, h - 106, 170, h - 56, "sync (folder)")
    arrow(c, 122, h - 172, 170, h - 60, "HMAC webhook", lx=-6, ly=-2)
    arrow(c, 320, h - 48, 340, h - 48)
    arrow(c, 415, h - 70, 415, h - 96, "analyse")
    arrow(c, 340, h - 118, 320, h - 118, both=True)
    arrow(c, 245, h - 140, 245, h - 166, both=True)
    arrow(c, 245, h - 210, 245, 68, "REST + SSE", both=True)
    arrow(c, 340, h - 188, 320, h - 188, "user token")
    arrow(c, 415, h - 210, 415, 68, "chat completions", both=True)
    arrow(c, 122, 43, 170, 46, "HTTPS", both=True)
    c.setFillColor(MUTED); c.setFont("Helvetica", 6.6)
    c.drawString(156, 13, "No component calls an external AI/LLM API. In the compose deployment the internal network has no internet egress.")


def page2():
    c = title("1. System context", "Who and what the platform talks to. Everything inside the dashed boundary runs on the owner's hardware.")
    c.append(Draw(300, ctx_diagram))
    c.append(P("Boundaries and trust", "h2"))
    c.append(table([["Boundary", "What crosses it", "Control"],
                    ["Phone/Drive -> platform", "an exported chat file (text, optionally zipped)", "file only, no WhatsApp access; size, type, stability and duplicate checks; incremental import"],
                    ["Meta -> platform", "signed webhook events for business-created groups and 1:1 chats", "HMAC-SHA256 over the raw body; only explicitly mapped conversations are stored; idempotent per message id"],
                    ["Browser -> platform", "HTTPS API calls, SSE stream", "JWT (15 min) + rotating refresh token; RBAC; project membership; rate limits at the edge"],
                    ["Assistant -> backend", "tool calls", "always with the signed-in user's token; tiers T0-T3; confirmation by UI button for sensitive actions"],
                    ["Platform -> internet", "none for AI", "models are local; internal compose network has no egress"]],
                   [88, 150, CW - 238]))
    c.append(Spacer(1, 5))
    c.append(P("Why WhatsApp ingestion looks like this", "h2"))
    c += bullets(["The official Cloud API can read only <b>business-created groups (max 8 participants)</b> and 1:1 customer chats, requires an Official Business Account, and offers <b>no history backfill for groups</b> (verified against Meta documentation, Oct 2026). Existing personal groups cannot be read by any authorized API.",
                  "Therefore the personal-WhatsApp path is <b>phone export -> Google Drive -> watched folder</b>, which is automatic from the synced file onward. Scraping or WhatsApp Web automation is deliberately not used (ban risk, security)."])
    return [fit(c)]


# ============================================================ page 3: deployment view
def deploy_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    box(c, 12, h - 50, w - 24, 38, "Edge proxy (nginx): TLS, rate limits (login 10/min, API 20/s, upload 6/min), SPA hosting, SSE without buffering, raw-body webhook route, no public /health", C_SEC, colors.HexColor("#b33"), size=7.2)
    region(c, 10, 58, w - 20, h - 122, "INTERNAL NETWORK (no internet egress)")
    n = 4
    bw = (w - 20 - 12 * (n + 1)) / n
    xs = [10 + 12 + i * (bw + 12) for i in range(n)]
    ya, yb = h - 156, h - 238
    apps = [("Backend API", "Node 20, Express, Prisma  :4000", C_BE), ("Worker", "BullMQ consumer, same image as the backend", C_BE),
            ("AI engine", "Python FastAPI  :8000 (service token)", C_AI), ("Assistant", "Python FastAPI  :8100", C_AS)]
    stores = [("PostgreSQL 16 + pgvector", ":5432 (dev: embedded :15433)", C_DB), ("Redis 7", "queue + live events (optional in dev)", C_DB),
              ("Model volume", "classifier registry, embedding weights", C_DB), ("LLM server", "llama.cpp :8081, Qwen2.5-7B Q4_K_M", C_AS)]
    for i in range(n):
        box(c, xs[i], ya, bw, 56, apps[i][0] + "\n" + apps[i][1], apps[i][2], size=7.2)
        box(c, xs[i], yb, bw, 56, stores[i][0] + "\n" + stores[i][1], stores[i][2], size=7.2)
    arrow(c, w / 2, h - 50, w / 2, h - 82, "proxy: /api, /assistant, /api/events", ly=2)
    arrow(c, xs[0] + bw / 2, ya, xs[0] + bw / 2, yb + 56, both=True)
    arrow(c, xs[1] + bw / 2, ya, xs[1] + bw / 2, yb + 56, both=True)
    arrow(c, xs[2] + bw / 2, ya, xs[2] + bw / 2, yb + 56, "files", both=True)
    arrow(c, xs[3] + bw / 2, ya, xs[3] + bw / 2, yb + 56, "chat completions", both=True)
    arrow(c, xs[0] + bw, ya + 38, xs[1], ya + 38, "jobs", both=True)
    arrow(c, xs[1] + bw, ya + 38, xs[2], ya + 38, "HTTP")
    c.saveState()
    c.setStrokeColor(colors.HexColor("#6a9a2a")); c.setFillColor(colors.HexColor("#6a9a2a")); c.setLineWidth(0.9)
    top = ya + 56
    p0 = c.beginPath(); p0.moveTo(xs[3] + bw / 2, top); p0.lineTo(xs[3] + bw / 2, top + 11); p0.lineTo(xs[0] + bw / 2, top + 11); p0.lineTo(xs[0] + bw / 2, top + 1)
    c.drawPath(p0, fill=0, stroke=1)
    c.setFont("Helvetica", 6.4); c.drawCentredString((xs[0] + xs[3] + bw) / 2, top + 14, "assistant -> backend with the user's own token")
    c.restoreState()
    box(c, 12, 12, w - 24, 38, "Backups: scripts/backup.sh (nightly, restore tested)  |  Uploads: encrypted files with TTL purge  |  Logs: JSON lines without message text or query strings  |  Secrets: environment only (scripts/gen-secrets.sh)", C_EXT, MUTED, size=7.0, bold_first=False)


def page3():
    c = title("2. Service and deployment view", "Production topology (docker-compose). Only the edge proxy is exposed; every other container sits on an internal network without internet access.")
    c.append(Draw(322, deploy_diagram))
    c.append(P("Services, ports and responsibilities", "h2"))
    c.append(table([["Service", "Tech", "Dev port", "Responsibility", "Scaling note"],
                    ["Frontend", "React 19, Vite 8, TypeScript, Tailwind 4, React Router 7, TanStack Query 5, Recharts", "5199", "dashboards, assistant panel, SSE client with polling fallback", "static assets behind nginx"],
                    ["Backend API", "Node, Express 4, TypeScript, Prisma 6, zod, helmet", "4000", "auth, RBAC, projects, import, analysis orchestration, analytics, webhook, retention, SSE, status", "stateless; scale horizontally"],
                    ["Worker", "BullMQ 6, ioredis", "-", "runs analysis jobs (2 attempts, exponential backoff)", "docker compose --scale worker=N"],
                    ["AI engine", "Python, FastAPI, scikit-learn, NumPy, NetworkX, reportlab", "8000", "parsing, analysis pipeline, search index, summaries, reports, annotation tool", "CPU-bound; index lives in memory"],
                    ["Assistant", "Python, FastAPI, pydantic, httpx", "8100", "agent loop, policy engine, tools, document RAG, voice endpoint", "stateless except sessions"],
                    ["LLM", "llama.cpp server, Qwen2.5-7B-Instruct Q4_K_M (4.68 GB, Apache-2.0)", "8081", "tool-calling language model", "CPU only here: about 1-4 tokens/s"],
                    ["PostgreSQL", "16 + pgvector (dev: embedded, TEXT embeddings)", "5432 / 15433", "single source of truth", "backup/restore tested"],
                    ["Redis", "7", "6379", "BullMQ and cross-process live events", "optional; inline queue without it"]],
                   [52, 138, 40, 175, CW - 405]))
    return [fit(c)]


# ============================================================ page 4: data flow
def flow_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    labels = [("1 Receive", "folder watcher | upload | webhook", C_EXT), ("2 Validate + dedupe", "type, size, stable file, hash, HMAC, mapping", C_SEC),
              ("3 Store messages", "write-once ChatMessage, encrypted upload, participants", C_DB), ("4 Queue job", "AnalysisJob + BullMQ (debounced for webhook)", C_BE)]
    bw = (w - 30 - 3 * 14) / 4
    for i, (t, d, f) in enumerate(labels):
        x = 15 + i * (bw + 14)
        box(c, x, h - 70, bw, 52, t + "\n" + d, f, BRAND_D, size=7.2)
        if i: arrow(c, x - 14, h - 44, x, h - 44)
    labels2 = [("5 Analyse (AI engine)", "parse, roles, tasks, Q&A, tone, decisions, risks, progress/health, summaries", C_AI), ("6 Persist", "derived rows + AIAnalysis snapshots (QA, SENTIMENT, PERIODIC ...)", C_DB),
               ("7 Index + notify", "search index, notifications, live event (SSE)", C_BE), ("8 Serve", "role-aware APIs, evidence links, dashboard refetch", C_FE)]
    for i, (t, d, f) in enumerate(labels2):
        x = 15 + i * (bw + 14)
        box(c, x, h - 150, bw, 56, t + "\n" + d, f, BRAND_D, size=7.2)
        if i: arrow(c, x - 14, h - 122, x, h - 122)
    arrow(c, 15 + 3 * (bw + 14) + bw / 2, h - 70, 15 + bw / 2, h - 94, "")      # wrap to row 2 start
    c.setStrokeColor(BRAND_D); c.setLineWidth(0.9)
    c.line(15 + 3 * (bw + 14) + bw / 2, h - 70, 15 + 3 * (bw + 14) + bw / 2, h - 82)
    c.line(15 + 3 * (bw + 14) + bw / 2, h - 82, 15 + bw / 2, h - 82)
    box(c, 15, 16, w - 30, 58, "Idempotency and ordering: message ids are deterministic (export: hash of the line; webhook: sha1 of the WhatsApp message id), so re-imports and Meta retries store nothing twice. "
        "Timestamps are wall-clock-as-UTC in the project timezone for both sources. A project is never analysed twice at once. A failure leaves stored messages intact and the job FAILED with a sanitised message; "
        "a transient AI-engine outage is retried by the queue.", C_EXT, MUTED, size=7.0, bold_first=False)


def page4():
    c = title("3. End-to-end data flow", "From a message on the phone to a number on the dashboard. The same eight steps serve all three ingestion paths.")
    c.append(Draw(238, flow_diagram))
    c.append(P("Ingestion paths compared", "h2"))
    c.append(table([["Path", "Trigger", "Automatic?", "Covers", "Key safeguards"],
                    ["Watched folder (personal WhatsApp)", "file appears in AUTO_IMPORT_DIR/<project>/ (.txt or .zip) every 30 s scan", "yes, after the phone export is saved to Drive", "any chat you can export, incl. existing groups",
                     "size+mtime stable across two scans, SHA-256 duplicate check, busy-project wait, zip-bomb cap, unknown/ambiguous folder untouched, moved to imported/ or rejected/ + reason"],
                    ["Manual upload", "POST /projects/:id/chat/upload (UI)", "no", "same", "extension, binary, size and WhatsApp-header checks; incremental append"],
                    ["Cloud API webhook", "Meta POSTs to /api/webhooks/whatsapp", "yes (real time)", "business-created groups (max 8) and 1:1 chats only", "HMAC on raw body, conversation must be mapped to a project, media metadata only, replies stored, reactions ignored"]],
                   [74, 100, 62, 90, CW - 326]))
    c.append(Spacer(1, 5))
    c.append(P("Worked example: one message, end to end", "h2"))
    c.append(table([["Step", "What happens to: <i>Priya (client): \"Rahul, please fix the payment bug by Friday\"</i>"],
                    ["Arrive", "exported on the phone, synced from Drive, found by the watcher, imported once (hash check); only messages not seen before are appended"],
                    ["Analyse", "assignment cue + vocative -> task 'fix the payment bug', assignee Rahul, deadline Friday (resolved against the message date); bug detected; question/tone/topic tags added"],
                    ["Evidence", "task and bug rows store the source message id and a confidence; low confidence or ambiguity sets needs_review"],
                    ["Later", "Rahul: 'payment bug fixed' -> task status trace TODO -> COMPLETED, bug FIXED; if the client replies 'still not working' the item is reopened for review"],
                    ["Show", "Tasks page, health and progress recalculated, summaries and Q&amp;A updated; the browser refreshes itself via the live event; every figure links back to the messages"]],
                   [44, CW - 44]))
    c.append(Spacer(1, 4))
    c.append(P("Live updates", "h2"))
    c += bullets(["Every stage change publishes an event (ids, stage, progress; never message text) to an in-process bus, or to a Redis channel when a separate worker runs.",
                  "<b>GET /api/events</b> (Server-Sent Events) delivers it to a browser only if the user can see that project (checked at delivery, cached 30 s), max 5 streams per user, heartbeat every 25 s.",
                  "The frontend refetches on completion and shows <i>Live</i>; after 3 failed connects it shows <i>Polling</i> and refreshes every 30 s."])
    return [fit(c)]


# ============================================================ page 5: backend
def page5():
    c = title("4. Backend architecture", "Node + Express + Prisma modular monolith. Authorization is enforced here on every request; the frontend only hides things.")
    c.append(P("Request pipeline", "h2"))
    c.append(table([["Layer", "What it does"],
                    ["requestLog", "one JSON line per request (route pattern, status, ms, user id); no bodies, no query strings, no message text"],
                    ["helmet + CORS", "security headers, HSTS, allow-listed origins with credentials"],
                    ["raw body for /webhooks/whatsapp, JSON (1 MB) elsewhere", "the webhook signature is computed over the exact bytes"],
                    ["authenticate", "JWT access token (15 min); refresh tokens are single-use and rotated; bcrypt (cost 12); constant-time compare for unknown users"],
                    ["requirePermission(action)", "role-permission matrix (SUPER_ADMIN, ADMIN, PROJECT_MANAGER, TEAM_MEMBER, SALES, CLIENT_VIEWER)"],
                    ["projectAccess(view|edit)", "project membership; non-members get 404 so existence is not leaked; read-only members cannot edit"],
                    ["validateBody / validateQuery (zod)", "typed input, 422 on failure; limits on sizes and enums"],
                    ["errorHandler", "sanitised errors {code, message}; no stack traces or upstream bodies to clients"]],
                   [128, CW - 128]))
    c.append(Spacer(1, 4))
    c.append(P("Modules", "h2"))
    c.append(table([["Module (backend/src)", "Endpoints / responsibility"],
                    ["controllers/auth", "register (first user = SUPER_ADMIN), login, refresh, logout, me"],
                    ["controllers/projects, tasks, chat, reports, overview", "projects and members, tasks (human edits are never overwritten by re-analysis), upload/uploads/messages/analysis status/reanalyze, report generate + export (PDF/XLSX/CSV), executive overview, users"],
                    ["controllers/analytics", "progress, health, team, sales, client-response-time, velocity, client-pending, risks, conflicts, timeline, insights, summary, notifications, audit, <b>qa, sentiment, summaries</b>"],
                    ["controllers/status", "/health, /ready, /queue/status, /ai/status, /auto-import/status, /auto-import/folders"],
                    ["controllers/whatsapp + services/whatsapp", "webhook verify + signed delivery, conversation-to-project mapping (WhatsappSource), normalisation, idempotent storage, debounced re-analysis"],
                    ["services/autoimport + importer + zipText", "watched-folder import, shared import checks, defensive ZIP reader"],
                    ["controllers/events + events/bus", "SSE stream with per-event authorization; in-process or Redis pub/sub"],
                    ["controllers/retention + services/retention", "per-project retention policy (30-3650 days), purge, erasure with derived data; scheduled sweep every 6 h"],
                    ["services/analysis + queues + workers", "job runner: parse -> store -> analyse -> persist -> index -> notify; BullMQ or inline"]],
                   [150, CW - 150]))
    c.append(Spacer(1, 4))
    c.append(P("Permissions at a glance", "h2"))
    c.append(table([["Role", "Typical rights"],
                    ["SUPER_ADMIN / ADMIN", "everything; manage users; see all projects; erase project data (project:delete)"],
                    ["PROJECT_MANAGER", "create projects, manage members, upload/connect sources, edit tasks, generate reports, set retention; sees only own projects"],
                    ["TEAM_MEMBER", "view analytics and tasks of member projects; change task status only; read raw chat"],
                    ["SALES", "sales analytics, client-facing views, reports (view)"],
                    ["CLIENT_VIEWER", "client-facing views only (progress, health, timeline, client-pending); no raw chat, no analytics"]],
                   [100, CW - 100]))
    return [fit(c)]


# ============================================================ page 6: data model
def data_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    cw = (w - 40) / 3
    xs = [14, 14 + cw + 6, 14 + 2 * (cw + 6)]
    y1, y2 = h - 104, 28
    box(c, xs[0], y1, cw, 84, "Identity and access\nUser, RefreshToken, Project, ProjectMember, Client, AuditLog, Notification", C_USER, size=7.2)
    box(c, xs[1], y1, cw, 84, "Conversation (write-once)\nChatUpload, ChatParticipant, ChatMessage (id = projectId:hash), WhatsappSource, MessageEnrichment, MessageEmbedding (pgvector)", C_DB, size=7.2)
    box(c, xs[2], y1, cw, 84, "Jobs and outputs\nAnalysisJob (status, stage, progress), Report, ModelVersion, TrainingExample", C_BE, size=7.2)
    box(c, xs[0], y2, cw, 84, "Work items (derived)\nTask (+TaskHistory, TaskAssignment), ProjectModule, Requirement (+RequirementChange), Deadline, Commitment, Bug, Meeting", C_AI, size=7.2)
    box(c, xs[1], y2, cw, 84, "Judgement items (derived)\nDecision, Conflict, Risk, ClientPendingItem, SalesActivity, Insight, ProjectEvent", C_AI, size=7.2)
    box(c, xs[2], y2, cw, 84, "Metrics and snapshots\nProjectProgress, ProjectHealth, AIAnalysis kinds: CONTRIBUTION, CLIENT_RESPONSE_TIME, VELOCITY, RISK_SUMMARY, QA, SENTIMENT, PERIODIC", C_FE, size=7.2)
    arrow(c, xs[1] + cw / 2, y1, xs[1] + cw / 2, y2 + 84, "source message ids")
    arrow(c, xs[0] + cw, y1 + 42, xs[1], y1 + 42)
    arrow(c, xs[1] + cw, y1 + 42, xs[2], y1 + 42)
    c.setFillColor(MUTED); c.setFont("Helvetica", 6.8)
    c.drawString(14, 13, "Every derived row has projectId and sourceMessageIds. Project deletion cascades; purge and erase use explicit child-first deletes (see retention).")


def page6():
    c = title("5. Data model and storage", "PostgreSQL via Prisma (38 models). Raw conversation data is write-once; AI interpretation lives in separate rows that always point back to the messages.")
    c.append(Draw(222, data_diagram))
    c.append(P("Rules the schema enforces", "h2"))
    c += bullets(["<b>Never destroy the original:</b> ChatMessage.originalText is the exact export/webhook text and is never updated; cleaned text and AI output are separate.",
                  "<b>Deterministic ids:</b> export lines hash to stable ids; webhook messages use sha1 of the WhatsApp id; re-imports and retries are no-ops.",
                  "<b>Human decisions win:</b> rows with reviewState HUMAN_CONFIRMED / HUMAN_CORRECTED are never overwritten by re-analysis; retention reports them instead of deleting.",
                  "<b>Evidence everywhere:</b> tasks, decisions, risks, Q&amp;A items and summary highlights store source message ids; the UI shows them.",
                  "<b>Time:</b> wall-clock-as-UTC in the project timezone (default Asia/Kolkata) so what users saw in WhatsApp is what the API returns."])
    c.append(P("Migrations added in this iteration (additive only)", "h2"))
    c.append(table([["Migration", "Change"],
                    ["20261006000000_whatsapp_sources", "table WhatsappSource: (phoneNumberId, conversationKey) -> project, carrier upload, counters; unique mapping"],
                    ["20261006010000_project_retention", "Project.retentionDays (nullable)"],
                    ["(no migration)", "Q&amp;A, tone and periodic summaries are stored as AIAnalysis snapshots with new kinds QA, SENTIMENT, PERIODIC"]],
                   [150, CW - 150]))
    c.append(Spacer(1, 4))
    c.append(P("Other stores", "h2"))
    c.append(table([["Store", "Holds", "Protection / lifecycle"],
                    ["Upload directory", "uploaded chat files (encrypted AES-256-GCM, random storage key)", "purged after UPLOAD_TTL_HOURS; messages stay in the DB"],
                    ["Phone numbers", "ChatParticipant.phone", "AES-256-GCM field encryption; masked in API responses"],
                    ["AI engine memory", "per-project search index (BM25 + vectors)", "rebuilt by analysis; dropped on purge/erase"],
                    ["Model registry (files)", "classifier versions, metrics, evaluation gate, rollback", "promotion needs a passing gate; drift monitored with PSI"],
                    ["Assistant files", "audit.jsonl, feedback.jsonl, document library", "no message text in audit; feedback is a review queue only"],
                    ["private-data/ (git-ignored)", "raw/anonymised chats, labels, LLM files, logs, dev credentials, watched inbox", "never committed; dev only"]],
                   [96, 190, CW - 286]))
    return [fit(c)]


# ============================================================ page 7: AI engine
def ai_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    bw = (w - 28 - 4 * 8) / 5
    rows = [[("Parse", "multi-format export parser, language, media/system flags", C_EXT), ("Roles", "name rules, then behaviour (client vs delivery side)", C_AI), ("Tasks", "creation, linking, status trace, assignee, deadline", C_AI),
             ("Client pending", "what the client owes, open/resolved, response time", C_AI), ("Requirements", "requirements, changes, bugs, commitments", C_AI)],
            [("Decisions, meetings", "evidence-bound", C_AI), ("Conflicts", "contradictory statements, never asserted", C_AI), ("Q&A", "question detection, evidence-scored answers", C_AI),
             ("Tone", "lexicon baseline: sentiment, frustration, urgency", C_AI), ("Risk", "weighted factors with reasons", C_AI)],
            [("Completion rule", "delivery announcement closes open tasks, flagged", C_AI), ("Progress + health", "weighted by task domain, configurable", C_FE), ("Summaries", "daily, weekly, monthly; templated", C_FE),
             ("Knowledge graph", "NetworkX; insights, next actions", C_FE), ("Search index", "BM25 + dense + filters", C_FE)]]
    c.setFillColor(MUTED); c.setFont("Helvetica", 6.8)
    c.drawString(14, h - 20, "analyze(messages) returns ONE dictionary (tasks, links, client_pending, requirements, bugs, commitments, conflicts, risk, decisions, meetings, qa, sentiment,")
    c.drawString(14, h - 29, "progress, health, velocity, contribution, summary, periodic, project_completion, graph stats). The backend persists it as rows and snapshots.")
    for ri, row in enumerate(rows):
        y = h - 100 - ri * 68
        for i, (t, d, f) in enumerate(row):
            x = 14 + i * (bw + 8)
            box(c, x, y, bw, 56, t + "\n" + d, f, BRAND_D, size=6.8)
            if i:
                arrow(c, x - 8, y + 28, x, y + 28)
    box(c, 14, 14, w - 28, 34, "Outside the per-chat pipeline: annotation tool with active learning and kappa, classifier training + model registry + evaluation gate + drift monitor, report builder (PDF, XLSX, CSV)", C_EXT, MUTED, size=7.0, bold_first=False)


def page7():
    c = title("6. AI engine and analysis pipeline", "Python FastAPI service. Rules and small models first; no generative model is involved in extraction, so every result is reproducible and explainable.")
    c.append(Draw(284, ai_diagram))
    c.append(P("Method and honest quality", "h2"))
    c.append(table([["Capability", "Method", "Measured so far"],
                    ["Message category proposals", "regex lexicons EN/Hinglish/Devanagari + signals; TF-IDF/LR classifier exists but is not deployed", "69.5% agreement with model-made labels on 233 messages of one chat (in-sample, silver labels); classifier scored lower and was not used"],
                    ["Tasks, assignees, status", "assignment/commit/done cues, topic linking, status trace", "hand-written unseen chats: recall 80-100% when tuned, 33% on a fresh holdout (tiny sets)"],
                    ["Questions and answers", "detection + evidence score; unconfirmed matches stay POSSIBLY_ANSWERED", "unit tests only; real chat: 7 answered / 7 possible / 6 unanswered of 20, not independently verified"],
                    ["Tone / urgency", "word lists with negation, emoji, repetition cues", ">=85% on 31 author-written examples; real chat mostly neutral (coverage limit)"],
                    ["Project completion", "delivery announcement by non-client closes open tasks, flagged for review", "HG chat: progress 22% -> 100%, health 46 CRITICAL -> 79 AT_RISK"],
                    ["Search", "hybrid BM25 + multilingual-e5 or hashing embedder, RRF", "benchmarks on synthetic and unseen chats (docs/PHASE7)"],
                    ["Summaries", "evidence-linked facts, templated text", "unit tests; no human quality rating yet"]],
                   [92, 215, CW - 307]))
    c.append(Spacer(1, 3))
    c.append(P("Labels used so far are model-made (single reviewer) and one real project: treat all accuracy figures as indicative, not as a claim of production accuracy. Human labelling of several chats is the largest remaining quality lever.", "small"))
    return [fit(c)]


# ============================================================ page 8: assistant + rag
def asst_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    bw = (w - 24 - 3 * 10) / 4
    xs = [12 + i * (bw + 10) for i in range(4)]
    ya, yb, yc = h - 62, h - 134, h - 204
    A = [("User message", "text; voice via WAV endpoint", C_USER, BRAND_D), ("Agent loop", "context + app state, max 6 steps", C_AS, BRAND_D),
         ("LLM (llama.cpp)", "proposes text or tool calls", C_AS, BRAND_D), ("Policy engine (code)", "schema, ids seen, rate, tier, taint", C_SEC, colors.HexColor("#b33"))]
    for i, (t, d, f, st) in enumerate(A):
        box(c, xs[i], ya, bw, 46, t + "\n" + d, f, st, size=7.2)
        if i:
            arrow(c, xs[i - 1] + bw, ya + 23, xs[i], ya + 23)
    B = [("T0 read / T1 write", "run now; T1 is read back afterwards", C_OK), ("T2 sensitive, or after untrusted text", "pending: UI Confirm button only", C_AI),
         ("T3 refused", "delete, roles, payments, export, external send", C_SEC), ("Executor", "backend API with the USER's token (403/404 apply)", C_BE)]
    for i, (t, d, f) in enumerate(B):
        box(c, xs[i], yb, bw, 50, t + "\n" + d, f, BRAND_D, size=7.0)
        arrow(c, xs[3] + bw / 2, ya, xs[i] + bw / 2, yb + 50)
    C3 = [("Verifier", "read back; verified, unverified, mismatch or failed", C_OK), ("Reply", "model text + system-written report + sources + citations", C_FE),
          ("Audit + feedback", "who, tool, decision, result (no message text)", C_EXT), ("Document RAG", "search_documents tool, see below", C_AS)]
    for i, (t, d, f) in enumerate(C3):
        box(c, xs[i], yc, bw, 46, t + "\n" + d, f, BRAND_D, size=7.0)
        if i < 3:
            arrow(c, xs[i] + bw, yc + 23, xs[i + 1], yc + 23)
    arrow(c, xs[3] + bw / 2, yb, xs[0] + bw / 2, yc + 46)
    region(c, 10, 12, w - 20, 80, "DOCUMENT RAG PIPELINE")
    names = ["Ingest PDF/MD/TXT/HTML: sections, parent/child chunks", "BM25 + dense + metadata, RRF; scope = access", "Rerank; abstain below threshold", "LLM sees passages as untrusted data", "Citation check; references built from metadata"]
    bw2 = (w - 36 - 4 * 6) / 5
    for i, n in enumerate(names):
        box(c, 18 + i * (bw2 + 6), 20, bw2, 46, n, C_AS if i != 4 else C_OK, BRAND_D, size=6.4, bold_first=False)
        if i:
            arrow(c, 18 + i * (bw2 + 6) - 6, 43, 18 + i * (bw2 + 6), 43)


def page8():
    c = title("7. Assistant, RAG and voice", "The assistant is an operating layer over the application, not a chatbot with its own authority. The model never touches the database or holds permissions.")
    c.append(Draw(312, asst_diagram))
    c.append(P("Tool registry (23 tools)", "h2"))
    c.append(table([["Tier", "Tools", "Rule"],
                    ["T0 read", "list_projects, get_project_overview, get_progress, get_health, get_summary, list_tasks, get_task_history, list_client_pending, list_risks, list_users, search_documents, navigate, set_dashboard_filter", "ids must come from an earlier lookup in the session"],
                    ["T1 reversible write", "create_project, create_task, update_task (not status), generate_report, reanalyze_project, mark_notifications_read", "typed args; rate limit 10/min; read-back verification; after untrusted text -> confirmation"],
                    ["T2 sensitive", "complete_task, cancel_task, add_project_member", "UI Confirm button only; hash of tool+args, 5 min, single use, same user"],
                    ["T3 refused", "delete_task, delete_project, remove_project_member, create_user, change_user_role, make_payment, send_external_message, export_all_data", "pointed to the admin UI"]],
                   [66, 296, CW - 362]))
    c.append(Spacer(1, 4))
    c.append(P("Voice and models", "h2"))
    c += bullets(["<b>Voice:</b> energy VAD, end-pointing and barge-in state machine and a WAV endpoint are built and tested with synthetic audio; <b>no ASR/TTS model is installed, so accuracy and latency are unmeasured</b>. Spoken input gets no extra trust and cannot confirm an action.",
                  "<b>LLM:</b> Qwen2.5-7B-Instruct Q4_K_M via llama.cpp, CPU only (about 1-4 tokens/s on this laptop). A 37-case state-diff bake-off (English + Hinglish) is running; sandbox safety suites passed against a worst-case obedient stub (0 state changes, 0 T3 executed). Real-model quality is not yet known.",
                  "<b>Untrusted data:</b> chat text, task titles and documents are wrapped as data with a 'never follow instructions' note; they can never confirm or originate a sensitive action."])
    return [fit(c)]


# ============================================================ page 9: security
def auth_diagram(c, w, h):
    region(c, 4, 6, w - 8, h - 12, "")
    steps = [("Request", "bearer token"), ("authenticate", "JWT valid? user active?"), ("requirePermission", "role allows this action?"), ("projectAccess", "member of the project? edit?"),
             ("validate", "zod schema, sizes"), ("handler", "business rule"), ("audit + sanitised response", "no stack traces")]
    bw = (w - 20 - 6 * 7) / 7
    for i, (t, d) in enumerate(steps):
        x = 10 + i * (bw + 7)
        box(c, x, 30, bw, 46, t + "\n" + d, C_SEC if i in (1, 2, 3) else C_BE, BRAND_D, size=6.6)
        if i:
            arrow(c, x - 7, 53, x, 53)
    c.setFillColor(MUTED); c.setFont("Helvetica", 6.8)
    c.drawString(12, 21, "401 no or expired token  |  403 role lacks permission  |  404 project not visible (existence not leaked)  |  422 invalid input")
    c.drawString(12, 11, "The assistant takes this same path with the signed-in user's own token.")


def page9():
    c = title("8. Security, privacy and reliability", "Threat model for a single-company deployment. Each control is implemented and has tests unless marked.")
    c.append(table([["Threat", "Control", "State"],
                    ["Unauthenticated / forged access", "JWT 15 min, rotating single-use refresh tokens, bcrypt 12; every router authenticates", "tested"],
                    ["Privilege escalation, cross-project reads", "role matrix + project membership; 404 for non-members; SSE checks membership per event", "tested"],
                    ["Forged or replayed webhook", "HMAC-SHA256 on the raw body (constant-time compare); idempotent ids; unmapped conversations dropped", "tested; no timestamp window"],
                    ["Malicious files (zip bomb, half-synced, junk)", "size caps, decompression cap, stability check, WhatsApp-header check, rejected/ + reason", "tested"],
                    ["Prompt injection through chats/documents", "untrusted-data wrapping, taint-then-confirm, T3 refusal, schema + id provenance, user-token execution", "tested vs worst-case stub; real model pending"],
                    ["Secrets / credential leakage", "env-only secrets; AES-256-GCM for uploads and phones; logs without bodies/queries; anonymiser masks pasted passwords for labelling", "tested; raw text not secret-scanned"],
                    ["Injection / mass assignment", "zod validation, Prisma parameterised queries", "tested"],
                    ["Denial of service", "edge rate limits, body caps, per-user SSE and assistant limits", "nginx config not validated here (no nginx)"],
                    ["Over-retention of personal data", "per-project retention 30-3650 days, purge with derived-data rebuild, erasure (needs project:delete + exact name)", "tested"],
                    ["Accountability", "AuditLog (who/what/when) in the backend; assistant audit of decisions and results", "implemented"]],
                   [118, 300, CW - 418]))
    c.append(Spacer(1, 4))
    c.append(P("Authorization path of every request", "h2"))
    c.append(Draw(100, auth_diagram))
    c.append(Spacer(1, 3))
    c.append(P("Reliability and failure behaviour", "h2"))
    c.append(table([["Failure", "What happens"],
                    ["AI engine down", "uploads still stored; analysis job retried by the queue; /api/ready reports <i>degraded</i>; stored dashboards keep working"],
                    ["Redis down (bullmq mode)", "events fall back to the local process; queue readiness fails (/api/ready 503); inline mode needs no Redis"],
                    ["Backend restart during analysis", "job marked failed with a sanitised message; re-run with reanalyze (inline mode); BullMQ retries when Redis is used"],
                    ["Live stream cannot connect", "dashboard shows Polling and refetches every 30 s"],
                    ["LLM unreachable", "assistant returns 503 with a clear message; nothing is executed"],
                    ["Action cannot be verified", "reply says so explicitly (unverified / mismatch / failed); it never says Done without evidence"]],
                   [118, CW - 118]))
    c.append(Spacer(1, 4))
    c.append(P("Residual risks that design cannot remove: a hijacked model can still do what the signed-in user may do within tiers and rate limits; rule-based extractors can misread chats (outputs are advisory and carry evidence and review flags); "
               "the HG chat contains a website password and an SMS API key that must be rotated.", "small"))
    return [fit(c)]


# ============================================================ page 10: stack, ops, quality, roadmap
def page10():
    c = title("9. Technology, operations, quality and roadmap", "How it is built, run and checked, and what is still open.")
    c.append(table([["Area", "Choices"],
                    ["Languages / frameworks", "TypeScript (Node, Express, Prisma, React, Vite, Tailwind), Python (FastAPI, scikit-learn, NumPy, NetworkX, reportlab, pydantic, httpx)"],
                    ["Data / messaging", "PostgreSQL 16 + pgvector, Redis 7 + BullMQ (RabbitMQ and Kafka deliberately not used, ADR-001), SSE for live updates"],
                    ["Models", "Qwen2.5-7B-Instruct Q4_K_M (llama.cpp), multilingual-e5 small or hashing embedder, lexical reranker (cross-encoder supported, untested), TF-IDF classifier (not deployed)"],
                    ["Dev stack", "scripts/dev/dev-up.ps1 starts embedded Postgres :15433, AI engine :8000, backend :4000, assistant :8100, LLM :8081, frontend :5199 as detached processes; logs in private-data/logs"],
                    ["Production", "docker-compose: postgres, redis, backend, worker, edge nginx (TLS), internal network, backups with restore test, secrets generator; assistant and LLM services not yet in compose"],
                    ["Health", "/api/health, /api/ready (db, queue, ai), admin /api/queue/status, /api/ai/status, /api/auto-import/status; assistant /health"]],
                   [96, CW - 96]))
    c.append(Spacer(1, 4))
    c.append(P("Quality gates", "h2"))
    c.append(table([["Suite", "Result", "Covers"],
                    ["AI engine (pytest)", "175 pass", "parser, extractors, Q&amp;A, tone, summaries, completion rule, analytics, search, reports, registry, annotation"],
                    ["Backend (vitest)", "83 pass, 11 files", "auth, e2e, failures, SSE, webhook, retention/erasure, watched folder, insights, status"],
                    ["Assistant (pytest)", "57 pass", "policy, confirmations, injection, RAG, API, evaluation harness, voice"],
                    ["Frontend", "12 pass + typecheck", "helpers, SSE parser; UI checked manually in a browser"],
                    ["Real-backend smoke", "pass", "create/verify/confirm/refuse against the live API"],
                    ["LLM bake-off (37 cases)", "running", "tool selection, arguments, state-diff success, safety, latency"]],
                   [110, 90, CW - 200]))
    c.append(Spacer(1, 4))
    c.append(P("Day-to-day operation", "h2"))
    c += bullets(["<b>Start / stop:</b> scripts/dev/dev-up.ps1 and dev-down.ps1 (dev); docker compose up -d (production). <b>Check:</b> /api/ready and the Settings page (auto-import status).",
                  "<b>Add data:</b> export on the phone to the Drive folder named like the project; or upload in the panel; or map a Cloud API conversation. <b>Retention:</b> set per project; sweep runs every 6 h.",
                  "<b>Keep safe:</b> backup nightly, test restore, rotate secrets that ever appeared in a chat (the HG website password and SMS API key), never expose the dev database or the weak dev password."])
    c.append(Spacer(1, 3))
    c.append(P("Roadmap (decisions already taken: BullMQ stays, single company, self-hosted models)", "h2"))
    c.append(table([["Next", "Why / dependency"],
                    ["1. Finish LLM bake-off; choose or reject Qwen2.5-7B for tool use", "needs hours of CPU time; may require a smaller/faster model or a GPU"],
                    ["2. Human-label several real chats (target 1,500+ messages, double annotation, kappa >= 0.7)", "largest quality lever; unlocks honest REAL_TEST and a trained classifier"],
                    ["3. Install Google Drive for desktop and point AUTO_IMPORT_DIR at the synced folder", "needed for the personal-WhatsApp automation; not testable here yet"],
                    ["4. ASR/TTS models with your approval, WER on your recordings, mic UI", "voice is unmeasured today"],
                    ["5. Add assistant + LLM to docker-compose; validate nginx config; load and failure tests", "production readiness"],
                    ["6. Webhook against Meta (only if an Official Business Account exists)", "business-created groups and 1:1 only"],
                    ["7. Streaming assistant replies, history, markdown; connections screen for webhook sources", "UX completeness"]],
                   [270, CW - 270]))
    return [fit(c)]


def build():
    doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M + 4, bottomMargin=M - 2,
                          title="WhatsApp Project Intelligence Platform - End-to-end architecture", author="Project Intelligence team", subject="Architecture")
    frame = Frame(M, M - 2, CW, H - 2 * M - 2, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="f")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=page_deco)])
    story = []
    for i, page in enumerate((page1, page2, page3, page4, page5, page6, page7, page8, page9, page10)):
        story += page()
        if i < 9:
            story.append(PageBreak())
    doc.build(story)
    print("wrote", OUT)


if __name__ == "__main__":
    build()
