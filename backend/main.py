import os
import re
import time
import asyncio
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
    LoginRequest,
    ArticleRequest,
    SettingsRequest,
    LeadUpdateRequest,
    CustomerUpdateRequest,
    SuggestionAcceptRequest,
)
from generator import process_email_combined, write_reply, extract_price
from rag.indexer import reindex_all, reindex_in_background
import provider as ai_provider
import logger as email_logger
import knowledge
import settings_store
import customers
import leads
import learning
import reports
from datetime import datetime, timezone
from auth import require_api_key, issue_session_token, check_dashboard_password, INSECURE_DEFAULTS
from notifier import send_webhook_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


def _warn_insecure_config():
    for var in ("API_KEY", "DASHBOARD_PASSWORD"):
        if os.getenv(var, "") in INSECURE_DEFAULTS:
            log.warning(
                "SECURITY: %s is empty or still the example value. "
                "Set a long random value in backend/.env before exposing this server.", var,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "Backend starting — provider: %s | model: %s",
        ai_provider.get_provider(),
        ai_provider.get_model_label(),
    )
    _warn_insecure_config()
    email_logger.init_logger()
    knowledge.init_knowledge_base()
    settings_store.init_settings()
    leads.init_leads()
    customers.init_customers()
    learning.init_learning()
    reports.init_reports()
    reindex_in_background()
    timer = asyncio.create_task(_auto_reply_loop())
    yield
    timer.cancel()
    log.info("Backend shutting down.")


FOLLOWUP_TEMPLATES = {
    "en": (
        "Hi,\n\nI'm just following up on my previous message about \"{subject}\". "
        "When you have a moment, could you reply with the details we asked for? "
        "Then we can continue helping you right away.\n\n"
        "If everything is already sorted, no reply is needed.\n\n{company}"
    ),
    "fi": (
        "Hei,\n\nPalaan vielä aiempaan viestiini aiheesta \"{subject}\". "
        "Voisitko vastata, kun ehdit, ja lähettää pyytämämme tiedot? "
        "Näin voimme jatkaa asian hoitamista heti.\n\n"
        "Jos asia on jo ratkennut, sinun ei tarvitse vastata.\n\n{company}"
    ),
}


