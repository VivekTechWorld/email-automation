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
) -> dict:
    """
    Persist a new email event to SQLite.
    Returns the inserted record as a dict.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_preview = reply_preview[:200] if reply_preview else ""

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO email_logs (
                timestamp, sender, subject, category, severity,
                lang, used_rag, alert, reply_preview, provider, processing_ms, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    }


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
                (status, updated_reply[:200], log_id),
            )
        else:
            cursor.execute(
                "UPDATE email_logs SET status = ? WHERE id = ?",
                (status, log_id),
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

        return {
            "total": total,
            "by_category": by_category,
            "by_severity": by_severity,
            "by_lang": by_lang,
            "rag_used": int(rag_used),
            "alerts_sent": int(alerts_sent),
            "by_provider": by_provider,
        }
