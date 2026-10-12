"""
ARCHIVED / LEGACY MODULE
========================
This module is unreferenced legacy code and is superseded by backend/generator.py
(process_email_combined) which unifies email classification and reply generation.
Retained for reference only.
"""

import ollama
import json
import re
import os
from models.schemas import EmailRequest, ClassificationResult


CLASSIFY_PROMPT = """Classify this customer email. Return ONLY valid JSON — no explanation, no markdown.

JSON format:
{{"category": "<category>", "severity": "<severity>"}}

Categories:
- sales       : pricing, purchase, upgrade, demo request
- inquiry     : general questions, how-to, feature questions
- billing     : invoice, payment, refund, subscription
- support     : bug, error, something not working (non-critical)
- bug         : reproducible technical issue with steps
- other       : anything that doesn't fit above

Severity:
- critical    : server down, system hacked, unauthorized access, data breach, data loss, complete outage
- high        : partial outage, service degraded, billing dispute, SLA breach concern
- normal      : everything else

Email Subject: {subject}
Email Body (first 600 chars): {body}"""


async def classify_email(email: EmailRequest) -> ClassificationResult:
    model = os.getenv("LLM_MODEL", "llama3.2:3b")

    response = ollama.chat(
        model=model,
        messages=[{
            "role": "user",
            "content": CLASSIFY_PROMPT.format(
                subject=email.subject,
                body=email.body[:600]
            )
        }],
        options={"temperature": 0}
    )

    text = response["message"]["content"].strip()

    json_match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            category = data.get("category", "other").lower().strip()
            severity = data.get("severity", "normal").lower().strip()

            valid_categories = {"sales", "inquiry", "billing", "support", "bug", "other"}
            valid_severities = {"normal", "high", "critical"}

            return ClassificationResult(
                category=category if category in valid_categories else "other",
                severity=severity if severity in valid_severities else "normal",
            )
        except json.JSONDecodeError:
            pass

    return ClassificationResult(category="other", severity="normal")
