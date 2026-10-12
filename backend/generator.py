import os
import re
import json
import logging
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

log = logging.getLogger(__name__)


def get_lang_info(lang: str) -> dict:
    """Return label + greeting for the given language code, defaulting to English."""
    return LANG_CONFIG.get(lang.lower(), LANG_CONFIG[DEFAULT_LANG])


def _known_greeting_starts() -> tuple[str, ...]:
    """All lowercase greeting strings used in startswith() checks."""
    return tuple(v["greeting"].lower() for v in LANG_CONFIG.values())


# ── Prompts ───────────────────────────────────────────────────────────────────

# CALL 1 — classification
# Focused on classification ONLY. No response generation (that's the generator's job).
CLASSIFY_PROMPT = """\
You are a professional email classifier for ArtCloud, a web hosting company.

Analyze this customer email and respond with ONLY valid JSON — no markdown, no explanation.

JSON format:
{{
  "category": "<sales|inquiry|billing|support|bug|other>",
  "severity": "<normal|high|critical>",
  "lang": "<en|fi>",
  "confidence": <1-5>,
  "needs_context": <true|false>
}}

Category definitions:
- sales     : pricing, purchase, upgrade, demo request
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
- en : customer is writing in English
- fi : customer is writing in Finnish (Suomi)

needs_context:
- true  : requires product documentation to answer accurately
- false : simple enough to answer without looking up documentation

Customer Email:
Subject: {subject}
Body: {body}\
"""


# CALL 2 — generation
# Receives language-matched context from ChromaDB.
RAG_PROMPT = """\
You are a professional customer support agent for ArtCloud, a web hosting company.

Write a helpful, professional reply to the customer email below.

STRICT RULES — you MUST follow ALL of them:
1. LANGUAGE    : The customer wrote in {lang_label}. Reply in {lang_label} ONLY.
2. GREETING    : Your reply MUST start with exactly this word: {greeting}
3. SIGN-OFF    : Your reply MUST end with exactly: {company_name}
4. CONTEXT ONLY: Use ONLY facts, steps, and URLs explicitly written in the
   KNOWLEDGE BASE CONTEXT block. If a specific answer is not there, do NOT
   fill the gap. Do NOT ask the customer for extra information (order numbers,
   account IDs, transaction dates, etc.) unless the knowledge base explicitly
   instructs you to do so.
5. NO INVENTION: When the context is absent or does not cover the customer's
   exact question, acknowledge their message and tell them the support team
   will review and follow up — nothing more.
6. NO MARKDOWN : Plain text only — no invented bullets, no JSON, no code
   fences, no placeholder text like [your name] or [date].
7. NO URL REPURPOSING: You may only reference a URL if the knowledge base
   explicitly associates it with the customer's exact topic. Do NOT reuse a
   URL found in the knowledge base for a different purpose than it is
   documented for (e.g. do not cite a theme-instructions URL as a pricing
   page).
8. COPY EXACT PHRASING: Whenever the knowledge base context contains exact
   troubleshooting steps, bullet points, or sample responses, copy their
   wording, grammar, and phrasing VERBATIM (word-for-word). Do NOT paraphrase,
   do NOT summarize, and do NOT invent new translations or wordings. This
   ensures grammatical correctness.
9. GREETINGS & PLEASANTRIES: If the customer's email is a general greeting,
   pleasantry, or testing message (e.g. "Hello, how are you?", "Hi there",
   "test", "how is it going"), do NOT apply any technical troubleshooting
   templates, steps, or error diagnostics from the context. Instead, write
   a warm, polite response in their language (e.g. wishing them a great day,
   thanking them for saying hello, and stating that the support team is at
   their service if they have any questions), followed by the required sign-off.

--- KNOWLEDGE BASE CONTEXT ---
{context}
--- END OF KNOWLEDGE BASE ---
{no_context_note}
Customer Email:
From: {sender}
Subject: {subject}
Body: {body}

Reply (plain text only):\
"""