def _seconds_since(iso: str) -> int:
    return int((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds())


async def _auto_reply_loop():
    """
    Every minute:
    - held emails nobody reviewed in time get the AI draft sent (auto-reply timer)
    - customers who never answered our question get one polite follow-up
    Both are delivered by n8n through GET /outbox.
    """
    while True:
        try:
            settings = settings_store.get_settings()
            if settings["auto_reply_enabled"]:
                promoted = await asyncio.to_thread(
                    email_logger.promote_expired_pending, settings["auto_reply_timeout_hours"]
                )
                for log_id in promoted:
                    item = email_logger.get_log_by_id(log_id)
                    leads.set_handler_for_log(log_id, "ai", _seconds_since(item["timestamp"]) if item else None)
                    if item and item.get("lead_id"):
                        leads.record_quote(item["lead_id"], item.get("quoted_price"))
                if promoted:
                    log.info("Auto-reply timeout reached for log(s) %s — queued for sending.", promoted)

            if settings["followup_enabled"]:
                company = os.getenv("COMPANY_NAME", "Support Team")
                for original in email_logger.due_followups(settings["followup_after_days"]):
                    template = FOLLOWUP_TEMPLATES.get(original["lang"], FOLLOWUP_TEMPLATES["en"])
                    subject = re.sub(r"^\s*re:\s*", "", original["subject"], flags=re.IGNORECASE)
                    new_id = email_logger.queue_followup(original, template.format(subject=subject, company=company))
                    log.info("Follow-up #%d queued for %s (no answer to #%d).", new_id, original["sender"], original["id"])
        except Exception:
            log.exception("Background automation loop failed")
        await asyncio.sleep(60)


_docs_enabled = os.getenv("ENABLE_API_DOCS", "true").lower() == "true"
app = FastAPI(
    title="Email Auto-Reply API",
    version="2.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
        if o.strip()
    ],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


def extract_email_address(raw: str) -> str:
    """Handles 'Name <email@domain.com>' format and plain addresses."""
    match = re.search(r'<([^>]+)>', raw)
    return match.group(1).strip() if match else raw.strip()


# Senders that never expect a reply — answering them just spams robots
_AUTOMATED_SENDER_RE = re.compile(
    r"(^|[._+-])(no-?reply|do-?not-?reply|notifications?|mailer-daemon|postmaster|bounce[s]?|"
    r"newsletter|news|alerts?|digest|jobs?|marketing|info-?noreply)([._+-]|@)",
    re.IGNORECASE,
)


def is_automated_sender(address: str) -> bool:
    local_part = address.split("@", 1)[0] + "@"
    return bool(_AUTOMATED_SENDER_RE.search(local_part))


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Dashboard login ──────────────────────────────────────────────────────────

@app.post("/auth/login")
async def login(body: LoginRequest):
    """Exchange the dashboard password for a short-lived session token."""
    if not check_dashboard_password(body.password):
        await asyncio.sleep(1.0)  # slow down brute-force attempts
        raise HTTPException(status_code=401, detail="Incorrect passphrase.")
    token, expires_at = issue_session_token()
    return {"token": token, "expires_at": expires_at}


# ── AI Provider Toggle ───────────────────────────────────────────────────────

@app.get("/get-provider", dependencies=[Depends(require_api_key)])
async def get_provider():
    """Returns the currently active AI provider."""
    return {
        "provider": ai_provider.get_provider(),
        "model": ai_provider.get_model_label(),
        "available": sorted(ai_provider.VALID_PROVIDERS),
    }


@app.post("/set-provider", dependencies=[Depends(require_api_key)])
async def set_provider(body: dict):
    """
    Switch AI provider at runtime — no restart needed.
    Body: { "provider": "local" | "gemini" }
    """
    new_provider = str(body.get("provider", "")).strip().lower()
    if not new_provider:
        raise HTTPException(status_code=400, detail="Missing 'provider' field in request body.")
    try:
        result = ai_provider.set_provider(new_provider)
        log.info("Provider switched to: %s", result)
        return {
            "provider": result,
            "model": ai_provider.get_model_label(),
            "message": f"Switched to {result} successfully.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Email Processing ──────────────────────────────────────────────────────────

async def _record(
    email: EmailRequest,
    *,
    status: str,
    category: str = "other",
    severity: str = "normal",
    lang: str = "en",
    reply: str = "",
    used_rag: bool = False,
    confidence: Optional[int] = None,
    alert: bool = False,
    review_reason: Optional[str] = None,
    summary: Optional[str] = None,
    processing_ms: Optional[int] = None,
    reply_subject: Optional[str] = None,
    handoff_email: Optional[str] = None,
    mood: Optional[str] = None,
    escalated: bool = False,
    awaiting_customer: bool = False,
    event_type: Optional[str] = None,
    quoted_price: Optional[float] = None,
) -> EmailResponse:
    """Persist the outcome, notify humans when needed, and build the API response."""
    entry = await email_logger.log_email_event(
        sender=email.sender,
        subject=email.subject,
        category=category,
        severity=severity,
        lang=lang,
        used_rag=used_rag,
        alert=alert,
        reply_preview=reply,
        provider=ai_provider.get_provider(),
        processing_ms=processing_ms,
        status=status,
        thread_id=email.thread_id,
        message_id=email.message_id,
        original_body=email.body,
        review_reason=review_reason,
        summary=summary,
        mood=mood,
        escalated=escalated,
        awaiting_customer=awaiting_customer and status == "sent",
        quoted_price=quoted_price,
    )

    if alert or status == "pending":
        await send_webhook_alert(
            event_type=event_type or ("critical" if alert else ("handoff" if handoff_email is not None else "pending")),
            sender=email.sender,
            subject=email.subject,
            category=category,
            severity=severity,
            detail=review_reason or reply,
            log_id=entry["id"],
        )

    return EmailResponse(
        alert=alert,
        alert_email=os.getenv("ALERT_EMAIL") if alert else None,
        category=category,
        severity=severity,
        lang=lang,
        sender=email.sender,
        subject=email.subject,
        reply_subject=reply_subject or _reply_subject(email.subject),
        body=reply,
        original_body=email.body,
        used_rag=used_rag,
        status=status,
        confidence=confidence,
        log_id=entry["id"],
        summary=summary,
        review_reason=review_reason,
        message_id=email.message_id,
        thread_id=email.thread_id,
        handoff_email=handoff_email or None,
        mood=mood,
        escalated=escalated or alert,
    )


_OWN_SUBJECT_RE = re.compile(
    r"^\s*(?:(?:re|fwd?):\s*)*(CRITICAL ALERT:|\[\w+ handoff\]|(daily|weekly) support & sales report)",
    re.IGNORECASE,
)


def _is_own_message(email: EmailRequest) -> bool:
    """True for alerts, handoff notices and reports this system sent to our own addresses."""
    settings = settings_store.get_settings()
    own = {
        a.strip().lower()
        for a in (
            os.getenv("SUPPORT_EMAIL", ""), os.getenv("ALERT_EMAIL", ""),
            settings.get("handoff_email", ""), settings.get("report_email", ""),
        )
        if a and "@" in a
    }
    return email.sender.lower() in own or bool(_OWN_SUBJECT_RE.match(email.subject or ""))


def _reply_subject(subject: str) -> str:
    return subject if re.match(r"^\s*re:", subject, re.IGNORECASE) else f"Re: {subject}"


@app.post("/process-email", response_model=EmailResponse, dependencies=[Depends(require_api_key)])
async def process_email(email: EmailRequest):
    email.sender = extract_email_address(email.sender)
    email.subject = (email.subject or "").strip() or "(no subject)"
    email.body = email.body or ""

    log.info("Processing email from=%s subject=%r", email.sender, email.subject)

    # ── Duplicate delivery guard (n8n retries / re-polls) ─────────────────
    existing = email_logger.find_by_message_id(email.message_id)
    if existing:
        log.info("Message %s already processed as log #%d — skipping.", email.message_id, existing["id"])
        return EmailResponse(
            alert=False, category=existing["category"], severity=existing["severity"],
            lang=existing["lang"], sender=email.sender, subject=email.subject,
            reply_subject=_reply_subject(email.subject), body="", original_body=email.body,
            status="skipped", log_id=existing["id"], review_reason="Duplicate delivery",
        )

    # ── Mail this system sent itself (alerts, team handoffs, reports) ─────
    # If ALERT_EMAIL / team / report addresses are the support inbox itself,
    # those messages land back in the inbox — answering them would loop forever.
    if _is_own_message(email):
        log.info("Skipping our own message from %s (%r)", email.sender, email.subject)
        return await _record(email, status="skipped", review_reason="Sent by this system or team — loop protection")

    # ── Automated / bulk mail: never auto-reply, don't spend LLM calls ────
    if email.is_bulk or is_automated_sender(email.sender):
        log.info("Skipping automated/bulk email from %s", email.sender)
        return await _record(email, status="skipped", review_reason="Automated or bulk sender")

    # The customer wrote again — stop waiting for an answer on earlier replies
    email_logger.customer_replied(email.thread_id, email.sender)

    open_lead = leads.open_lead_for(email.sender)

    start_ms = int(time.time() * 1000)
    try:
        result = await process_email_combined(
            email, customers.profile_block(email.sender), leads.lead_block(open_lead),
        )
    except Exception as e:
        # The email is already marked read in Gmail — keep it visible for a human
        # instead of returning a 500 and losing it.
        log.exception("AI processing failed for email from %s", email.sender)
        return await _record(
            email,
            status="pending",
            review_reason=f"AI processing failed — write the reply manually ({type(e).__name__})",
            processing_ms=int(time.time() * 1000) - start_ms,
        )
    processing_ms = int(time.time() * 1000) - start_ms

    log.info(
        "Classified: category=%s severity=%s lang=%s confidence=%s mood=%s auto=%s used_rag=%s time=%dms",
        result.category, result.severity, result.lang, result.confidence, result.mood,
        result.auto_generated, result.used_rag, processing_ms,
    )

    common = dict(
        category=result.category, severity=result.severity, lang=result.lang,
        confidence=result.confidence, summary=result.summary, processing_ms=processing_ms,
        mood=result.mood,
    )

    # ── Automated mail detected by the classifier (no profile, no lead) ───
    if result.auto_generated:
        return await _record(email, status="skipped", review_reason="Classified as automated mail", **common)

    # ── Customer profile (built from the same classification call) ────────
    customers.record_interaction(
        email=email.sender, name=result.sender_name, company=result.company, lang=result.lang,
        category=result.category, mood=result.mood, fact=result.customer_fact, summary=result.summary,
    )
    settings = settings_store.get_settings()

    # ── Critical alert path ───────────────────────────────────────────────
    if result.severity == "critical":
        customers.add_escalation(email.sender)
        alert_email = os.getenv("ALERT_EMAIL", "")
        if not alert_email:
            log.error("CRITICAL email from %s but ALERT_EMAIL is not set — queuing for review.", email.sender)
            return await _record(
                email, status="pending", escalated=True,
                review_reason="Critical issue — ALERT_EMAIL not configured", **common,
            )
        log.warning("CRITICAL email detected from %s — alerting %s", email.sender, alert_email)
        company = os.getenv("COMPANY_NAME", "Support Team")
        alert_body = (
            f"A critical issue has been reported.\n\n"
            f"From: {email.sender}\n"
            f"Subject: {email.subject}\n"
            f"Summary: {result.summary}\n\n"
            f"--- Original Message ---\n{email.body}\n\n"
            f"Immediate action may be required.\n\n{company}"
        )
        return await _record(
            email, status="sent", alert=True, reply=alert_body,
            reply_subject=f"CRITICAL ALERT: {email.subject}",
            review_reason="Critical severity — escalated", **common,
        )

    # ── Decide: auto-send or hold for a person ────────────────────────────
    timeout_note = (
        f" — AI replies automatically after {settings['auto_reply_timeout_hours']:g}h if not reviewed"
        if settings["auto_reply_enabled"] else ""
    )
    status, reason, handoff_email, escalated, event_type = "sent", None, None, False, None

    escalation = (
        customers.should_escalate(email.sender, result.mood, result.category, email.thread_id, result.summary)
        if settings["escalation_enabled"] else None
    )
    review_threshold = int(os.getenv("REVIEW_CONFIDENCE_THRESHOLD", "2"))

    # Sales emails, and anything from a customer with an open lead (except real
    # problem reports), belong to the lead — whatever the classifier called them.
    is_lead = result.category == "sales" or (open_lead is not None and result.category not in ("support", "bug"))
    lead_handler = (
        open_lead["handled_by"] if open_lead
        else ("human" if "sales" in settings["handoff_categories"] else "ai")
    )

    if escalation:
        log.warning("Escalating email from %s: %s", email.sender, escalation)
        customers.add_escalation(email.sender)
        status, escalated, event_type = "pending", True, "escalation"
        reason = f"Escalated: {escalation}{timeout_note}"
        if common["severity"] == "normal":
            common["severity"] = "high"
    elif is_lead:
        if lead_handler == "human":
            status, handoff_email = "pending", settings["handoff_email"]
            reason = f"Handed off to sales team{timeout_note}"
        else:
            status, reason = "sent", "AI is handling this sales lead"
    elif result.category in settings["handoff_categories"]:
        log.info("Handing %s email from %s to the team.", result.category, email.sender)
        status, handoff_email = "pending", settings["handoff_email"]
        reason = f"Handed off to {result.category} team{timeout_note}"
    elif email.has_attachments:
        status, reason = "pending", f"Email contains attachments{timeout_note}"
    elif result.confidence < review_threshold:
        status, reason = "pending", f"Low classifier confidence ({result.confidence}/5){timeout_note}"

    response = await _record(
        email, status=status, reply=result.reply, used_rag=result.used_rag,
        review_reason=reason, handoff_email=handoff_email, escalated=escalated,
        awaiting_customer=result.awaiting_customer, event_type=event_type,
        quoted_price=result.quoted_price, **common,
    )

    # ── Sales lead tracking ───────────────────────────────────────────────
    if is_lead:
        lead = leads.upsert_from_email(
            email=email.sender, name=result.sender_name, company=result.company,
            subject=email.subject, summary=result.summary, details=result.lead or {},
            log_id=response.log_id, handled_by="ai" if status == "sent" else "human",
        )
        email_logger.set_lead_id(response.log_id, lead["id"])
        if status == "sent":
            leads.set_first_response(lead["id"], processing_ms // 1000)
        response.lead_id = lead["id"]

        # The customer accepted or declined our offer → won (revenue) / lost
        closed = leads.apply_deal_signal(lead["id"], result.deal_signal)
        if closed:
            log.info("Lead #%d %s by the customer (%s).", lead["id"], closed, email.sender)
        elif status == "sent" and result.quoted_price:
            # The AI's reply offered a price and went out now → quote sent
            leads.record_quote(lead["id"], result.quoted_price)

    # ── Knowledge gap: a real question the knowledge base could not answer ─
    if result.knowledge_gap:
        learning.record_gap(
            question=result.summary or email.subject, category=result.category,
            lang=result.lang, log_id=response.log_id,
        )

    return response


# ── Analytics / Logs ──────────────────────────────────────────────────────────

@app.get("/logs", dependencies=[Depends(require_api_key)])
async def get_logs(limit: int = 200, status: Optional[str] = None):
    """Returns recent email processing logs for the dashboard, optionally filtered by status."""
    limit = max(1, min(limit, 1000))
    return {
        "logs": email_logger.get_logs(limit=limit, status=status),
        "total": email_logger.get_total_count(status=status),
    }


# ── Human Review Queue ────────────────────────────────────────────────────────

@app.get("/logs/pending", dependencies=[Depends(require_api_key)])
async def get_pending_reviews(limit: int = 100):
    """Returns email responses currently awaiting human review."""
    limit = max(1, min(limit, 1000))
    return {
        "pending": email_logger.get_logs(limit=limit, status="pending"),
        "total": email_logger.get_total_count(status="pending"),
    }


@app.post("/logs/{log_id}/approve", dependencies=[Depends(require_api_key)])
async def approve_log(log_id: int, body: Optional[ApproveReviewRequest] = None):
    """
    Approves a held draft reply (optionally edited) and marks it 'approved'.
    n8n picks approved replies up from GET /outbox and sends them.
    """
    item = email_logger.get_log_by_id(log_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Log entry #{log_id} not found.")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Log #{log_id} is '{item['status']}', not pending.")

    edited_reply = body.reply.strip() if (body and body.reply) else None
    if not (edited_reply or item.get("reply_preview")):
        raise HTTPException(status_code=400, detail="Reply text is empty — write a reply before approving.")

    updated = email_logger.update_log_status(log_id=log_id, status="approved", updated_reply=edited_reply)
    log.info("Log #%d approved by reviewer.", log_id)
    leads.set_handler_for_log(log_id, "human", _seconds_since(item["timestamp"]))
    if item.get("lead_id"):
        # A price in the reply the team approved means a quote was sent
        unchanged = edited_reply is None or edited_reply == item.get("reply_preview")
        price = extract_price(updated["reply_preview"]) or (item.get("quoted_price") if unchanged else None)
        leads.record_quote(item["lead_id"], price)

    # Self-learning: turn the approved answer into a suggested article (background, one AI call)
    if settings_store.get_settings()["learning_enabled"] and not item["alert"]:
        asyncio.create_task(asyncio.to_thread(
            learning.create_suggestion_from_approval,
            log_item=item,
            approved_reply=updated["reply_preview"],
            lang=item["lang"],
            company_desc=os.getenv("COMPANY_DESCRIPTION", "ArtCloud, a web hosting company"),
        ))
    return {"status": "approved", "message": f"Log #{log_id} approved and queued for sending.", "log": updated}


@app.post("/logs/{log_id}/reject", dependencies=[Depends(require_api_key)])
async def reject_log(log_id: int, body: Optional[RejectReviewRequest] = None):
    """Rejects a held draft reply and marks it 'rejected' (closed without sending)."""
    item = email_logger.get_log_by_id(log_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Log entry #{log_id} not found.")
    if item["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Log #{log_id} is '{item['status']}', not pending.")

    updated = email_logger.update_log_status(log_id=log_id, status="rejected")
    leads.set_handler_for_log(log_id, "human")
    log.info("Log #%d rejected by reviewer.", log_id)
    return {"status": "rejected", "message": f"Log #{log_id} rejected.", "log": updated}


# ── Outbox (approved replies waiting to be sent by n8n) ──────────────────────

@app.get("/outbox", dependencies=[Depends(require_api_key)])
async def get_outbox(limit: int = 50):
    items = email_logger.claim_outbox(limit=max(1, min(limit, 200)))
    return {
        "items": [
            {
                "log_id": i["id"],
                "sender": i["sender"],
                "message_id": i["message_id"],
                "thread_id": i["thread_id"],
                "reply_subject": _reply_subject(i["subject"]),
                "body": i["reply_preview"],
            }
            for i in items
        ]
    }


@app.post("/outbox/{log_id}/delivered", dependencies=[Depends(require_api_key)])
async def mark_delivered(log_id: int):
    item = email_logger.get_log_by_id(log_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Log entry #{log_id} not found.")
    return {"log": email_logger.mark_delivered(log_id)}


@app.get("/stats", dependencies=[Depends(require_api_key)])
async def get_stats():
    """Returns aggregated statistics for dashboard charts."""
    return email_logger.get_stats()


# ── Knowledge Base (managed from the dashboard) ──────────────────────────────

@app.get("/kb/articles", dependencies=[Depends(require_api_key)])
async def kb_list(category: Optional[str] = None):
    return {"articles": knowledge.list_articles(category), "usage": knowledge.usage(), "learning": learning.counts()}


@app.get("/kb/articles/{article_id}", dependencies=[Depends(require_api_key)])
async def kb_get(article_id: int):
    article = knowledge.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")
    return article


@app.post("/kb/articles", dependencies=[Depends(require_api_key)])
async def kb_create(body: ArticleRequest):
    try:
        article = knowledge.create_article(**body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    reindex_in_background()
    return {"article": article, "usage": knowledge.usage()}


@app.put("/kb/articles/{article_id}", dependencies=[Depends(require_api_key)])
async def kb_update(article_id: int, body: ArticleRequest):
    try:
        article = knowledge.update_article(article_id, **body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not article:
        raise HTTPException(status_code=404, detail="Article not found.")
    reindex_in_background()
    return {"article": article, "usage": knowledge.usage()}


@app.delete("/kb/articles/{article_id}", dependencies=[Depends(require_api_key)])
async def kb_delete(article_id: int):
    if not knowledge.delete_article(article_id):
        raise HTTPException(status_code=404, detail="Article not found.")
    reindex_in_background()
    return {"deleted": article_id, "usage": knowledge.usage()}


@app.post("/ingest", dependencies=[Depends(require_api_key)])
async def ingest():
    """Rebuild the ChromaDB vector index from the knowledge-base articles (local mode only)."""
    try:
        count = await asyncio.to_thread(reindex_all)
        return {"status": "ok", "chunks_indexed": count}
    except Exception:
        log.exception("Reindex failed")
        raise HTTPException(status_code=500, detail="Reindex failed — see server logs.")


# ── Automation settings ──────────────────────────────────────────────────────

@app.get("/settings", dependencies=[Depends(require_api_key)])
async def get_settings():
    return {"settings": settings_store.get_settings(), "handoff_choices": settings_store.HANDOFF_CHOICES}


@app.put("/settings", dependencies=[Depends(require_api_key)])
async def put_settings(body: SettingsRequest):
    try:
        updated = settings_store.update_settings(body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"settings": updated, "handoff_choices": settings_store.HANDOFF_CHOICES}


# ── Self-learning: suggestions & knowledge gaps ──────────────────────────────

@app.get("/kb/suggestions", dependencies=[Depends(require_api_key)])
async def kb_suggestions():
    return {"suggestions": learning.list_suggestions(), "counts": learning.counts()}


@app.post("/kb/suggestions/{sid}/accept", dependencies=[Depends(require_api_key)])
async def kb_accept_suggestion(sid: int, body: Optional[SuggestionAcceptRequest] = None):
    sug = learning.get_suggestion(sid)
    if not sug or sug["status"] != "pending":
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    edits = body.model_dump(exclude_none=True) if body else {}
    try:
        article = knowledge.create_article(
            title=edits.get("title", sug["title"]),
            category=edits.get("category", sug["category"]),
            lang=sug["lang"],
            content=edits.get("content", sug["content"]),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    learning.set_suggestion_status(sid, "accepted")
    reindex_in_background()
    return {"article": article, "counts": learning.counts(), "usage": knowledge.usage()}


@app.post("/kb/suggestions/{sid}/discard", dependencies=[Depends(require_api_key)])
async def kb_discard_suggestion(sid: int):
    if not learning.get_suggestion(sid):
        raise HTTPException(status_code=404, detail="Suggestion not found.")
    learning.set_suggestion_status(sid, "discarded")
    return {"counts": learning.counts()}


@app.get("/kb/gaps", dependencies=[Depends(require_api_key)])
async def kb_gaps():
    return {"gaps": learning.list_gaps(), "counts": learning.counts()}


@app.post("/kb/gaps/{gap_id}/resolve", dependencies=[Depends(require_api_key)])
async def kb_resolve_gap(gap_id: int):
    if not learning.resolve_gap(gap_id):
        raise HTTPException(status_code=404, detail="Question not found.")
    return {"counts": learning.counts()}


# ── Customers ────────────────────────────────────────────────────────────────

@app.get("/customers", dependencies=[Depends(require_api_key)])
async def list_customers(search: str = ""):
    return {"customers": customers.list_customers(search.strip())}


@app.get("/customers/{email}", dependencies=[Depends(require_api_key)])
async def get_customer(email: str):
    c = customers.get_customer(email)
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return {
        "customer": c,
        "emails": email_logger.get_logs_for_sender(email, limit=20),
        "leads": [l for l in leads.list_leads() if l["customer_email"] == email.lower()],
    }


@app.patch("/customers/{email}", dependencies=[Depends(require_api_key)])
async def patch_customer(email: str, body: CustomerUpdateRequest):
    c = customers.update_customer(email, **body.model_dump(exclude_none=True))
    if not c:
        raise HTTPException(status_code=404, detail="Customer not found.")
    return {"customer": c}


@app.delete("/customers/{email}", dependencies=[Depends(require_api_key)])
async def erase_customer(email: str):
    """GDPR erase — profile, leads and all stored emails from this sender."""
    if not customers.delete_customer(email):
        raise HTTPException(status_code=404, detail="Customer not found.")
    log.info("Customer data erased on request: %s", email)
    return {"deleted": email}


# ── Sales leads ──────────────────────────────────────────────────────────────

@app.get("/leads", dependencies=[Depends(require_api_key)])
async def list_leads(stage: Optional[str] = None, handled_by: Optional[str] = None):
    return {"leads": leads.list_leads(stage, handled_by)}


@app.get("/leads/metrics", dependencies=[Depends(require_api_key)])
async def lead_metrics(days: int = 30):
    return leads.metrics(days=max(7, min(days, 90)))


@app.patch("/leads/{lead_id}", dependencies=[Depends(require_api_key)])
async def patch_lead(lead_id: int, body: LeadUpdateRequest):
    before = leads.get_lead(lead_id)
    try:
        lead = leads.update_lead(lead_id, body.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found.")

    takeover = None
    if body.handled_by == "ai" and before["handled_by"] != "ai" and lead["stage"] not in ("won", "lost"):
        takeover = await _ai_take_over(lead)
    return {"lead": leads.get_lead(lead_id), "takeover": takeover}


async def _ai_take_over(lead: dict) -> dict:
    """
    The team handed a lead to the AI. If the customer's latest email is still
    waiting in the review queue, the AI answers it now in sales mode (one AI call)
    and older waiting drafts for this customer are closed so nobody is answered twice.
    """
    waiting = [
        l for l in email_logger.get_logs_for_sender(lead["customer_email"], limit=20)
        if l["status"] == "pending" and l.get("message_id")
    ]
    if not waiting:
        return {"sent": False, "message": "No unanswered email — the AI will answer this customer's next email."}

    latest = waiting[0]  # newest first
    msg = EmailRequest(
        sender=latest["sender"], subject=latest["subject"], body=latest.get("original_body") or "",
        thread_id=latest.get("thread_id"), message_id=latest.get("message_id"),
    )
    classification = {
        "category": latest["category"], "severity": latest["severity"],
        "lang": latest["lang"], "summary": latest.get("summary") or "",
    }
    try:
        w = await write_reply(
            msg, classification, customers.profile_block(lead["customer_email"]), leads.lead_block(lead),
        )
    except Exception as e:
        log.exception("AI takeover failed for lead #%d", lead["id"])
        return {"sent": False, "message": f"AI could not write the reply ({type(e).__name__}) — try again."}

    with email_logger.get_db_connection() as conn:
        conn.execute(
            "UPDATE email_logs SET reply_preview = ?, status = 'auto_approved', quoted_price = ?, "
            "awaiting_customer = ?, lead_id = ?, review_reason = 'AI took over this sales lead' WHERE id = ?",
            (w["reply"], w["quoted_price"], 1 if w["awaiting"] else 0, lead["id"], latest["id"]),
        )
        for older in waiting[1:]:
            conn.execute(
                "UPDATE email_logs SET status = 'rejected', review_reason = 'Superseded — AI answered the newer email' "
                "WHERE id = ?", (older["id"],),
            )
        conn.commit()
    leads.set_first_response(lead["id"], _seconds_since(latest["timestamp"]))
    leads.record_quote(lead["id"], w["quoted_price"])
    log.info("AI took over lead #%d and answered log #%d.", lead["id"], latest["id"])
    return {
        "sent": True, "log_id": latest["id"], "quoted_price": w["quoted_price"],
        "message": "AI took over — its reply is being sent to the customer now.",
    }


# ── Reports ──────────────────────────────────────────────────────────────────

@app.get("/reports/summary", dependencies=[Depends(require_api_key)])
async def report_summary(days: int = 7):
    return reports.build_report(days=max(1, min(days, 90)))


@app.get("/reports/insights", dependencies=[Depends(require_api_key)])
async def report_insights(days: int = 7, refresh: bool = False):
    report = reports.build_report(days=max(1, min(days, 90)))
    return await asyncio.to_thread(reports.insights, report, refresh)


@app.get("/reports/email", dependencies=[Depends(require_api_key)])
async def report_email(force: bool = False):
    """
    Called by n8n every morning. Returns {send: false} unless a report is due
    (enabled, recipient set, right day, not already sent today) — or force=true.
    """
    settings = settings_store.get_settings()
    today = datetime.now(timezone.utc).date()
    due = (
        settings["report_enabled"] and settings["report_email"]
        and (settings["report_frequency"] == "daily" or today.weekday() == 0)
        and reports.get_cache("report:last_sent") != today.isoformat()
    )
    if not (due or (force and settings["report_email"])):
        return {"send": False}

    days = 1 if settings["report_frequency"] == "daily" else 7
    report = reports.build_report(days=days)
    summary = await asyncio.to_thread(reports.insights, report, False)
    company = os.getenv("COMPANY_NAME", "Support Team")
    return {
        "send": True,
        "to": settings["report_email"],
        "subject": f"{'Daily' if days == 1 else 'Weekly'} support & sales report — {today.isoformat()}",
        "html": reports.email_html(report, summary, company),
    }


@app.post("/reports/sent", dependencies=[Depends(require_api_key)])
async def report_sent():
    reports.set_cache("report:last_sent", datetime.now(timezone.utc).date().isoformat())
    return {"ok": True}
