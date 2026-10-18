import os
import re
import json
import asyncio
import logging
from dataclasses import dataclass
from models.schemas import EmailRequest, ClassificationResult
from provider import classify, generate, get_provider
from rag.retriever import retrieve_context


# ── Language configuration ────────────────────────────────────────────────────
# Add new languages here — no other code changes needed.
# Key: ISO 639-1 code.  Value: (human-readable label, greeting)

LANG_CONFIG: dict[str, dict] = {
    "en": {"label": "English",         "greeting": "Hi,"},
    "fi": {"label": "Finnish (Suomi)", "greeting": "Hei,"},
}

DEFAULT_LANG = "en"

VALID_CATEGORIES = {"sales", "inquiry", "billing", "support", "bug", "other"}
VALID_SEVERITIES = {"normal", "high", "critical"}

log = logging.getLogger(__name__)


def get_lang_info(lang: str) -> dict:
    """Return label + greeting for the given language code, defaulting to English."""
    return LANG_CONFIG.get(lang.lower(), LANG_CONFIG[DEFAULT_LANG])


def _known_greeting_starts() -> tuple[str, ...]:
    """All lowercase greeting strings used in startswith() checks."""
    return tuple(v["greeting"].lower() for v in LANG_CONFIG.values())


# ── Prompts ───────────────────────────────────────────────────────────────────

# CALL 1 — classification
CLASSIFY_PROMPT = """\
You are a professional email classifier for {company_desc}.

Analyze this incoming email and respond with ONLY valid JSON — no markdown, no explanation.

JSON format:
{{
  "category": "<sales|inquiry|billing|support|bug|other>",
  "severity": "<normal|high|critical>",
  "lang": "<en|fi>",
  "confidence": <1-5>,
  "auto_generated": <true|false>,
  "summary": "<one short sentence: what the sender wants>",
  "sender_name": "<the sender's name if they sign or state it, else empty>",
  "company": "<the sender's company if mentioned, else empty>",
  "mood": "<happy|neutral|frustrated|angry>",
  "customer_fact": "<one lasting fact worth remembering about this customer (services they use, size, plans), else empty>",
  "deal_signal": "<accept|reject|none>",
  "lead": {{
    "services": "<what they want to buy, if sales, else empty>",
    "websites": "<number of websites, if stated, else empty>",
    "mailboxes": "<number of mailboxes/users, if stated, else empty>",
    "storage": "<storage need, if stated, else empty>",
    "budget": "<budget, if stated, else empty>",
    "timeline": "<when they need it, if stated, else empty>"
  }}
}}

Category definitions:
- sales     : pricing, quotation, purchase, upgrade, demo request
- inquiry   : general questions, how-to, feature questions
- billing   : invoice, payment, refund, subscription
- support   : something not working (non-critical)
- bug       : reproducible technical issue with steps
- other     : anything else

Severity rules:
- critical  : server down, hacked, data breach, unauthorized access, complete outage
- high      : partial outage, billing dispute, service degraded
- normal    : everything else

Language:
- en : sender is writing in English
- fi : sender is writing in Finnish (Suomi)

auto_generated:
- true  : newsletters, job alerts, marketing/promotions, social-network or system
          notifications, receipts, no-reply senders — anything NOT written by a
          person expecting a reply from customer support
- false : a real person (customer or prospect) writing to us

confidence: how sure you are about the category (5 = certain).

mood: the sender's emotional tone — "frustrated" for repeated problems or
impatience, "angry" for hostile language, threats to leave, or demands.

lead: fill when category is "sales" or the sender has an open sales lead; leave every field empty otherwise.

deal_signal:
- accept : the sender clearly confirms they want to buy / proceed with an offer or
           plan we proposed ("let's go ahead", "we'll take the Business plan", "please set it up")
- reject : the sender clearly declines or chose another provider
- none   : anything else (questions, negotiating, thinking about it)
{lead_hint}
Email:
From: {sender}
Subject: {subject}
Body: {body}\
"""


