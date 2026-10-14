// Shared injury-risk (workload) UI: level badge, factor bars, feature grid.
// Colour is never the only signal: every level also has an icon and a text label.
import { DATA_QUALITY, FEATURES, formatFeature, LEVEL_META } from '../lib/risk';
import { WORKLOAD_DISCLAIMER } from '../lib/metrics';
import { Icon } from './ui';

export function RiskLevelBadge({ level, riskPercent, className = '' }) {
  const meta = LEVEL_META[level] || LEVEL_META.unknown;
  const known = level !== 'unknown' && riskPercent != null;
  return (
    <span
      data-level={level}
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-chip px-2.5 py-0.5 text-caption font-semibold ring-1 ring-inset ${meta.bg} ${meta.text} ${meta.ring} ${
        level === 'unknown' ? 'border border-dashed border-risk-unknown-ring ring-0' : ''
      } ${className}`}
    >
      {meta.icon ? <Icon name={meta.icon} className="size-3.5" /> : <NotScoredIcon />}
      <span>{meta.label}</span>
      {known && (
        <span className="font-mono tabular-nums">
          {Number.isInteger(riskPercent) ? riskPercent : Number(riskPercent).toFixed(1)}%
        </span>
      )}
    </span>
  );
}

// Neutral slate "not scored" mark (circle with a slash); never a risk colour.
function NotScoredIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" />
      <path d="M6 18L18 6" />
    </svg>
  );
}

// Why a player has no number (score_note), shown instead of a percentage.
export function ScoreNote({ item, className = '' }) {
  if (!item || item.score_status === 'scored' || !item.score_note) return null;
  return (
    <span className={`text-caption text-fg-muted ${className}`} data-score-note={item.score_status}>
      {item.score_note}
    </span>
  );
}

// Where a score came from. Demo/stub data is loudly marked (dashed amber status chip).
export function DataQualityBadge({ quality, className = '' }) {
  const meta = DATA_QUALITY[quality];
  if (!meta) return null;
  const tone =
    quality === 'demo'
      ? 'border border-dashed border-risk-medium-ring bg-risk-medium-bg text-status-warning font-semibold uppercase tracking-label'
      : 'bg-surface-overlay text-fg-secondary ring-1 ring-inset ring-line-strong';
  return (
    <span data-quality={quality} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-chip px-2 py-0.5 text-caption ${tone} ${className}`}>
      {quality === 'demo' && <Icon name="alert" className="size-3.5" />}
      {quality === 'csv' && <Icon name="chart" className="size-3.5" />}
      {quality === 'calibrated' && <Icon name="video" className="size-3.5" />}
      {meta.label}
    </span>
  );
}

export function WorkloadDisclaimer({ className = '' }) {
  return (
    <p className={`text-caption text-fg-muted ${className}`} data-disclaimer>
      {WORKLOAD_DISCLAIMER}.
    </p>
  );
}

// Bars show relative size only (log-odds contributions are not percentages).
export function FactorBars({ factors, limit, className = '' }) {
  const list = limit ? factors.slice(0, limit) : factors;
  if (!list.length) return <p className={`text-caption text-fg-muted ${className}`}>No contributing factors reported.</p>;
  return (
    <ul className={`space-y-2.5 ${className}`} data-factors>
      {list.map((f, i) => {
        const up = f.direction === 'up';
        return (
          <li key={`${f.feature}-${i}`} data-factor={f.feature} data-direction={f.direction} data-width={f.width}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 text-caption">
              <span className="font-medium text-fg-secondary">
                {f.label}
                {f.value != null && <span className="ml-1.5 font-mono text-fg-muted">{formatFeature(f.feature, f.value)}</span>}
              </span>
              <span className={`inline-flex items-center gap-1 ${up ? 'text-risk-high' : 'text-risk-low'}`}>
                <span aria-hidden="true">{up ? '▲' : '▼'}</span>
                {up ? 'Raises risk' : 'Lowers risk'}
              </span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-surface-overlay" aria-hidden="true">
              <div className={`h-full rounded-full ${up ? 'bg-risk-high' : 'bg-risk-low'}`} style={{ width: `${Math.max(f.width, 2)}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const toneClass = { speed: 'text-metric-speed', distance: 'text-metric-distance' };

export function FeatureGrid({ features }) {
  const known = FEATURES.filter((f) => features?.[f.key] != null);
  if (!known.length) return <p className="text-caption text-fg-muted">No workload inputs recorded.</p>;
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3" data-features>
      {known.map((f) => (
        <div key={f.key} className="min-w-0">
          <dt className="truncate text-caption text-fg-muted">{f.label}</dt>
          <dd className={`font-mono text-body tabular-nums ${toneClass[f.tone] || 'text-fg'}`}>{formatFeature(f.key, features[f.key])}</dd>
        </div>
      ))}
    </dl>
  );
}
