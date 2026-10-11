"""Builds docx/00-overview/Architecture_OnePage.pdf: a one-page (A4 landscape) architecture diagram of the current system.
   ai-engine/.venv/Scripts/python.exe docx/00-overview/build_architecture_onepage.py
Facts come from the repository (backend/src, ai-engine/app, assistant/, docker-compose.yml, docx/); update them here when the system changes."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

OUT = Path(__file__).with_name("Architecture_OnePage.pdf")
W, H = landscape(A4)
INK, MUTED, LINE, BG = colors.HexColor("#1b2033"), colors.HexColor("#5d6480"), colors.HexColor("#cfd4e2"), colors.HexColor("#f6f7fb")
GREEN, BLUE, VIOLET, AMBER, TEAL, SLATE, RED = (colors.HexColor(c) for c in ("#00a884", "#4a5be0", "#8b5cf6", "#d97706", "#0e9f9a", "#475569", "#dc2626"))


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    out, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def box(c, x, y, w, h, title, lines, color, *, size=6.9, sub=None):
    """Rounded card with a coloured title bar; lines starting with '-' are bullets, '#' are small sub-headings."""
    c.setFillColor(colors.white); c.setStrokeColor(color); c.setLineWidth(1)
    c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    c.setFillColor(color); c.roundRect(x, y + h - 17, w, 17, 6, stroke=0, fill=1); c.rect(x, y + h - 17, w, 8, stroke=0, fill=1)
    c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 8.3); c.drawString(x + 7, y + h - 12, title)
    ty = y + h - 27
    if sub:
        c.setFillColor(MUTED); c.setFont("Helvetica-Oblique", 6.5)
        for ln in wrap(sub, "Helvetica-Oblique", 6.5, w - 14):
            c.drawString(x + 7, ty, ln); ty -= 8.3
        ty -= 2
    for raw in lines:
        if raw.startswith("#"):
            ty -= 2
            c.setFillColor(color); c.setFont("Helvetica-Bold", 6.9); c.drawString(x + 7, ty, raw[1:].strip()); ty -= 8.6
            continue
        bullet = raw.startswith("-")
        text = raw[1:].strip() if bullet else raw
        indent = 13 if bullet else 7
        c.setFillColor(INK); c.setFont("Helvetica", size)
        for i, ln in enumerate(wrap(text, "Helvetica", size, w - indent - 7)):
            if bullet and i == 0:
                c.setFillColor(color); c.circle(x + 9, ty + 2.2, 1.2, stroke=0, fill=1); c.setFillColor(INK)
            c.drawString(x + indent, ty, ln); ty -= size + 1.7
    return ty


def arrow(c, x1, y1, x2, y2, color=SLATE, label=None, num=None, dashed=False, lx=None, ly=None):
    c.setStrokeColor(color); c.setFillColor(color); c.setLineWidth(1.1)
    c.setDash(3, 2) if dashed else c.setDash()
    c.line(x1, y1, x2, y2); c.setDash()
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    p = c.beginPath(); p.moveTo(x2, y2)
    p.lineTo(x2 - 6 * math.cos(a - 0.4), y2 - 6 * math.sin(a - 0.4)); p.lineTo(x2 - 6 * math.cos(a + 0.4), y2 - 6 * math.sin(a + 0.4)); p.close()
    c.drawPath(p, stroke=0, fill=1)
    if label or num:
        mx, my = (lx if lx is not None else (x1 + x2) / 2), (ly if ly is not None else (y1 + y2) / 2 + 3)
        if num:
            c.setFillColor(color); c.circle(mx - (stringWidth(label or "", "Helvetica", 6.2) / 2) - 7, my + 2, 5, stroke=0, fill=1)
            c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 6.3); c.drawCentredString(mx - (stringWidth(label or "", "Helvetica", 6.2) / 2) - 7, my - 0.2, str(num))
        if label:
            c.setFillColor(INK); c.setFont("Helvetica", 6.2); c.drawCentredString(mx, my, label)


def zone(c, x, y, w, h, label, color):
    c.setStrokeColor(color); c.setLineWidth(0.8); c.setDash(4, 3)
    c.roundRect(x, y, w, h, 9, stroke=1, fill=0); c.setDash()
    c.setFillColor(color); c.setFont("Helvetica-Bold", 6.6); c.drawString(x + 8, y + h - 10, label)


def build() -> None:
    c = canvas.Canvas(str(OUT), pagesize=(W, H))
    c.setTitle("Project Intelligence: system architecture"); c.setAuthor("Project Intelligence")
    c.setFillColor(BG); c.rect(0, 0, W, H, stroke=0, fill=1)

    # ---- header
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 16); c.drawString(24, H - 34, "Project Intelligence: system architecture")
    c.setFillColor(MUTED); c.setFont("Helvetica", 8.2)
    c.drawString(24, H - 47, "Team chat that turns project conversations into tasks, progress, health and risks. Self-hosted: no external AI, no WhatsApp or Meta API.")
    c.setFont("Helvetica", 7); c.drawRightString(W - 24, H - 34, "October 2026")
    c.drawRightString(W - 24, H - 45, "Facts: backend/src, ai-engine/app, assistant/, docker-compose.yml")

    top, bottom = H - 62, 132                 # main diagram band
    # ---- zones
    zone(c, 18, bottom - 6, 120, top - bottom + 12, "PEOPLE", SLATE)
    zone(c, 146, bottom - 6, 160, top - bottom + 12, "EDGE NETWORK  (browser-facing)", BLUE)
    zone(c, 314, bottom - 6, 510, top - bottom + 12, "INTERNAL NETWORK  (no internet access, except the backend's SMTP egress)", TEAL)

    # ---- people
    py = top - 26
    for name, desc, col in (("Admin / Project manager", "creates projects and groups, invites people, reviews tasks", BLUE),
                            ("Team member", "chats in project groups and DMs, updates task status", GREEN),
                            ("Client", "joins by e-mail invitation; sees only their project / group", AMBER)):
        c.setFillColor(colors.white); c.setStrokeColor(col); c.roundRect(26, py - 46, 104, 46, 5, stroke=1, fill=1)
        c.setFillColor(col); c.circle(37, py - 12, 5, stroke=0, fill=1)
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 7); c.drawString(46, py - 14, name if len(name) < 20 else "Admin / PM")
        c.setFont("Helvetica", 6.2); c.setFillColor(MUTED)
        for i, ln in enumerate(wrap(desc, "Helvetica", 6.2, 94)):
            c.drawString(31, py - 25 - i * 7.4, ln)
        py -= 56
    c.setFillColor(MUTED); c.setFont("Helvetica-Oblique", 6.3)
    for i, ln in enumerate(wrap("All use a web browser. Roles and per-project membership are checked by the API on every call.", "Helvetica-Oblique", 6.3, 100)):
        c.drawString(27, py - 4 - i * 7.6, ln)

    # ---- frontend + nginx
    box(c, 154, top - 34 - 196, 144, 214, "Web app  (React + Vite)", [
        "#Team chat",
        "- groups, DMs, replies, emoji, search",
        "- read ticks, typing, unread divider",
        "- add people / invite by e-mail",
        "#Insight",
        "- Executive and project dashboards with reliability labels",
        "- Chat analysis + message explorer",
        "- Tasks, Risks, Client pending, Timeline, Reports, Insights",
        "#Assistant panel",
        "- chat with the assistant; Confirm / Cancel for sensitive actions",
    ], BLUE)
    box(c, 154, bottom + 4, 144, 92, "nginx edge", [
        "- TLS termination, security headers",
        "- rate limits: login, API",
        "- SSE passthrough (no buffering)",
        "- serves the built web app",
    ], SLATE)

    # ---- backend
    bx, bw = 322, 176
    box(c, bx, bottom + 4, bw, top - bottom - 30, "Backend API  (Node, Express, Prisma)", [
        "#Access",
        "- JWT + refresh tokens; role matrix; project isolation (404 to outsiders)",
        "#In-app chat",
        "- rooms: project group / group / DM; messages, replies, read state, typing",
        "- project-group messages mirrored into the project conversation",
        "- e-mail invitations: single-use token, only its SHA-256 stored, 7-day expiry",
        "#Analysis orchestration",
        "- debounce ~30 s after the chat goes quiet, then ONE job (BullMQ or inline)",
        "- persists tasks, progress, health, risks; human edits never overwritten",
        "#Live events (SSE)",
        "- ids only, never message text; chat events go to room members only",
        "#Also",
        "- reports (PDF/XLSX/CSV), notifications, audit log",
        "- retention / erasure per project; AES-256-GCM field encryption",
    ], TEAL, size=6.6)

    # ---- AI engine + assistant + LLM
    ax, aw = 516, 168
    box(c, ax, top - 34 - 160, aw, 178, "AI engine  (Python, FastAPI)", [
        "- task extraction with title-quality gate, completion rule",
        "- people & roles, client pending, requirement changes, conflicts",
        "- risks, progress, health score, sentiment, Q&A, summaries",
        "- every result carries confidence + evidence message ids",
        "- hybrid search index (BM25 + embeddings) per project",
        "- rule based and local models only: no external AI",
    ], VIOLET, size=6.6)
    box(c, ax, bottom + 4, aw, 150, "Assistant service  (Python)", [
        "- the LLM proposes; a deterministic policy decides (read / write / confirm / refuse)",
        "- tools call the backend with the USER's token, then read the result back",
        "- documents: retrieval with citations, abstains when unsure",
        "#Local LLM",
        "- Qwen2.5-7B-Instruct (Q4) on llama.cpp, CPU, fully offline",
    ], AMBER, size=6.6)

    # ---- data
    dx, dw = 700, 116
    box(c, dx, top - 34 - 170, dw, 188, "PostgreSQL", [
        "- users, projects, members",
        "- ChatRoom, RoomMember, RoomMessage, ChatInvite",
        "- ChatMessage (analysed conversation)",
        "- tasks, risks, progress, health, insights",
        "- reports, notifications, audit log",
    ], SLATE, size=6.6)
    box(c, dx, bottom + 70, dw, 84, "Redis", [
        "- BullMQ analysis queue",
        "- pub/sub for live events between API and workers",
    ], RED, size=6.6)
    box(c, dx, bottom + 4, dw, 58, "Model files (volume)", [
        "- LLM weights, embeddings",
    ], MUTED, size=6.6)

    # ---- arrows (main flows)
    arrow(c, 130, top - 50, 154, top - 50, BLUE)
    arrow(c, 130, top - 106, 154, top - 106, GREEN)
    arrow(c, 130, top - 162, 154, top - 162, AMBER)
    arrow(c, 226, top - 230 - 4, 226, bottom + 96, SLATE)                                      # web app -> nginx
    arrow(c, 298, bottom + 50, 322, bottom + 50, SLATE, num=1, lx=310, ly=bottom + 56)          # nginx -> backend
    arrow(c, 322, top - 70, 298, top - 70, TEAL, dashed=True)                                   # SSE back to browser
    c.setFillColor(TEAL); c.setFont("Helvetica-Oblique", 5.8); c.drawCentredString(310, top - 64, "SSE")
    arrow(c, bx + bw, top - 92, ax, top - 92, VIOLET, num=3, lx=bx + bw + 9, ly=top - 86)       # backend -> AI engine
    arrow(c, ax, top - 120, bx + bw, top - 120, VIOLET, dashed=True)                            # results back
    arrow(c, ax, bottom + 90, bx + bw, bottom + 90, AMBER, num=5, lx=bx + bw + 9, ly=bottom + 96)   # assistant -> backend (user token)
    # backend -> Postgres / Redis: routed through the gap between the AI engine and the assistant
    gap_hi, gap_lo = top - 34 - 160 - 14, bottom + 154 + 14
    c.setLineWidth(1.1); c.setStrokeColor(SLATE)
    c.line(bx + bw, gap_hi, dx + 30, gap_hi); arrow(c, dx + 30, gap_hi, dx + 30, top - 34 - 170, SLATE)
    c.setStrokeColor(RED)
    c.line(bx + bw, gap_lo, dx + 80, gap_lo); arrow(c, dx + 80, gap_lo, dx + 80, bottom + 154, RED)
    c.setFillColor(MUTED); c.setFont("Helvetica-Oblique", 5.8)
    c.drawString(ax + 6, gap_hi + 3, "SQL via Prisma"); c.drawString(ax + 6, gap_lo + 3, "jobs + live-event pub/sub")
    arrow(c, ax + aw, bottom + 30, dx, bottom + 30, MUTED, dashed=True)                          # assistant -> model files

    # SMTP (outside, bottom of backend)
    sx, sy = 322, 30
    c.setFillColor(colors.white); c.setStrokeColor(GREEN); c.roundRect(sx, sy + 46, 176, 40, 5, stroke=1, fill=1)
    c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 7.4); c.drawString(sx + 8, sy + 74, "SMTP server (e.g. Gmail app password)")
    c.setFillColor(INK); c.setFont("Helvetica", 6.4)
    c.drawString(sx + 8, sy + 63, "Only outbound connection: invitation and")
    c.drawString(sx + 8, sy + 55, "\"added to group\" e-mails (egress network)")
    arrow(c, sx + 88, bottom + 4, sx + 88, sy + 86, GREEN, num=6, lx=sx + 108, ly=bottom - 14)

    # ---- flows legend
    fx, fy = 516, 30
    c.setFillColor(colors.white); c.setStrokeColor(LINE); c.roundRect(fx, fy, 300, 86, 5, stroke=1, fill=1)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 7.6); c.drawString(fx + 8, fy + 74, "Main flows")
    flows = [
        (1, "A message is sent in Team chat; the API stores it (and mirrors it for project groups)."),
        (2, "Members get a live event (ids only) and refetch; ticks turn blue when everyone has read."),
        (3, "After ~30 s of quiet one analysis job runs; the AI engine returns tasks, risks, progress, health."),
        (4, "Dashboards show the numbers with evidence and a reliability label (HIGH / MEDIUM / LOW)."),
        (5, "The assistant answers and acts through the API with the user's own permissions."),
        (6, "Invitations e-mail a single-use link; accepting creates a client account in that group."),
    ]
    yy = fy + 63
    for n, t in flows:
        c.setFillColor(SLATE); c.circle(fx + 12, yy + 2, 4.3, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 5.8); c.drawCentredString(fx + 12, yy + 0.2, str(n))
        c.setFillColor(INK); c.setFont("Helvetica", 6.3); c.drawString(fx + 21, yy, t)
        yy -= 9.6

    # ---- guarantees strip (bottom left)
    gx, gy = 18, 30
    c.setFillColor(colors.white); c.setStrokeColor(LINE); c.roundRect(gx, gy, 288, 86, 5, stroke=1, fill=1)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 7.6); c.drawString(gx + 8, gy + 74, "Guarantees")
    rules = [
        "Direct messages are private: never analysed, not readable even by admins.",
        "Every AI result links back to the exact source messages (evidence).",
        "Human corrections survive re-analysis; thin evidence is labelled LOW confidence.",
        "Database, queue and AI engine have no internet access; no external AI or WhatsApp.",
        "Secrets only in the environment; tokens hashed; sensitive fields encrypted at rest.",
        "Retention and erasure per project also remove derived data and chat copies.",
    ]
    yy = gy + 63
    for t in rules:
        c.setFillColor(GREEN); c.circle(gx + 11, yy + 2.2, 1.6, stroke=0, fill=1)
        c.setFillColor(INK); c.setFont("Helvetica", 6.3); c.drawString(gx + 18, yy, t)
        yy -= 9.6

    # flow numbers 2 and 4 placed on the SSE / dashboard paths
    for n, (x, y) in ((2, (310, top - 82)), (4, (226 + 9, top - 230 + 6))):
        c.setFillColor(SLATE); c.circle(x, y, 5, stroke=0, fill=1)
        c.setFillColor(colors.white); c.setFont("Helvetica-Bold", 6.3); c.drawCentredString(x, y - 2.2, str(n))

    c.setFillColor(MUTED); c.setFont("Helvetica", 6)
    c.drawRightString(W - 24, 16, "Production: docker compose (postgres, redis, ai-engine, backend, worker, assistant, nginx edge). Development: scripts/dev/dev-up.ps1.")
    c.showPage(); c.save()


if __name__ == "__main__":
    build()
    print(OUT)
