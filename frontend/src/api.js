// API base URL — adjust if your backend runs on a different port
export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// The dashboard never holds the backend API key. It exchanges the dashboard
// password for a short-lived session token (POST /auth/login) instead, so no
// secret is compiled into the JavaScript bundle.
const TOKEN_KEY = 'dashboard_token';

export function getToken() {
  try {
    const raw = sessionStorage.getItem(TOKEN_KEY);
    if (!raw) return null;
    const { token, expiresAt } = JSON.parse(raw);
    if (!token || Date.now() / 1000 >= expiresAt) {
      sessionStorage.removeItem(TOKEN_KEY);
      return null;
    }
    return token;
  } catch {
    return null;
  }
}

export function clearToken() {
  try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
}

/**
 * Exchange the dashboard password for a session token.
 */
export async function login(password) {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Login failed: ${res.status}`);
  }
  const { token, expires_at } = await res.json();
  try {
    sessionStorage.setItem(TOKEN_KEY, JSON.stringify({ token, expiresAt: expires_at }));
  } catch { /* storage unavailable — token lives only for this page load */ }
  return token;
}

/**
 * Error thrown when the session is missing/expired so the app can show the login screen.
 */
export class AuthError extends Error {}

/**
 * Helper to attach Bearer Authorization header to fetch options.
 */
function getHeaders(customHeaders = {}) {
  const headers = { ...customHeaders };
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

async function authFetch(url, options = {}) {
  const res = await fetch(url, { ...options, headers: getHeaders(options.headers) });
  if (res.status === 401) {
    clearToken();
    throw new AuthError('Session expired — please sign in again.');
  }
  return res;
}

/**
 * Fetch current AI provider state
 */
export async function getProvider() {
  const res = await authFetch(`${BASE_URL}/get-provider`);
  if (!res.ok) throw new Error(`Failed to get provider: ${res.status}`);
  return res.json();
}

/**
 * Switch AI provider at runtime
 * @param {string} provider - "local" or "gemini"
 */
export async function setProvider(provider) {
  const res = await authFetch(`${BASE_URL}/set-provider`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  const res = await authFetch(url);
  if (!res.ok) throw new Error(`Failed to fetch logs: ${res.status}`);
  return res.json();
}

/**
 * Fetch items currently pending human review
 * @param {number} limit - max items to return
 */
export async function getPendingReviews(limit = 100) {
  const res = await authFetch(`${BASE_URL}/logs/pending?limit=${limit}`);
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
  const res = await authFetch(`${BASE_URL}/logs/${logId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  const res = await authFetch(`${BASE_URL}/logs/${logId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  const res = await authFetch(`${BASE_URL}/stats`);
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

async function jsonOrThrow(res, fallback) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `${fallback}: ${res.status}`);
  }
  return res.json();
}

// ── Knowledge base ──────────────────────────────────────────────────────────

export async function getArticles(category = null) {
  const q = category ? `?category=${encodeURIComponent(category)}` : '';
  return jsonOrThrow(await authFetch(`${BASE_URL}/kb/articles${q}`), 'Failed to load knowledge base');
}

export async function getArticle(id) {
  return jsonOrThrow(await authFetch(`${BASE_URL}/kb/articles/${id}`), 'Failed to load article');
}

export async function saveArticle(article) {
  const isNew = !article.id;
  const res = await authFetch(`${BASE_URL}/kb/articles${isNew ? '' : `/${article.id}`}`, {
    method: isNew ? 'POST' : 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: article.title,
      category: article.category,
      lang: article.lang,
      content: article.content,
    }),
  });
  return jsonOrThrow(res, 'Failed to save article');
}

export async function deleteArticle(id) {
  return jsonOrThrow(
    await authFetch(`${BASE_URL}/kb/articles/${id}`, { method: 'DELETE' }),
    'Failed to delete article',
  );
}

// ── Automation settings ─────────────────────────────────────────────────────

export async function getSettings() {
  return jsonOrThrow(await authFetch(`${BASE_URL}/settings`), 'Failed to load settings');
}

export async function updateSettings(changes) {
  const res = await authFetch(`${BASE_URL}/settings`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  });
  return jsonOrThrow(res, 'Failed to save settings');
}

async function send(path, method, body, fallback) {
  const res = await authFetch(`${BASE_URL}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  return jsonOrThrow(res, fallback);
}

// ── Self-learning ───────────────────────────────────────────────────────────

export const getSuggestions = () => send('/kb/suggestions', 'GET', undefined, 'Failed to load suggestions');
export const acceptSuggestion = (id, edits = {}) => send(`/kb/suggestions/${id}/accept`, 'POST', edits, 'Failed to accept suggestion');
export const discardSuggestion = (id) => send(`/kb/suggestions/${id}/discard`, 'POST', undefined, 'Failed to discard suggestion');
export const getGaps = () => send('/kb/gaps', 'GET', undefined, 'Failed to load questions');
export const resolveGap = (id) => send(`/kb/gaps/${id}/resolve`, 'POST', undefined, 'Failed to update question');

// ── Customers ───────────────────────────────────────────────────────────────

export const getCustomers = (search = '') =>
  send(`/customers${search ? `?search=${encodeURIComponent(search)}` : ''}`, 'GET', undefined, 'Failed to load customers');
export const getCustomer = (email) => send(`/customers/${encodeURIComponent(email)}`, 'GET', undefined, 'Failed to load customer');
export const updateCustomer = (email, changes) => send(`/customers/${encodeURIComponent(email)}`, 'PATCH', changes, 'Failed to save customer');
export const eraseCustomer = (email) => send(`/customers/${encodeURIComponent(email)}`, 'DELETE', undefined, 'Failed to delete customer');

// ── Leads ───────────────────────────────────────────────────────────────────

export const getLeads = () => send('/leads', 'GET', undefined, 'Failed to load leads');
export const getLeadMetrics = (days = 30) => send(`/leads/metrics?days=${days}`, 'GET', undefined, 'Failed to load sales metrics');
export const updateLead = (id, changes) => send(`/leads/${id}`, 'PATCH', changes, 'Failed to update lead');

// ── Reports ─────────────────────────────────────────────────────────────────

export const getReport = (days = 7) => send(`/reports/summary?days=${days}`, 'GET', undefined, 'Failed to load report');
export const getInsights = (days = 7, refresh = false) =>
  send(`/reports/insights?days=${days}${refresh ? '&refresh=true' : ''}`, 'GET', undefined, 'Failed to load insights');
