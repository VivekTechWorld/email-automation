"""
customers.py — Customer profiles (per-sender memory)
=====================================================
Every real person who writes in gets a profile that is built automatically from
their emails: name, company, language, topics, mood trend and short AI notes.

The AI never sees a customer's full history — only the compact profile_block()
(capped at PROFILE_MAX_CHARS) — so a customer with 500 emails costs the same
tokens as a new one. Profiles are filled from the existing classification call;
no extra AI calls are made.

Escalation rules (should_escalate) also live here because they read the profile.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from logger import get_db_connection

MOODS = ["happy", "neutral", "frustrated", "angry"]
NOTES_MAX_CHARS = 800
PROFILE_MAX_CHARS = int(os.getenv("PROFILE_MAX_CHARS", "900"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def init_customers():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                email TEXT PRIMARY KEY,
                name TEXT,
                company TEXT,
                lang TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                email_count INTEGER NOT NULL DEFAULT 0,
                topics TEXT NOT NULL DEFAULT '{}',
                mood TEXT,
                mood_history TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                last_summary TEXT,
                escalations INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


def _to_dict(row) -> Optional[dict]:
    if not row:
        return None
    d = dict(row)
    d["topics"] = json.loads(d.get("topics") or "{}")
    d["mood_history"] = json.loads(d.get("mood_history") or "[]")
    return d


def get_customer(email: str) -> Optional[dict]:
    with get_db_connection() as conn:
        return _to_dict(conn.execute("SELECT * FROM customers WHERE email = ?", (email.lower(),)).fetchone())


def list_customers(search: str = "", limit: int = 300) -> list[dict]:
    with get_db_connection() as conn:
        if search:
            like = f"%{search.lower()}%"
            rows = conn.execute(
                "SELECT * FROM customers WHERE lower(email) LIKE ? OR lower(name) LIKE ? OR lower(company) LIKE ? "
                "ORDER BY last_seen DESC LIMIT ?",
                (like, like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM customers ORDER BY last_seen DESC LIMIT ?", (limit,)).fetchall()
    return [_to_dict(r) for r in rows]


def _merge_notes(existing: str, new_fact: str) -> str:
    """Append a new fact as a bullet; drop the oldest bullets when over the cap."""
    new_fact = (new_fact or "").strip().rstrip(".")
    lines = [l for l in (existing or "").split("\n") if l.strip()]
    if new_fact and not any(new_fact.lower() in l.lower() for l in lines):
        lines.append(f"• {new_fact}")
    while lines and len("\n".join(lines)) > NOTES_MAX_CHARS:
        lines.pop(0)
    return "\n".join(lines)


def record_interaction(
    *,
    email: str,
    name: str = "",
    company: str = "",
    lang: str = "en",
    category: str = "other",
    mood: str = "neutral",
    fact: str = "",
    summary: str = "",
) -> dict:
    """Create or update the sender's profile after an email was classified."""
    email = email.lower()
    now_iso = _now().isoformat()
    mood = mood if mood in MOODS else "neutral"
    existing = get_customer(email)

    if existing:
        topics = existing["topics"]
        topics[category] = topics.get(category, 0) + 1
        history = (existing["mood_history"] + [{"at": now_iso, "mood": mood}])[-10:]
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE customers SET name = COALESCE(NULLIF(?, ''), name), "
                "company = COALESCE(NULLIF(?, ''), company), lang = ?, last_seen = ?, "
                "email_count = email_count + 1, topics = ?, mood = ?, mood_history = ?, notes = ?, "
                "last_summary = ? WHERE email = ?",
                (name.strip(), company.strip(), lang, now_iso, json.dumps(topics), mood,
                 json.dumps(history), _merge_notes(existing["notes"], fact), summary, email),
            )
            conn.commit()
    else:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO customers (email, name, company, lang, first_seen, last_seen, email_count, "
                "topics, mood, mood_history, notes, last_summary) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
                (email, name.strip(), company.strip(), lang, now_iso, now_iso,
                 json.dumps({category: 1}), mood, json.dumps([{"at": now_iso, "mood": mood}]),
                 _merge_notes("", fact), summary),
            )
            conn.commit()
    return get_customer(email)


