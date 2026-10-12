/**
 * SeverityBreakdown — Visual severity distribution with bar charts
 */
export default function SeverityBreakdown({ stats }) {
  const bySev = stats?.by_severity ?? { normal: 0, high: 0, critical: 0 };
  const total = (bySev.normal ?? 0) + (bySev.high ?? 0) + (bySev.critical ?? 0);
  const pct = (val) => total === 0 ? 0 : Math.round((val / total) * 100);

  const rows = [
    { key: 'normal',   label: 'Normal',   count: bySev.normal   ?? 0, dot: '🟢' },
    { key: 'high',     label: 'High',     count: bySev.high     ?? 0, dot: '🟡' },
    { key: 'critical', label: 'Critical', count: bySev.critical ?? 0, dot: '🔴' },
  ];

  const byCategory = stats?.by_category ?? {};
  const catEntries = Object.entries(byCategory).sort((a, b) => b[1] - a[1]);

  return (
    <div className="card" style={{ height: '100%' }}>
      <div className="card-header">
        <span className="card-title">Severity Breakdown</span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {total} total
        </span>
      </div>
      <div className="card-body">
        <div className="severity-list">
          {rows.map(({ key, label, count, dot }) => (
            <div className="severity-row" key={key}>
              <div className="severity-row-top">
                <span className={`severity-badge ${key}`}>
                  {dot} {label}
                </span>
                <span className="severity-count">{count}</span>
              </div>
              <div className="severity-bar-track">
                <div
                  className={`severity-bar-fill ${key}`}
                  style={{ width: `${pct(count)}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        {/* Category breakdown */}
        {catEntries.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <div className="section-title" style={{ marginBottom: 12 }}>By Category</div>
            <div className="category-grid">
              {catEntries.map(([cat, count]) => (
                <span key={cat} className={`cat-pill ${cat}`}>
                  {catIcon(cat)} {cat}
                  <strong style={{ marginLeft: 4, opacity: 0.9 }}>{count}</strong>
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function catIcon(cat) {
  const icons = {
    sales: '💼', inquiry: '❓', billing: '💳',
    support: '🔧', bug: '🐛', other: '📌',
  };
  return icons[cat] ?? '📌';
}
