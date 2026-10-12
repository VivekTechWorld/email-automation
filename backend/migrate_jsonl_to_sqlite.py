"""
migrate_jsonl_to_sqlite.py — One-time JSONL to SQLite migration script
=====================================================================
Reads existing records from data/email_logs.jsonl and inserts them into
data/email_logs.db, preserving IDs, timestamps, and all schema fields.
"""

import os
import json
import sqlite3
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
JSONL_FILE = PROJECT_ROOT / "data" / "email_logs.jsonl"
DB_FILE = PROJECT_ROOT / "data" / "email_logs.db"


def init_db(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_logs (
            id INTEGER PRIMARY KEY,
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


def migrate():
    log.info("Starting JSONL to SQLite migration...")
    log.info("Source: %s", JSONL_FILE)
    log.info("Target: %s", DB_FILE)

    if not JSONL_FILE.exists():
        log.warning("Source JSONL file does not exist: %s. Nothing to migrate.", JSONL_FILE)
        return 0

    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    init_db(conn)

    migrated_count = 0
    skipped_count = 0

    with open(JSONL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("Skipping invalid JSON line: %s", e)
                continue

            entry_id = entry.get("id")
            timestamp = entry.get("timestamp")
            sender = entry.get("sender", "")
            subject = entry.get("subject", "")
            category = entry.get("category", "other")
            severity = entry.get("severity", "normal")
            lang = entry.get("lang", "en")
            used_rag = 1 if entry.get("used_rag") else 0
            alert = 1 if entry.get("alert") else 0
            reply_preview = entry.get("reply_preview", "")
            provider = entry.get("provider", "local")
            processing_ms = entry.get("processing_ms")
            status = entry.get("status", "sent")

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO email_logs (
                        id, timestamp, sender, subject, category, severity,
                        lang, used_rag, alert, reply_preview, provider, processing_ms, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry_id, timestamp, sender, subject, category, severity,
                    lang, used_rag, alert, reply_preview, provider, processing_ms, status
                ))
                migrated_count += 1
            except Exception as e:
                log.error("Failed to insert record id=%s: %s", entry_id, e)
                skipped_count += 1

    conn.commit()
    conn.close()

    log.info(
        "Migration complete: %d records processed (%d skipped). Database ready at %s",
        migrated_count, skipped_count, DB_FILE
    )
    return migrated_count


if __name__ == "__main__":
    migrate()