# CALL 2 — generation
REPLY_PROMPT = """\
You are an experienced customer support agent for {company_desc}.
Write a reply to the customer email below. The reply must be specific to THIS
email — a generic "we received your message" reply is a failure.

RULES:
1. LANGUAGE : The customer wrote in {lang_label}. Reply in {lang_label} only.
2. GREETING : Start with exactly: {greeting}
3. SIGN-OFF : End with exactly: {company_name}
4. BE SPECIFIC: Restate what the customer is asking about in your own words and
   respond to each point they raised. Mention the concrete things they named
   (service, product, error message, domain, etc.).
5. USE THE KNOWLEDGE BASE: When the KNOWLEDGE BASE CONTEXT below covers the
   question, give the actual steps / answer from it. Keep its steps and URLs
   exactly as written. Only cite a URL for the topic it is documented for.
6. WHEN THE KNOWLEDGE BASE DOES NOT COVER IT:
   - Answer with general, widely-true guidance where that is safe and helpful
     (e.g. how DNS propagation works, clearing browser cache).
   - NEVER invent prices, discounts, delivery dates, account details, policies,
     URLs, phone numbers or promises.
   - For requests that need a human (quotations, refunds, account changes),
     say clearly what will happen next AND ask for the specific details the
     team will need to handle THIS request (e.g. for a quotation: which
     services, number of sites/domains, expected traffic, timeline).
7. GREETINGS / TESTS: If the email is only a greeting or test message, reply
   warmly and briefly and invite them to share their question.
8. FORMAT : Plain text, short paragraphs, numbered steps allowed. No markdown
   headings, no bold, no code fences, no placeholders like [name] or [date].
9. LENGTH : 60–200 words. Concise and warm, not robotic.
10. CUSTOMER PROFILE: If a customer profile is given, use it to personalise
   (their name, what they asked before) but never mention that you keep notes.
   If they seem frustrated, acknowledge it briefly and sincerely.

--- KNOWLEDGE BASE CONTEXT ---
{context}
--- END OF KNOWLEDGE BASE ---

{sales_block}{customer_profile}{thread_history}--- CUSTOMER EMAIL ---
From: {sender}
Subject: {subject}
Category (internal): {category} / severity {severity}
Body:
{body}
--- END OF CUSTOMER EMAIL ---

After the sign-off, add THREE final lines:
WAITING_FOR_CUSTOMER: yes   (if your reply asks the customer to send information or answer a question)
WAITING_FOR_CUSTOMER: no    (otherwise)
KB_COVERED: yes             (the customer asked a question and the KNOWLEDGE BASE CONTEXT answered it)
KB_COVERED: no              (the customer asked a question the KNOWLEDGE BASE CONTEXT does not answer)
KB_COVERED: not_needed      (no question needing knowledge: greetings, thanks, sending details, complaints)
QUOTED_PRICE: <number>      (the price of the ONE plan/offer your reply recommends, digits only, e.g. 199)
QUOTED_PRICE: none          (your reply quotes no price)

Reply (plain text only):\
"""


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class ProcessResult:
    category: str
    severity: str
    lang: str
    reply: str
    used_rag: bool
    confidence: int
    auto_generated: bool
    summary: str
    sender_name: str = ""
    company: str = ""
    mood: str = "neutral"
    customer_fact: str = ""
    lead: dict | None = None
    awaiting_customer: bool = False
    knowledge_gap: bool = False   # the customer asked something the knowledge base could not answer
    deal_signal: str = "none"     # accept | reject | none — the customer's answer to our offer
    quoted_price: float | None = None  # price our reply offered (from the QUOTED_PRICE marker)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _company_desc() -> str:
    return os.getenv("COMPANY_DESCRIPTION", "ArtCloud, a web hosting company")


