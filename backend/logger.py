"""
logger.py — Email Processing Event Logger (SQLite-backed)
=========================================================
Stores all processed email events in a SQLite database (stdlib sqlite3)
so that the dashboard survives backend restarts and scales reliably.

Indexes are created on timestamp, category, severity, and status.
"""

import os
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

log = logging.getLogger(__name__)

# Paths resolved relative to backend/
_BACKEND_DIR = Path(__file__).resolve().parent
_DEFAULT_DB_FILE = _BACKEND_DIR.parent / "data" / "email_logs.db"
_DB_FILE = Path(os.getenv("EMAIL_DB_PATH", str(_DEFAULT_DB_FILE))).resolve()
_JSONL_FALLBACK = _BACKEND_DIR.parent / "data" / "email_logs.jsonl"


def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection configured with Row factory and WAL mode."""
    _DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_FILE, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db_schema():
    """Creates the email_logs table and performance indexes if they don't exist."""
    with get_db_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                lang TEXT NOT NULL,
                used_rag INTEGER NOT NULL DEFAULT 0,
                alert INTEGER NOT NULL DEFAULT 0,
                reply_preview TEXT,
                provider TEXT,
                processing_ms INTEGER,
                status TEXT NOT NULL DEFAULT 'sent'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON email_logs(timestamp);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_category ON email_logs(category);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_severity ON email_logs(severity);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_status ON email_logs(status);")

        # Migrate existing schema if thread_id or message_id columns are missing
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(email_logs)")
        cols = {row["name"] for row in cursor.fetchall()}
        if "thread_id" not in cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN thread_id TEXT;")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_thread_id ON email_logs(thread_id);")
        if "message_id" not in cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN message_id TEXT;")
        if "original_body" not in cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN original_body TEXT;")
        if "review_reason" not in cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN review_reason TEXT;")
        if "summary" not in cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN summary TEXT;")
        if "delivered_at" not in cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN delivered_at TEXT;")
        for col, ddl in (
            ("mood", "TEXT"),
            ("escalated", "INTEGER NOT NULL DEFAULT 0"),
            ("awaiting_customer", "INTEGER NOT NULL DEFAULT 0"),
            ("followup_sent", "INTEGER NOT NULL DEFAULT 0"),
            ("lead_id", "INTEGER"),
            ("delivery_confirmed", "INTEGER NOT NULL DEFAULT 0"),
            ("quoted_price", "REAL"),
        ):
            if col not in cols:
                conn.execute(f"ALTER TABLE email_logs ADD COLUMN {col} {ddl};")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_sender ON email_logs(sender);")
        conn.commit()


def _auto_migrate_jsonl_if_empty():
    """One-time auto-migration from JSONL if SQLite table is empty."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM email_logs")
            count = cursor.fetchone()[0]
            if count == 0 and _JSONL_FALLBACK.exists():
                log.info("SQLite table empty. Migrating existing logs from %s...", _JSONL_FALLBACK)
                migrated = 0
                with open(_JSONL_FALLBACK, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            item = json.loads(line)
                            cursor.execute("""
                                INSERT OR IGNORE INTO email_logs (
                                    id, timestamp, sender, subject, category, severity,
                                    lang, used_rag, alert, reply_preview, provider, processing_ms, status
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                item.get("id"),
                                item.get("timestamp"),
                                item.get("sender", ""),
                                item.get("subject", ""),
                                item.get("category", "other"),
                                item.get("severity", "normal"),
                                item.get("lang", "en"),
                                1 if item.get("used_rag") else 0,
                                1 if item.get("alert") else 0,
                                item.get("reply_preview", ""),
                                item.get("provider", "local"),
                                item.get("processing_ms"),
                                item.get("status", "sent"),
                            ))
                            migrated += 1
                        except Exception as parse_err:
                            log.warning("Skipping invalid JSON line during migration: %s", parse_err)
                conn.commit()
                log.info("Auto-migrated %d records into SQLite.", migrated)
    except Exception as e:
        log.error("Auto-migration check failed: %s", e)


