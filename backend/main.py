import os
import re
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path)

from typing import Optional
from models.schemas import (
    EmailRequest,
    EmailResponse,
    ApproveReviewRequest,
    RejectReviewRequest,
)
from generator import process_email_combined
from rag.indexer import ingest_documents
import provider as ai_provider
import logger as email_logger
from auth import require_api_key
from notifier import send_webhook_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "Backend starting — classify_model: %s | rag_model: %s | provider: %s",
        os.getenv("LLM_MODEL", "email-support-v2"),
        os.getenv("RAG_MODEL", "qwen2.5:7b"),
        ai_provider.get_provider(),
    )
    email_logger.init_logger()
    yield
    log.info("Backend shutting down.")


app = FastAPI(title="Email Auto-Reply API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_email_address(raw: str) -> str:
    """Handles 'Name <email@domain.com>' format and plain addresses."""
    match = re.search(r'<([^>]+)>', raw)
    return match.group(1).strip() if match else raw.strip()


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "classify_model": os.getenv("LLM_MODEL", "email-support-v2"),
        "rag_model": os.getenv("RAG_MODEL", "qwen2.5:7b"),
        "provider": ai_provider.get_provider(),
    }


# ── AI Provider Toggle ───────────────────────────────────────────────────────

@app.get("/get-provider", dependencies=[Depends(require_api_key)])
async def get_provider():
    """Returns the currently active AI provider."""
    return {
        "provider": ai_provider.get_provider(),
        "available": list(ai_provider.VALID_PROVIDERS),
    }