def _parse_classification(raw: str, default_lang: str) -> dict:
    """Parse the classifier's JSON, falling back to safe defaults on any problem."""
    result = {
        "category": "other",
        "severity": "normal",
        "lang": default_lang,
        "confidence": 1,
        "auto_generated": False,
        "summary": "",
        "sender_name": "",
        "company": "",
        "mood": "neutral",
        "customer_fact": "",
        "lead": None,
        "deal_signal": "none",
    }

    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)

    start, end = raw.find("{"), raw.rfind("}")
    if start == -1:
        log.warning("Classifier returned no JSON: %r", raw[:200])
        return result

    fragment = raw[start:end + 1] if end > start else raw[start:] + "}"
    try:
        data = json.loads(fragment)
    except json.JSONDecodeError:
        log.warning("Classifier returned invalid JSON: %r", raw[:200])
        return result

    category = str(data.get("category", "other")).lower().strip()
    severity = str(data.get("severity", "normal")).lower().strip()
    lang     = str(data.get("lang", default_lang)).lower().strip()
    try:
        confidence = max(1, min(5, int(data.get("confidence", 1))))
    except (TypeError, ValueError):
        confidence = 1

    auto = data.get("auto_generated", False)
    if isinstance(auto, str):
        auto = auto.strip().lower() == "true"

    result.update(
        category=category if category in VALID_CATEGORIES else "other",
        severity=severity if severity in VALID_SEVERITIES else "normal",
        lang=lang if lang in LANG_CONFIG else default_lang,
        confidence=confidence,
        auto_generated=bool(auto),
        summary=str(data.get("summary", ""))[:300],
        sender_name=str(data.get("sender_name") or "")[:120],
        company=str(data.get("company") or "")[:120],
        mood=str(data.get("mood") or "neutral").lower() if str(data.get("mood") or "").lower() in
             ("happy", "neutral", "frustrated", "angry") else "neutral",
        customer_fact=str(data.get("customer_fact") or "")[:200],
        lead=data.get("lead") if isinstance(data.get("lead"), dict) else None,
        deal_signal=str(data.get("deal_signal") or "none").lower()
        if str(data.get("deal_signal") or "").lower() in ("accept", "reject") else "none",
    )
    return result


def _thread_history_block(thread_id: str | None, current_message_id: str | None) -> str:
    """Prior messages + our replies in the same thread, oldest first."""
    if not thread_id:
        return ""
    try:
        import logger as email_logger
        history = email_logger.get_thread_history(thread_id, limit=3)
    except Exception as th_err:
        log.warning("Could not load thread history for %s: %s", thread_id, th_err)
        return ""

    history = [h for h in history if h.get("message_id") != current_message_id]
    if not history:
        return ""

    lines = ["--- EARLIER MESSAGES IN THIS THREAD (oldest first) ---"]
    for h in history:
        lines.append(f"Customer subject: {h.get('subject')}")
        if h.get("original_body"):
            lines.append(f"Customer wrote: {h['original_body'][:600]}")
        if h.get("reply_preview"):
            lines.append(f"We replied: {h['reply_preview'][:600]}")
        lines.append("")
    lines.append("--- END OF EARLIER MESSAGES ---\n\n")
    return "\n".join(lines)


# ── Main pipeline ─────────────────────────────────────────────────────────────

SALES_MODE_RULES = """\
--- YOU ARE HANDLING THIS SALES LEAD ---
Act as a helpful sales consultant whose goal is to turn this enquiry into a sale:
- Recommend the ONE plan from the KNOWLEDGE BASE that best fits their stated needs,
  with its exact price from the knowledge base, and say briefly why it fits.
- If key details are missing to recommend a plan (websites, mailboxes, storage,
  timeline), ask for them in one short question.
- If they accepted an offer, thank them warmly and explain the next steps
  (we prepare the account / send the order confirmation). Do not re-pitch.
- If they hesitate, address the concern once; never pressure them.
- NEVER invent prices, discounts or plans that are not in the knowledge base.
  If the knowledge base has no prices, say the sales team will send the quote.
{lead_details}
--- END OF SALES INSTRUCTIONS ---

"""