def init_logger():
    """Initialise SQLite database and indexes at app startup."""
    _init_db_schema()
    _auto_migrate_jsonl_if_empty()
    total = get_total_count()
    log.info("SQLite email logger initialised. Active database has %d log records.", total)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Converts a SQLite Row into the exact API dictionary contract."""
    d = dict(row)
    d["used_rag"] = bool(d.get("used_rag", 0))
    d["alert"] = bool(d.get("alert", 0))
    d["escalated"] = bool(d.get("escalated", 0))
    d["awaiting_customer"] = bool(d.get("awaiting_customer", 0))
    d["delivery_confirmed"] = bool(d.get("delivery_confirmed", 0))
    return d


# ── Write a new log entry ──────────────────────────────────────────────────────

async def log_email_event(
    *,
    sender: str,
    subject: str,
    category: str,
    severity: str,
    lang: str,
    used_rag: bool,
    alert: bool,
    reply_preview: str,
    provider: str,
    processing_ms: Optional[int] = None,
    status: str = "sent",
    thread_id: Optional[str] = None,
    message_id: Optional[str] = None,
    original_body: Optional[str] = None,
    review_reason: Optional[str] = None,
    summary: Optional[str] = None,
    mood: Optional[str] = None,
    escalated: bool = False,
    awaiting_customer: bool = False,
    quoted_price: Optional[float] = None,
) -> dict:
    """
    Persist a new email event to SQLite.
    Returns the inserted record as a dict.

    reply_preview holds the FULL reply text (the dashboard truncates for display);
    approving a pending item sends exactly what is stored here.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_preview = reply_preview or ""
    original_body = (original_body or "")[:20000]

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO email_logs (
                timestamp, sender, subject, category, severity,
                lang, used_rag, alert, reply_preview, provider, processing_ms, status,
                thread_id, message_id, original_body, review_reason, summary,
                mood, escalated, awaiting_customer, quoted_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now_iso,
            sender,
            subject,
            category,
            severity,
            lang,
            1 if used_rag else 0,
            1 if alert else 0,
            clean_preview,
            provider,
            processing_ms,
            status,
            thread_id,
            message_id,
            original_body,
            review_reason,
            summary,
            mood,
            1 if escalated else 0,
            1 if awaiting_customer else 0,
            quoted_price,
        ))
        conn.commit()
        new_id = cursor.lastrowid

    return {
        "id": new_id,
        "timestamp": now_iso,
        "sender": sender,
        "subject": subject,
        "category": category,
        "severity": severity,
        "lang": lang,
        "used_rag": used_rag,
        "alert": alert,
        "reply_preview": clean_preview,
        "provider": provider,
        "processing_ms": processing_ms,
        "status": status,
        "thread_id": thread_id,
        "message_id": message_id,
        "original_body": original_body,
        "review_reason": review_reason,
        "summary": summary,
        "mood": mood,
        "escalated": escalated,
        "awaiting_customer": awaiting_customer,
        "quoted_price": quoted_price,
    }


def get_thread_history(thread_id: str, limit: int = 5) -> list[dict]:
    """Retrieve the most recent `limit` messages in the same Gmail thread, oldest first."""
    if not thread_id:
        return []
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM email_logs WHERE thread_id = ? ORDER BY id DESC LIMIT ?",
            (thread_id, limit),
        )
        rows = cursor.fetchall()
        return [_row_to_dict(r) for r in reversed(rows)]


def find_by_message_id(message_id: str) -> Optional[dict]:
    """Return the existing log entry for a Gmail message id (duplicate-delivery guard)."""
    if not message_id:
        return None
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM email_logs WHERE message_id = ? ORDER BY id DESC LIMIT 1",
            (message_id,),
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None


# ── Read log entries ───────────────────────────────────────────────────────────

