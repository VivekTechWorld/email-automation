from pydantic import BaseModel
from typing import Optional


class EmailRequest(BaseModel):
    sender: str
    subject: str
    body: str
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    has_attachments: Optional[bool] = False
    # Set by n8n when Gmail headers/labels mark the message as bulk mail
    # (List-Unsubscribe, Precedence: bulk, Promotions/Social/Updates tabs).
    is_bulk: Optional[bool] = False


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
    status: str = "sent"                # sent | pending | approved | rejected | skipped | failed
    confidence: Optional[int] = None
    log_id: Optional[int] = None
    summary: Optional[str] = None
    review_reason: Optional[str] = None
    message_id: Optional[str] = None
    thread_id: Optional[str] = None
    handoff_email: Optional[str] = None   # set when the email was handed to a human team
    mood: Optional[str] = None
    escalated: bool = False
    lead_id: Optional[int] = None


class ApproveReviewRequest(BaseModel):
    reply: Optional[str] = None


class RejectReviewRequest(BaseModel):
    reason: Optional[str] = None


class LoginRequest(BaseModel):
    password: str


class ArticleRequest(BaseModel):
    title: str
    category: str = "general"
    lang: str = "en"
    content: str


class SettingsRequest(BaseModel):
    handoff_categories: Optional[list[str]] = None
    handoff_email: Optional[str] = None
    auto_reply_enabled: Optional[bool] = None
    auto_reply_timeout_hours: Optional[float] = None
    followup_enabled: Optional[bool] = None
    followup_after_days: Optional[float] = None
    escalation_enabled: Optional[bool] = None
    learning_enabled: Optional[bool] = None
    report_enabled: Optional[bool] = None
    report_email: Optional[str] = None
    report_frequency: Optional[str] = None


class LeadUpdateRequest(BaseModel):
    stage: Optional[str] = None
    handled_by: Optional[str] = None
    owner: Optional[str] = None
    value: Optional[float] = None
    name: Optional[str] = None
    company: Optional[str] = None
    services: Optional[str] = None
    websites: Optional[str] = None
    mailboxes: Optional[str] = None
    storage: Optional[str] = None
    budget: Optional[str] = None
    timeline: Optional[str] = None


class CustomerUpdateRequest(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None


class SuggestionAcceptRequest(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