async def write_reply(email: EmailRequest, c: dict, customer_profile: str = "", lead_details: str = "") -> dict:
    """
    Retrieval + reply generation (CALL 2). Returns the cleaned reply and the
    markers the model reported. `lead_details` switches on sales mode.
    """
    company_name = os.getenv("COMPANY_NAME", "Support Team")

    # Sales leads look up pricing articles; everything else searches by category.
    search_category = "sales" if lead_details else c["category"]
    context = await asyncio.to_thread(
        retrieve_context,
        f"{email.subject} {c.get('summary', '')} {email.body[:600]} {'plans prices pricing' if lead_details else ''}",
        c["lang"],
        4,
        search_category,
    )

    lang_info = get_lang_info(c["lang"])
    reply_prompt = REPLY_PROMPT.format(
        company_desc=_company_desc(),
        lang_label=lang_info["label"],
        greeting=lang_info["greeting"],
        company_name=company_name,
        context=context.strip() or "(No knowledge-base article matches this email.)",
        sales_block=SALES_MODE_RULES.format(lead_details=lead_details) if lead_details else "",
        customer_profile=customer_profile,
        thread_history=_thread_history_block(email.thread_id, email.message_id),
        sender=email.sender,
        subject=email.subject,
        category=c["category"],
        severity=c["severity"],
        body=email.body[:3000],
    )
    reply_raw = await asyncio.to_thread(generate, reply_prompt)
    reply_raw, awaiting = _split_waiting_marker(reply_raw)
    reply_raw, kb_covered = _split_kb_marker(reply_raw)
    reply_raw, quoted_price = _split_price_marker(reply_raw)
    return {
        "reply": clean_response(reply_raw, greeting=lang_info["greeting"], company_name=company_name),
        "used_rag": bool(context.strip()),
        "awaiting": awaiting,
        "kb_covered": kb_covered,
        "quoted_price": quoted_price,
    }


async def process_email_combined(
    email: EmailRequest, customer_profile: str = "", open_lead_details: str = "",
) -> ProcessResult:
    """
    Two-call pipeline.

    Call 1 — classify(): category, severity, language, mood, lead details, deal signal.
    Retrieval — knowledge-base context (vector search, or keyword fallback).
    Call 2 — generate(): writes the reply. Skipped for auto-generated mail and
             critical emails (those are escalated to a human instead).

    `open_lead_details` is set when the sender already has an open sales lead:
    their emails are then always treated as part of that lead.
    """
    default_lang = os.getenv("DEFAULT_LANG", DEFAULT_LANG)
    log.info("Processing email via provider: %s", get_provider())

    # ── CALL 1 — Classify ─────────────────────────────────────────────────────
    classify_prompt = CLASSIFY_PROMPT.format(
        company_desc=_company_desc(),
        sender=email.sender,
        subject=email.subject,
        body=email.body[:1500],
        lead_hint="\nNOTE: this sender has an open sales lead with us.\n" if open_lead_details else "",
    )
    raw = await asyncio.to_thread(classify, classify_prompt)
    c = _parse_classification(raw, default_lang)

    base = dict(
        category=c["category"], severity=c["severity"], lang=c["lang"], confidence=c["confidence"],
        auto_generated=c["auto_generated"], summary=c["summary"],
        sender_name=c["sender_name"], company=c["company"], mood=c["mood"],
        customer_fact=c["customer_fact"], lead=c["lead"], deal_signal=c["deal_signal"],
    )
    if c["auto_generated"] or c["severity"] == "critical":
        # No customer-facing reply is needed: automated mail is skipped and
        # critical mail is escalated to a human by the caller.
        return ProcessResult(reply="", used_rag=False, **base)

    # Sales mode for sales emails and for anyone with an open lead (unless it is a real problem report)
    is_lead = c["category"] == "sales" or (open_lead_details and c["category"] not in ("support", "bug"))
    lead_details = open_lead_details or ("(New lead — no details captured yet.)" if is_lead else "")

    # ── CALL 2 — Generate ─────────────────────────────────────────────────────
    w = await write_reply(email, c, customer_profile, lead_details if is_lead else "")
    return ProcessResult(
        reply=w["reply"], used_rag=w["used_rag"], awaiting_customer=w["awaiting"],
        knowledge_gap=w["kb_covered"] == "no", quoted_price=w["quoted_price"], **base,
    )