def update_customer(email: str, *, name: Optional[str] = None, company: Optional[str] = None,
                    notes: Optional[str] = None) -> Optional[dict]:
    if not get_customer(email):
        return None
    with get_db_connection() as conn:
        if name is not None:
            conn.execute("UPDATE customers SET name = ? WHERE email = ?", (name.strip()[:120], email.lower()))
        if company is not None:
            conn.execute("UPDATE customers SET company = ? WHERE email = ?", (company.strip()[:120], email.lower()))
        if notes is not None:
            conn.execute("UPDATE customers SET notes = ? WHERE email = ?", (notes.strip()[:NOTES_MAX_CHARS], email.lower()))
        conn.commit()
    return get_customer(email)


def delete_customer(email: str) -> bool:
    """GDPR erase: removes the profile, the customer's leads and every stored email from them."""
    email = email.lower()
    with get_db_connection() as conn:
        cur = conn.execute("DELETE FROM customers WHERE email = ?", (email,))
        conn.execute("DELETE FROM email_logs WHERE lower(sender) = ?", (email,))
        conn.execute("DELETE FROM leads WHERE customer_email = ?", (email,))
        conn.commit()
    return cur.rowcount > 0


def add_escalation(email: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE customers SET escalations = escalations + 1 WHERE email = ?", (email.lower(),))
        conn.commit()


def profile_block(email: str) -> str:
    """Compact, size-capped profile text for the reply prompt ('' for first-time senders)."""
    c = get_customer(email)
    if not c:
        return ""
    top_topics = ", ".join(f"{t} ({n})" for t, n in sorted(c["topics"].items(), key=lambda kv: -kv[1])[:4])
    recent_moods = ", ".join(m["mood"] for m in c["mood_history"][-4:])
    lines = [
        "--- WHAT WE KNOW ABOUT THIS CUSTOMER (use naturally, never quote it) ---",
        f"Name: {c['name'] or 'unknown'}" + (f" | Company: {c['company']}" if c["company"] else ""),
        f"Customer since: {c['first_seen'][:10]} | Emails so far: {c['email_count']}",
        f"Usual topics: {top_topics or 'none yet'}",
        f"Recent mood: {recent_moods or 'unknown'}",
    ]
    if c["last_summary"]:
        lines.append(f"Their previous request: {c['last_summary']}")
    if c["notes"]:
        lines.append(f"Notes:\n{c['notes']}")
    block = "\n".join(lines)
    return block[:PROFILE_MAX_CHARS] + "\n--- END OF CUSTOMER PROFILE ---\n\n"


def _same_issue_count(email: str, category: str, thread_id: Optional[str], summary: str) -> int:
    """
    Emails from this sender in the last 48 hours about the SAME issue — same
    thread, or same category with a similar summary. Different questions from
    one active customer must not count as "chasing us".
    """
    from learning import _terms, _similar

    since = (_now() - timedelta(hours=48)).isoformat()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT thread_id, category, summary, subject FROM email_logs "
            "WHERE lower(sender) = ? AND timestamp >= ? AND status NOT IN ('skipped', 'followup')",
            (email.lower(), since),
        ).fetchall()

    current_terms = _terms(summary)
    count = 0
    for r_thread, r_category, r_summary, r_subject in rows:
        if thread_id and r_thread == thread_id:
            count += 1
        elif r_category == category and current_terms:
            other = _terms(r_summary or r_subject or "")
            if other and _similar(current_terms, other):
                count += 1
    return count


def should_escalate(email: str, mood: str, category: str,
                    thread_id: Optional[str] = None, summary: str = "") -> Optional[str]:
    """
    Returns a human-readable reason when the email should go to a person with
    high priority, else None. Rules use the profile (call after record_interaction).
    """
    c = get_customer(email)
    if not c:
        return None

    if mood == "angry":
        return "Customer sounds angry"

    week_ago = (_now() - timedelta(days=7)).isoformat()
    recent = [m["mood"] for m in c["mood_history"] if m["at"] >= week_ago]
    # current email is the last entry; look for an earlier unhappy one too
    if mood == "frustrated" and any(m in ("frustrated", "angry") for m in recent[:-1]):
        return "Customer has been frustrated more than once this week"

    if category not in ("sales", "other"):
        # +1 for the email being processed now (not logged yet)
        count = _same_issue_count(email, category, thread_id, summary) + 1
        if count >= 3:
            return f"{count} emails about the same issue in 48 hours"

    return None
