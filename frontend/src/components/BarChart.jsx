import { useState, useRef } from 'react';
import { formatDay } from '../lib/format';

const HEIGHT = 200;
const PAD = { top: 8, right: 4, bottom: 22, left: 44 };
const GAP = 2; // surface gap between stacked segments

/**
 * BarChart — per-day bars, one series or stacked.
 * data:   [{ date, <seriesKey>: number, ... }]
 * series: [{ key, label, color }]   (bottom segment first)
 */
export default function BarChart({ data, series, emptyText = 'No data yet', format = (v) => v }) {
  const wrapRef = useRef(null);
  const [hover, setHover] = useState(null);

  const totals = data.map((d) => series.reduce((sum, s) => sum + (d[s.key] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const niceMax = max <= 4 ? 4 : Math.ceil(max / 4) * 4;
  const ticks = [0, niceMax / 2, niceMax];

  const width = 600; // viewBox width; the SVG scales to its container
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(1, data.length);
  const barW = Math.max(4, Math.min(22, slot * 0.6));
  const y = (v) => PAD.top + plotH - (v / niceMax) * plotH;
  const labelEvery = Math.ceil(data.length / 7);

  if (!totals.some(Boolean)) {
    return <div className="card-sub" style={{ padding: '40px 0', textAlign: 'center' }}>{emptyText}</div>;
  }

  return (
    <div className="chart" ref={wrapRef} onMouseLeave={() => setHover(null)}>
      {series.length > 1 && (
        <div className="legend" style={{ marginBottom: 10 }}>
          {series.map((s) => (
            <span key={s.key} className="legend-item">
              <span className="swatch" style={{ background: s.color }} />{s.label}
            </span>
          ))}
        </div>
      )}

      <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${width} ${HEIGHT}`} role="img" aria-label={`Bar chart: ${series.map((s) => s.label).join(' and ')} per day`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid-line" x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} />
            <text className="axis-label" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">{format(t)}</text>
          </g>
        ))}

        {data.map((d, i) => {
          const cx = PAD.left + slot * i + slot / 2;
          let base = 0;
          const visible = series.filter((s) => (d[s.key] ?? 0) > 0);
          return (
            <g key={d.date}>
              {visible.map((s, si) => {
                const v = d[s.key];
                const top = y(base + v);
                const bottom = y(base) - (si > 0 ? GAP : 0);
                base += v;
                const h = Math.max(1, bottom - top);
                const isTop = si === visible.length - 1;
                const r = isTop ? Math.min(4, barW / 2, h) : 0;
                // Rounded top corners only on the outermost segment; square at the baseline
                const path = `M${cx - barW / 2},${top + h} V${top + r} Q${cx - barW / 2},${top} ${cx - barW / 2 + r},${top}
                  H${cx + barW / 2 - r} Q${cx + barW / 2},${top} ${cx + barW / 2},${top + r} V${top + h} Z`;
                return <path key={s.key} d={path} fill={s.color} opacity={hover == null || hover === i ? 1 : 0.45} />;
              })}
              {i % labelEvery === 0 && (
                <text className="axis-label" x={cx} y={HEIGHT - 6} textAnchor="middle">{formatDay(d.date)}</text>
              )}
              {/* hit target wider than the bar */}
              <rect
                className="hit"
                x={cx - slot / 2}
                y={PAD.top}
                width={slot}
                height={plotH}
                onMouseEnter={() => setHover(i)}
              />
            </g>
          );
        })}
      </svg>

      {hover != null && (
        <div
          className="chart-tip"
          style={{
            left: `${((PAD.left + slot * hover + slot / 2) / width) * 100}%`,
            top: `${(y(totals[hover]) / HEIGHT) * 100}%`,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{formatDay(data[hover].date)}</div>
          {series.map((s) => (
            <div key={s.key} className="chart-tip-row">
              <span className="swatch" style={{ background: s.color }} />
              {s.label}: <b>{format(data[hover][s.key] ?? 0)}</b>
            </div>
          ))}
        </div>
      )}
      </div>
    </div>
  );
}
