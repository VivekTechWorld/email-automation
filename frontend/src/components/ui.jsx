import {
  Smile, Meh, Frown, Angry, Bot, UserRound, ArrowUpRight, ArrowDownRight,
} from 'lucide-react';
import {
  CATEGORY_TONE, STATUS_INFO, MOOD_INFO, STAGE_INFO, avatarClass, initials,
} from '../lib/format';

export function CategoryBadge({ category }) {
  return <span className={`badge cap tone-${CATEGORY_TONE[category] ?? 'gray'}`}>{category || 'other'}</span>;
}

export function StatusBadge({ log }) {
  const key = log.alert ? 'alert' : (log.status || 'sent');
  const info = STATUS_INFO[key] ?? STATUS_INFO.sent;
  return <span className={`badge tone-${info.tone}`}>{info.label}</span>;
}

const MOOD_ICON = { happy: Smile, neutral: Meh, frustrated: Frown, angry: Angry };

export function MoodBadge({ mood }) {
  if (!mood) return null;
  const info = MOOD_INFO[mood] ?? MOOD_INFO.neutral;
  const Icon = MOOD_ICON[mood] ?? Meh;
  return <span className={`badge tone-${info.tone}`}><Icon />{info.label}</span>;
}

export function StageBadge({ stage }) {
  const info = STAGE_INFO[stage] ?? STAGE_INFO.new;
  return <span className={`badge tone-${info.tone}`}>{info.label}</span>;
}

export function HandlerBadge({ handledBy }) {
  return handledBy === 'human'
    ? <span className="badge tone-human"><UserRound />Team</span>
    : <span className="badge tone-ai"><Bot />AI</span>;
}

export function Avatar({ name, email, size }) {
  return (
    <span className={`avatar ${size === 'lg' ? 'lg' : ''} ${avatarClass(email || name)}`} aria-hidden="true">
      {initials(name, email)}
    </span>
  );
}

export function Empty({ icon: Icon, title, children }) {
  return (
    <div className="empty">
      <div className="empty-icon"><Icon size={24} /></div>
      <div className="empty-title">{title}</div>
      <div>{children}</div>
    </div>
  );
}

/**
 * KpiTile — one headline number with a gradient icon and optional change vs. the previous period.
 */
export function KpiTile({ icon: Icon, gradient, label, value, hint, delta }) {
  return (
    <div className="card kpi">
      <div className={`kpi-icon ${gradient}`}><Icon size={20} /></div>
      <div className="kpi-body">
        <div className="kpi-label">{label}</div>
        <div className="kpi-value num">{value}</div>
        <div className="kpi-hint">
          {delta != null && (
            <span className={`delta ${delta >= 0 ? 'up' : 'down'}`}>
              {delta >= 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />}
              {Math.abs(delta)}%
            </span>
          )}
          {hint}
        </div>
      </div>
    </div>
  );
}
