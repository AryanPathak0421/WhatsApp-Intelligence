"""Synthetic WhatsApp project-chat generator with gold labels.

For TRAINING / AUGMENTATION ONLY. Synthetic data must never be used as the
test set (it inflates scores). Every record carries source="synthetic".

    python -m app.datasets.synthetic --projects 20 --out data/synthetic --seed 7
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

DEVS = [("Amit", "BACKEND_DEVELOPER"), ("Rohan", "FRONTEND_DEVELOPER"),
        ("Priya", "FULLSTACK_DEVELOPER"), ("Karan", "QA"), ("Sneha", "DESIGNER")]
PM = ("Rahul", "PROJECT_MANAGER")
SALES = ("Sales - Neha", "SALES")
CLIENTS = [("Mr. Sharma", "CLIENT"), ("Anjali (Client)", "CLIENT_REPRESENTATIVE")]

TASKS = [  # (english title, module, weight, [hinglish title variants])
    ("Razorpay integration", "Payments", 5, ["Razorpay integration", "payment gateway"]),
    ("login screen", "Authentication", 2, ["login screen", "login page"]),
    ("admin dashboard", "Admin Panel", 5, ["admin dashboard", "admin panel"]),
    ("product listing API", "Backend", 3, ["product listing API", "product API"]),
    ("cart module", "Frontend", 3, ["cart module", "cart page"]),
    ("push notifications", "Notifications", 3, ["push notifications", "notification system"]),
    ("homepage design", "Design", 2, ["homepage design", "home page UI"]),
    ("order tracking page", "Frontend", 3, ["order tracking page", "tracking page"]),
    ("database migration", "Database", 3, ["database migration", "DB migration"]),
    ("invoice PDF export", "Backend", 2, ["invoice PDF export", "invoice PDF"]),
    ("search filters", "Frontend", 2, ["search filters", "filter option"]),
    ("production deployment", "Deployment", 5, ["production deployment", "live deployment"]),
]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "tomorrow", "today EOD"]
DAYS_HI = ["kal tak", "Friday tak", "aaj shaam tak", "Monday tak", "parso tak"]

# Templates: {t}=task, {p}=person, {d}=deadline. status = label for the *task*.
T = {
 "en": {
  "TASK": ["{p}, please work on {t} by {d}.", "{p} can you take up {t}? Need it by {d}.", "Assigning {t} to {p}. Deadline {d}."],
  "TASK_IN_PROGRESS": ["Working on {t} now.", "{t} is in progress.", "Currently developing {t}, will update soon."],
  "TASK_COMPLETED": ["{t} completed.", "Done with {t}, pushed to staging.", "{t} is implemented and working now."],
  "TASK_BLOCKED": ["Blocked on {t}, waiting for the API credentials.", "Can't proceed with {t}, dependency not ready."],
  "TASK_PENDING": ["{t} is still pending.", "Haven't started {t} yet, will pick it up next."],
  "TESTING": ["{t} tested successfully.", "QA started testing {t}.", "Found everything working in {t} after testing."],
  "DEPLOYMENT": ["{t} deployed to production.", "Deployed {t} on the live server.", "{t} is live now."],
  "QUESTION": ["Any update on {t}?", "What is the status of {t}?", "{p}, is {t} ready?"],
  "CLIENT_PENDING": ["Waiting for client confirmation on {t}.", "Client has not shared credentials for {t}.", "{t} approval is pending from the client."],
  "CLIENT_APPROVAL": ["Client has approved {t}.", "Looks good, approved for {t}.", "Approved. Please proceed with {t}."],
  "CLIENT_FEEDBACK": ["Client feedback on {t}: the layout needs changes.", "Please change the colours in {t}, we don't like it."],
  "BUG": ["Found a bug in {t}, it crashes on submit.", "{t} is not working on mobile.", "Bug: {t} shows wrong total."],
  "BUG_FIXED": ["Fixed the bug in {t}.", "{t} issue resolved, please recheck."],
  "REQUIREMENT": ["Requirement: {t} should support UPI and cards.", "Client wants {t} to work on mobile too."],
  "REQUIREMENT_CHANGE": ["Client wants Razorpay instead of Stripe for {t}.", "Scope change: {t} must now include a new report."],
  "DEADLINE": ["{t} deadline is {d}.", "We need {t} ready by {d}."],
  "RISK": ["Risk: {t} may slip the release date.", "If {t} is delayed we will miss the launch."],
  "BLOCKER": ["Major blocker for {t}: the server access is missing."],
  "PAYMENT": ["Client payment for milestone 2 is still pending.", "Invoice for {t} sent, payment awaited."],
  "SALES": ["Followed up with client regarding {t} scope.", "Sent updated proposal for {t}."],
  "MEETING": ["Meeting with client at 4 PM to discuss {t}.", "Call scheduled {d} for {t} review."],
  "DECISION": ["Decision: we will use Razorpay for {t}.", "Finalised: {t} will go live on Friday."],
  "DISCUSSION": ["I think we should rethink the approach for {t}.", "What if we split {t} into two parts?"],
  "GENERAL": ["Good morning team", "ok", "thanks 👍", "sure", "Happy Diwali everyone 🎉", "noted"],
 },
 "hi": {  # Hinglish (romanised) + a few Devanagari
  "TASK": ["{p}, {t} {d} kar dena.", "{p} please {t} par kaam shuru karo, {d}.", "{t} {p} ko assign kiya hai, {d}."],
  "TASK_IN_PROGRESS": ["{t} par kaam chal raha hai.", "{t} abhi in progress hai.", "Abhi {t} bana raha hu."],
  "TASK_COMPLETED": ["{t} complete ho gaya.", "{t} kr diya, staging pe push kiya.", "{t} ho gaya hai, ab chal raha hai."],
  "TASK_BLOCKED": ["{t} ready hai but credentials nahi mile.", "{t} aage nahi badh sakta, API available nahi hai."],
  "TASK_PENDING": ["{t} abhi pending hai.", "{t} abhi start nahi kiya."],
  "TESTING": ["{t} ka testing ho gaya, sab theek hai.", "{t} test kar liya, working hai."],
  "DEPLOYMENT": ["{t} production pe deploy ho gaya.", "{t} live ho gaya hai."],
  "QUESTION": ["{t} ka kya update hai?", "{p}, {t} ready hai kya?"],
  "CLIENT_PENDING": ["Client ka response abhi pending hai for {t}.", "Client ne {t} ke credentials nahi diye.", "{t} ka approval client se pending hai."],
  "CLIENT_APPROVAL": ["Client ne {t} approve kar diya.", "Client ko {t} pasand aaya, approved."],
  "CLIENT_FEEDBACK": ["Client ko {t} me changes chahiye.", "{t} ka design client ko pasand nahi aaya."],
  "BUG": ["{t} me bug mila hai.", "{t} mobile pe kaam nahi kar raha.", "{t} me crash aa raha hai."],
  "BUG_FIXED": ["{t} ka bug fix kar diya.", "{t} ka issue solve ho gaya."],
  "REQUIREMENT": ["{t} me UPI support chahiye.", "Client chahta hai ki {t} mobile pe bhi chale."],
  "REQUIREMENT_CHANGE": ["Client ko Stripe ki jagah Razorpay chahiye for {t}.", "{t} me naya requirement aa gaya hai."],
  "DEADLINE": ["{t} ka deadline {d} hai.", "{t} {d} ready chahiye."],
  "RISK": ["{t} late ho sakta hai, release miss ho jayegi.", "Risk hai ki {t} time pe nahi hoga."],
  "BLOCKER": ["{t} me bada blocker hai, server access nahi mila."],
  "PAYMENT": ["Client ka payment abhi pending hai.", "{t} ka invoice bhej diya, payment ka wait hai."],
  "SALES": ["Client se {t} ke scope par follow-up kiya.", "{t} ka proposal bhej diya hai."],
  "MEETING": ["Client ke saath 4 baje meeting hai {t} ke baare me.", "{d} call rakhi hai {t} ke liye."],
  "DECISION": ["Decision hua: {t} ke liye Razorpay use karenge.", "Final: {t} Friday ko live jayega."],
  "DISCUSSION": ["Mujhe lagta hai {t} ka approach change karna chahiye.", "{t} ko do parts me kar dete hain?"],
  "GENERAL": ["Good morning sab ko", "ok", "thik hai 👍", "haan ji", "dhanyavaad", "ठीक है"],
 },
}
DEVANAGARI = {"TASK_COMPLETED": ["{t} पूरा हो गया।"], "CLIENT_PENDING": ["क्लाइंट का जवाब अभी pending है।"],
              "TASK_IN_PROGRESS": ["{t} पर काम चल रहा है।"]}

ROLE_FOR = {  # who typically authors a category
    "CLIENT_PENDING": ["pm", "sales", "dev"], "CLIENT_APPROVAL": ["client"], "CLIENT_FEEDBACK": ["client"],
    "REQUIREMENT": ["client", "pm"], "REQUIREMENT_CHANGE": ["client", "pm"], "PAYMENT": ["sales", "pm"],
    "SALES": ["sales"], "TASK": ["pm"], "DEADLINE": ["pm", "client"], "MEETING": ["pm", "sales"],
    "DECISION": ["pm", "client"], "BUG": ["qa", "client"], "TESTING": ["qa"], "RISK": ["pm", "dev"],
    "QUESTION": ["pm", "client"], "GENERAL": ["any"], "DISCUSSION": ["dev", "pm"],
}

TASK_LABEL_STATUS = {"TASK": "TODO", "TASK_PENDING": "TODO", "TASK_IN_PROGRESS": "IN_PROGRESS",
                     "TASK_COMPLETED": "COMPLETED", "TASK_BLOCKED": "BLOCKED",
                     "DEPLOYMENT": "COMPLETED", "TESTING": None}


@dataclass
class _Gen:
    rng: random.Random
    project_id: str
    start: datetime
    style: str  # android24 | ios12 | us12
    lang_mix: float  # prob Hinglish

    def person(self, kind: str, dev: tuple):
        r = self.rng
        pools = {"pm": [PM], "sales": [SALES], "client": CLIENTS, "qa": [DEVS[3]],
                 "dev": [d for d in DEVS if d[1] != "DESIGNER"], "any": DEVS + [PM, SALES] + CLIENTS}
        return r.choice(pools.get(kind, [dev]))

    def text(self, cat: str, task: tuple, assignee: str, hinglish: bool):
        r = self.rng
        lang = "hi" if hinglish else "en"
        pool = T[lang].get(cat) or T["en"][cat]
        if hinglish and cat in DEVANAGARI and r.random() < 0.15:
            pool = DEVANAGARI[cat]
        d = r.choice(DAYS_HI if hinglish else DAYS)
        title = r.choice(task[3])
        s = r.choice(pool).format(t=title, p=assignee, d=d)
        if r.random() < 0.2:
            s = s.lower()
        if r.random() < 0.08:
            s += r.choice([" 👍", " 🙏", " ✅", "!!"])
        return s, d


def _fmt(ts: datetime, sender: str | None, text: str, style: str) -> str:
    if style == "android24":
        head = f"{ts:%d/%m/%Y, %H:%M} - "
    elif style == "ios12":
        head = f"[{ts:%d/%m/%Y, %I:%M:%S %p}] "
    else:
        head = f"{ts.month}/{ts.day}/{ts:%y}, {ts.hour % 12 or 12}:{ts:%M} {ts:%p} - "
    return head + (f"{sender}: {text}" if sender else text)


def generate_project(seed: int, project_id: str, n_tasks: int = 8):
    rng = random.Random(seed)
    g = _Gen(rng, project_id, datetime(2026, 1, 1, 9, 0) + timedelta(days=rng.randint(0, 200)),
             rng.choice(["android24", "ios12", "us12"]), rng.choice([0.0, 0.3, 0.6]))
    tasks = rng.sample(TASKS, k=min(n_tasks, len(TASKS)))
    events = []  # (ts, sender, text, label dict)
    ts = g.start
    events.append((ts, None, "Messages and calls are end-to-end encrypted.", {"category": "GENERAL", "is_system": True}))

    def add(cat, task_idx, sender_tuple, task, assignee, status=None, force_lang=None):
        nonlocal ts
        ts += timedelta(minutes=rng.randint(2, 240))
        if ts.hour >= 22 or ts.hour < 8:
            ts = ts.replace(hour=9, minute=rng.randint(0, 59)) + timedelta(days=1)
        hing = rng.random() < g.lang_mix
        text, dl = g.text(cat, task, assignee, hing)
        lab = {"category": cat, "task_key": f"{project_id}-T{task_idx}" if task_idx is not None else None,
               "assignee": assignee if cat == "TASK" else None,
               "deadline_text": dl if cat in ("TASK", "DEADLINE") else None,
               "status": status or TASK_LABEL_STATUS.get(cat), "language": "hinglish" if hing else "en"}
        events.append((ts, sender_tuple[0], text, lab))

    for i, task in enumerate(tasks):
        dev = rng.choice([d for d in DEVS if d[1] not in ("QA", "DESIGNER")] if task[1] != "Design" else [DEVS[4]])
        a = dev[0]
        add("TASK", i, PM, task, a, "TODO")
        if rng.random() < 0.3:
            add("QUESTION", i, PM, task, a, None)
        add("TASK_IN_PROGRESS", i, dev, task, a, "IN_PROGRESS")
        outcome = rng.choices(["done", "blocked", "client", "open"], [0.5, 0.2, 0.15, 0.15])[0]
        if outcome == "blocked":
            add("TASK_BLOCKED", i, dev, task, a, "BLOCKED")
            add("CLIENT_PENDING", i, g.person("pm", dev), task, a, "BLOCKED")
            if rng.random() < 0.6:
                add("BLOCKER", i, dev, task, a, "BLOCKED")
        elif outcome == "client":
            add("CLIENT_PENDING", i, g.person("sales", dev), task, a, "IN_PROGRESS")
            if rng.random() < 0.7:
                add("CLIENT_APPROVAL", i, g.person("client", dev), task, a, None)
        elif outcome == "open":
            if rng.random() < 0.5:
                add("TASK_PENDING", i, dev, task, a, "TODO")
        if outcome in ("done", "client"):
            if rng.random() < 0.4:
                add("BUG", i, g.person("qa", dev), task, a, None)
                add("BUG_FIXED", i, dev, task, a, None)
            add("TASK_COMPLETED", i, dev, task, a, "COMPLETED")
            if rng.random() < 0.6:
                add("TESTING", i, DEVS[3], task, a, None)
            if rng.random() < 0.4:
                add("DEPLOYMENT", i, dev, task, a, "COMPLETED")
        # background chatter between tasks
        for _ in range(rng.randint(2, 5)):
            cat = rng.choice(["GENERAL", "GENERAL", "DISCUSSION", "SALES", "PAYMENT", "MEETING", "DECISION",
                              "REQUIREMENT", "REQUIREMENT_CHANGE", "CLIENT_FEEDBACK", "DEADLINE", "RISK", "QUESTION"])
            who = g.person(rng.choice(ROLE_FOR.get(cat, ["any"])), dev)
            tk = i if cat not in ("GENERAL", "SALES", "PAYMENT", "MEETING") else None
            add(cat, tk, who, task, a)
    events.sort(key=lambda e: e[0])
    chat = "\n".join(_fmt(e[0], e[1], e[2], g.style) for e in events) + "\n"
    gold = []
    for i, (t, s, txt, lab) in enumerate(events):
        gold.append({"project_id": project_id, "index": i, "timestamp": t.isoformat(), "sender": s,
                     "message": txt, "source": "synthetic", "confidence": 1.0, **lab})
    return chat, gold, g.style


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", type=int, default=20)
    ap.add_argument("--out", default="data/synthetic")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "chats").mkdir(parents=True, exist_ok=True)
    rows = []
    for n in range(a.projects):
        pid = f"syn{n:03d}"
        chat, gold, style = generate_project(a.seed * 1000 + n, pid, n_tasks=random.Random(n).randint(5, 12))
        (out / "chats" / f"{pid}.txt").write_text(chat, encoding="utf-8")
        rows += gold
    with (out / "gold.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {a.projects} projects, {len(rows)} labelled messages -> {out}")


if __name__ == "__main__":
    main()