# Injected into RAG_PROMPT when ChromaDB returns no relevant chunks.
NO_CONTEXT_NOTE = """
CRITICAL INSTRUCTION — NO KNOWLEDGE BASE CONTEXT WAS FOUND:
You MUST NOT invent, guess, or assume any technical steps, URLs, account
details, procedures, or product-specific information.
Your ONLY allowed action is to:
  1. Acknowledge the customer's message politely.
  2. Inform them that their request has been received and the support team
     will review it and follow up with them directly.
  3. Do NOT ask for any information (account numbers, dates, etc.).
  4. Do NOT suggest any external websites or workarounds.
  5. Do NOT apologise for issues you cannot confirm exist.
Write nothing beyond this. Any invented detail is strictly forbidden.
"""


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def process_email_combined(
    email: EmailRequest,
) -> tuple[str, str, str, str, bool, int]:
    """
    Two-call pipeline. Returns (category, severity, lang, reply_body, used_rag, confidence).

    Call 1 — classify():
        Determines category, severity, language, confidence, needs_context.
        Routes to Ollama or Gemini based on active provider.

    Call 2 — generate():
        Writes the actual reply.
        Uses ChromaDB context (language-filtered) when needs_context=True
        or confidence is below the threshold.
        If ChromaDB returns nothing → graceful fallback reply.
    """
    min_confidence   = int(os.getenv("MIN_CONFIDENCE_THRESHOLD", "2"))
    company_name     = os.getenv("COMPANY_NAME",             "Support Team")
    default_lang     = os.getenv("DEFAULT_LANG",             "en")

    active_provider = get_provider()
    log.info("Processing email via provider: %s", active_provider)

    # ── CALL 1 — Classify ─────────────────────────────────────────────────────
    classify_prompt = CLASSIFY_PROMPT.format(
        subject=email.subject,
        body=email.body[:800],
    )

    raw = classify(classify_prompt)

    # Strip markdown code fences some models add
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$",          "", raw, flags=re.MULTILINE)

    # Defaults
    category      = "other"
    severity      = "normal"
    lang          = default_lang
    confidence    = 1
    needs_context = True

    start = raw.find("{")
    if start != -1:
        try:
            fragment = raw[start:]
            # Repair common truncation: missing closing brace
            if fragment.count("{") > fragment.count("}"):
                fragment += "}"
            data          = json.loads(fragment)
            category      = data.get("category",      "other").lower().strip()
            severity      = data.get("severity",      "normal").lower().strip()
            lang          = data.get("lang",          default_lang).lower().strip()
            confidence    = int(data.get("confidence", 1))
            needs_context = bool(data.get("needs_context", True))
        except (json.JSONDecodeError, ValueError):
            needs_context = True

    # Validate enums
    if category not in {"sales", "inquiry", "billing", "support", "bug", "other"}:
        category = "other"
    if severity not in {"normal", "high", "critical"}:
        severity = "normal"
    if lang not in LANG_CONFIG:
        lang = default_lang

    # ── ChromaDB retrieval (conditional) ──────────────────────────────────────
    needs_rag = needs_context or (confidence < min_confidence)
    context   = ""
    used_rag  = False

    if needs_rag:
        context  = retrieve_context(
            query=f"{email.subject} {email.body[:400]}",
            lang=lang,
            n_results=4,
        )
        used_rag = True

    # ── CALL 2 — Generate ─────────────────────────────────────────────────────
    lang_info  = get_lang_info(lang)
    greeting   = lang_info["greeting"]
    lang_label = lang_info["label"]

    # Inject strict no-hallucination instruction when context is empty
    no_context_note = NO_CONTEXT_NOTE if not context.strip() else ""
    rag_prompt = RAG_PROMPT.format(
        lang_label=lang_label,
        greeting=greeting,
        company_name=company_name,
        context=context.strip() or "(No relevant context found.)",
        no_context_note=no_context_note,
        sender=email.sender,
        subject=email.subject,
        body=email.body[:1200],
    )

    reply_raw = generate(rag_prompt)

    reply = clean_response(
        reply_raw,
        greeting=greeting,
        company_name=company_name,
    )

    return category, severity, lang, reply, used_rag, confidence


# ── Response cleaner ──────────────────────────────────────────────────────────

def clean_response(text: str, greeting: str, company_name: str) -> str:
    """
    Post-process the LLM reply:
    1. Strip markdown fences.
    2. Remove hallucinated greeting lines (Dear X, Hi there, etc.).
    3. Ensure the reply starts with the correct language greeting.
    4. Cut off any hallucinated prompt artifacts after the real reply.
    5. Ensure the company sign-off is present at the end.
    """
    # 1. Strip markdown
    text = re.sub(r"^```[a-z]*\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$",       "", text, flags=re.MULTILINE)

    # 2. Remove hallucinated greeting lines like "Dear Customer," / "Hello John,"
    greeting_words = "|".join([
        "Dear", "Hi", "Hello", "Greetings", "Hei", "Moi", "Hyvä"
    ])
    text = re.sub(
        rf"^({greeting_words})[^\n]{{0,80}}?,\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip()

    # 3. Ensure correct greeting at start
    if not text.lower().startswith(_known_greeting_starts()):
        text = f"{greeting}\n\n{text}"

    # 4. Cut off hallucinated content after the reply ends
    CUTOFFS = [
        "--- KNOWLEDGE BASE",
        "--- END",
        "Customer Email:",
        "From: test@",
        "From: example@",
        "\n---",
        "Please respond",
        "\n\nNote:",
        "\n\nPlease note:",
        "KNOWLEDGE BASE CONTEXT",
    ]
    for marker in CUTOFFS:
        idx = text.find(marker)
        if idx > 50:
            text = text[:idx]
    text = text.strip()

    # 5. Remove any accidental duplicate greetings right before the sign-off at the end
    text = re.sub(
        rf"({greeting_words}),?\s+{re.escape(company_name)}$",
        company_name,
        text,
        flags=re.IGNORECASE
    )

    # 6. Ensure sign-off is present (check last 120 chars)
    if company_name.lower() not in text[-120:].lower():
        text = f"{text}\n\n{company_name}"

    return text.strip()


# ── Backwards-compatibility alias ─────────────────────────────────────────────

async def generate_response(
    email: EmailRequest, classification: ClassificationResult
) -> tuple[str, bool]:
    _, _, _, reply, used_rag, _ = await process_email_combined(email)
    return reply, used_rag
