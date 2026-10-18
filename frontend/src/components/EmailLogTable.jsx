import { useState, useMemo, Fragment } from 'react';
import { Inbox, Download, Search, ScrollText, ChevronLeft, ChevronRight } from 'lucide-react';
import { CategoryBadge, StatusBadge, MoodBadge, Empty } from './ui';
import { STATUS_INFO, SEVERITY_TONE, formatTime, timeAgo } from '../lib/format';

const CATEGORIES = ['sales', 'inquiry', 'billing', 'support', 'bug', 'other'];

/**
 * EmailLogTable — every processed email; click a row to read the full conversation
 */
const PAGE_SIZE = 10;

export default function EmailLogTable({ logs }) {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [category, setCategory] = useState('all');
  const [openId, setOpenId] = useState(null);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (logs ?? []).filter((log) => {
      if (q && ![log.sender, log.subject, log.reply_preview, log.summary]
        .some((v) => v?.toLowerCase().includes(q))) return false;
      if (category !== 'all' && log.category !== category) return false;
      if (status !== 'all') {
        const s = log.alert ? 'alert' : (log.status || 'sent');
        if (s !== status) return false;
      }
      return true;
    });
  }, [logs, search, status, category]);

  // Pagination — clamp so a filter that shrinks the list never shows an empty page
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const current = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  const exportCsv = () => {
    const cols = ['id', 'timestamp', 'status', 'sender', 'subject', 'category', 'severity', 'lang',
      'summary', 'review_reason', 'reply_preview'];
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const csv = [cols.join(','), ...filtered.map((r) => cols.map((c) => esc(r[c])).join(','))].join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = Object.assign(document.createElement('a'), {
      href: url,
      download: `email_log_${new Date().toISOString().slice(0, 10)}.csv`,
    });
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div className="card-title"><ScrollText size={16} />Email log</div>
          <div className="card-sub">Showing {filtered.length} of {logs?.length ?? 0} · click a row for details</div>
        </div>
        <div className="toolbar">
          <label className="input-icon search">
            <Search size={15} />
            <input
              className="input"
              placeholder="Search emails…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="all">All statuses</option>
            {Object.entries(STATUS_INFO).map(([key, info]) => (
              <option key={key} value={key}>{info.label}</option>
            ))}
          </select>
          <select className="select" value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="all">All topics</option>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c[0].toUpperCase() + c.slice(1)}</option>)}
          </select>
          <button className="btn" onClick={exportCsv} disabled={!filtered.length}><Download size={15} />CSV</button>
        </div>
      </div>

      {filtered.length === 0 ? (
        <Empty icon={Inbox} title={logs?.length ? 'No matching emails' : 'No emails yet'}>
          {logs?.length ? 'Try a different search or filter.' : 'Emails appear here once n8n sends them to the backend.'}
        </Empty>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th style={{ width: 170 }}>Status</th>
                <th>Email</th>
                <th style={{ width: 120 }}>Topic</th>
                <th style={{ width: 130 }}>Received</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((log) => (
                <Fragment key={log.id}>
                  <tr
                    className={`row ${openId === log.id ? 'open' : ''}`}
                    onClick={() => setOpenId(openId === log.id ? null : log.id)}
                  >
                    <td><StatusBadge log={log} /></td>
                    <td>
                      <div className="cell-main">{log.subject || '(no subject)'}</div>
                      <div className="cell-sub">{log.sender}{log.summary ? ` · ${log.summary}` : ''}</div>
                    </td>
                    <td><CategoryBadge category={log.category} /></td>
                    <td className="cell-time" title={formatTime(log.timestamp)}>{timeAgo(log.timestamp)}</td>
                  </tr>
                  {openId === log.id && (
                    <tr>
                      <td colSpan={4} className="detail-cell"><LogDetail log={log} /></td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {pageCount > 1 && (
            <div className="pager">
              <span>
                {current * PAGE_SIZE + 1}–{Math.min((current + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div className="toolbar">
                <button className="btn btn-sm" disabled={current === 0} onClick={() => setPage(current - 1)}>
                  <ChevronLeft size={14} />Previous
                </button>
                <button className="btn btn-sm" disabled={current >= pageCount - 1} onClick={() => setPage(current + 1)}>
                  Next<ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LogDetail({ log }) {
  const seconds = log.processing_ms != null ? `${(log.processing_ms / 1000).toFixed(1)}s` : '—';
  return (
    <div className="detail">
      <div className="detail-facts">
        <span><b>#{log.id}</b></span>
        <span>{formatTime(log.timestamp)}</span>
        <span>Severity <span className={`badge cap tone-${SEVERITY_TONE[log.severity] ?? 'gray'}`}>{log.severity}</span></span>
        {log.mood && <span>Mood <MoodBadge mood={log.mood} /></span>}
        {log.escalated && <span className="badge tone-red">Escalated</span>}
        <span>Language <b>{log.lang?.toUpperCase()}</b></span>
        <span>Knowledge base <b>{log.used_rag ? 'used' : 'not used'}</b></span>
        <span>AI <b>{log.provider}</b> · {seconds}</span>
        {log.delivered_at && <span>Delivered <b>{formatTime(log.delivered_at)}</b></span>}
      </div>
      {log.review_reason && <div className="reason">{log.review_reason}</div>}
      <div className="detail-grid">
        <div>
          <div className="detail-label">Customer wrote</div>
          <div className="message">{log.original_body || '(not stored for emails processed before this update)'}</div>
        </div>
        <div>
          <div className="detail-label">{log.alert ? 'Alert sent to team' : 'Reply'}</div>
          <div className="message">{log.reply_preview || '(no reply)'}</div>
        </div>
      </div>
    </div>
  );
}