@app.post("/set-provider", dependencies=[Depends(require_api_key)])
async def set_provider(body: dict):
    """
    Switch AI provider at runtime — no restart needed.
    Body: { "provider": "local" | "gemini" }
    """
    new_provider = body.get("provider", "").strip().lower()
    if not new_provider:
        raise HTTPException(status_code=400, detail="Missing 'provider' field in request body.")
    try:
        result = ai_provider.set_provider(new_provider)
        log.info("Provider switched to: %s", result)
        return {"provider": result, "message": f"Switched to {result} successfully."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Email Processing ──────────────────────────────────────────────────────────

@app.post("/process-email", response_model=EmailResponse, dependencies=[Depends(require_api_key)])
async def process_email(email: EmailRequest):
    sender_email = extract_email_address(email.sender)
    email.sender = sender_email

    log.info("Processing email from=%s subject=%r", sender_email, email.subject)

    start_ms = int(time.time() * 1000)

    # ── Call 1 (classify) + Call 2 (generate) ───────────────────────
    category, severity, lang, reply_body, used_rag, confidence = await process_email_combined(email)

    processing_ms = int(time.time() * 1000) - start_ms

    log.info(
        "Classified: category=%s severity=%s lang=%s confidence=%s used_rag=%s provider=%s time=%dms",
        category, severity, lang, confidence, used_rag, ai_provider.get_provider(), processing_ms,
    )

    # ── Critical alert path ───────────────────────────────────────
    if severity == "critical":
        alert_email = os.getenv("ALERT_EMAIL", "realParthiv@gmail.com")
        company = os.getenv("COMPANY_NAME", "Support Team")
        log.warning("CRITICAL email detected from %s — alerting %s", sender_email, alert_email)

        alert_body = (
            f"A critical issue has been reported.\n\n"
            f"From: {sender_email}\n"
            f"Subject: {email.subject}\n\n"
            f"--- Original Message ---\n{email.body}\n\n"
            f"Immediate action may be required.\n\n{company}"
        )

        # Log the critical alert
        entry = await email_logger.log_email_event(
            sender=sender_email,
            subject=email.subject,
            category=category,
            severity="critical",
            lang=lang,
            used_rag=False,
            alert=True,
            reply_preview=alert_body,
            provider=ai_provider.get_provider(),
            processing_ms=processing_ms,
            status="sent",
        )

        await send_webhook_alert(
            event_type="critical",
            sender=sender_email,
            subject=email.subject,
            category=category,
            severity="critical",
            detail=alert_body,
            log_id=entry["id"],
        )

        return EmailResponse(
            alert=True,
            alert_email=alert_email,
            category=category,
            severity="critical",
            lang=lang,
            sender=sender_email,
            subject=email.subject,
            reply_subject=f"CRITICAL ALERT: {email.subject}",
            body=alert_body,
            original_body=email.body,
            used_rag=False,
            status="sent",
            confidence=confidence,
            log_id=entry["id"],
        )

    # ── Confidence threshold check for human review queue ─────────
    review_threshold = int(os.getenv("REVIEW_CONFIDENCE_THRESHOLD", os.getenv("MIN_CONFIDENCE_THRESHOLD", "2")))
    if confidence < review_threshold:
        log.warning(
            "Low confidence (%d < %d) for email from %s — queuing for human review (status=pending)",
            confidence, review_threshold, sender_email,
        )

        entry = await email_logger.log_email_event(
            sender=sender_email,
            subject=email.subject,
            category=category,
            severity=severity,
            lang=lang,
            used_rag=used_rag,
            alert=False,
            reply_preview=reply_body,
            provider=ai_provider.get_provider(),
            processing_ms=processing_ms,
            status="pending",
        )

        await send_webhook_alert(
            event_type="pending",
            sender=sender_email,
            subject=email.subject,
            category=category,
            severity=severity,
            detail=reply_body,
            log_id=entry["id"],
        )

        return EmailResponse(
            alert=False,
            category=category,
            severity=severity,
            lang=lang,
            sender=sender_email,
            subject=email.subject,
            reply_subject=f"Re: {email.subject}",
            body=reply_body,
            original_body=email.body,
            used_rag=used_rag,
            status="pending",
            confidence=confidence,
            log_id=entry["id"],
        )

    # ── Normal auto-send path ─────────────────────────────────────
    entry = await email_logger.log_email_event(
        sender=sender_email,
        subject=email.subject,
        category=category,
        severity=severity,
        lang=lang,
        used_rag=used_rag,
        alert=False,
        reply_preview=reply_body,
        provider=ai_provider.get_provider(),
        processing_ms=processing_ms,
        status="sent",
    )

    return EmailResponse(
        alert=False,
        category=category,
        severity=severity,
        lang=lang,
        sender=sender_email,
        subject=email.subject,
        reply_subject=f"Re: {email.subject}",
        body=reply_body,
        original_body=email.body,
        used_rag=used_rag,
        status="sent",
        confidence=confidence,
        log_id=entry["id"],
    )


# ── Analytics / Logs ──────────────────────────────────────────────────────────

@app.get("/logs", dependencies=[Depends(require_api_key)])
async def get_logs(limit: int = 200, status: Optional[str] = None):
    """Returns recent email processing logs for the dashboard, optionally filtered by status."""
    return {
        "logs": email_logger.get_logs(limit=limit, status=status),
        "total": email_logger.get_total_count(status=status),
    }


# ── Human Review Queue ────────────────────────────────────────────────────────

@app.get("/logs/pending", dependencies=[Depends(require_api_key)])
async def get_pending_reviews(limit: int = 100):
    """Returns email responses currently awaiting human review."""
    pending_items = email_logger.get_logs(limit=limit, status="pending")
    return {
        "pending": pending_items,
        "total": len(pending_items),
    }


@app.post("/logs/{log_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_log(log_id: int, body: Optional[ApproveReviewRequest] = None):
    """
    Approves a held draft reply, optionally updating the reply body, and marks it 'approved'.
    """
    item = email_logger.get_log_by_id(log_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Log entry #{log_id} not found.")

    edited_reply = body.reply if (body and body.reply) else None
    updated = email_logger.update_log_status(log_id=log_id, status="approved", updated_reply=edited_reply)
    log.info("Log #%d approved by reviewer.", log_id)
    return {
        "status": "approved",
        "message": f"Log #{log_id} approved.",
        "log": updated,
    }


@app.post("/logs/{log_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_log(log_id: int, body: Optional[RejectReviewRequest] = None):
    """
    Rejects a held draft reply and marks it 'rejected' (closed without sending).
    """
    item = email_logger.get_log_by_id(log_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Log entry #{log_id} not found.")

    updated = email_logger.update_log_status(log_id=log_id, status="rejected")
    log.info("Log #%d rejected by reviewer.", log_id)
    return {
        "status": "rejected",
        "message": f"Log #{log_id} rejected.",
        "log": updated,
    }


@app.get("/stats", dependencies=[Depends(require_api_key)])
async def get_stats():
    """Returns aggregated statistics for dashboard charts."""
    return email_logger.get_stats()


# ── Knowledge Base Ingestion ──────────────────────────────────────────────────

@app.post("/ingest", dependencies=[Depends(require_api_key)])
async def ingest(directory: str = None):
    """Ingest documents from the knowledge base directory into ChromaDB."""
    dir_path = directory or os.getenv("KNOWLEDGE_BASE_DIR", "../data/knowledge_base")
    log.info("Ingesting documents from: %s", dir_path)
    try:
        count = await ingest_documents(dir_path)
        return {"status": "ok", "chunks_ingested": count, "directory": dir_path}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.error("Ingest failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
