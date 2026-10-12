import { useState, useMemo } from 'react';

/**
 * EmailLogTable — Filterable table of all processed emails with SLA indicator and CSV export
 */
export default function EmailLogTable({ logs }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('all');
  const [selectedSeverity, setSelectedSeverity] = useState('all');
  const [selectedStatus, setSelectedStatus] = useState('all');

  // Filtered log list
  const filteredLogs = useMemo(() => {
    if (!logs) return [];
    return logs.filter((log) => {
      // Search text (sender or subject)
      if (searchTerm) {
        const query = searchTerm.toLowerCase();
        const matchesSender = log.sender?.toLowerCase().includes(query);
        const matchesSubject = log.subject?.toLowerCase().includes(query);
        if (!matchesSender && !matchesSubject) return false;
      }

      // Category filter
      if (selectedCategory !== 'all' && log.category !== selectedCategory) {
        return false;
      }

      // Severity filter
      if (selectedSeverity !== 'all' && log.severity !== selectedSeverity) {
        return false;
      }

      // Status filter
      if (selectedStatus !== 'all') {
        const itemStatus = log.status || (log.alert ? 'sent' : 'sent');
        if (itemStatus !== selectedStatus) return false;
      }

      return true;
    });
  }, [logs, searchTerm, selectedCategory, selectedSeverity, selectedStatus]);

  // CSV Export
  const handleExportCSV = () => {
    if (!filteredLogs.length) return;

    const headers = [
      'ID',
      'Timestamp',
      'Status',
      'Sender',
      'Subject',
      'Category',
      'Severity',
      'Language',
      'Used RAG',
      'Alert',
      'Provider',
      'Processing (ms)',
      'Reply Preview',
    ];

    const escapeCsv = (val) => {
      if (val === null || val === undefined) return '""';
      const str = String(val).replace(/"/g, '""');
      return `"${str}"`;
    };

    const rows = filteredLogs.map((item) => [
      item.id,
      escapeCsv(item.timestamp),
      escapeCsv(item.status || 'sent'),
      escapeCsv(item.sender),
      escapeCsv(item.subject),
      escapeCsv(item.category),
      escapeCsv(item.severity),
      escapeCsv(item.lang),
      item.used_rag ? 'true' : 'false',
      item.alert ? 'true' : 'false',
      escapeCsv(item.provider),
      item.processing_ms ?? '',
      escapeCsv(item.reply_preview),
    ]);

    const csvContent =
      'data:text/csv;charset=utf-8,' +
      [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    const dateStr = new Date().toISOString().slice(0, 10);
    link.setAttribute('download', `email_logs_${dateStr}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const clearFilters = () => {
    setSearchTerm('');
    setSelectedCategory('all');
    setSelectedSeverity('all');
    setSelectedStatus('all');
  };

  const isFiltered =
    searchTerm !== '' ||
    selectedCategory !== 'all' ||
    selectedSeverity !== 'all' ||
    selectedStatus !== 'all';

  return (
    <div className="card">
      <div className="card-header" style={{ flexWrap: 'wrap', gap: 12 }}>
        <div>
          <span className="card-title">📋 Email Processing Log</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
            Showing {filteredLogs.length} of {logs?.length ?? 0}
          </span>
        </div>

        <button
          className="csv-btn"
          onClick={handleExportCSV}
          disabled={filteredLogs.length === 0}
          title="Export visible logs as CSV"
        >
          📥 Download CSV
        </button>
      </div>

      {/* Filter toolbar */}
      <div className="table-filter-bar">
        <div className="search-box">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="filter-input"
            placeholder="Search sender or subject..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="filter-select-group">
          <select
            className="filter-select"
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
          >
            <option value="all">All Categories</option>
            <option value="sales">Sales</option>
            <option value="inquiry">Inquiry</option>
            <option value="billing">Billing</option>
            <option value="support">Support</option>
            <option value="bug">Bug</option>
            <option value="other">Other</option>
          </select>

          <select
            className="filter-select"
            value={selectedSeverity}
            onChange={(e) => setSelectedSeverity(e.target.value)}
          >
            <option value="all">All Severities</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>

          <select
            className="filter-select"
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="sent">Sent</option>
            <option value="pending">Pending Review</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>

          {isFiltered && (
            <button className="clear-filters-btn" onClick={clearFilters}>
              ✕ Reset
            </button>
          )}
        </div>
      </div>

      {/* Table content */}
      {filteredLogs.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">📭</div>
          <div className="empty-title">
            {logs?.length === 0 ? 'No emails processed yet' : 'No matching emails found'}
          </div>
          <div className="empty-desc">
            {logs?.length === 0
              ? 'Emails will appear here once n8n starts sending them to the backend.'
              : 'Try clearing your search term or filter dropdowns.'}
          </div>
        </div>
      ) : (
        <div className="log-table-wrap">
          <table className="log-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Sender</th>
                <th>Subject</th>
                <th>Category</th>
                <th>Severity</th>
                <th>Lang</th>
                <th>RAG</th>
                <th>Provider</th>
                <th>SLA / Latency</th>
                <th>Reply Preview</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.map((log) => (
                <tr key={log.id}>
                  <td style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                    {log.id}
                  </td>

                  <td>
                    <StatusBadge status={log.status || (log.alert ? 'sent' : 'sent')} />
                  </td>

                  <td className="td-sender" title={log.sender}>
                    {log.sender}
                  </td>

                  <td className="td-subject" title={log.subject}>
                    {log.subject || '(no subject)'}
                  </td>

                  <td>
                    <span className={`cat-badge ${log.category}`}>
                      {catIcon(log.category)} {log.category}
                    </span>
                  </td>

                  <td>
                    <span className={`sev-badge ${log.severity}`}>
                      {log.severity}
                    </span>
                  </td>

                  <td style={{ fontSize: 12 }}>
                    {langFlag(log.lang)} {log.lang?.toUpperCase()}
                  </td>

                  <td>
                    {log.used_rag ? (
                      <span className="rag-chip">RAG</span>
                    ) : (
                      <span className="rag-chip none">—</span>
                    )}
                  </td>

                  <td>
                    <span className={`prov-chip ${log.provider}`}>
                      {log.provider === 'gemini' ? '☁️' : '⚡'} {log.provider}
                    </span>
                  </td>

                  <td>
                    <SlaIndicator ms={log.processing_ms} />
                  </td>

                  <td className="td-preview" title={log.reply_preview}>
                    {log.reply_preview}
                  </td>

                  <td className="td-time">
                    {formatTime(log.timestamp)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Components & Helpers ─────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const norm = (status || 'sent').toLowerCase();
  const config = {
    sent: { label: 'Sent', className: 'status-sent', icon: '✓' },
    pending: { label: 'Pending', className: 'status-pending', icon: '⏳' },
    approved: { label: 'Approved', className: 'status-approved', icon: '✓' },
    rejected: { label: 'Rejected', className: 'status-rejected', icon: '✕' },
  };
  const item = config[norm] || config.sent;

  return (
    <span className={`status-badge ${item.className}`}>
      {item.icon} {item.label}
    </span>
  );
}

function SlaIndicator({ ms }) {
  if (ms === null || ms === undefined) {
    return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  }

  // Format seconds or ms
  const formatted = ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;

  // SLA Thresholds: < 5s (Good/Fast), 5s - 30s (Moderate), > 30s (Slow SLA anomaly)
  let slaClass = 'sla-fast';
  let flag = '';

  if (ms > 30000) {
    slaClass = 'sla-slow';
    flag = '⚠️ ';
  } else if (ms > 5000) {
    slaClass = 'sla-mid';
  }

  return (
    <span className={`sla-badge ${slaClass}`} title={`Total execution time: ${ms} ms`}>
      {flag}{formatted}
    </span>
  );
}

function catIcon(cat) {
  const icons = {
    sales: '💼', inquiry: '❓', billing: '💳',
    support: '🔧', bug: '🐛', other: '📌',
  };
  return icons[cat] ?? '📌';
}

function langFlag(lang) {
  const flags = { en: '🇬🇧', fi: '🇫🇮', de: '🇩🇪', fr: '🇫🇷', es: '🇪🇸' };
  return flags[lang] ?? '🌐';
}

function formatTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}
