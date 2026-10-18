import { useState } from 'react';
import { Handshake, Timer, Repeat, Flame, GraduationCap, FileBarChart, Cpu, Save, Undo2 } from 'lucide-react';
import { updateSettings, setProvider } from '../api';

/**
 * Settings — how the automation behaves.
 * The parent remounts this (via key) when fresh settings arrive, which resets the form.
 */
export default function Settings({ settings, handoffChoices, provider, model, onSaved, onProviderChange, onToast }) {
  const [form, setForm] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [switching, setSwitching] = useState(false);

  if (!form) return <div className="skeleton" style={{ height: 300 }} />;

  const dirty = JSON.stringify(form) !== JSON.stringify(settings);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  const toggleCategory = (cat) => setForm((f) => ({
    ...f,
    handoff_categories: f.handoff_categories.includes(cat)
      ? f.handoff_categories.filter((c) => c !== cat)
      : [...f.handoff_categories, cat],
  }));

  const save = async () => {
    setSaving(true);
    try {
      const res = await updateSettings({
        ...form,
        auto_reply_timeout_hours: Number(form.auto_reply_timeout_hours),
        followup_after_days: Number(form.followup_after_days),
      });
      onSaved(res.settings);
      onToast('Settings saved.');
    } catch (err) {
      onToast(err.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const switchProvider = async (next) => {
    if (next === provider) return;
    setSwitching(true);
    try {
      const res = await setProvider(next);
      onProviderChange(next, res.model);
      onToast(`Now using ${next === 'gemini' ? 'Google Gemini' : 'local Ollama'}.`);
    } catch (err) {
      onToast(err.message, 'error');
    } finally {
      setSwitching(false);
    }
  };

  return (
    <>
      <div className="section-head">
        <div>
          <div className="section-desc">Decide what the AI does on its own and when a person steps in.</div>
        </div>
        <div className="toolbar">
          {dirty && <button className="btn" onClick={() => setForm(settings)}><Undo2 size={15} />Undo</button>}
          <button className="btn btn-primary" disabled={!dirty || saving} onClick={save}>
            <Save size={15} />{saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>

      <div className="settings-grid">
        <SettingCard icon={Handshake} gradient="g-teal" title="Team handoff" sub="These topics go to the Review queue instead of being answered automatically">
          <div className="check-grid">
            {handoffChoices.map((cat) => (
              <label key={cat} className="check">
                <input type="checkbox" checked={form.handoff_categories.includes(cat)} onChange={() => toggleCategory(cat)} />
                {cat}
              </label>
            ))}
          </div>
          <Field id="handoff-email" label="Notify this team email" hint="They get the customer's message and the AI draft. Leave empty for no email.">
            <input id="handoff-email" className="input" type="email" placeholder="sales@yourcompany.com"
                   value={form.handoff_email} onChange={set('handoff_email')} />
          </Field>
        </SettingCard>

        <SettingCard icon={Timer} gradient="g-amber" title="Auto-reply timer" sub="So no customer waits forever">
          <Toggle label="Send the AI draft if nobody reviews it" hint="Applies to held emails that have a draft."
                  checked={form.auto_reply_enabled} onChange={set('auto_reply_enabled')} />
          <Field id="timeout-hours" label="Wait time (hours)"
                 hint={form.auto_reply_enabled ? `After ${form.auto_reply_timeout_hours || '?'} h without review, the AI reply is sent.` : 'Off — held emails wait for a person.'}>
            <input id="timeout-hours" className="input" type="number" min="0.25" max="720" step="0.5"
                   disabled={!form.auto_reply_enabled} value={form.auto_reply_timeout_hours} onChange={set('auto_reply_timeout_hours')} />
          </Field>
        </SettingCard>

        <SettingCard icon={Repeat} gradient="g-violet" title="Customer follow-ups" sub="One polite reminder when a customer goes quiet">
          <Toggle label="Follow up once if the customer doesn't answer" hint="Only when our reply asked them for information."
                  checked={form.followup_enabled} onChange={set('followup_enabled')} />
          <Field id="followup-days" label="Wait time (days)" hint="Sent in the same email thread, in the customer's language.">
            <input id="followup-days" className="input" type="number" min="0.5" max="30" step="0.5"
                   disabled={!form.followup_enabled} value={form.followup_after_days} onChange={set('followup_after_days')} />
          </Field>
        </SettingCard>

        <SettingCard icon={Flame} gradient="g-rose" title="Escalation" sub="Unhappy customers get a person, fast">
          <Toggle label="Escalate unhappy customers" checked={form.escalation_enabled} onChange={set('escalation_enabled')}
                  hint="Angry tone, frustration repeating within a week, or 3+ emails in 48 hours → Review queue with high priority and an alert." />
        </SettingCard>

        <SettingCard icon={GraduationCap} gradient="g-green" title="Self-learning" sub="The knowledge base grows from your team's answers">
          <Toggle label="Suggest articles from approved replies" checked={form.learning_enabled} onChange={set('learning_enabled')}
                  hint="Personal details are removed. Suggestions wait in Knowledge base → Suggested until someone accepts them." />
        </SettingCard>

        <SettingCard icon={FileBarChart} gradient="g-blue" title="Automatic report" sub="Summary email from n8n every morning at 08:00">
          <Toggle label="Email a report" checked={form.report_enabled} onChange={set('report_enabled')}
                  hint="Includes emails, AI rate, leads, unhappy customers and knowledge gaps." />
          <div className="form-grid">
            <Field id="report-email" label="Send to">
              <input id="report-email" className="input" type="email" placeholder="manager@yourcompany.com"
                     value={form.report_email} onChange={set('report_email')} />
            </Field>
            <Field id="report-frequency" label="How often">
              <select id="report-frequency" className="select" value={form.report_frequency} onChange={set('report_frequency')}>
                <option value="weekly">Weekly (Mondays)</option>
                <option value="daily">Daily</option>
              </select>
            </Field>
          </div>
        </SettingCard>

        <SettingCard icon={Cpu} gradient="g-primary" title="AI engine" sub="Switches instantly, no restart">
          <div className="segmented">
            <button className={provider === 'gemini' ? 'active' : ''} disabled={switching} onClick={() => switchProvider('gemini')}>Google Gemini</button>
            <button className={provider === 'local' ? 'active' : ''} disabled={switching} onClick={() => switchProvider('local')}>Local (Ollama)</button>
          </div>
          <div className="field-hint">
            Current model: <b>{model || '—'}</b>
            {provider === 'local' && ' · falls back to Gemini if Ollama is not running'}
          </div>
        </SettingCard>
      </div>
    </>
  );
}

function SettingCard({ icon: Icon, gradient, title, sub, children }) {
  return (
    <div className="card">
      <div className="card-head">
        <div className="person">
          <span className={`setting-icon ${gradient}`}><Icon size={17} /></span>
          <div className="person-text">
            <div className="card-title">{title}</div>
            <div className="card-sub">{sub}</div>
          </div>
        </div>
      </div>
      <div className="card-body setting-body">{children}</div>
    </div>
  );
}

function Toggle({ label, hint, checked, onChange }) {
  return (
    <div className="switch-row">
      <div>
        <div style={{ fontWeight: 600 }}>{label}</div>
        {hint && <div className="field-hint">{hint}</div>}
      </div>
      <label className="switch">
        <input type="checkbox" checked={checked} onChange={onChange} aria-label={label} />
        <span />
      </label>
    </div>
  );
}

function Field({ id, label, hint, children }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>{label}</label>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}