_PRICE_RE = re.compile(r"^\s*QUOTED_PRICE\s*:\s*([0-9][0-9 .,]*|none)\s*\S*\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_amount(text: str) -> float | None:
    """'1 299,00' / '1,299.00' / '199' → float."""
    t = text.strip().replace(" ", "")
    if not t or not t[0].isdigit():
        return None
    if "," in t and "." in t:
        t = t.replace(",", "") if t.rfind(".") > t.rfind(",") else t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", "") if re.search(r",\d{3}$", t) else t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _split_price_marker(text: str) -> tuple[str, float | None]:
    match = _PRICE_RE.search(text)
    if not match:
        return text, None
    value = None if match.group(1).lower() == "none" else _parse_amount(match.group(1))
    return _PRICE_RE.sub("", text).strip(), value


_MONEY_RE = re.compile(
    r"(?:€|\bEUR\b)\s?(\d[\d ,.]*\d|\d)|(\d[\d ,.]*\d|\d)\s?(?:€|\bEUR\b|\beuros?\b)",
    re.IGNORECASE,
)


def extract_price(text: str) -> float | None:
    """First money amount in a reply written by a person (e.g. an edited quote)."""
    match = _MONEY_RE.search(text or "")
    if not match:
        return None
    return _parse_amount(match.group(1) or match.group(2))


_WAITING_RE = re.compile(r"^\s*WAITING_FOR_CUSTOMER\s*:\s*(yes|no)\s*$", re.IGNORECASE | re.MULTILINE)


_KB_RE = re.compile(r"^\s*KB_COVERED\s*:\s*(yes|no|not_needed)\s*$", re.IGNORECASE | re.MULTILINE)


def _split_kb_marker(text: str) -> tuple[str, str]:
    match = _KB_RE.search(text)
    if match:
        return _KB_RE.sub("", text).strip(), match.group(1).lower()
    return text, "unknown"


def _split_waiting_marker(text: str) -> tuple[str, bool]:
    """Remove the WAITING_FOR_CUSTOMER line; fall back to 'ends with a question' if it is missing."""
    match = _WAITING_RE.search(text)
    if match:
        return _WAITING_RE.sub("", text).strip(), match.group(1).lower() == "yes"
    return text, "?" in text[-400:]


# ── Response cleaner ──────────────────────────────────────────────────────────

def clean_response(text: str, greeting: str, company_name: str) -> str:
    """
    Post-process the LLM reply:
    1. Strip markdown fences and bold markers.
    2. Replace a hallucinated greeting line (Dear X, Hello John, ...) with the configured one.
    3. Cut off any echoed prompt artifacts after the real reply.
    4. Ensure the company sign-off is present at the end.
    """
    # 1. Strip markdown
    text = re.sub(r"^```[a-z]*\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$",       "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = text.strip()

    # 2. Normalise the greeting line — only touch the first line, and only if it is short
    greeting_words = "Dear|Hi|Hello|Greetings|Hey|Hei|Moi|Hyvä"
    first_line, _, rest = text.partition("\n")
    if re.match(rf"^({greeting_words})\b", first_line, flags=re.IGNORECASE) and len(first_line) <= 60:
        text = rest.strip()
    if not text.lower().startswith(_known_greeting_starts()):
        text = f"{greeting}\n\n{text}"

    # 3. Cut off echoed prompt sections
    cutoffs = [
        "--- KNOWLEDGE BASE",
        "--- END",
        "--- CUSTOMER EMAIL",
        "--- EARLIER MESSAGES",
        "KNOWLEDGE BASE CONTEXT",
        "Customer Email:",
    ]
    for marker in cutoffs:
        idx = text.find(marker)
        if idx > 50:
            text = text[:idx]
    text = text.strip()

    # 4. Ensure sign-off is present (check last 120 chars)
    if company_name.lower() not in text[-120:].lower():
        text = f"{text}\n\n{company_name}"

    return text.strip()


# ── Backwards-compatibility alias ─────────────────────────────────────────────

async def generate_response(
    email: EmailRequest, classification: ClassificationResult
) -> tuple[str, bool]:
    result = await process_email_combined(email)
    return result.reply, result.used_rag
