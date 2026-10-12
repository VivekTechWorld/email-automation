from pydantic import BaseModel
from typing import Optional


class EmailRequest(BaseModel):
    sender: str
    subject: str
    body: str
    message_id: Optional[str] = None
    thread_id: Optional[str] = None


class ClassificationResult(BaseModel):
    category: str   # sales | inquiry | billing | support | bug | other
    severity: str   # normal | high | critical
    confidence: Optional[int] = None


class EmailResponse(BaseModel):
    alert: bool
    alert_email: Optional[str] = None
    category: str
    severity: str
    lang: Optional[str] = None          # ISO 639-1 code detected from the email
    sender: str
    subject: str
    reply_subject: str
    body: str
    original_body: str
    used_rag: bool = False
    status: str = "sent"                # sent | pending | approved | rejected
    confidence: Optional[int] = None
    log_id: Optional[int] = None


class ApproveReviewRequest(BaseModel):
    reply: Optional[str] = None


class RejectReviewRequest(BaseModel):
    reason: Optional[str] = None
