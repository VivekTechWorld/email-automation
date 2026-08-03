import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
KB_FILE = BASE_DIR / "data" / "knowledge_base" / "clean-artcloud-data.txt"
OUTPUT_FILE = BASE_DIR / "data" / "training" / "7b_kb_train.jsonl"

SYSTEM_PROMPT = """You are a professional customer support agent.
Analyze this customer email and respond with ONLY valid JSON.

JSON format:
{{
  "category": "<sales|inquiry|billing|support|bug|other>",
  "severity": "normal",
  "confidence": 5,
  "needs_context": false,
  "response": "<your full email reply>"
}}

Strict Rule: NEVER use placeholders like [Your Name]. Always sign off as: Support Team"""

def parse_kb():
    if not KB_FILE.exists():
        print(f"Error: {KB_FILE} not found")
        return []

    with open(KB_FILE, 'r') as f:
        content = f.read()

    # Split into situations (case insensitive)
    situations = re.split(r'[Cc]ustomer [sS]ituation \d+', content)
    
    training_data = []
    
    for sit in situations:
        if not sit.strip():
            continue
            
        # Extract message and response
        message_match = re.search(r'[Cc]ustomer [Mm]essage\n[“"](.+?)[”"]', sit, re.DOTALL)
        response_match = re.search(r'[Cc]ustomer [Ss]ervice [Rr]esponse\n(.+)', sit, re.DOTALL)
        
        if message_match and response_match:
            msg = message_match.group(1).strip()
            resp = response_match.group(1).strip()
            
            # Create the JSONL record
            # We assume "support" category for these technical KB items
            record = {
                "instruction": SYSTEM_PROMPT,
                "input": f"Customer Email:\nSubject: Assistance Needed\nBody: {msg}",
                "output": json.dumps({
                    "category": "support",
                    "severity": "normal",
                    "confidence": 5,
                    "needs_context": False,
                    "response": resp
                })
            }
            training_data.append(record)
            
    return training_data

def main():
    print(f"Parsing {KB_FILE}...")
    data = parse_kb()
    
    if not data:
        print("No situations found. Check the text format.")
        return

    print(f"Found {len(data)} scenarios. Writing to {OUTPUT_FILE}...")
    
    with open(OUTPUT_FILE, 'w') as f:
        for record in data:
            f.write(json.dumps(record) + '\n')
            
    print("Done! Data ready for 7B fine-tuning.")

if __name__ == "__main__":
    main()
