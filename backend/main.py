import os
import re
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from models.schemas import EmailRequest, EmailResponse
from generator import process_email_combined
from rag.indexer import ingest_documents

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "Backend starting — classify_model: %s | rag_model: %s",
        os.getenv("LLM_MODEL", "email-support-v2"),
        os.getenv("RAG_MODEL", "qwen2.5:7b"),
    )
    yield
    log.info("Backend shutting down.")


app = FastAPI(title="Email Auto-Reply API", version="1.0.0", lifespan=lifespan)

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
    }


@app.post("/process-email", response_model=EmailResponse)
async def process_email(email: EmailRequest):
    sender_email = extract_email_address(email.sender)
    email.sender = sender_email

    log.info("Processing email from=%s subject=%r", sender_email, email.subject)

    # ── Call 1 (classify) + Call 2 (generate) ───────────────────────
    category, severity, lang, reply_body, used_rag = await process_email_combined(email)
    log.info(
        "Classified: category=%s severity=%s lang=%s used_rag=%s",
        category, severity, lang, used_rag,
    )

    # ── Critical alert path ───────────────────────────────────────
    if severity == "critical":
        alert_email = os.getenv("ALERT_EMAIL", "realParthiv@gmail.com")
        company = os.getenv("COMPANY_NAME", "Support Team")
        log.warning("CRITICAL email detected from %s — alerting %s", sender_email, alert_email)

        return EmailResponse(
            alert=True,
            alert_email=alert_email,
            category=category,
            severity="critical",
            lang=lang,
            sender=sender_email,
            subject=email.subject,
            reply_subject=f"CRITICAL ALERT: {email.subject}",
            body=(
                f"A critical issue has been reported.\n\n"
                f"From: {sender_email}\n"
                f"Subject: {email.subject}\n\n"
                f"--- Original Message ---\n{email.body}\n\n"
                f"Immediate action may be required.\n\n{company}"
            ),
            original_body=email.body,
            used_rag=False,
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
    )


@app.post("/ingest")
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
