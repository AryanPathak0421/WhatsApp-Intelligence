"""Project-level completion: "project is live and deployed" / "project is completed" closes the work that was never closed one by one.

Per-task linking cannot do this: the delivery announcement names the project, not each task, so the open tasks stay TODO forever and
the dashboard reports a delivered project as 22% done / CRITICAL. This pass finds the announcement and closes the open tasks it covers,
but every task it closes is flagged for review (it is an inference from one message, not per-task evidence).

Conservative on purpose:
  * the announcer must not be client-side (a client saying "the project is complete" is not a delivery claim from the team);
  * conditionals / negations ("once the project is live", "not completed yet", "will be deployed") are ignored;
  * a client complaint, bug or rejection AFTER the announcement marks it DISPUTED and closes nothing;
  * BLOCKED and CANCELLED tasks are left alone.
"""
from __future__ import annotations

import re
from typing import Optional

from app.intelligence.roles import CLIENT_SIDE, COMPLAINT
from app.intelligence.rules import norm, signals
from app.intelligence.types import Evidence, Msg, Task

SUBJECT = r"(?:project|website|web ?site|site|app|application|portal|platform|everything|sab ?kuch|sara kaam|poora kaam)"
DONE_WORD = (r"(?:completed?|complete ho (?:gaya|gya|gaye)|delivered|handed over|finished|"
             r"live (?:and|&|aur) (?:deployed|running|working)|deployed (?:and|&|aur) live|(?:is|are|ho gaya|ho gya|hai) live|went live|"
             r"go[- ]?live (?:done|complete|completed)|deployed|deploy ho (?:gaya|gya)|पूरा हो गया|हो गया)")
ANNOUNCE = re.compile(rf"(?<!\w){SUBJECT}\b[^.!?\n]{{0,30}}?(?<!\w){DONE_WORD}(?!\w)", re.I)
CONDITIONAL = re.compile(r"(?<!\w)(?:once|when|after|if|until|before|jab|jaise hi|to be|will be|should be|shall be|going to be|soon|expected)(?!\w)", re.I)
NEGATED = re.compile(r"(?<!\w)(?:not|nahi|nhi|nahin|yet|pending|baaki|incomplete|only)(?!\w)", re.I)
OPEN_STATES = ("TODO", "IN_PROGRESS")


def _announces(text: str) -> bool:
    t = norm(text)
    m = ANNOUNCE.search(t)
    if not m:
        return False
    before = t[max(0, m.start() - 40):m.start()]
    return not (CONDITIONAL.search(before) or CONDITIONAL.search(m.group(0)) or NEGATED.search(t))


def detect_project_completion(msgs: list[Msg], roles: dict[str, dict]) -> Optional[dict]:
    """Latest delivery announcement by a non-client, with its state: CLAIMED, or DISPUTED if the client pushed back afterwards."""
    found = None
    for i, m in enumerate(msgs):
        if not m.text or (roles.get(m.sender or "", {}).get("role") in CLIENT_SIDE) or not _announces(m.text):
            continue
        found = i
    if found is None:
        return None
    m = msgs[found]
    for later in msgs[found + 1:]:
        if roles.get(later.sender or "", {}).get("role") not in CLIENT_SIDE or not later.text:
            continue
        s = signals(later.text)
        if s["bug"] or s["reject"] or COMPLAINT.search(later.text):
            return {"message_id": m.id, "ts": m.ts, "sender": m.sender, "text": m.text[:240], "state": "DISPUTED",
                    "disputed_by_message_id": later.id}
    return {"message_id": m.id, "ts": m.ts, "sender": m.sender, "text": m.text[:240], "state": "CLAIMED"}


def apply_project_completion(tasks: list[Task], completion: Optional[dict]) -> list[str]:
    """Close the open tasks the announcement covers (created before it). Returns the ids it closed."""
    if not completion or completion["state"] != "CLAIMED":
        return []
    closed = []
    for t in tasks:
        if t.status not in OPEN_STATES or t.created_at > completion["ts"]:
            continue
        t.status_trace.append({"message_id": completion["message_id"], "event": "project_completed", "from": t.status, "status": "COMPLETED"})
        t.status = "COMPLETED"
        t.completed_at = completion["ts"]
        t.external_dependency = None
        t.evidence.append(Evidence(completion["message_id"], "project_completion", 0.6))
        t.needs_review = True
        t.review_reasons.append("closed by the project-completion announcement, not by evidence about this task; verify")
        t.confidence = round(min(t.confidence, 0.6), 2)
        closed.append(t.id)
    return closed
