import { useState, useEffect } from 'react';
import { CheckCheck, Flame, Info, Timer, X, Send } from 'lucide-react';
import { CategoryBadge, MoodBadge, Avatar, Empty } from './ui';
import { formatDuration, timeAgo } from '../lib/format';

/**
 * ReviewQueue — emails held back from auto-sending (team handoff, low confidence,
 * attachments, AI failures). Edit the draft, then approve or reject.
 */
export default function ReviewQueue({ pendingLogs, settings, onApprove, onReject }) {
  const [drafts, setDrafts] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  // Tick every 30s so the auto-reply countdowns stay current
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const run = async (id, action) => {
    setBusyId(id);
    try {
      await action();
    } finally {
      setBusyId(null);
    }
  };

  if (!pendingLogs?.length) {
    return (
      <div className="card">
        <Empty icon={CheckCheck} title="Nothing to review">
          Emails that need a person — sales handoffs, unclear questions, attachments — will appear here.
        </Empty>
      </div>
    );
  }

  return (
    <div className="review-list">
      {pendingLogs.map((item) => {
        const text = drafts[item.id] ?? item.reply_preview ?? '';
        const busy = busyId === item.id;
        return (
          <div key={item.id} className={`card review ${item.escalated ? 'escalated' : ''}`}>
            <div className="review-top">
              <div className="person">
                <Avatar email={item.sender} />
                <div className="person-text">
                  <div className="review-subject">{item.subject || '(no subject)'}</div>
                  <div className="review-from">{item.sender} · {timeAgo(item.timestamp)}</div>
                </div>
              </div>
              <div className="review-tags">
                <MoodBadge mood={item.mood} />
                <CategoryBadge category={item.category} />
                {item.severity !== 'normal' && (
                  <span className={`badge cap tone-${item.severity === 'critical' ? 'red' : 'amber'}`}>{item.severity}</span>
                )}
              </div>
            </div>

            {item.review_reason && (
              <div className={`reason ${item.escalated ? 'red' : ''}`}>
                {item.escalated ? <Flame size={15} /> : <Info size={15} />}
                {reasonText(item.review_reason)}
              </div>
            )}
            {item.summary && <div className="profile-strip"><span>Summary: <b>{item.summary}</b></span></div>}

            {item.original_body && (
              <div>
                <div className="detail-label">Customer wrote</div>
                <div className="message">{item.original_body}</div>
              </div>
            )}

            <div className="field">
              <label className="detail-label" htmlFor={`draft-${item.id}`}>
                {item.reply_preview ? 'AI draft — edit before sending' : 'No AI draft — write the reply'}
              </label>
              <textarea
                id={`draft-${item.id}`}
                className="textarea"
                rows={Math.min(14, Math.max(6, text.split('\n').length + 1))}
                value={text}
                disabled={busy}
                onChange={(e) => setDrafts((d) => ({ ...d, [item.id]: e.target.value }))}
              />
            </div>

            <div className="review-actions">
              <Countdown item={item} settings={settings} now={now} />
              <div className="toolbar">
                <button className="btn btn-danger" disabled={busy} onClick={() => run(item.id, () => onReject(item.id))}>
                  <X size={15} />Reject
                </button>
                <button
                  className="btn btn-primary"
                  disabled={busy || !text.trim()}
                  onClick={() => run(item.id, () => onApprove(item.id, text))}
                >
                  <Send size={15} />{busy ? 'Saving…' : 'Approve & send'}
                </button>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// The countdown is shown separately, so drop the backend's "— AI replies automatically…" suffix
function reasonText(reason) {
  return reason.split(' — AI replies automatically')[0];
}

function Countdown({ item, settings, now }) {
  if (!settings) return <span />;
  if (!item.reply_preview) return <span className="countdown"><Timer size={14} />Waiting for a person to write the reply</span>;
  if (!settings.auto_reply_enabled) return <span className="countdown"><Timer size={14} />Auto-reply is off — waits for a person</span>;

  const due = new Date(item.timestamp).getTime() + settings.auto_reply_timeout_hours * 3600_000;
  const left = due - now;
  return (
    <span className={`countdown ${left < 3600_000 ? 'soon' : ''}`}>
      <Timer size={14} />AI sends this draft in {formatDuration(left)} if nobody reviews it
    </span>
  );
}
