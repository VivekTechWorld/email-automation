import { useState } from 'react';

/**
 * ReviewQueue — Interactive human review tab for low-confidence pending drafts
 */
export default function ReviewQueue({ pendingLogs, onApprove, onReject }) {
  const [editedReplies, setEditedReplies] = useState({});
  const [submittingId, setSubmittingId] = useState(null);

  const handleTextChange = (id, text) => {
    setEditedReplies((prev) => ({
      ...prev,
      [id]: text,
    }));
  };

  const handleApprove = async (item) => {
    const finalReply = editedReplies[item.id] !== undefined
      ? editedReplies[item.id]
      : item.reply_preview;

    setSubmittingId(item.id);
    try {
      await onApprove(item.id, finalReply);
    } finally {
      setSubmittingId(null);
    }
  };

  const handleReject = async (item) => {
    setSubmittingId(item.id);
    try {
      await onReject(item.id);
    } finally {
      setSubmittingId(null);
    }
  };

  if (!pendingLogs || pendingLogs.length === 0) {
    return (
      <div className="card">
        <div className="card-header">
          <span className="card-title">⏳ Human Review Queue</span>
          <span className="badge-count zero">0 Pending</span>
        </div>
        <div className="empty-state">
          <div className="empty-icon">✨</div>
          <div className="empty-title">Queue is clear!</div>
          <div className="empty-desc">
            All customer replies have met confidence criteria or have been reviewed.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <span className="card-title">⏳ Human Review Queue</span>
          <span className="badge-count active" style={{ marginLeft: 8 }}>
            {pendingLogs.length} Pending Approval
          </span>
        </div>
        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          Replies are held until approved
        </span>
      </div>

      <div className="review-list">
        {pendingLogs.map((item) => {
          const currentText =
            editedReplies[item.id] !== undefined
              ? editedReplies[item.id]
              : item.reply_preview || '';
          const isBusy = submittingId === item.id;

          return (
            <div key={item.id} className="review-card">
              <div className="review-header">
                <div className="review-meta">
                  <span className="review-id">#{item.id}</span>
                  <span className="review-sender">{item.sender}</span>
                  <span className={`cat-badge ${item.category}`}>
                    {item.category}
                  </span>
                  <span className={`sev-badge ${item.severity}`}>
                    {item.severity}
                  </span>
                </div>

                <div className="review-flags">
                  <span className="review-warn-pill">
                    ⚠️ Low Confidence Gate
                  </span>
                  <span className="review-time">
                    {formatTime(item.timestamp)}
                  </span>
                </div>
              </div>

              <div className="review-subject">
                <strong>Subject:</strong> {item.subject || '(no subject)'}
              </div>

              <div className="review-body-section">
                <label className="review-label" htmlFor={`reply-edit-${item.id}`}>
                  Drafted AI Reply (Editable before sending):
                </label>
                <textarea
                  id={`reply-edit-${item.id}`}
                  className="review-textarea"
                  rows={5}
                  value={currentText}
                  onChange={(e) => handleTextChange(item.id, e.target.value)}
                  disabled={isBusy}
                  placeholder="Review or customize response..."
                />
              </div>

              <div className="review-actions">
                <button
                  type="button"
                  className="reject-btn"
                  onClick={() => handleReject(item)}
                  disabled={isBusy}
                  title="Mark rejected and close without sending"
                >
                  ✕ Reject (Don't Send)
                </button>

                <button
                  type="button"
                  className="approve-btn"
                  onClick={() => handleApprove(item)}
                  disabled={isBusy}
                  title="Approve reply and send to customer"
                >
                  {isBusy ? 'Processing...' : '✓ Approve & Send'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
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
