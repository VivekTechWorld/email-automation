import { useState, useEffect, useCallback } from 'react';
import { Users, Search, Trash2, Save, Mail, Briefcase, StickyNote, Activity } from 'lucide-react';
import { getCustomers, getCustomer, updateCustomer, eraseCustomer } from '../api';
import { Avatar, MoodBadge, StageBadge, HandlerBadge, StatusBadge, CategoryBadge, Empty } from './ui';
import { formatTime, timeAgo, money } from '../lib/format';

/**
 * Customers — automatic per-person profiles built from their emails.
 * The AI only ever sees the short profile, never the full history.
 */
export default function Customers({ focusEmail, refreshKey, onToast }) {
  const [list, setList] = useState([]);
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(focusEmail ?? null);
  const [detail, setDetail] = useState(null);

  const loadList = useCallback(async () => {
    try {
      setList((await getCustomers(search)).customers);
    } catch (err) {
      onToast(err.message, 'error');
    }
  }, [search, onToast]);

  useEffect(() => {
    const t = setTimeout(loadList, 250); // debounce typing
    return () => clearTimeout(t);
  }, [loadList, refreshKey]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    getCustomer(selected)
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((err) => onToast(err.message, 'error'));
    return () => { cancelled = true; };
  }, [selected, onToast]);

  const erase = async () => {
    const who = detail.customer.name || detail.customer.email;
    if (!window.confirm(`Permanently delete ALL data about ${who}? This removes the profile, their leads and every stored email. This cannot be undone.`)) return;
    try {
      await eraseCustomer(detail.customer.email);
      onToast(`All data about ${who} was deleted.`);
      setSelected(null);
      setDetail(null);
      loadList();
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-desc">Profiles build themselves from emails — name, company, topics, mood and notes the AI uses to personalise replies.</div>
        </div>
      </div>

      <div className="md-layout">
        <div className="card">
          <div className="card-head">
            <label className="input-icon" style={{ flex: 1 }}>
              <Search size={15} />
              <input className="input" placeholder="Search name, company, email…" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
          </div>
          <div className="md-list">
            {list.length === 0 ? (
              <Empty icon={Users} title="No customers yet">Profiles appear after the first real customer email.</Empty>
            ) : list.map((c) => (
              <button key={c.email} className={`md-item ${selected === c.email ? 'active' : ''}`} onClick={() => setSelected(c.email)}>
                <div className="person">
                  <Avatar name={c.name} email={c.email} />
                  <div className="person-text">
                    <div className="md-item-title">{c.name || c.email}</div>
                    <div className="md-item-meta">
                      {c.company && <span>{c.company} ·</span>}
                      <span>{c.email_count} email{c.email_count === 1 ? '' : 's'}</span>
                      <span>· {timeAgo(c.last_seen)}</span>
                    </div>
                  </div>
                  <span style={{ marginLeft: 'auto' }}><MoodBadge mood={c.mood} /></span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="card">
          {!detail || detail.customer.email !== selected ? (
            <Empty icon={Users} title="Select a customer">See everything the AI knows about them, edit notes, or delete their data.</Empty>
          ) : (
            <Profile key={detail.customer.email} detail={detail} onErase={erase} onToast={onToast}
                     onSaved={(c) => setDetail((d) => ({ ...d, customer: c }))} />
          )}
        </div>
      </div>
    </>
  );
}

function Profile({ detail, onErase, onToast, onSaved }) {
  const c = detail.customer;
  const [form, setForm] = useState({ name: c.name ?? '', company: c.company ?? '', notes: c.notes ?? '' });
  const dirty = form.name !== (c.name ?? '') || form.company !== (c.company ?? '') || form.notes !== (c.notes ?? '');
  const topics = Object.entries(c.topics ?? {}).sort((a, b) => b[1] - a[1]);

  const save = async () => {
    try {
      onSaved((await updateCustomer(c.email, form)).customer);
      onToast('Profile saved — the AI uses it from the next email.');
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  return (
    <>
      <div className="card-body editor">
        <div className="profile-head">
          <Avatar name={c.name} email={c.email} size="lg" />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="profile-name">{c.name || c.email}</div>
            <div className="card-sub">{c.email}{c.company ? ` · ${c.company}` : ''}</div>
          </div>
          <MoodBadge mood={c.mood} />
          {c.escalations > 0 && <span className="badge tone-red">{c.escalations} escalation{c.escalations === 1 ? '' : 's'}</span>}
        </div>

        <div className="facts">
          <div className="fact"><span>Customer since</span><b>{formatTime(c.first_seen).split(',')[0]}</b></div>
          <div className="fact"><span>Last contact</span><b>{timeAgo(c.last_seen)}</b></div>
          <div className="fact"><span>Emails</span><b className="num">{c.email_count}</b></div>
          <div className="fact"><span>Language</span><b>{(c.lang || 'en').toUpperCase()}</b></div>
        </div>

        {topics.length > 0 && (
          <div>
            <div className="detail-label">Topics</div>
            <div className="chips">
              {topics.map(([t, n]) => <span key={t} className="badge cap tone-gray">{t} · {n}</span>)}
            </div>
          </div>
        )}

        {c.mood_history?.length > 0 && (
          <div>
            <div className="detail-label"><Activity size={12} style={{ verticalAlign: -1 }} /> Mood over time</div>
            <div className="mood-trail">
              {c.mood_history.map((m, i) => (
                <span key={i} title={formatTime(m.at)}><MoodBadge mood={m.mood} /></span>
              ))}
            </div>
          </div>
        )}

        <div className="form-grid">
          <div className="field">
            <label className="field-label" htmlFor="cust-name">Name</label>
            <input id="cust-name" className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="cust-company">Company</label>
            <input id="cust-company" className="input" value={form.company} onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))} />
          </div>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="cust-notes"><StickyNote size={13} style={{ verticalAlign: -2 }} /> Notes the AI remembers</label>
          <textarea id="cust-notes" className="textarea" rows={5} maxLength={800} value={form.notes}
                    onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
          <div className="counter"><span>Kept short on purpose so replies stay fast and cheap.</span><span>{form.notes.length} / 800</span></div>
        </div>

        <div className="toolbar" style={{ justifyContent: 'space-between' }}>
          <button className="btn btn-danger" onClick={onErase}><Trash2 size={15} />Delete all data (GDPR)</button>
          <button className="btn btn-primary" disabled={!dirty} onClick={save}><Save size={15} />Save profile</button>
        </div>
      </div>

      {detail.leads.length > 0 && (
        <>
          <div className="card-head" style={{ borderTop: '1px solid var(--border)' }}>
            <span className="card-title"><Briefcase size={16} />Leads</span>
          </div>
          {detail.leads.map((l) => (
            <div key={l.id} className="list-row">
              <div className="list-row-main">
                <div className="cell-main">{l.summary || l.subject}</div>
                <div className="cell-sub">{[l.services, l.websites && `${l.websites} sites`, l.mailboxes && `${l.mailboxes} mailboxes`, l.timeline].filter(Boolean).join(' · ')}</div>
              </div>
              {l.value ? <b className="num">{money(l.value)}</b> : null}
              <HandlerBadge handledBy={l.handled_by} />
              <StageBadge stage={l.stage} />
            </div>
          ))}
        </>
      )}

      <div className="card-head" style={{ borderTop: '1px solid var(--border)' }}>
        <span className="card-title"><Mail size={16} />Recent emails</span>
      </div>
      <div className="card-body" style={{ paddingTop: 4 }}>
        <div className="timeline">
          {detail.emails.map((e) => (
            <div key={e.id} className="timeline-item">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="cell-main">{e.subject}</div>
                <div className="cell-sub">{e.summary || e.original_body?.slice(0, 120)}</div>
              </div>
              <CategoryBadge category={e.category} />
              <StatusBadge log={e} />
              <span className="cell-time">{timeAgo(e.timestamp)}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
