import urllib.request
import json

data = json.dumps({
    "sender": "test@example.com",
    "subject": "Charged twice this month",
    "body": "I was charged twice this month. Please refund the duplicate charge."
}).encode()

req = urllib.request.Request(
    "http://localhost:8000/process-email",
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST"
)

with urllib.request.urlopen(req) as r:
    print(json.dumps(json.loads(r.read()), indent=2))
