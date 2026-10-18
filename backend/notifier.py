"""
notifier.py — Unified Webhook Notification Service
===================================================
Sends notifications to Slack, Microsoft Teams, Discord, or generic webhooks
when an email enters 'pending' (human review needed) or 'critical' (urgent escalation) state.

Uses ALERT_WEBHOOK_URL from the environment.
"""

import os
import json
import logging
import urllib.request
import urllib.error
import asyncio

log = logging.getLogger(__name__)


def send_webhook_alert_sync(
    *,
    event_type: str,  # "critical" | "pending" | "handoff"
    sender: str,
    subject: str,
    category: str,
    severity: str,
    detail: str = "",
    log_id: int = 0,
):
    """
    Sends a formatted JSON alert to ALERT_WEBHOOK_URL if configured.
    Compatible with Slack, Teams incoming webhooks, and generic HTTP receivers.
    """
    webhook_url = os.getenv("ALERT_WEBHOOK_URL") or os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        log.info("No ALERT_WEBHOOK_URL configured — skipping external notification for %s event.", event_type)
        return False

    is_critical = event_type == "critical" or severity == "critical"
    if is_critical:
        title = "🚨 CRITICAL EMAIL ESCALATION"
    elif event_type == "escalation":
        title = "🔥 UNHAPPY CUSTOMER — PRIORITY"
    elif event_type == "handoff":
        title = f"🤝 {category.upper()} TEAM HANDOFF"
    else:
        title = "⏳ HUMAN REVIEW REQUIRED"
    
    text_message = (
        f"{title}\n"
        f"• Log ID: #{log_id}\n"
        f"• From: {sender}\n"
        f"• Subject: {subject}\n"
        f"• Category: {category} | Severity: {severity}\n"
        f"• Action: {'Immediate manual intervention required!' if is_critical else 'Drafted reply held in review queue for approval.'}\n"
    )
    if detail:
        text_message += f"\nSnippet:\n{detail[:250]}"

    payload = {
        "text": text_message,
        "event_type": event_type,
        "log_id": log_id,
        "sender": sender,
        "subject": subject,
        "category": category,
        "severity": severity,
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Email-Automation-Notifier/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            log.info("Webhook alert delivered successfully (HTTP %d)", resp.status)
            return True
    except urllib.error.URLError as e:
        log.warning("Failed to deliver webhook alert: %s", e)
        return False
    except Exception as e:
        log.warning("Unexpected error sending webhook alert: %s", e)
        return False


async def send_webhook_alert(
    *,
    event_type: str,
    sender: str,
    subject: str,
    category: str,
    severity: str,
    detail: str = "",
    log_id: int = 0,
):
    """Non-blocking asynchronous wrapper for sending webhook notifications."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: send_webhook_alert_sync(
            event_type=event_type,
            sender=sender,
            subject=subject,
            category=category,
            severity=severity,
            detail=detail,
            log_id=log_id,
        ),
    )
