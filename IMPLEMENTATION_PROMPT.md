# IMPLEMENTATION_PROMPT.md

Single high-level prompt for a coding agent (e.g. Claude Code) to implement the approved feature set for the Email Automation System. Execute in the phase order below — do not implement out of order; later phases depend on earlier ones.

---

## Context to give the agent

This is an existing FastAPI + React + n8n email automation system. It polls Gmail, classifies incoming support emails with an LLM, optionally grounds replies in a ChromaDB knowledge base, and auto-sends replies or escalates critical issues. It currently has no authentication and no human review step before AI replies are sent — fixing both is the top priority before any other feature work.

---

## Phase 0 — Security foundation (blocking, do first)

### Task 1: API Key Authentication

- Add a FastAPI dependency checking a bearer token (`API_KEY` env var) on every route except `/health`.
- Update `backend/main.py` to apply it via `Depends()`.
- Update the n8n HTTP Request node to send the `Authorization` header.
- Update `frontend/src/api.js` to send the same header on every fetch call.
- **Acceptance**: a request without the header returns `401` on every protected route.

### Task 2: Dashboard Login Screen

- Add a login gate to the React dashboard, separate from the API key.
- A shared passphrase is sufficient for this stage.
- **Acceptance**: dashboard shows a login form before any data loads.

---

## Phase 1 — Storage foundation (blocking for Phase 2)

### Task 3: Migrate Logs from JSONL to SQLite

- Replace the JSONL-backed `_email_logs` list in `backend/logger.py` with a SQLite-backed store (stdlib `sqlite3`), same field set as today's schema (`id`, `timestamp`, `sender`, `subject`, `category`, `severity`, `lang`, `used_rag`, `alert`, `reply_preview`, `provider`, `processing_ms`).
- Add indexes on `timestamp`, `category`, `severity`.
- Write a one-time migration script to import the existing `data/email_logs.jsonl` into the new table.
- Keep `/logs` and `/stats` API response shapes identical — this is a backing-store swap, not an API change.
- **Acceptance**: `/stats` and `/logs` return identical results pre/post migration on the existing dataset.

### Task 4: Cleanup

- Remove or clearly archive `backend/classifier.py` (unreferenced legacy module).
- Replace hardcoded user-specific paths in `setup.sh` and `load_7b_model.sh` with relative paths or env vars.

---

## Phase 2 — Core safety and visibility features

### Task 5: Human Review Queue + Critical Alert (merged)

- Add a `status` field to the log schema: `sent`, `pending`, `approved`, `rejected`.
- In `/process-email`: for severity `normal`/`high` where confidence is below a configurable threshold (env var, default matches existing `MIN_CONFIDENCE_THRESHOLD`), write `status` `pending` instead of auto-sending. For severity `critical`, keep existing escalation behavior unchanged.
- Add `POST /logs/{id}/approve` and `POST /logs/{id}/reject` endpoints. Approve triggers the actual send (via n8n webhook or a second n8n poll node watching for `approved` status); reject marks it closed with no send.
- Add a review tab to the dashboard: list of `pending` items, each with the drafted reply, an edit box, and approve/reject buttons.
- Send a Slack/Teams webhook notification whenever a new item enters `pending` OR `critical` state, so a human knows to check — reuse the same webhook for both cases rather than building two separate alert paths.
- Define and implement a timeout behavior for unreviewed pending items (confirm with project owner: auto-send after N hours, or hold indefinitely — do not assume).
- **Acceptance**: a low-confidence reply is held, visible in the review queue, and only sent after explicit approval; a critical email still escalates immediately as before; both cases trigger the Slack/Teams alert.

### Task 6: Dashboard Search/Filter + CSV Export

- Add search/filter controls to `EmailLogTable.jsx`: filter by sender, category, severity, status.
- Add a "Download CSV" button that exports the currently filtered log set.
- **Acceptance**: filtering updates the visible table without a full page reload; CSV download matches the filtered view.

### Task 7: Processing-Time / SLA Indicator

- Display `processing_ms` per row in the log table with a simple visual flag for anomalously slow processing.
- **Acceptance**: visible on every row, no new backend field needed (already logged).

---

## Phase 3 — Reliability fix (gate on deployment-target decision)

### Task 8: ChromaDB/RAG Reliability via Docker

- **Before starting**: confirm with the project owner whether deployment target is Linux cloud or Windows+WSL. Do not build this without that answer.
- Add a `Dockerfile` and `docker-compose.yml` for the backend so ChromaDB builds natively (resolves the Windows MSVC build gap).
- In `backend/rag/retriever.py`, distinguish and separately log `"RAG attempted but unavailable"` vs. `"RAG ran, no match found"` — these currently look identical and this is how RAG failures go unnoticed.
- **Acceptance**: a known knowledge-base query returns a grounded match on the containerized environment; the two failure states are distinguishable in logs.

---

## Phase 4 — Optional, lower priority (only if time allows)

### Task 9: Thread/Conversation Memory

- Use the existing but currently-unused `thread_id` field from the Gmail payload to detect when an incoming email is a reply to a prior auto-reply, and include prior context when generating the new reply instead of treating it as unrelated.

### Task 10: Attachment Detection

- If an incoming email has an attachment, flag it for manual review instead of silently processing only the text body (full attachment parsing is out of scope — detection only).

### Task 11: Daily Summary Digest

- Scheduled n8n node that emails a daily summary (volume, category breakdown, alerts sent, pending-review count) to the support manager using existing `/stats` data.

### Task 12: Dynamic Knowledge Base with Categories

- Confirm first whether this means (a) re-running the existing `/ingest` endpoint after manual file edits — already supported, no code change needed — or (b) a UI for non-technical KB editing with auto-reindex on save. Only build (b) if explicitly confirmed.
- If filtering RAG by content category (`sales`/`inquiry`/`support`/etc.) rather than just language: reuse the existing classify-step category output to filter the ChromaDB query, and reconcile the category taxonomy between the classifier (`sales`, `inquiry`, `billing`, `support`, `bug`, `other`) and any KB content tags before implementing — do not let these silently diverge.

---

## Explicitly excluded from this prompt

- **Local fine-tuned model production rollout** — unvalidated (no trained weights, no accuracy evaluation exists). Do not wire into production flow.
- **Multi-tenant/SaaS architecture changes** — no confirmed business requirement; would be a separate, much larger scoping effort.

---

## General constraints for the agent

- Do not break existing n8n workflow compatibility without updating `n8n/email_flow_clean.json` in the same change.
- Every new endpoint requires the Phase 0 auth dependency — no exceptions.
- Add a smoke test (extending the existing `test_api.py` pattern) for each new endpoint.
- Do not implement Phase 2+ before Phase 0 and Phase 1 are complete — Task 5 specifically requires the auth layer and SQLite-backed `status` field to function correctly.
