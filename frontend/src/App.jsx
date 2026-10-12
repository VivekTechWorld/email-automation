import { useState, useEffect, useCallback, useRef } from 'react';
import './index.css';
import { getProvider, getLogs, getStats, getHealth } from './api';
import ProviderToggle from './components/ProviderToggle';
import StatCards from './components/StatCards';
import SeverityBreakdown from './components/SeverityBreakdown';
import EmailLogTable from './components/EmailLogTable';
import LoginGate from './components/LoginGate';

const REFRESH_INTERVAL = 30_000; // 30 seconds auto-refresh

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return sessionStorage.getItem('dashboard_auth') === 'true';
  });
  const [provider, setProvider]   = useState('gemini');
  const [stats, setStats]         = useState(null);
  const [logs, setLogs]           = useState([]);
  const [loading, setLoading]     = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError]         = useState(null);
  const [toast, setToast]         = useState(null);
  const [backendOk, setBackendOk] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const toastTimer = useRef(null);

  // ── Authentication Handlers ──────────────────────────────────────────────
  const handleLogin = useCallback(() => {
    sessionStorage.setItem('dashboard_auth', 'true');
    setIsAuthenticated(true);
  }, []);

  const handleLogout = useCallback(() => {
    sessionStorage.removeItem('dashboard_auth');
    setIsAuthenticated(false);
  }, []);

  // ── Data fetching ────────────────────────────────────────────────────────
  const fetchAll = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    setError(null);

    try {
      const [providerRes, statsRes, logsRes] = await Promise.all([
        getProvider(),
        getStats(),
        getLogs(200),
      ]);

      setProvider(providerRes.provider);
      setStats(statsRes);
      setLogs(logsRes.logs ?? []);
      setBackendOk(true);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err.message);
      setBackendOk(false);
    } finally {
      setLoading(false);
      if (showSpinner) setRefreshing(false);
    }
  }, []);

  // Initial load + polling (only when authenticated)
  useEffect(() => {
    if (!isAuthenticated) return;
    fetchAll(false);
    const interval = setInterval(() => fetchAll(false), REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchAll, isAuthenticated]);

  // ── Toast helper ─────────────────────────────────────────────────────────
  const showToast = useCallback((message, type = 'success') => {
    setToast({ message, type });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }, []);

  // ── Provider change ───────────────────────────────────────────────────────
  const handleProviderChange = useCallback((newProvider) => {
    setProvider(newProvider);
    // Re-fetch stats after a short delay to capture new provider in logs
    setTimeout(() => fetchAll(false), 500);
  }, [fetchAll]);

  // If unauthenticated, show the Login Gate before any data loads
  if (!isAuthenticated) {
    return <LoginGate onLogin={handleLogin} />;
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="header">
        <div className="header-brand">
          <div className="header-logo">✉️</div>
          <div>
            <div className="header-title">Email Automation</div>
            <div className="header-subtitle">ArtCloud · AI Dashboard</div>
          </div>
        </div>

        <div className="header-right">
          {backendOk && (
            <div className="live-indicator">
              <div className="live-dot" />
              {lastRefresh
                ? `Last updated ${lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
                : 'Live'}
            </div>
          )}

          {!backendOk && (
            <span style={{ fontSize: 12, color: 'var(--sev-critical)' }}>
              ⚠️ Backend offline
            </span>
          )}

          <button
            id="refresh-btn"
            className={`refresh-btn ${refreshing ? 'spinning' : ''}`}
            onClick={() => fetchAll(true)}
            disabled={refreshing}
            title="Refresh data"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M23 4v6h-6M1 20v-6h6" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            Refresh
          </button>

          <button
            id="lock-btn"
            className="refresh-btn"
            onClick={handleLogout}
            title="Lock dashboard"
            style={{ width: 'auto', padding: '0 12px', gap: 6 }}
          >
            🔒 Lock
          </button>
        </div>
      </header>

      {/* ── Main ─────────────────────────────────────────────────────────── */}
      <main className="main-content">

        {/* Error banner */}
        {error && (
          <div className="error-banner" role="alert">
            <span>⚠️</span>
            <span>
              <strong>Backend connection failed:</strong> {error}.
              Make sure the FastAPI server is running at{' '}
              <code style={{ opacity: 0.8 }}>http://localhost:8000</code>.
            </span>
          </div>
        )}

        {/* ── Provider Toggle ───────────────────────────────────────────── */}
        <div className="section-title">AI Engine</div>
        {loading ? (
          <div className="skeleton" style={{ height: 88, marginBottom: 24, borderRadius: 16 }} />
        ) : (
          <ProviderToggle
            provider={provider}
            onProviderChange={handleProviderChange}
            onToast={showToast}
          />
        )}

        {/* ── Stat Cards ────────────────────────────────────────────────── */}
        <div className="section-title">Overview</div>
        {loading ? (
          <div className="stats-grid">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="skeleton" style={{ height: 100, borderRadius: 16 }} />
            ))}
          </div>
        ) : (
          <StatCards stats={stats} />
        )}

        {/* ── Severity + Category ───────────────────────────────────────── */}
        <div className="section-title">Analytics</div>
        <div className="two-col" style={{ marginBottom: 24 }}>
          <div>
            {loading ? (
              <div className="skeleton" style={{ height: 340, borderRadius: 16 }} />
            ) : (
              <SeverityBreakdown stats={stats} />
            )}
          </div>

          {/* Quick info panel */}
          <div className="card">
            <div className="card-header">
              <span className="card-title">📊 Provider Usage</span>
            </div>
            <div className="card-body">
              {loading ? (
                <div className="skeleton" style={{ height: 200, borderRadius: 8 }} />
              ) : (
                <ProviderUsageChart stats={stats} />
              )}
            </div>
          </div>
        </div>

        {/* ── Email Log Table ───────────────────────────────────────────── */}
        <div className="section-title">Email Log</div>
        {loading ? (
          <div className="skeleton" style={{ height: 400, borderRadius: 16 }} />
        ) : (
          <EmailLogTable logs={logs} />
        )}

        {/* Footer spacer */}
        <div style={{ height: 40 }} />
      </main>

      {/* ── Toast ────────────────────────────────────────────────────────── */}
      {toast && (
        <div className={`toast ${toast.type}`} role="status">
          {toast.message}
        </div>
      )}
    </div>
  );
}


// ── Inline provider usage chart ───────────────────────────────────────────────
function ProviderUsageChart({ stats }) {
  const byProv   = stats?.by_provider ?? { local: 0, gemini: 0 };
  const total    = (byProv.local ?? 0) + (byProv.gemini ?? 0);
  const localPct = total === 0 ? 0 : Math.round(((byProv.local ?? 0) / total) * 100);
  const gemPct   = 100 - localPct;

  const ragRate  = stats?.total > 0
    ? Math.round(((stats.rag_used ?? 0) / stats.total) * 100)
    : 0;

  const rows = [
    {
      label: '⚡ Local (Ollama)',
      value: byProv.local ?? 0,
      pct: localPct,
      color: 'var(--accent-blue)',
    },
    {
      label: '☁️ Gemini Flash',
      value: byProv.gemini ?? 0,
      pct: gemPct,
      color: 'var(--accent-purple)',
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {rows.map((row) => (
        <div key={row.label}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
            <span style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 500 }}>
              {row.label}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
              {row.value} <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>({row.pct}%)</span>
            </span>
          </div>
          <div className="severity-bar-track">
            <div
              style={{
                height: '100%',
                width: `${row.pct}%`,
                background: row.color,
                borderRadius: 3,
                transition: 'width 0.8s cubic-bezier(0.4,0,0.2,1)',
              }}
            />
          </div>
        </div>
      ))}

      <div style={{
        marginTop: 8,
        padding: '14px 16px',
        background: 'var(--bg-elevated)',
        borderRadius: 'var(--radius-md)',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}>
        <span style={{ fontSize: 22 }}>🔍</span>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1 }}>
            {ragRate}%
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
            RAG Knowledge Base Hit Rate
          </div>
        </div>
      </div>

      {/* Language breakdown */}
      {stats?.by_lang && Object.keys(stats.by_lang).length > 0 && (
        <div>
          <div className="section-title" style={{ marginBottom: 10 }}>Languages Detected</div>
          {Object.entries(stats.by_lang).sort((a, b) => b[1] - a[1]).map(([lang, count]) => (
            <div key={lang} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>
                {langFlag(lang)} {lang.toUpperCase()}
              </span>
              <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function langFlag(lang) {
  const flags = { en: '🇬🇧', fi: '🇫🇮', de: '🇩🇪', fr: '🇫🇷', es: '🇪🇸' };
  return flags[lang] ?? '🌐';
}
