import { useState, useEffect, useMemo, useCallback, Fragment } from 'react';
import {
  Coins, Clock, Trophy, AlertTriangle, Bot, UserRound, BarChart3, Filter,
  BellRing, Search, Briefcase, ExternalLink, Save, Repeat,
} from 'lucide-react';
import { getLeads, getLeadMetrics, updateLead } from '../api';
import { KpiTile, StageBadge, HandlerBadge, Avatar, Empty } from './ui';
import BarChart from './BarChart';
import { STAGE_INFO, SERIES, formatSeconds, money, timeAgo, pct } from '../lib/format';

const DETAIL_FIELDS = [
  ['services', 'Services'], ['websites', 'Websites'], ['mailboxes', 'Mailboxes'],
  ['storage', 'Storage'], ['budget', 'Budget'], ['timeline', 'Timeline'],
];

export default function Sales({ refreshKey, onToast, onOpenCustomer }) {
  const [metrics, setMetrics] = useState(null);
  const [leads, setLeads] = useState([]);
  const [stage, setStage] = useState('all');
  const [handler, setHandler] = useState('all');
  const [search, setSearch] = useState('');
  const [openId, setOpenId] = useState(null);

  const load = useCallback(async () => {
    try {
      const [m, l] = await Promise.all([getLeadMetrics(30), getLeads()]);
      setMetrics(m);
      setLeads(l.leads);
    } catch (err) {
      onToast(err.message, 'error');
    }
  }, [onToast]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const save = async (id, changes, message = 'Lead updated.') => {
    try {
      const { lead, takeover } = await updateLead(id, changes);
      setLeads((all) => all.map((l) => (l.id === id ? lead : l)));
      // Handing a lead to the AI may answer the customer right away — say what happened
      onToast(takeover ? takeover.message : message, takeover && !takeover.sent && takeover.message.includes('could not') ? 'error' : 'success');
      getLeadMetrics(30).then(setMetrics).catch(() => {});
    } catch (err) {
      onToast(err.message, 'error');
    }
  };

  const switchHandler = (lead) => {
    const next = lead.handled_by === 'ai' ? 'human' : 'ai';
    const question = next === 'ai'
      ? `Hand ${lead.name || lead.customer_email} to the AI?\n\nThe AI will answer this customer from now on, recommend a plan with the price from your knowledge base, and close the deal when they accept. If an email from them is waiting in the Review queue, the AI replies to it now.`
      : `Hand ${lead.name || lead.customer_email} to your sales team?\n\nTheir next emails will wait in the Review queue for a person.`;
    if (window.confirm(question)) save(lead.id, { handled_by: next }, `${lead.name || 'Lead'} is now handled by your team.`);
  };

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return leads.filter((l) =>
      (stage === 'all' || l.stage === stage) &&
      (handler === 'all' || l.handled_by === handler) &&
      (!q || [l.name, l.company, l.customer_email, l.summary, l.services].some((v) => v?.toLowerCase().includes(q))));
  }, [leads, stage, handler, search]);

  if (!metrics) {
    return <div className="kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 104 }} />)}</div>;
  }

  const ai = metrics.by_handler.ai;
  const human = metrics.by_handler.human;
  const totalHandled = ai.total + human.total;

  return (
    <>
      <div className="hero sales">
        <div className="hero-text">
          <div className="hero-eyebrow">Sales pipeline</div>
          <div className="hero-title">{metrics.open} open lead{metrics.open === 1 ? '' : 's'} worth {money(metrics.pipeline_value)}</div>
          <div className="hero-sub">Leads are captured from sales emails. Quotes move them to “Quote sent”; the customer’s yes turns them into revenue.</div>
        </div>
        <div className="hero-figures">
          <div className="hero-figure"><b className="num">{money(metrics.revenue_period)}</b><span>revenue (30 days)</span></div>
          <div className="hero-figure"><b className="num">{metrics.win_rate ?? '—'}{metrics.win_rate != null && '%'}</b><span>win rate</span></div>
          <div className="hero-figure"><b className="num">{metrics.new_this_week}</b><span>new this week</span></div>
        </div>
      </div>

      <div className="kpis">
        <KpiTile icon={Coins} gradient="g-green" label="Revenue (all time)" value={money(metrics.won_value)}
                 hint={`${money(metrics.revenue_week)} this week`} />
        <KpiTile icon={Trophy} gradient="g-teal" label="Won deals" value={metrics.won}
                 hint={`${metrics.lost} lost · ${metrics.open} open`} />
        <KpiTile icon={Clock} gradient="g-blue" label="First response time" value={formatSeconds(metrics.avg_response_sec)}
                 hint="average, all leads" />
        <KpiTile icon={AlertTriangle} gradient="g-amber" label="Needs attention" value={metrics.attention.length}
                 hint="see list below" />
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head">
            <span className="card-title"><Bot size={16} />AI vs team</span>
            <span className="card-sub">who is working the leads</span>
          </div>
          <div className="card-body">
            <div className="split">
              <HandlerSide kind="ai" data={ai} />
              <HandlerSide kind="human" data={human} />
            </div>
            <div className="split-bar" aria-label={`AI ${pct(ai.total, totalHandled)}%, team ${pct(human.total, totalHandled)}%`}>
              {ai.total > 0 && <div style={{ width: `${pct(ai.total, totalHandled)}%`, background: SERIES.ai.color }} />}
              {human.total > 0 && <div style={{ width: `${pct(human.total, totalHandled)}%`, background: SERIES.human.color }} />}
            </div>
            <div className="legend" style={{ marginTop: 8, justifyContent: 'space-between' }}>
              <span className="legend-item"><span className="swatch" style={{ background: SERIES.ai.color }} />AI {pct(ai.total, totalHandled)}%</span>
              <span className="legend-item"><span className="swatch" style={{ background: SERIES.human.color }} />Team {pct(human.total, totalHandled)}%</span>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title"><Coins size={16} />Revenue per day</span>
            <span className="card-sub">deals won · last 30 days</span>
          </div>
          <div className="card-body">
            <BarChart
              data={metrics.daily}
              series={[
                { key: 'revenue_ai', label: 'Closed by AI', color: SERIES.ai.color },
                { key: 'revenue_human', label: 'Closed by team', color: SERIES.human.color },
              ]}
              format={money}
              emptyText="No deals won in the last 30 days yet."
            />
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-head">
            <span className="card-title"><BarChart3 size={16} />New leads per day</span>
            <span className="card-sub">last 30 days</span>
          </div>
          <div className="card-body">
            <BarChart
              data={metrics.daily}
              series={[
                { key: 'ai', label: 'Handled by AI', color: SERIES.ai.color },
                { key: 'human', label: 'Handled by team', color: SERIES.human.color },
              ]}
              emptyText="No new leads in the last 30 days."
            />
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title"><Filter size={16} />Pipeline by stage</span>
            <div className="legend">
              <span className="legend-item"><span className="swatch" style={{ background: SERIES.ai.color }} />AI</span>
              <span className="legend-item"><span className="swatch" style={{ background: SERIES.human.color }} />Team</span>
            </div>
          </div>
          <div className="card-body">
            <Funnel byStage={metrics.by_stage} stages={metrics.stages} onPick={(s) => setStage(s)} />
          </div>
        </div>
      </div>

      <div>
        <div className="card">
          <div className="card-head">
            <span className="card-title"><BellRing size={16} />Needs attention</span>
            <span className="card-sub">{metrics.attention.length} lead{metrics.attention.length === 1 ? '' : 's'}</span>
          </div>
          {metrics.attention.length === 0 ? (
            <Empty icon={Trophy} title="All caught up">No stalled leads right now.</Empty>
          ) : (
            <div>
              {metrics.attention.map((l) => (
                <div key={l.id} className="list-row">
                  <Avatar name={l.name} email={l.customer_email} />
                  <div className="list-row-main">
                    <div className="cell-main">{l.name || l.customer_email}{l.company ? ` · ${l.company}` : ''}</div>
                    <div className="cell-sub">{l.reason}</div>
                  </div>
                  <StageBadge stage={l.stage} />
                  <button className="btn btn-sm" onClick={() => { setStage('all'); setOpenId(l.id); }}>Open</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <div className="card-title"><Briefcase size={16} />Leads</div>
            <div className="card-sub">Showing {visible.length} of {leads.length} · click a lead to edit</div>
          </div>
          <div className="toolbar">
            <label className="input-icon search">
              <Search size={15} />
              <input className="input" placeholder="Search leads…" value={search} onChange={(e) => setSearch(e.target.value)} />
            </label>
            <div className="segmented">
              {[['all', 'All'], ['ai', 'AI'], ['human', 'Team']].map(([k, label]) => (
                <button key={k} className={handler === k ? 'active' : ''} onClick={() => setHandler(k)}>{label}</button>
              ))}
            </div>
          </div>
        </div>
        <div className="card-body" style={{ paddingBottom: 12 }}>
          <div className="chips">
            <button className={`chip ${stage === 'all' ? 'active' : ''}`} onClick={() => setStage('all')}>All stages</button>
            {metrics.stages.map((s) => (
              <button key={s} className={`chip ${stage === s ? 'active' : ''}`} onClick={() => setStage(s)}>
                {STAGE_INFO[s].label}
                <span className="chip-n">{metrics.by_stage[s].ai + metrics.by_stage[s].human}</span>
              </button>
            ))}
          </div>
        </div>

        {visible.length === 0 ? (
          <Empty icon={Briefcase} title={leads.length ? 'No matching leads' : 'No leads yet'}>
            {leads.length ? 'Try another filter.' : 'Sales emails (quotes, pricing, upgrades) create leads automatically.'}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Lead</th>
                  <th>Stage</th>
                  <th>Handled by</th>
                  <th>Owner</th>
                  <th style={{ textAlign: 'right' }}>Value</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((l) => (
                  <Fragment key={l.id}>
                    <tr className={`row ${openId === l.id ? 'open' : ''}`} onClick={() => setOpenId(openId === l.id ? null : l.id)}>
                      <td>
                        <div className="person">
                          <Avatar name={l.name} email={l.customer_email} />
                          <div className="person-text">
                            <div className="cell-main">{l.name || l.customer_email}{l.company ? ` · ${l.company}` : ''}</div>
                            <div className="cell-sub">{l.summary || l.subject}</div>
                          </div>
                        </div>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <select
                          className="select select-sm"
                          value={l.stage}
                          aria-label="Stage"
                          onChange={(e) => save(l.id, { stage: e.target.value }, `Moved to ${STAGE_INFO[e.target.value].label}.`)}
                        >
                          {metrics.stages.map((s) => <option key={s} value={s}>{STAGE_INFO[s].label}</option>)}
                        </select>
                      </td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <button className="handler-switch" onClick={() => switchHandler(l)} disabled={l.stage === 'won' || l.stage === 'lost'}
                                title={l.handled_by === 'ai' ? 'Click to hand this lead to your team' : 'Click to let the AI handle this lead'}>
                          <HandlerBadge handledBy={l.handled_by} /><Repeat size={12} />
                        </button>
                      </td>
                      <td className="cell-time">{l.owner || '—'}</td>
                      <td className="num" style={{ textAlign: 'right', fontWeight: 600 }}>{l.value ? money(l.value) : '—'}</td>
                      <td className="cell-time">{timeAgo(l.updated_at)}</td>
                    </tr>
                    {openId === l.id && (
                      <tr>
                        <td colSpan={6} className="detail-cell">
                          <LeadEditor lead={l} onSave={(changes) => save(l.id, changes)} onOpenCustomer={onOpenCustomer} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  );
}

function HandlerSide({ kind, data }) {
  const isAi = kind === 'ai';
  const Icon = isAi ? Bot : UserRound;
  return (
    <div className={`split-side ${kind}`}>
      <div className="split-head">
        <span className={`setting-icon ${isAi ? 'g-blue' : 'g-amber'}`} style={{ width: 26, height: 26, borderRadius: 8 }}>
          <Icon size={14} />
        </span>
        {isAi ? 'Handled by AI' : 'Handled by team'}
      </div>
      <div className="split-big num">{data.total}</div>
      <div className="split-facts">
        <span><b>{data.open}</b> open · <b>{data.won}</b> won</span>
        <span>Win rate <b>{data.win_rate != null ? `${data.win_rate}%` : '—'}</b></span>
        <span>First reply <b>{formatSeconds(data.avg_response_sec)}</b></span>
        <span>Revenue <b>{money(data.revenue)}</b></span>
      </div>
    </div>
  );
}

function Funnel({ byStage, stages, onPick }) {
  const max = Math.max(1, ...stages.map((s) => byStage[s].ai + byStage[s].human));
  return (
    <div className="bars">
      {stages.map((s) => {
        const { ai, human } = byStage[s];
        const total = ai + human;
        return (
          <button
            key={s}
            onClick={() => onPick(s)}
            style={{ border: 'none', background: 'none', textAlign: 'left', padding: 0 }}
            title={`${STAGE_INFO[s].label}: ${ai} AI, ${human} team — click to filter`}
          >
            <div className="bar-row-top">
              <span style={{ textTransform: 'none' }}>{STAGE_INFO[s].label}</span>
              <span className="num">{total}</span>
            </div>
            <div className="bar-track" style={{ background: total ? 'var(--gray-soft)' : 'var(--gray-soft)' }}>
              {ai > 0 && <div className="bar-fill" style={{ width: `${(ai / max) * 100}%`, background: SERIES.ai.color }} />}
              {human > 0 && <div className="bar-fill" style={{ width: `${(human / max) * 100}%`, background: SERIES.human.color }} />}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function LeadEditor({ lead, onSave, onOpenCustomer }) {
  const [form, setForm] = useState(() => ({
    owner: lead.owner ?? '',
    value: lead.value ?? '',
    handled_by: lead.handled_by,
    ...Object.fromEntries(DETAIL_FIELDS.map(([k]) => [k, lead[k] ?? ''])),
  }));
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = () => {
    const changes = { ...form, value: form.value === '' ? 0 : Number(form.value) };
    onSave(changes);
  };

  return (
    <div className="detail">
      <div className="detail-facts">
        <span><b>{lead.customer_email}</b></span>
        <span>{lead.email_count} email{lead.email_count === 1 ? '' : 's'}</span>
        <span>First reply <b>{formatSeconds(lead.first_response_sec)}</b></span>
        <span>Created {timeAgo(lead.created_at)}</span>
        {lead.quoted_at && <span>Quote sent {timeAgo(lead.quoted_at)}{lead.value_source === 'quote' ? ' (value taken from the quote)' : ''}</span>}
        {lead.closed_at && <span>{lead.stage === 'won' ? 'Won' : 'Lost'} {timeAgo(lead.closed_at)}{lead.closed_by === 'customer' ? ' — customer replied' : ' — set by team'}</span>}
        <button className="btn btn-sm" onClick={() => onOpenCustomer(lead.customer_email)}>
          <ExternalLink size={14} />Customer profile
        </button>
      </div>
      <div className="form-grid">
        <div className="field">
          <label className="field-label" htmlFor={`owner-${lead.id}`}>Owner</label>
          <input id={`owner-${lead.id}`} className="input" placeholder="Who is working this lead?" value={form.owner} onChange={set('owner')} />
        </div>
        <div className="field">
          <label className="field-label" htmlFor={`value-${lead.id}`}>Deal value (EUR)</label>
          <input id={`value-${lead.id}`} className="input" type="number" min="0" value={form.value} onChange={set('value')} />
        </div>
        <div className="field">
          <span className="field-label">Handled by</span>
          <div className="segmented">
            <button className={form.handled_by === 'ai' ? 'active' : ''} onClick={() => setForm((f) => ({ ...f, handled_by: 'ai' }))}>AI</button>
            <button className={form.handled_by === 'human' ? 'active' : ''} onClick={() => setForm((f) => ({ ...f, handled_by: 'human' }))}>Team</button>
          </div>
        </div>
        {DETAIL_FIELDS.map(([k, label]) => (
          <div key={k} className="field">
            <label className="field-label" htmlFor={`${k}-${lead.id}`}>{label}</label>
            <input id={`${k}-${lead.id}`} className="input" value={form[k]} onChange={set(k)} placeholder="—" />
          </div>
        ))}
      </div>
      <div className="toolbar" style={{ justifyContent: 'flex-end' }}>
        <button className="btn btn-primary" onClick={submit}><Save size={15} />Save lead</button>
      </div>
    </div>
  );
}
