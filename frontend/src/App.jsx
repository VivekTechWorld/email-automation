import { useState, useEffect, useCallback, useRef } from 'react';
import {
  LayoutDashboard, TrendingUp, Inbox, Users, BookOpen, Settings as SettingsIcon,
  Mail, RefreshCw, LogOut, AlertTriangle, CheckCircle2, XCircle,
} from 'lucide-react';
import './index.css';
import {
  getProvider,
  getLogs,
  getPendingReviews,
  getSettings,
  approveLog,
  rejectLog,
  getToken,
  clearToken,
  AuthError,
  BASE_URL,
} from './api';
import Overview from './components/Overview';
import Sales from './components/Sales';
import ReviewQueue from './components/ReviewQueue';
import Customers from './components/Customers';
import KnowledgeBase from './components/KnowledgeBase';
import Settings from './components/Settings';
import LoginGate from './components/LoginGate';
import { formatTime } from './lib/format';

const REFRESH_INTERVAL = 30_000; // 30 seconds auto-refresh

const NAV = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, group: 'Insights' },
  { id: 'sales', label: 'Sales', icon: TrendingUp, group: 'Insights' },
  { id: 'review', label: 'Review queue', icon: Inbox, group: 'Work' },
  { id: 'customers', label: 'Customers', icon: Users, group: 'Work' },
  { id: 'knowledge', label: 'Knowledge base', icon: BookOpen, group: 'Work' },
  { id: 'settings', label: 'Settings', icon: SettingsIcon, group: 'Setup' },
];

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => Boolean(getToken()));
  const [authNotice, setAuthNotice] = useState('');
  const [page, setPage]           = useState('overview');
  const [provider, setProvider]   = useState('gemini');
  const [model, setModel]         = useState('');
  const [logs, setLogs]           = useState([]);
  const [pendingLogs, setPendingLogs] = useState([]);
  const [settings, setSettings]   = useState(null);
  const [handoffChoices, setHandoffChoices] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [focusEmail, setFocusEmail] = useState(null);
  const [error, setError]         = useState(null);
  const [toast, setToast]         = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);
  const toastTimer = useRef(null);

  // ── Authentication ───────────────────────────────────────────────────────
  const handleLogin = useCallback(() => {
    setAuthNotice('');
    setIsAuthenticated(true);
  }, []);

  const handleLogout = useCallback((notice = '') => {
    clearToken();
    setAuthNotice(typeof notice === 'string' ? notice : '');
    setIsAuthenticated(false);
  }, []);

  // ── Data fetching (shared data; pages load their own details) ────────────
  const fetchAll = useCallback(async (showSpinner = false) => {
    if (showSpinner) setRefreshing(true);
    try {
      const [providerRes, logsRes, pendingRes, settingsRes] = await Promise.all([
        getProvider(),
        getLogs(300),
        getPendingReviews(100),
        getSettings(),
      ]);
      setProvider(providerRes.provider);
      setModel(providerRes.model ?? '');
      setLogs(logsRes.logs ?? []);
      setPendingLogs(pendingRes.pending ?? []);
      setSettings(settingsRes.settings);
      setHandoffChoices(settingsRes.handoff_choices ?? []);
      setError(null);
      setLastRefresh(new Date());
      setRefreshKey((k) => k + 1);
    } catch (err) {
      if (err instanceof AuthError) {
        handleLogout(err.message);
        return;
      }
      setError(err.message);
    } finally {
      if (showSpinner) setRefreshing(false);
    }
  }, [handleLogout]);

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

  // ── Review queue actions ─────────────────────────────────────────────────
  const handleApprove = useCallback(async (logId, editedReply) => {
    try {
      await approveLog(logId, editedReply);
      showToast('Approved — the reply goes out within a minute.');
      fetchAll(false);
    } catch (err) {
      showToast(`Approval failed: ${err.message}`, 'error');
    }
  }, [fetchAll, showToast]);

  const handleReject = useCallback(async (logId) => {
    try {
      await rejectLog(logId);
      showToast('Rejected — nothing will be sent.');
      fetchAll(false);
    } catch (err) {
      showToast(`Rejection failed: ${err.message}`, 'error');
    }
  }, [fetchAll, showToast]);

  const handleProviderChange = useCallback((newProvider, newModel) => {
    setProvider(newProvider);
    if (newModel) setModel(newModel);
  }, []);

  const openCustomer = useCallback((email) => {
    setFocusEmail(email);
    setPage('customers');
  }, []);

  if (!isAuthenticated) {
    return <LoginGate onLogin={handleLogin} notice={authNotice} />;
  }

  const current = NAV.find((n) => n.id === page);
  const groups = [...new Set(NAV.map((n) => n.group))];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><Mail size={18} /></div>
          <div>
            <div className="brand-name">Email Automation</div>
            <div className="brand-sub">AI support & sales</div>
          </div>
        </div>

        <nav className="nav" aria-label="Main">
          {groups.map((g) => (
            <div key={g} style={{ display: 'contents' }}>
              <div className="nav-label">{g}</div>
              {NAV.filter((n) => n.group === g).map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  className={`nav-item ${page === id ? 'active' : ''}`}
                  onClick={() => { setPage(id); if (id !== 'customers') setFocusEmail(null); }}
                  aria-current={page === id ? 'page' : undefined}
                >
                  <Icon size={18} />
                  <span className="nav-text">{label}</span>
                  {id === 'review' && pendingLogs.length > 0 && <span className="nav-count">{pendingLogs.length}</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="engine">
            <span className={`status-dot ${error ? 'offline' : ''}`} />
            <div>
              <b>{error ? 'Backend offline' : provider === 'gemini' ? 'Google Gemini' : 'Local Ollama'}</b>
              <span>{error ? 'Check the API server' : model}</span>
            </div>
          </div>
          <button className="nav-item" onClick={() => handleLogout()}>
            <LogOut size={18} /><span className="nav-text">Sign out</span>
          </button>
        </div>
      </aside>

      <div className="content">
        <header className="topbar">
          <div className="topbar-title">{current?.label}</div>
          <div className="topbar-actions">
            <span className="updated">
              {lastRefresh ? `Updated ${formatTime(lastRefresh)}` : 'Connecting…'}
            </span>
            <button className="btn btn-sm btn-icon" onClick={() => fetchAll(true)} disabled={refreshing} title="Refresh" aria-label="Refresh">
              <RefreshCw size={15} className={refreshing ? 'spin' : ''} />
            </button>
          </div>
        </header>

        <main className="main">
          {error && (
            <div className="banner" role="alert">
              <AlertTriangle size={18} />
              <span>
                <b>Can't reach the backend:</b> {error}. Check that the API server is running at <code>{BASE_URL}</code>.
              </span>
            </div>
          )}

          {page === 'overview' && <Overview logs={logs} refreshKey={refreshKey} onToast={showToast} />}
          {page === 'sales' && <Sales refreshKey={refreshKey} onToast={showToast} onOpenCustomer={openCustomer} />}
          {page === 'review' && (
            <>
              <div className="section-head">
                <div>
                  <div className="section-desc">Emails the AI held back for a person — escalations first. Edit the draft, then approve or reject.</div>
                </div>
              </div>
              <ReviewQueue
                pendingLogs={[...pendingLogs].sort((a, b) => Number(b.escalated) - Number(a.escalated))}
                settings={settings}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            </>
          )}
          {page === 'customers' && (
            <Customers key={focusEmail ?? 'all'} focusEmail={focusEmail} refreshKey={refreshKey} onToast={showToast} />
          )}
          {page === 'knowledge' && <KnowledgeBase onToast={showToast} />}
          {page === 'settings' && (
            <Settings
              key={JSON.stringify(settings)}
              settings={settings}
              handoffChoices={handoffChoices}
              provider={provider}
              model={model}
              onSaved={setSettings}
              onProviderChange={handleProviderChange}
              onToast={showToast}
            />
          )}
        </main>
      </div>

      {toast && (
        <div className={`toast ${toast.type}`} role="status">
          {toast.type === 'error' ? <XCircle size={18} /> : <CheckCircle2 size={18} />}
          {toast.message}
        </div>
      )}
    </div>
  );
}
