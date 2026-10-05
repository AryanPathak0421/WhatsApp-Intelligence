"""Single source of truth for label sets (shared by annotation, training, eval)."""

CATEGORIES = [
    "TASK", "TASK_COMPLETED", "TASK_PENDING", "TASK_IN_PROGRESS", "TASK_BLOCKED",
    "BUG", "BUG_FIXED", "REQUIREMENT", "REQUIREMENT_CHANGE",
    "CLIENT_FEEDBACK", "CLIENT_APPROVAL", "CLIENT_PENDING", "SALES", "PAYMENT",
    "DEPLOYMENT", "TESTING", "MEETING", "DECISION", "DEADLINE", "QUESTION",
    "DISCUSSION", "RISK", "BLOCKER", "GENERAL",
]

# Merged labels: "task not done yet" is a STATUS (TODO) of a TASK, not a separate category. The old name stays valid
# in the trained models / synthetic gold / DB enum and is mapped to its canonical label wherever labels are read or written.
CATEGORY_ALIASES = {"TASK_PENDING": "TASK"}
ACTIVE_CATEGORIES = [c for c in CATEGORIES if c not in CATEGORY_ALIASES]


def canonical(category):
    return CATEGORY_ALIASES.get(category, category)


TASK_STATUSES = ["TODO", "IN_PROGRESS", "COMPLETED", "BLOCKED", "CANCELLED"]

ENTITY_TYPES = [
    "PERSON", "CLIENT", "COMPANY", "PROJECT", "PRODUCT", "FEATURE", "TECHNOLOGY",
    "DATE", "TIME", "DEADLINE", "MONEY", "URL", "TASK", "MODULE", "BUG", "TEAM",
]

ROLES = [
    "PROJECT_MANAGER", "DEVELOPER", "FRONTEND_DEVELOPER", "BACKEND_DEVELOPER",
    "FULLSTACK_DEVELOPER", "QA", "DESIGNER", "SALES", "CLIENT",
    "CLIENT_REPRESENTATIVE", "ADMIN", "OTHER",
]

# Active-learning thresholds (spec): >0.95 auto-accept, 0.70-0.95 review, <0.70 queue
AUTO_ACCEPT = 0.95
REVIEW_MIN = 0.70
