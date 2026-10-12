/**
 * StatCards — Row of summary metric cards
 */
export default function StatCards({ stats }) {
  const cards = [
    {
      icon: '📧',
      iconBg: 'rgba(59,130,246,0.12)',
      label: 'Total Emails',
      value: stats?.total ?? 0,
      accent: 'var(--accent-blue)',
    },
    {
      icon: '🚨',
      iconBg: 'rgba(239,68,68,0.12)',
      label: 'Critical Alerts',
      value: stats?.alerts_sent ?? 0,
      accent: 'var(--accent-red)',
    },
    {
      icon: '🔍',
      iconBg: 'rgba(6,182,212,0.12)',
      label: 'RAG Lookups',
      value: stats?.rag_used ?? 0,
      accent: 'var(--accent-cyan)',
    },
    {
      icon: '⚠️',
      iconBg: 'rgba(245,158,11,0.12)',
      label: 'High Severity',
      value: stats?.by_severity?.high ?? 0,
      accent: 'var(--accent-amber)',
    },
    {
      icon: '✅',
      iconBg: 'rgba(16,185,129,0.12)',
      label: 'Normal Replies',
      value: stats?.by_severity?.normal ?? 0,
      accent: 'var(--accent-green)',
    },
    {
      icon: '☁️',
      iconBg: 'rgba(139,92,246,0.12)',
      label: 'Gemini Calls',
      value: stats?.by_provider?.gemini ?? 0,
      accent: 'var(--accent-purple)',
    },
  ];

  return (
    <div className="stats-grid">
      {cards.map((card) => (
        <div
          key={card.label}
          className="stat-card"
          style={{ '--accent-gradient': `linear-gradient(90deg, ${card.accent}, transparent)` }}
        >
          <div className="stat-card-top">
            <div className="stat-icon" style={{ background: card.iconBg }}>
              {card.icon}
            </div>
          </div>
          <div className="stat-value">{card.value.toLocaleString()}</div>
          <div className="stat-label">{card.label}</div>
        </div>
      ))}
    </div>
  );
}
