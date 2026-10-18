"""
test_api.py — Comprehensive API Smoke Test Suite
=================================================
Validates:
1. Public route /health is accessible without authentication.
2. All protected routes strictly require Bearer token (reject 401 without or with invalid token).
3. Review queue endpoints (/logs/pending, /logs/{id}/approve, /logs/{id}/reject) require Bearer auth.
4. Protected endpoints succeed with valid API_KEY.
"""

import json
import os
import urllib.request
import urllib.error
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent / "backend" / ".env"
load_dotenv(dotenv_path=env_path)

API_KEY = os.environ["API_KEY"]  # read from backend/.env — never hard-code it
BASE_URL = os.getenv("API_URL", "http://localhost:8000")


def make_request(url, method="GET", body=None, token=None):
    headers = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    return req


def run_tests():
    print(f"=== Starting API Smoke Tests against {BASE_URL} ===\n")
    passed = 0
    total = 0

    # ── Test 1: Unauthenticated health check ──────────────────────────────────
    total += 1
    req = make_request(f"{BASE_URL}/health")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read())
            assert res.status == 200
            assert data.get("status") == "ok"
            print(" PASS: [Health] GET /health returns 200 without auth")
            passed += 1
    except Exception as e:
        print(f" FAIL: [Health] GET /health failed: {e}")

    # ── Test 2: Protected routes reject requests without Authorization header ──
    protected_endpoints = [
        ("GET",  f"{BASE_URL}/get-provider", None),
        ("POST", f"{BASE_URL}/set-provider", {"provider": "gemini"}),
        ("GET",  f"{BASE_URL}/logs", None),
        ("GET",  f"{BASE_URL}/stats", None),
        ("GET",  f"{BASE_URL}/logs/pending", None),
        ("POST", f"{BASE_URL}/logs/1/approve", {"reply": "looks good"}),
        ("POST", f"{BASE_URL}/logs/1/reject", {"reason": "spam"}),
        ("POST", f"{BASE_URL}/process-email", {"sender": "test@domain.com", "subject": "test", "body": "test"}),
    ]

    for method, url, body in protected_endpoints:
        total += 1
        endpoint_name = url.replace(BASE_URL, "")
        req = make_request(url, method=method, body=body, token=None)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                print(f" FAIL: [Auth-401] {method} {endpoint_name} returned {res.status} instead of 401")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print(f" PASS: [Auth-401] {method} {endpoint_name} rejected with 401 when missing token")
                passed += 1
            else:
                print(f" FAIL: [Auth-401] {method} {endpoint_name} returned HTTP {e.code} instead of 401")
        except Exception as e:
            print(f" FAIL: [Auth-401] {method} {endpoint_name} error: {e}")

    # ── Test 3: Protected routes reject invalid bearer token ─────────────────
    total += 1
    req = make_request(f"{BASE_URL}/get-provider", token="bad-invalid-token")
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            print(f" FAIL: [Auth-BadToken] /get-provider returned {res.status} instead of 401")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(" PASS: [Auth-BadToken] /get-provider rejected with 401 on invalid token")
            passed += 1
        else:
            print(f" FAIL: [Auth-BadToken] /get-provider returned HTTP {e.code}")
    except Exception as e:
        print(f" FAIL: [Auth-BadToken] /get-provider error: {e}")

    # ── Test 4: Protected routes succeed with valid Bearer token ───────────────
    valid_tests = [
        ("GET", f"{BASE_URL}/get-provider", None),
        ("GET", f"{BASE_URL}/logs?limit=5", None),
        ("GET", f"{BASE_URL}/stats", None),
        ("GET", f"{BASE_URL}/logs/pending", None),
    ]

    for method, url, body in valid_tests:
        total += 1
        endpoint_name = url.replace(BASE_URL, "")
        req = make_request(url, method=method, body=body, token=API_KEY)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                data = json.loads(res.read())
                assert res.status == 200
                print(f" PASS: [Auth-Valid] {method} {endpoint_name} succeeded with valid Bearer token")
                passed += 1
        except Exception as e:
            print(f" FAIL: [Auth-Valid] {method} {endpoint_name} failed with valid token: {e}")

    # ── Test 5: Review endpoints handle existing or nonexistent IDs ────────────
    total += 1
    req = make_request(f"{BASE_URL}/logs/999999/approve", method="POST", body={"reply": "ok"}, token=API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            print(f" FAIL: [Review-404] /logs/999999/approve returned {res.status} instead of 404")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(" PASS: [Review-404] /logs/999999/approve correctly returned 404 for missing record")
            passed += 1
        else:
            print(f" FAIL: [Review-404] returned HTTP {e.code}")
    except Exception as e:
        print(f" FAIL: [Review-404] error: {e}")

    print(f"\n=== Summary: {passed}/{total} tests passed ===")
    return passed == total


if __name__ == "__main__":
    run_tests()
