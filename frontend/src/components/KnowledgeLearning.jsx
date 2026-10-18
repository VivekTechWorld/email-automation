import { useState, useEffect } from 'react';
import { Lightbulb, HelpCircle, Check, X, PenLine } from 'lucide-react';
import { getSuggestions, acceptSuggestion, discardSuggestion, getGaps, resolveGap } from '../api';
import { CategoryBadge, Empty } from './ui';
import { timeAgo } from '../lib/format';

/**
 * Suggestions — articles the AI drafted from replies the team approved.
 * Nothing reaches the knowledge base until a person accepts it.
 */
export function Suggestions({ onToast, onCounts }) {
  const [items, setItems] = useState(null);
  const [edits, setEdits] = useState({});

  useEffect(() => {
    getSuggestions()
      .then((r) => { setItems(r.suggestions); onCounts(r.counts); })
      .catch((err) => onToast(err.message, 'error'));
  }, [onToast, onCounts]);

  const act = async (s, accept) => {
    try {
      const r = accept ? await acceptSuggestion(s.id, edits[s.id] ?? {}) : await discardSuggestion(s.id);
      setItems((list) => list.filter((x) => x.id !== s.id));
      onCounts(r.counts);
      onToast(accept ? 'Added to the knowledge base — the AI uses it right away.' : 'Suggestion discarded.');
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  if (!items) return <div className="skeleton" style={{ height: 200 }} />;
  if (!items.length) {
    return (
      <div className="card">
        <Empty icon={Lightbulb} title="No suggestions right now">
          When your team approves a reply in the Review queue, the AI turns reusable answers into suggested articles here.
        </Empty>
      </div>
    );
  }

  return (
    <div className="review-list">
      {items.map((s) => {
        const e = edits[s.id] ?? {};
        const set = (k) => (ev) => setEdits((all) => ({ ...all, [s.id]: { ...e, [k]: ev.target.value } }));
        return (
          <div key={s.id} className="card review">
            <div className="review-top">
              <div className="person">
                <span className="setting-icon g-amber"><Lightbulb size={16} /></span>
                <div className="card-sub">Learned from an approved reply · {timeAgo(s.created_at)} · personal details removed</div>
              </div>
              <div className="review-tags">
                <CategoryBadge category={s.category} />
                <span className="badge tone-gray">{s.lang.toUpperCase()}</span>
              </div>
            </div>
            <div className="field">
              <label className="field-label" htmlFor={`sug-title-${s.id}`}>Title</label>
              <input id={`sug-title-${s.id}`} className="input" value={e.title ?? s.title} onChange={set('title')} />
            </div>
            <div className="field">
              <label className="field-label" htmlFor={`sug-content-${s.id}`}>Content</label>
              <textarea id={`sug-content-${s.id}`} className="textarea" rows={6} value={e.content ?? s.content} onChange={set('content')} />
            </div>
            <div className="toolbar" style={{ justifyContent: 'flex-end' }}>
              <button className="btn btn-danger" onClick={() => act(s, false)}><X size={15} />Discard</button>
              <button className="btn btn-success" onClick={() => act(s, true)}><Check size={15} />Accept & add</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Gaps — customer questions the knowledge base could not answer, most asked first.
 */
export function Gaps({ onToast, onCounts, onWrite }) {
  const [items, setItems] = useState(null);

  useEffect(() => {
    getGaps()
      .then((r) => { setItems(r.gaps); onCounts(r.counts); })
      .catch((err) => onToast(err.message, 'error'));
  }, [onToast, onCounts]);

  const dismiss = async (g) => {
    try {
      const r = await resolveGap(g.id);
      setItems((list) => list.filter((x) => x.id !== g.id));
      onCounts(r.counts);
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  if (!items) return <div className="skeleton" style={{ height: 200 }} />;
  return (
    <div className="card">
      <div className="card-head">
        <span className="card-title"><HelpCircle size={16} />Questions the AI could not answer</span>
        <span className="card-sub">Most asked first — add an article and the AI answers them next time</span>
      </div>
      {!items.length ? (
        <Empty icon={Check} title="No open questions">Every recent question was covered by the knowledge base.</Empty>
      ) : items.map((g) => (
        <div key={g.id} className="list-row">
          <span className="badge tone-violet num" title="Times asked">{g.count}×</span>
          <div className="list-row-main">
            <div className="cell-main" style={{ whiteSpace: 'normal' }}>{g.question}</div>
            <div className="cell-sub">Last asked {timeAgo(g.last_seen)} · {g.lang.toUpperCase()}</div>
          </div>
          <CategoryBadge category={g.category} />
          <button className="btn btn-sm btn-ghost" onClick={() => dismiss(g)} title="Not relevant"><X size={14} />Dismiss</button>
          <button className="btn btn-sm btn-primary" onClick={() => onWrite(g)}><PenLine size={14} />Write article</button>
        </div>
      ))}
    </div>
  );
}
