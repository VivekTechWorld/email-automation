"""
learning.py — Self-learning knowledge base
===========================================
Two automatic inputs, both reviewed by a person before anything reaches the
knowledge base:

1. Suggestions  — when a reviewer approves a reply, the AI rewrites the
                  question + approved answer as a general article with all
                  personal details removed. One AI call per approval (human-paced,
                  so it stays inside free-tier quotas). Accepting a suggestion
                  creates a normal article and counts toward the KB limits.
2. Gaps         — when the AI had no knowledge-base match for a real customer
                  question, the question is recorded. Similar questions are
                  grouped and counted so the team sees what is missing most.
"""

import json
import re
import logging
from datetime import datetime, timezone
from typing import Optional

from logger import get_db_connection

log = logging.getLogger(__name__)

GAP_CATEGORIES = {"sales", "inquiry", "billing", "support", "bug"}

SUGGEST_PROMPT = """\
You maintain the support knowledge base for {company_desc}.
A support agent approved the reply below to a customer question. Decide whether
it contains reusable knowledge that would help answer OTHER customers.

Respond with ONLY valid JSON:
{{
  "useful": <true|false>,
  "title": "<short article title, e.g. 'Resetting the customer portal password'>",
  "category": "<general|sales|inquiry|billing|support|bug>",
  "content": "<the reusable knowledge as plain text: the typical question, then the answer/steps>"
}}

Rules:
- useful = false when the reply is only about this one customer's situation
  (their specific quote, invoice, account, order, or a simple acknowledgement).
- REMOVE all personal details: names, email addresses, phone numbers, domain
  names, order/invoice numbers, prices quoted for this customer.
- Keep concrete steps, URLs and policies exactly as written in the reply.
- Write in the same language as the reply.

Customer question:
{question}

Approved reply:
{reply}\
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_learning():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                lang TEXT NOT NULL,
                content TEXT NOT NULL,
                source_log_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                category TEXT NOT NULL,
                lang TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 1,
                sample_log_id INTEGER,
                status TEXT NOT NULL DEFAULT 'open',
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)
        conn.commit()


# ── Suggestions ───────────────────────────────────────────────────────────────

def create_suggestion_from_approval(*, log_item: dict, approved_reply: str, lang: str, company_desc: str):
    """Ask the AI to turn an approved reply into a general article. Runs in a worker thread."""
    from provider import classify  # JSON-mode call

    question = (log_item.get("original_body") or log_item.get("summary") or log_item.get("subject") or "")[:2000]
    if not question.strip() or not approved_reply.strip():
        return
    prompt = SUGGEST_PROMPT.format(company_desc=company_desc, question=question, reply=approved_reply[:3000])
    try:
        raw = classify(prompt)
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1])
    except Exception as e:
        log.warning("Knowledge suggestion skipped for log #%s: %s", log_item.get("id"), e)
        return

    if not data.get("useful") or not str(data.get("content", "")).strip():
        log.info("Approved reply #%s judged customer-specific — no suggestion.", log_item.get("id"))
        return

    category = str(data.get("category", "general")).lower()
    if category not in {"general", "sales", "inquiry", "billing", "support", "bug"}:
        category = "general"
    title = str(data.get("title", "")).strip()[:200] or (log_item.get("subject") or "Suggested article")[:200]

    with get_db_connection() as conn:
        duplicate = conn.execute(
            "SELECT 1 FROM kb_suggestions WHERE lower(title) = ? AND status = 'pending'", (title.lower(),)
        ).fetchone()
        if duplicate:
            return
        conn.execute(
            "INSERT INTO kb_suggestions (title, category, lang, content, source_log_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, category, lang, str(data["content"]).strip()[:15000], log_item.get("id"), _now()),
        )
        conn.commit()
    log.info("New knowledge suggestion from approved reply #%s: %s", log_item.get("id"), title)


def list_suggestions(status: str = "pending") -> list[dict]:
    with get_db_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM kb_suggestions WHERE status = ? ORDER BY id DESC", (status,)
        ).fetchall()]


def get_suggestion(sid: int) -> Optional[dict]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM kb_suggestions WHERE id = ?", (sid,)).fetchone()
    return dict(row) if row else None


def set_suggestion_status(sid: int, status: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE kb_suggestions SET status = ? WHERE id = ?", (status, sid))
        conn.commit()


# ── Gaps ──────────────────────────────────────────────────────────────────────

_WORD = re.compile(r"[a-zA-ZäöåÄÖÅ0-9]{3,}")
_STOP = {"the", "and", "for", "with", "that", "this", "wants", "want", "know", "how", "what", "sender",
         "customer", "asks", "asking", "about", "their", "they", "would", "like", "help", "need", "needs"}


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> set[str]:
    return {_stem(w.lower()) for w in _WORD.findall(text or "") if w.lower() not in _STOP}


def _similar(a: set[str], b: set[str]) -> bool:
    """Overlap coefficient — robust when one question is worded longer than the other."""
    shared = len(a & b)
    return shared >= 2 and shared / min(len(a), len(b)) >= 0.6


def record_gap(*, question: str, category: str, lang: str, log_id: int):
    """Store an unanswered question, merging it into a similar open one when possible."""
    if category not in GAP_CATEGORIES or not (question or "").strip():
        return
    terms = _terms(question)
    if not terms:
        return
    now = _now()
    with get_db_connection() as conn:
        open_gaps = conn.execute(
            "SELECT id, question FROM kb_gaps WHERE status = 'open' AND category = ? AND lang = ?",
            (category, lang),
        ).fetchall()
        for gap_id, existing in open_gaps:
            other = _terms(existing)
            if other and _similar(terms, other):
                conn.execute("UPDATE kb_gaps SET count = count + 1, last_seen = ? WHERE id = ?", (now, gap_id))
                conn.commit()
                return
        conn.execute(
            "INSERT INTO kb_gaps (question, category, lang, sample_log_id, first_seen, last_seen) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (question.strip()[:300], category, lang, log_id, now, now),
        )
        conn.commit()


def list_gaps(status: str = "open") -> list[dict]:
    with get_db_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM kb_gaps WHERE status = ? ORDER BY count DESC, last_seen DESC", (status,)
        ).fetchall()]


def resolve_gap(gap_id: int) -> bool:
    with get_db_connection() as conn:
        cur = conn.execute("UPDATE kb_gaps SET status = 'resolved' WHERE id = ?", (gap_id,))
        conn.commit()
    return cur.rowcount > 0


def counts() -> dict:
    with get_db_connection() as conn:
        s = conn.execute("SELECT COUNT(*) FROM kb_suggestions WHERE status = 'pending'").fetchone()[0]
        g = conn.execute("SELECT COUNT(*) FROM kb_gaps WHERE status = 'open'").fetchone()[0]
    return {"suggestions": s, "gaps": g}