def get_logs(limit: int = 200, status: Optional[str] = None) -> list[dict]:
    """Return the most recent `limit` entries, newest first."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM email_logs WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor.execute("SELECT * FROM email_logs ORDER BY id DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_log_by_id(log_id: int) -> Optional[dict]:
    """Retrieve a single log entry by its primary key ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM email_logs WHERE id = ?", (log_id,))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None


def update_log_status(log_id: int, status: str, updated_reply: Optional[str] = None) -> Optional[dict]:
    """Update status and optionally reply preview of a log item."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if updated_reply is not None:
            cursor.execute(
                "UPDATE email_logs SET status = ?, reply_preview = ? WHERE id = ?",
                (status, updated_reply, log_id),
            )
        else:
            cursor.execute(
                "UPDATE email_logs SET status = ? WHERE id = ?",
                (status, log_id),
            )
        conn.commit()
    return get_log_by_id(log_id)


def claim_outbox(limit: int = 50) -> list[dict]:
    """
    Hand approved replies to n8n exactly once.

    Items are marked delivered (claimed) in the same transaction that selects
    them, so a reply is never returned twice — even if n8n's "Mark Delivered"
    step fails or two polls overlap. POST /outbox/{id}/delivered then only
    confirms the send. (At-most-once: a duplicate email to a customer is worse
    than a missed one, which stays visible as "not confirmed" in the log.)
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")  # lock so concurrent polls can't claim the same rows
        rows = conn.execute(
            "SELECT * FROM email_logs WHERE status IN ('approved', 'auto_approved', 'followup') AND delivered_at IS NULL "
            "AND message_id IS NOT NULL AND reply_preview IS NOT NULL AND reply_preview != '' "
            "ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        for r in rows:
            conn.execute("UPDATE email_logs SET delivered_at = ? WHERE id = ?", (now_iso, r["id"]))
        conn.commit()
    return [_row_to_dict(r) for r in rows]


def promote_expired_pending(timeout_hours: float) -> list[int]:
    """
    Pending items that have waited longer than `timeout_hours` and have an AI draft
    become 'auto_approved' so n8n sends the draft. Items without a draft
    (e.g. AI failures) stay pending — there is nothing to send.
    Returns the promoted log ids.
    """
    if timeout_hours <= 0:
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - timeout_hours * 3600
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM email_logs WHERE status = 'pending' AND alert = 0 AND timestamp <= ? "
            "AND message_id IS NOT NULL AND reply_preview IS NOT NULL AND reply_preview != ''",
            (cutoff_iso,),
        ).fetchall()
        ids = [r[0] for r in rows]
        for log_id in ids:
            conn.execute(
                "UPDATE email_logs SET status = 'auto_approved', "
                "review_reason = COALESCE(review_reason, '') || ' → no review within ' || ? || 'h, AI replied automatically' "
                "WHERE id = ? AND status = 'pending'",
                (f"{timeout_hours:g}", log_id),
            )
        conn.commit()
    return ids


def set_lead_id(log_id: int, lead_id: int):
    with get_db_connection() as conn:
        conn.execute("UPDATE email_logs SET lead_id = ? WHERE id = ?", (lead_id, log_id))
        conn.commit()


def customer_replied(thread_id: Optional[str], sender: str):
    """The customer wrote again — stop waiting for them on earlier replies."""
    with get_db_connection() as conn:
        if thread_id:
            conn.execute("UPDATE email_logs SET awaiting_customer = 0 WHERE thread_id = ?", (thread_id,))
        else:
            conn.execute("UPDATE email_logs SET awaiting_customer = 0 WHERE lower(sender) = ?", (sender.lower(),))
        conn.commit()


