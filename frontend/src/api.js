// API base URL — adjust if your backend runs on a different port
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const DEFAULT_API_KEY = import.meta.env.VITE_API_KEY || 'changeme-secret-api-key-2026';

/**
 * Returns the active API key from localStorage or Vite environment variable.
 */
export function getApiKey() {
  return localStorage.getItem('api_key') || DEFAULT_API_KEY;
}

/**
 * Persists or clears the API key in localStorage.
 */
export function setApiKey(key) {
  if (key) {
    localStorage.setItem('api_key', key);
  } else {
    localStorage.removeItem('api_key');
  }
}

/**
 * Helper to attach Bearer Authorization header to fetch options.
 */
function getHeaders(customHeaders = {}) {
  const headers = { ...customHeaders };
  const key = getApiKey();
  if (key) {
    headers['Authorization'] = `Bearer ${key}`;
  }
  return headers;
}

/**
 * Fetch current AI provider state
 */
export async function getProvider() {
  const res = await fetch(`${BASE_URL}/get-provider`, {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to get provider: ${res.status}`);
  return res.json();
}

/**
 * Switch AI provider at runtime
 * @param {string} provider - "local" or "gemini"
 */
export async function setProvider(provider) {
  const res = await fetch(`${BASE_URL}/set-provider`, {
    method: 'POST',
    headers: getHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ provider }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || `Failed to set provider: ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch email processing logs
 * @param {number} limit - max entries to return
 * @param {string|null} status - optional status filter
 */
export async function getLogs(limit = 200, status = null) {
  let url = `${BASE_URL}/logs?limit=${limit}`;
  if (status) {
    url += `&status=${encodeURIComponent(status)}`;
  }
  const res = await fetch(url, {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch logs: ${res.status}`);
  return res.json();
}

/**
 * Fetch items currently pending human review
 * @param {number} limit - max items to return
 */
export async function getPendingReviews(limit = 100) {
  const res = await fetch(`${BASE_URL}/logs/pending?limit=${limit}`, {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch pending reviews: ${res.status}`);
  return res.json();
}

/**
 * Approve a held draft reply, optionally with user edits
 * @param {number} logId - log entry ID
 * @param {string|null} reply - edited reply text
 */
export async function approveLog(logId, reply = null) {
  const body = reply !== null ? { reply } : {};
  const res = await fetch(`${BASE_URL}/logs/${logId}/approve`, {
    method: 'POST',
    headers: getHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || `Failed to approve log #${logId}: ${res.status}`);
  }
  return res.json();
}

/**
 * Reject a held draft reply (close without sending)
 * @param {number} logId - log entry ID
 * @param {string|null} reason - optional rejection reason
 */
export async function rejectLog(logId, reason = null) {
  const body = reason ? { reason } : {};
  const res = await fetch(`${BASE_URL}/logs/${logId}/reject`, {
    method: 'POST',
    headers: getHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || `Failed to reject log #${logId}: ${res.status}`);
  }
  return res.json();
}

/**
 * Fetch aggregated stats for charts
 */
export async function getStats() {
  const res = await fetch(`${BASE_URL}/stats`, {
    headers: getHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.status}`);
  return res.json();
}

/**
 * Health check (unauthenticated route)
 */
export async function getHealth() {
  const res = await fetch(`${BASE_URL}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}
