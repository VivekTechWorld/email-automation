"""
Prepares training data in the COMBINED format used by the backend.

The model is trained to handle ONE prompt that does BOTH:
  1. Classify the email (category + severity)
  2. Generate the response

This matches generator.py's COMBINED_PROMPT exactly so the fine-tuned
model is a perfect drop-in replacement for the base llama3.2:3b.

Input CSVs (place in ../data/training/):
  classification.csv  → email_subject, email_body, category, severity
  responses.csv       → email_subject, email_body, response

Output:
  combined_train.jsonl  → Alpaca format, ready for Colab fine-tuning

Usage:
    python prepare_dataset.py
"""

import csv
import json
from pathlib import Path

TRAINING_DIR = Path(__file__).parent.parent / "data" / "training"

# Must match COMBINED_PROMPT in backend/generator.py exactly
SYSTEM_PROMPT = (
    "You are a professional customer support agent.\n\n"
    "Analyze this customer email and respond with ONLY valid JSON — no markdown, no explanation.\n\n"
    "JSON format:\n"
    "{{\n"
    '  "category": "<sales|inquiry|billing|support|bug|other>",\n'
    '  "severity": "<normal|high|critical>",\n'
    '  "confidence": <1-5>,\n'
    '  "needs_context": <true if you need product docs to answer accurately>,\n'
    '  "response": "<your full email reply, or empty string if needs_context is true>"\n'
    "}}\n\n"
    "Severity rules:\n"
    "- critical: server down, hacked, data breach, unauthorized access, complete outage\n"
    "- high: partial outage, billing dispute, service degraded\n"
    "- normal: everything else"
)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_records() -> list[dict]:
    cls_rows  = read_csv(TRAINING_DIR / "classification.csv")
    resp_rows = read_csv(TRAINING_DIR / "responses.csv")

    # Index responses by (subject, first 60 chars of body) for matching
    resp_index = {}
    for r in resp_rows:
        key = (r.get("email_subject", "").strip(), r.get("email_body", "")[:60].strip())
        resp_index[key] = r.get("response", "").strip()

    records = []

    for row in cls_rows:
        subject  = row.get("email_subject", "").strip()
        body     = row.get("email_body", "").strip()
        category = row.get("category", "other").strip().lower()
        severity = row.get("severity", "normal").strip().lower()

        if not body:
            continue

        # Look for a matching response
        key      = (subject, body[:60])
        response = resp_index.get(key, "")

        needs_context = not bool(response)
        confidence    = 5 if response else 3

        output = json.dumps({
            "category":     category,
            "severity":     severity,
            "confidence":   confidence,
            "needs_context": needs_context,
            "response":     response,
        }, ensure_ascii=False)

        records.append({
            "instruction": SYSTEM_PROMPT,
            "input": f"Customer Email:\nFrom: customer@example.com\nSubject: {subject}\nBody: {body}",
            "output": output,
        })

    # Add response-only rows that didn't match classification
    cls_keys = {(r.get("email_subject","").strip(), r.get("email_body","")[:60].strip()) for r in cls_rows}
    for row in resp_rows:
        subject  = row.get("email_subject", "").strip()
        body     = row.get("email_body", "").strip()
        response = row.get("response", "").strip()
        key = (subject, body[:60])

        if key in cls_keys or not response:
            continue

        output = json.dumps({
            "category":     "support",
            "severity":     "normal",
            "confidence":   5,
            "needs_context": False,
            "response":     response,
        }, ensure_ascii=False)

        records.append({
            "instruction": SYSTEM_PROMPT,
            "input": f"Customer Email:\nFrom: customer@example.com\nSubject: {subject}\nBody: {body}",
            "output": output,
        })

    return records


def main():
    print("Preparing combined training dataset...\n")

    records = build_records()

    if not records:
        print("ERROR: No records found. Check that classification.csv and responses.csv exist.")
        return

    output_path = TRAINING_DIR / "combined_train.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"  Total records : {len(records)}")
    print(f"  Saved to      : {output_path}")
    print(f"\n  Sample record:")
    sample = records[0]
    print(f"    Input  : {sample['input'][:80]}...")
    print(f"    Output : {sample['output'][:80]}...")
    print("\nDone. Upload combined_train.jsonl to Google Colab.")


if __name__ == "__main__":
    main()
