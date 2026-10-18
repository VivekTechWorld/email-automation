import { useState, useEffect, useCallback } from 'react';
import {
  Mail, Bot, Hourglass, ShieldAlert, Sparkles, RefreshCw, BarChart3, Tags, Lightbulb, Repeat,
} from 'lucide-react';
import { getReport, getInsights } from '../api';
import { KpiTile } from './ui';
import BarChart from './BarChart';
import EmailLogTable from './EmailLogTable';
import { CATEGORY_TONE, SERIES } from '../lib/format';

const TONE_COLOR = {
  teal: 'var(--teal)', blue: 'var(--primary)', violet: 'var(--violet)',
  amber: 'var(--amber)', red: 'var(--red)', gray: 'var(--gray)',
};

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

export default function Overview({ logs, refreshKey, onToast }) {
  const [days, setDays] = useState(7);
  const [report, setReport] = useState(null);
  const [insights, setInsights] = useState(null);
  const [thinking, setThinking] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getReport(days)
      .then((r) => { if (!cancelled) setReport(r); })
      .catch((err) => onToast(err.message, 'error'));
    return () => { cancelled = true; };
  }, [days, refreshKey, onToast]);

  const loadInsights = useCallback(async (refresh = false) => {
    setThinking(true);
    try {
      setInsights(await getInsights(days, refresh));
    } catch (err) {
      onToast(err.message, 'error');
    } finally {
      setThinking(false);
    }
  }, [days, onToast]);

  useEffect(() => { loadInsights(false); }, [loadInsights]);

  const delta = report && report.emails_prev
    ? Math.round(((report.emails - report.emails_prev) / report.emails_prev) * 100)
    : null;

  const daily = (report?.daily ?? []).map((d) => ({ date: d.date, ai: d.ai, human: d.emails - d.ai }));
  const topics = Object.entries(report?.topics ?? {});
  const maxTopic = Math.max(1, ...topics.map(([, n]) => n));

  return (
    <>
      <div className="hero">
        <div className="hero-text">
          <div className="hero-eyebrow">{greeting()}</div>
          <div className="hero-title">Here’s how your inbox is doing</div>
          <div className="hero-sub">
            {report
              ? `The AI answered ${report.ai_rate}% of ${report.emails} emails in the last ${days} days.`
              : 'Loading the latest numbers…'}
          </div>
        </div>
        <div className="hero-figures">
          <div className="segmented" style={{ background: 'rgba(255,255,255,0.15)', borderColor: 'rgba(255,255,255,0.25)' }}>
            {[7, 30].map((d) => (
              <button
                key={d}
                className={days === d ? 'active' : ''}
                style={days === d ? {} : { color: '#fff' }}
                onClick={() => setDays(d)}
              >
                {d} days
              </button>
            ))}
          </div>
        </div>
      </div>

      {!report ? (
        <div className="kpis">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 104 }} />)}</div>
      ) : (
        <div className="kpis">
          <KpiTile icon={Mail} gradient="g-primary" label="Customer emails" value={report.emails}
                   delta={delta} hint="vs previous period" />
          <KpiTile icon={Bot} gradient="g-blue" label="Answered by AI" value={`${report.ai_rate}%`}
                   hint={`${report.ai_answered} replies sent automatically`} />
          <KpiTile icon={Hourglass} gradient="g-amber" label="Waiting for review" value={report.waiting_review}
                   hint={`${report.human_reviewed} handled by the team`} />
          <KpiTile icon={ShieldAlert} gradient="g-rose" label="Escalations" value={report.escalations}
                   hint={`${report.skipped_automated} automated emails skipped`} />
          <KpiTile icon={Repeat} gradient="g-violet" label="Follow-ups sent" value={report.followups_sent}
                   hint="to customers who went quiet" />
        </div>
      )}

      <div className="card card-accent">
        <div className="card-head">
          <span className="card-title"><Sparkles size={16} />AI insights</span>
          <div className="toolbar">
            <span className="card-sub">
              {insights && (insights.source === 'ai' ? 'Written by AI · refreshed once a day' : 'Summary from rules (AI unavailable)')}
            </span>
            <button className="btn btn-sm btn-ghost btn-icon" onClick={() => loadInsights(true)} disabled={thinking}
                    title="Regenerate" aria-label="Regenerate insights">
              <RefreshCw size={14} className={thinking ? 'spin' : ''} />
            </button>
          </div>
        </div>
        <div className="card-body">
          {!insights ? (
            <div className="skeleton" style={{ height: 90 }} />
          ) : (
            <div className="insights wide">
              {insights.bullets.map((b, i) => (
                <div key={i} className="insight">
                  <span className={`insight-dot ${['g-primary', 'g-teal', 'g-violet', 'g-amber', 'g-blue', 'g-green'][i % 6]}`}>
                    <Lightbulb size={12} />
                  </span>
                  <span>{b}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid-3-1">
        <div className="card">
          <div className="card-head">
            <span className="card-title"><BarChart3 size={16} />Emails per day</span>
            <span className="card-sub">who answered</span>
          </div>
          <div className="card-body">
            <BarChart
              data={daily}
              series={[
                { key: 'ai', label: 'Answered by AI', color: SERIES.ai.color },
                { key: 'human', label: 'Needed the team', color: SERIES.human.color },
              ]}
              emptyText="No customer emails in this period."
            />
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <span className="card-title"><Tags size={16} />Topics</span>
            <span className="card-sub">{report ? `${report.kb_hit_rate}% answered from knowledge base` : ''}</span>
          </div>
          <div className="card-body">
            {topics.length === 0 ? (
              <div className="card-sub">No emails in this period.</div>
            ) : (
              <div className="bars">
                {topics.map(([cat, count]) => (
                  <div key={cat}>
                    <div className="bar-row-top"><span>{cat}</span><span className="num">{count}</span></div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{
                        width: `${(count / maxTopic) * 100}%`,
                        background: TONE_COLOR[CATEGORY_TONE[cat] ?? 'gray'],
                      }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <EmailLogTable logs={logs} />
    </>
  );
}
