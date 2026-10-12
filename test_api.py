import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv

# Load env from backend/.env if available
env_path = Path(__file__).resolve().parent / "backend" / ".env"
load_dotenv(dotenv_path=env_path)

API_KEY = os.getenv("API_KEY", "changeme-secret-api-key-2026")
BASE_URL = os.getenv("API_URL", "http://localhost:8000")

def run_tests():
    print(f"Running API smoke tests against {BASE_URL}...\n")
    passed = 0
    total = 0

    # ── Test 1: /health is accessible without auth ─────────────────────────────
    total += 1
    req = urllib.request.Request(f"{BASE_URL}/health")
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
            assert res.status == 200
            assert data.get("status") == "ok"
            print(" PASS: /health returns 200 without auth")
            passed += 1
    except Exception as e:
        print(f" FAIL: /health failed: {e}")

    # ── Test 2: Protected routes reject request without auth (401) ─────────────
    protected_endpoints = [
        ("GET", f"{BASE_URL}/get-provider", None),
        ("GET", f"{BASE_URL}/logs", None),
        ("GET", f"{BASE_URL}/stats", None),
        ("POST", f"{BASE_URL}/process-email", json.dumps({"sender": "a@b.com", "subject": "hi", "body": "test"}).encode()),
    ]

    for method, url, body in protected_endpoints:
        total += 1
        headers = {"Content-Type": "application/json"} if body else {}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as res:
                print(f" FAIL: {method} {url} returned {res.status} instead of 401")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print(f" PASS: {method} {url} correctly rejected with 401 without auth")
                passed += 1
            else:
                print(f" FAIL: {method} {url} returned HTTP {e.code} instead of 401")
        except Exception as e:
            print(f" FAIL: {method} {url} error: {e}")

    # ── Test 3: Protected routes reject request with invalid key (401) ─────────
    total += 1
    req = urllib.request.Request(
        f"{BASE_URL}/get-provider",
        headers={"Authorization": "Bearer wrong-key"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req) as res:
            print(f" FAIL: /get-provider returned {res.status} instead of 401 with bad key")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(" PASS: /get-provider rejected with 401 when invalid Bearer token provided")
            passed += 1
        else:
            print(f" FAIL: /get-provider returned HTTP {e.code}")
    except Exception as e:
        print(f" FAIL: /get-provider error: {e}")

    # ── Test 4: Protected routes succeed with valid Bearer token ───────────────
    total += 1
    req = urllib.request.Request(
        f"{BASE_URL}/get-provider",
        headers={"Authorization": f"Bearer {API_KEY}"},
        method="GET"
    )
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read())
            assert res.status == 200
            assert "provider" in data
            print(f" PASS: /get-provider accepted with valid Bearer token (provider: {data['provider']})")
            passed += 1
    except Exception as e:
        print(f" FAIL: /get-provider failed with valid token: {e}")

    print(f"\nResults: {passed}/{total} tests passed.")

if __name__ == "__main__":
    run_tests()