def due_followups(after_days: float) -> list[dict]:
    """
    Replies that asked the customer something, were delivered, and got no answer
    within `after_days`. Each original gets at most one follow-up.
    """
    cutoff = (datetime.now(timezone.utc).timestamp() - after_days * 86400)
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM email_logs WHERE awaiting_customer = 1 AND followup_sent = 0 "
            "AND message_id IS NOT NULL AND status IN ('sent', 'approved', 'auto_approved') AND alert = 0 "
            "AND COALESCE(delivered_at, CASE WHEN status = 'sent' THEN timestamp END) <= ?",
            (cutoff_iso,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def queue_followup(original: dict, text: str) -> int:
    """Insert a follow-up message into the outbox (replies in the original thread)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO email_logs (timestamp, sender, subject, category, severity, lang, used_rag, alert, "
            "reply_preview, provider, processing_ms, status, thread_id, message_id, review_reason, summary, lead_id) "
            "VALUES (?, ?, ?, ?, 'normal', ?, 0, 0, ?, 'template', 0, 'followup', ?, ?, ?, ?, ?)",
            (now_iso, original["sender"], original["subject"], original["category"], original["lang"], text,
             original["thread_id"], original["message_id"],
             f"Automatic follow-up — no answer to reply #{original['id']}",
             original.get("summary"), original.get("lead_id")),
        )
        conn.execute("UPDATE email_logs SET followup_sent = 1 WHERE id = ?", (original["id"],))
        conn.commit()
        return cur.lastrowid


def get_logs_for_sender(sender: str, limit: int = 20) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM email_logs WHERE lower(sender) = ? ORDER BY id DESC LIMIT ?", (sender.lower(), limit)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_delivered(log_id: int) -> Optional[dict]:
    """n8n confirms the reply was actually sent (the item was already claimed by claim_outbox)."""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE email_logs SET delivery_confirmed = 1, "
            "delivered_at = COALESCE(delivered_at, ?) WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), log_id),
        )
        conn.commit()
    return get_log_by_id(log_id)


def get_total_count(status: Optional[str] = None) -> int:
    """Return total number of rows in the table."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute("SELECT COUNT(*) FROM email_logs WHERE status = ?", (status,))
        else:
            cursor.execute("SELECT COUNT(*) FROM email_logs")
        return cursor.fetchone()[0]


def get_stats() -> dict:
    """Aggregate statistics for the dashboard with exact contract matching."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*),
                COALESCE(SUM(CASE WHEN used_rag = 1 THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN alert = 1 THEN 1 ELSE 0 END), 0)
            FROM email_logs
        """)
        total, rag_used, alerts_sent = cursor.fetchone()

        if total == 0:
            return {
                "total": 0,
                "by_category": {},
                "by_severity": {"normal": 0, "high": 0, "critical": 0},
                "by_lang": {},
                "rag_used": 0,
                "alerts_sent": 0,
                "by_provider": {"local": 0, "gemini": 0},
                "by_status": {},
            }

        cursor.execute("SELECT category, COUNT(*) FROM email_logs GROUP BY category")
        by_category = {cat: count for cat, count in cursor.fetchall()}

        by_severity = {"normal": 0, "high": 0, "critical": 0}
        cursor.execute("SELECT severity, COUNT(*) FROM email_logs GROUP BY severity")
        for sev, count in cursor.fetchall():
            by_severity[sev] = count

        cursor.execute("SELECT lang, COUNT(*) FROM email_logs GROUP BY lang")
        by_lang = {lang: count for lang, count in cursor.fetchall()}

        by_provider = {"local": 0, "gemini": 0}
        cursor.execute("SELECT provider, COUNT(*) FROM email_logs GROUP BY provider")
        for prov, count in cursor.fetchall():
            by_provider[prov] = count

        cursor.execute("SELECT status, COUNT(*) FROM email_logs GROUP BY status")
        by_status = {st: count for st, count in cursor.fetchall()}

        return {
            "total": total,
            "by_status": by_status,
            "by_category": by_category,
            "by_severity": by_severity,
            "by_lang": by_lang,
            "rag_used": int(rag_used),
            "alerts_sent": int(alerts_sent),
            "by_provider": by_provider,
        }
