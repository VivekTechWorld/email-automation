"""
settings_store.py — Automation settings editable from the dashboard
====================================================================
Stored as JSON values in a small key/value table in the email-log database.

  handoff_categories        email categories that go to a human team instead of
                            being auto-sent (default: ["sales"])
  handoff_email             address notified when an email is handed off
  auto_reply_enabled        send the AI draft automatically when nobody reviews it
  auto_reply_timeout_hours  how long a held email waits before the AI replies
  followup_enabled / followup_after_days
                            one polite reminder when a customer never answered our question
  escalation_enabled        angry / repeatedly unhappy customers go to a person with priority
  learning_enabled          approved replies become suggested knowledge-base articles
  report_enabled / report_email / report_frequency
                            scheduled summary email (sent by n8n)
"""

import json
import os
import re
from typing import Any

from logger import get_db_connection

HANDOFF_CHOICES = ["sales", "inquiry", "billing", "support", "bug", "other"]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _defaults() -> dict[str, Any]:
    # PENDING_REVIEW_TIMEOUT_HOURS=0 historically meant "hold forever", so 0 disables auto-reply
    try:
        env_hours = float(os.getenv("PENDING_REVIEW_TIMEOUT_HOURS", "24") or 0)
    except ValueError:
        env_hours = 24.0
    return {
        "handoff_categories": ["sales"],
        "handoff_email": os.getenv("SALES_TEAM_EMAIL", ""),
        "auto_reply_enabled": env_hours > 0,
        "auto_reply_timeout_hours": env_hours if env_hours > 0 else 24.0,
        "followup_enabled": True,
        "followup_after_days": 3.0,
        "escalation_enabled": True,
        "learning_enabled": True,
        "report_enabled": False,
        "report_email": os.getenv("REPORT_EMAIL", ""),
        "report_frequency": "weekly",
    }


def init_settings():
    with get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()


def get_settings() -> dict[str, Any]:
    settings = _defaults()
    with get_db_connection() as conn:
        for key, value in conn.execute("SELECT key, value FROM app_settings").fetchall():
            if key in settings:
                settings[key] = json.loads(value)
    return settings


def update_settings(changes: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist the given keys. Raises ValueError with a readable message."""
    clean: dict[str, Any] = {}

    if "handoff_categories" in changes:
        cats = changes["handoff_categories"]
        if not isinstance(cats, list) or any(c not in HANDOFF_CHOICES for c in cats):
            raise ValueError(f"handoff_categories must be a list from: {', '.join(HANDOFF_CHOICES)}.")
        clean["handoff_categories"] = sorted(set(cats))

    if "handoff_email" in changes:
        email = str(changes["handoff_email"] or "").strip()
        if email and not _EMAIL_RE.match(email):
            raise ValueError("Team email address is not valid.")
        clean["handoff_email"] = email

    if "auto_reply_enabled" in changes:
        clean["auto_reply_enabled"] = bool(changes["auto_reply_enabled"])

    if "auto_reply_timeout_hours" in changes:
        try:
            hours = float(changes["auto_reply_timeout_hours"])
        except (TypeError, ValueError):
            raise ValueError("Auto-reply timeout must be a number of hours.")
        if not 0.25 <= hours <= 720:
            raise ValueError("Auto-reply timeout must be between 0.25 and 720 hours.")
        clean["auto_reply_timeout_hours"] = hours

    for key in ("followup_enabled", "escalation_enabled", "learning_enabled", "report_enabled"):
        if key in changes:
            clean[key] = bool(changes[key])

    if "followup_after_days" in changes:
        try:
            days = float(changes["followup_after_days"])
        except (TypeError, ValueError):
            raise ValueError("Follow-up delay must be a number of days.")
        if not 0.5 <= days <= 30:
            raise ValueError("Follow-up delay must be between 0.5 and 30 days.")
        clean["followup_after_days"] = days

    if "report_email" in changes:
        email = str(changes["report_email"] or "").strip()
        if email and not _EMAIL_RE.match(email):
            raise ValueError("Report email address is not valid.")
        clean["report_email"] = email

    if "report_frequency" in changes:
        if changes["report_frequency"] not in ("daily", "weekly"):
            raise ValueError("Report frequency must be 'daily' or 'weekly'.")
        clean["report_frequency"] = changes["report_frequency"]

    with get_db_connection() as conn:
        for key, value in clean.items():
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        conn.commit()
    return get_settings()
