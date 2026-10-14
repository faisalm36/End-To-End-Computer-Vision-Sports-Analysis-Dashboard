import { useState, useEffect, useMemo, useRef } from 'react';
import { API_BASE, getJerseyCorrections, saveJerseyCorrection } from './lib/api';
import { thresholdText, WORKLOAD_DISCLAIMER, zoneText } from './lib/metrics';
import { anyValue, combineHeatmaps, fatiguePct, isNum, LOW_COVERAGE_PCT, NEXT_FIELDS, normalizePlayers, videoThresholds } from './lib/playerStats';
import { useMetricDefs } from './lib/useMetricDefs';
import { SAMPLE_PLAYERS } from './lib/sampleData';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const DEFAULT_ENDPOINT = `${API_BASE}/api/players/stats`;

// Fallback data (same shape the FastAPI backend returns) so the dashboard
// renders standalone when the API is unreachable. Lives in lib/sampleData.js.

const RISK_LEVELS = ['Low', 'Medium', 'High'];
const RISK_ORDER = { Low: 0, Medium: 1, High: 2, Unknown: -1 };
const RISK_STYLES = {
  Low: { badge: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30', dot: 'bg-emerald-400', bar: 'bg-emerald-400' },
  Medium: { badge: 'bg-amber-500/15 text-amber-300 ring-amber-500/30', dot: 'bg-amber-400', bar: 'bg-amber-400' },
  High: { badge: 'bg-rose-500/15 text-rose-300 ring-rose-500/30', dot: 'bg-rose-400', bar: 'bg-rose-500' },
  Unknown: { badge: 'bg-slate-500/15 text-slate-300 ring-slate-500/30', dot: 'bg-slate-400', bar: 'bg-slate-500' },
};
// Coaching context only: the workload indicator is not a medical assessment.
const RISK_NOTES = {
  Low: 'Workload within this squad’s normal range for the match.',
  Medium: 'Above-average workload. Worth keeping an eye on in the next session.',
  High: 'Among the highest workloads in this match. Consider extra recovery time.',
  Unknown: 'No workload indicator available for this player yet.',
};

const METRICS = {
  top_speed_mph: { label: 'Top Speed', unit: 'mph', bar: 'bg-metric-speed', text: 'text-metric-speed' },
  distance_km: { label: 'Distance', unit: 'km', bar: 'bg-metric-distance', text: 'text-metric-distance' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
// Every number shown goes through fmt: missing values render as an em dash.
const fmt = (n, digits = 1) => (isNum(n) ? n.toFixed(digits) : '\u2014');
const pctOf = (value, max) => (isNum(value) && isNum(max) && max > 0 ? Math.min(100, (value / max) * 100) : 0);

function initials(name) {
  // Placeholder names like "Unknown #7" or "Player 10" read better as the number.
  const num = /#?(\d{1,3})\s*$/.exec(name)?.[1];
  if (num) return num.slice(0, 3);
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

// "Unknown #7" is the backend's name for an unidentified player seen wearing 7;
// once the user corrects the shirt number the placeholder follows it.
function displayName(p, shirt) {
  if (shirt == null) return p.name;
  return /^Unknown #\d+$/.test(p.name) ? `Unknown #${shirt}` : p.name;
}

function rankMap(players, key) {
  const map = new Map();
  players
    .filter((p) => isNum(p[key]))
    .sort((a, b) => b[key] - a[key])
    .forEach((p, idx) => map.set(p.player_id, idx + 1));
  return map;
}

// ---------------------------------------------------------------------------
// Presentational sub-components
// ---------------------------------------------------------------------------
// True when an element is wider than its box (re-checked on resize and when `dep` changes),
// so wide tables can show a visible "scroll sideways" hint on small screens.
function useHorizontalOverflow(dep) {
  const ref = useRef(null);
  const [overflow, setOverflow] = useState(false);
  useEffect(() => {
    const check = () => {
      const el = ref.current;
      if (el) setOverflow(el.scrollWidth - el.clientWidth > 1);
    };
    const raf = requestAnimationFrame(check);
    window.addEventListener('resize', check);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', check);
    };
  }, [dep]);
  return [ref, overflow];
}

function RiskBadge({ risk }) {
  const style = RISK_STYLES[risk] || RISK_STYLES.Unknown;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${style.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} />
      {risk}
    </span>
  );
}

function MetricBar({ value, max, unit, barClass, emphasized, digits = 1 }) {
  const pct = pctOf(value, max);
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 min-w-[80px] flex-1 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barClass} ${emphasized ? 'opacity-100' : 'opacity-60'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-20 shrink-0 text-right font-mono text-sm tabular-nums text-slate-200">
        {fmt(value, digits)} {isNum(value) && <span className="text-xs text-slate-400">{unit}</span>}
      </span>
    </div>
  );
}

// Physical stats are estimates from video (CV Engineer rule).
export function EstimatedBadge({ className = '' }) {
  return (
    <span
      title="Estimated from video: accuracy depends on camera position, calibration and tracking"
      className={`inline-flex shrink-0 items-center rounded-full bg-slate-800 px-2 py-0.5 text-[11px] font-medium normal-case tracking-normal text-slate-300 ring-1 ring-inset ring-slate-700 ${className}`}
    >
      Estimated from video
    </span>
  );
}

function KpiCard({ label, value, unit, sub, accent, estimated = false }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/70 p-5 shadow-lg shadow-black/20">
      <div className={`absolute inset-x-0 top-0 h-0.5 ${accent}`} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</p>
        {estimated && <EstimatedBadge />}
      </div>
      <p className="mt-2 text-3xl font-bold tracking-tight text-white">
        {value}
        {unit && value !== '\u2014' && value !== '--' && <span className="ml-1 text-base font-medium text-slate-400">{unit}</span>}
      </p>
      {sub && <div className="mt-2 text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

function SortHeader({ label, sortKey, sortConfig, onSort, className = '' }) {
  const active = sortConfig.key === sortKey;
  const arrow = active ? (sortConfig.direction === 'asc' ? '\u25B2' : '\u25BC') : '\u2195';
  return (
    <th
      scope="col"
      aria-sort={active ? (sortConfig.direction === 'asc' ? 'ascending' : 'descending') : 'none'}
      className={`px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider ${className}`}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1.5 transition-colors hover:text-white ${active ? 'text-white' : 'text-slate-400'}`}
      >
        {label}
        <span className={`text-[10px] ${active ? 'opacity-100' : 'opacity-40'}`}>{arrow}</span>
      </button>
    </th>
  );
}

function DetailStat({ label, value, unit, secondary, avg, max, rank, total, barClass, textClass, missingText, digits = 1, estimated = true }) {
  const hasValue = isNum(value);
  const diff = hasValue && isNum(avg) ? value - avg : null;
  const pct = pctOf(value, max);
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-widest text-slate-400">
          {label}
          {estimated && <EstimatedBadge />}
        </p>
        <p className="text-xs text-slate-400">
          Rank <span className="font-semibold text-slate-200">{rank ?? '\u2014'}</span> / {total}
        </p>
      </div>
      <p className={`mt-1 text-3xl font-bold tabular-nums ${hasValue ? textClass : 'text-slate-300'}`}>
        {fmt(value, digits)}
        {hasValue && <span className="ml-1 text-sm font-medium text-slate-400">{unit}</span>}
      </p>
      <p className="text-xs text-slate-400">{hasValue ? secondary : missingText || 'Not available: camera not calibrated for this match'}</p>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${barClass}`} style={{ width: `${pct}%` }} />
      </div>
      {(hasValue || isNum(avg)) && <p className="mt-2 text-xs text-slate-400">
        {diff !== null && (
          <>
            <span className="font-mono tabular-nums text-slate-200">
              {diff >= 0 ? '\u25B2' : '\u25BC'} {fmt(Math.abs(diff), digits)} {unit}
            </span>{' '}
          </>
        )}
        vs squad avg ({fmt(avg, digits)}
        {isNum(avg) ? ` ${unit}` : ''})
      </p>}
    </div>
  );
}

// Speed thresholds: the ones this video was processed with (stats rows' speed_thresholds),
// else the documented default, labelled as such.
function ThresholdNote({ thresholds = null, className = '' }) {
  const zones = zoneText(thresholds?.zone_edges_kmh);
  return (
    <div className={`font-mono text-[11px] text-slate-400 ${className}`} data-thresholds={thresholds ? thresholds.source || 'video' : 'default'}>
      {!thresholds ? (
        <p>Default speed thresholds (not reported for this video): {thresholdText()}</p>
      ) : thresholds.source === 'default' ? (
        <p>Default speed thresholds (the pipeline didn’t report its own): {thresholdText(thresholds)}</p>
      ) : thresholds.source === 'mixed' ? (
        <p>Speed thresholds (mixed: pipeline values for some players, defaults for others): {thresholdText(thresholds)}</p>
      ) : (
        <p>
          Speed thresholds used: {thresholdText(thresholds)}
          {thresholds.source === 'pipeline' && ' · from the pipeline'}
        </p>
      )}
      {zones && <p className="mt-0.5">Speed zones: {zones}</p>}
    </div>
  );
}

// Minutes carry 2 decimals since v0.4.1: short clips read "0.25 min", long ones "54 min".
const fmtMin = (m) => fmt(m, m < 1 ? 2 : m < 10 ? 1 : 0);

// "Tracked 78% of match": share of the match the player was visible to the tracker.
function CoverageBadge({ pct, visible, minutes, className = '' }) {
  if (!isNum(pct)) return null;
  const low = pct < LOW_COVERAGE_PCT;
  const mins = isNum(visible) && isNum(minutes) && minutes > 0 ? ` · ${fmtMin(visible)} of ${fmtMin(minutes)} min` : '';
  return (
    <span
      title="Share of the match this player was visible to the tracker"
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
        low ? 'bg-amber-500/15 text-amber-300 ring-amber-500/30' : 'bg-slate-800 text-slate-300 ring-slate-700'
      } ${className}`}
    >
      Tracked {Math.round(pct)}% of match{mins}
    </span>
  );
}

function ComingSoonBadge() {
  return (
    <span className="inline-flex shrink-0 items-center rounded-full border border-dashed border-slate-600 px-2 py-0.5 text-[11px] font-medium text-slate-300">
      Coming soon
    </span>
  );
}

const fmtField = (f, v, digits = f.digits) => (isNum(v) ? (digits ? v.toFixed(digits) : String(Math.round(v))) : '\u2014');

// Pitch drawn at 105 x 68 with optional average-position dots and/or a heat map.
// heatmap = { cols, rows, grid: rows x cols (0-1), length, width } from lib/playerStats
// (row 0 = pitch_y 0 = top edge, col 0 = pitch_x 0 = left goal line). Any cols x rows
// works (12 x 8 today). Positions are metres on a length x width pitch.
function MiniPitch({ points = [], heatmap = null, label, pitch = null }) {
  const W = 105;
  const H = 68;
  const L = pitch?.length || heatmap?.length || 105;
  const Wd = pitch?.width || heatmap?.width || 68;
  const sx = (x) => (x / L) * W;
  const sy = (y) => (y / Wd) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="w-full rounded-lg bg-slate-950 ring-1 ring-inset ring-slate-800">
      {heatmap &&
        heatmap.grid.map((row, r) =>
          row.map((c, k) =>
            c > 0 ? (
              <rect
                key={`${r}-${k}`}
                x={(k * W) / heatmap.cols}
                y={(r * H) / heatmap.rows}
                width={W / heatmap.cols + 0.05}
                height={H / heatmap.rows + 0.05}
                fill="var(--color-metric-distance)"
                opacity={0.08 + c * 0.77}
              />
            ) : null,
          ),
        )}
      <g fill="none" stroke="#334155" strokeWidth="0.5">
        <rect x="0.5" y="0.5" width={W - 1} height={H - 1} />
        <line x1={W / 2} y1="0.5" x2={W / 2} y2={H - 0.5} />
        <circle cx={W / 2} cy={H / 2} r="9.15" />
        <rect x="0.5" y={H / 2 - 20.16} width="16.5" height="40.32" />
        <rect x={W - 17} y={H / 2 - 20.16} width="16.5" height="40.32" />
      </g>
      {points
        .filter((pt) => isNum(pt.x) && isNum(pt.y))
        .map((pt) => (
          <g key={pt.id}>
            <circle cx={sx(pt.x)} cy={sy(pt.y)} r="2.4" fill="#e2e8f0" stroke="#020617" strokeWidth="0.6" />
            {pt.text && (
              <text x={sx(pt.x)} y={sy(pt.y) - 3.4} textAnchor="middle" fontSize="3.2" fill="#cbd5e1">
                {pt.text}
              </text>
            )}
          </g>
        ))}
    </svg>
  );
}

function HeatLegend({ heatmap }) {
  return (
    <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-slate-400">
      <span className="flex items-center gap-1.5">
        Less
        <span aria-hidden="true" className="h-2 w-16 rounded-full bg-gradient-to-r from-metric-distance/10 to-metric-distance" />
        More time
      </span>
      <span className="font-mono">
        {heatmap.cols}×{heatmap.rows} grid{isNum(heatmap.samples) ? ` · ${heatmap.samples.toLocaleString()} samples` : ''}
      </span>
    </div>
  );
}

// "Played as #7 · Change". Saved on the server for this video (PATCH, v0.4.1); older
// servers fall back to a local-only override and say so. 409/422 show inline.
function JerseyControl({ detected, override, onSave, note = null }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const current = override ?? detected;

  const start = () => {
    setDraft(current != null ? String(current) : '');
    setError(null);
    setEditing(true);
  };
  const save = async (value) => {
    setSaving(true);
    setError(null);
    try {
      await onSave(value);
      setEditing(false);
    } catch (err) {
      setError(err?.message || 'Couldn’t save the shirt number.');
      setEditing(true);
    } finally {
      setSaving(false);
    }
  };
  const submit = (e) => {
    e.preventDefault();
    const v = draft.trim();
    if (v === '') return save(null);
    if (!/^\d{1,2}$/.test(v)) {
      setError('Enter a shirt number from 0 to 99, or leave it empty for no number.');
      return;
    }
    save(Number(v));
  };

  if (!editing) {
    return (
      <div className="mt-3 text-sm text-slate-300">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {current != null ? (
            <>
              Played as <span className="font-mono font-semibold text-white">#{current}</span>
            </>
          ) : (
            'Shirt number not read'
          )}
          {override != null && <span className="text-xs text-slate-400">(corrected on this device{detected != null ? `, detected #${detected}` : ''})</span>}
          <span aria-hidden="true" className="text-slate-600">&middot;</span>
          <button type="button" onClick={start} className="rounded font-medium text-white underline decoration-slate-600 underline-offset-4 hover:decoration-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
            {current != null ? 'Change' : 'Set number'}
          </button>
          {override != null && (
            <button type="button" onClick={() => save(detected ?? null)} className="rounded text-xs text-slate-400 underline underline-offset-4 hover:text-white">
              Undo correction
            </button>
          )}
        </p>
        {note && (
          <p role="status" className="mt-1 text-xs text-slate-400" data-jersey-note>
            {note}
          </p>
        )}
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="mt-3" onKeyDown={(e) => e.key === 'Escape' && (e.stopPropagation(), setEditing(false))}>
      <label htmlFor="jersey-input" className="text-xs font-medium uppercase tracking-widest text-slate-400">
        Shirt number
      </label>
      <div className="mt-1 flex items-center gap-2">
        <input
          id="jersey-input"
          inputMode="numeric"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? 'jersey-error' : 'jersey-hint'}
          className="h-9 w-20 rounded-lg border border-slate-700 bg-slate-950 px-2 font-mono text-sm text-white outline-none focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-accent aria-invalid:border-rose-500"
        />
        <button type="submit" disabled={saving} className="h-9 rounded-lg bg-accent px-3 text-sm font-semibold text-slate-950 hover:bg-accent-hover disabled:opacity-60">
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="h-9 rounded-lg px-3 text-sm text-slate-300 hover:bg-slate-800">
          Cancel
        </button>
      </div>
      {error ? (
        <p id="jersey-error" role="alert" className="mt-1 text-xs text-rose-300">{error}</p>
      ) : (
        <p id="jersey-hint" className="mt-1 text-xs text-slate-400">Fix a misread shirt number for this video. Leave empty for no number.</p>
      )}
    </form>
  );
}

// Intensity metrics: the value when present. When missing: "Coming soon" if the
// /api/metrics registry marks the metric `soon`, otherwise "—" (ready but not measured).
function MissingValue({ soon }) {
  return soon ? <ComingSoonBadge /> : <span className="font-mono text-slate-400">&mdash;</span>;
}

function NextReleaseList({ player, availability, digits }) {
  return (
    <ul className="divide-y divide-slate-800">
      {NEXT_FIELDS.map((f) => {
        const v = player[f.key];
        return (
          <li key={f.key} className="flex items-center justify-between gap-3 py-2 text-sm">
            <span className="text-slate-300">{f.label}</span>
            {isNum(v) ? (
              <span className="font-mono tabular-nums text-slate-100">
                {fmtField(f, v, digits(f.key, f.digits))} {f.unit && <span className="text-xs text-slate-400">{f.unit}</span>}
              </span>
            ) : (
              <MissingValue soon={availability(f.key) !== 'ready'} />
            )}
          </li>
        );
      })}
    </ul>
  );
}

// Squad-level strip: launch-set position map + next-release metrics.
function SquadExtras({ players, jerseyOf, availability, digits, isEstimate, thresholds }) {
  const withPos = players.filter((p) => p.avg_position);
  const teamHeat = useMemo(() => combineHeatmaps(players.map((p) => p.heatmap)), [players]);
  const allSoon = NEXT_FIELDS.every((f) => availability(f.key) !== 'ready');
  const anyEstimate = NEXT_FIELDS.some((f) => isEstimate(f.key));
  return (
    <section className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-white">Heat map &amp; average position</h2>
          {isEstimate('avg_pitch_x') && <EstimatedBadge />}
        </div>
        <div className="mt-4">
          <MiniPitch
            label={withPos.length ? 'Average positions of tracked players' : 'Empty pitch: no position data yet'}
            heatmap={teamHeat}
            points={withPos.map((p) => ({ id: p.player_id, x: p.avg_position.x, y: p.avg_position.y, text: jerseyOf(p) != null ? `#${jerseyOf(p)}` : '' }))}
          />
        </div>
        {teamHeat && <HeatLegend heatmap={teamHeat} />}
        <p className="mt-3 text-xs text-slate-400">
          {withPos.length || teamHeat
            ? `Squad heat map from ${teamHeat?.players ?? 0} players · average positions for ${withPos.length} of ${players.length}.`
            : 'No position data was returned for this match (\u2014). It appears here once the stats include average positions.'}
        </p>
      </div>
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 lg:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-white">Intensity metrics</h2>
          {allSoon ? <span className="text-xs text-slate-400">Next release</span> : anyEstimate && <EstimatedBadge />}
        </div>
        <ThresholdNote thresholds={thresholds} className="mt-1" />
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {NEXT_FIELDS.map((f) => {
            const vals = players.map((p) => p[f.key]).filter(isNum);
            const has = anyValue(players, f.key);
            const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
            return (
              <li key={f.key} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                <p className="text-xs font-medium uppercase tracking-widest text-slate-400">{f.label}</p>
                {has ? (
                  <>
                    <p className="mt-1 font-mono text-xl tabular-nums text-white">
                      {fmtField(f, avg, Math.max(1, digits(f.key, f.digits)))} {f.unit && <span className="text-xs text-slate-400">{f.unit}</span>}
                    </p>
                    <p className="text-xs text-slate-400">Squad average &middot; {vals.length} of {players.length} players</p>
                  </>
                ) : (
                  <div className="mt-2">
                    <MissingValue soon={availability(f.key) !== 'ready'} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function Dashboard({
  players: playersProp,
  endpoint = DEFAULT_ENDPOINT,
  title = 'Player Stats Dashboard',
  subtitle = 'Top speed, distance covered and a workload indicator from YOLO + EasyOCR match tracking.',
  eyebrow = 'Tactical Telemetry',
  notice = null,
  sample = false,
  actions = null,
  videoId = null,
  showExtras = true,
  headerExtra = null,
}) {
  // Data / network state
  const [fetchedPlayers, setFetchedPlayers] = useState([]);
  const [loading, setLoading] = useState(!playersProp);
  const [error, setError] = useState(null);
  const [usingSample, setUsingSample] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // UI state
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState('All');
  const [sortConfig, setSortConfig] = useState({ key: 'top_speed_mph', direction: 'desc' });
  const [focusMetric, setFocusMetric] = useState('top_speed_mph');
  const [selectedId, setSelectedId] = useState(null);
  const [jerseyFix, setJerseyFix] = useState(() => getJerseyCorrections(videoId));
  const [serverJersey, setServerJersey] = useState({});
  const [jerseyNote, setJerseyNote] = useState({});
  const { availability, digits, isEstimate } = useMetricDefs();

  // Fetch from FastAPI only when the parent did not pass `players`.
  useEffect(() => {
    if (playersProp) return undefined;
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(endpoint, { signal: controller.signal });
        if (!res.ok) throw new Error(`API responded with HTTP ${res.status}`);
        const data = await res.json();
        setFetchedPlayers(normalizePlayers(data));
        setUsingSample(false);
      } catch (err) {
        if (err.name === 'AbortError') return;
        setError(err.message || 'Could not reach the analytics API.');
        setFetchedPlayers(normalizePlayers(SAMPLE_PLAYERS));
        setUsingSample(true);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    load();
    return () => controller.abort();
  }, [playersProp, endpoint, reloadKey]);

  // Close the detail panel with Escape.
  useEffect(() => {
    if (selectedId === null) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') setSelectedId(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedId]);

  // ---- Derived data -------------------------------------------------------
  const players = useMemo(
    () => (playersProp ? normalizePlayers(playersProp) : fetchedPlayers),
    [playersProp, fetchedPlayers],
  );
  const isLoading = !playersProp && loading;
  // Server-saved numbers (PATCH response rows) win over the stats rows; local-only
  // overrides apply when the server couldn't store them.
  const jerseyOf = (p) => (p.player_id in serverJersey ? serverJersey[p.player_id] : (jerseyFix[p.player_id] ?? p.jersey_number));
  const saveJersey = async (playerId, jersey) => {
    const res = await saveJerseyCorrection({ videoId, playerId, jersey });
    setJerseyFix(res.map);
    if (res.mode === 'server') {
      const n = res.row?.jersey_number;
      setServerJersey((m) => ({ ...m, [playerId]: n === undefined ? jersey : n }));
      setJerseyNote((m) => ({ ...m, [playerId]: 'Saved for this video.' }));
    } else {
      setJerseyNote((m) => ({ ...m, [playerId]: res.note }));
    }
  };

  // Aggregates skip null metrics (uncalibrated players); counts of players with
  // a value are tracked so averages never divide by the wrong number.
  const summary = useMemo(() => {
    const count = players.length;
    const riskCounts = { Low: 0, Medium: 0, High: 0, Unknown: 0 };
    let totalSpeed = 0;
    let totalDistance = 0;
    let speedCount = 0;
    let distanceCount = 0;
    let maxSpeed = null;
    let maxDistance = null;
    let fastest = null;
    let workhorse = null;

    let missingCount = 0;
    const perMinVals = players.map((p) => p.distance_per_min).filter(isNum);
    const coverageVals = players.map((p) => p.coverage_pct).filter(isNum);
    const lowCoverage = players.filter((p) => isNum(p.coverage_pct) && p.coverage_pct < LOW_COVERAGE_PCT).length;
    players.forEach((p) => {
      if (!isNum(p.top_speed_mph) || !isNum(p.distance_km)) missingCount += 1;
      riskCounts[p.injury_risk] = (riskCounts[p.injury_risk] || 0) + 1;
      if (isNum(p.top_speed_mph)) {
        totalSpeed += p.top_speed_mph;
        speedCount += 1;
        if (maxSpeed === null || p.top_speed_mph > maxSpeed) {
          maxSpeed = p.top_speed_mph;
          fastest = p;
        }
      }
      if (isNum(p.distance_km)) {
        totalDistance += p.distance_km;
        distanceCount += 1;
        if (maxDistance === null || p.distance_km > maxDistance) {
          maxDistance = p.distance_km;
          workhorse = p;
        }
      }
    });

    return {
      count,
      speedCount,
      distanceCount,
      missingCount,
      riskCounts,
      avgSpeed: speedCount ? totalSpeed / speedCount : null,
      avgDistance: distanceCount ? totalDistance / distanceCount : null,
      totalDistance: distanceCount ? totalDistance : null,
      avgPerMin: perMinVals.length ? perMinVals.reduce((a, b) => a + b, 0) / perMinVals.length : null,
      maxPerMin: perMinVals.length ? Math.max(...perMinVals) : null,
      avgCoverage: coverageVals.length ? coverageVals.reduce((a, b) => a + b, 0) / coverageVals.length : null,
      lowCoverage,
      maxSpeed,
      maxDistance,
      fastest,
      workhorse,
    };
  }, [players]);

  const ranks = useMemo(
    () => ({
      top_speed_mph: rankMap(players, 'top_speed_mph'),
      distance_km: rankMap(players, 'distance_km'),
      distance_per_min: rankMap(players, 'distance_per_min'),
    }),
    [players],
  );

  const visiblePlayers = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = players.filter((p) => {
      const shirt = jerseyFix[p.player_id] ?? p.jersey_number;
      const matchesSearch =
        !q || p.name.toLowerCase().includes(q) || String(p.player_id).includes(q) || (shirt != null && `#${shirt}`.includes(q));
      const matchesRisk = riskFilter === 'All' || p.injury_risk === riskFilter;
      return matchesSearch && matchesRisk;
    });

    const { key, direction } = sortConfig;
    const dir = direction === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      if (key === 'name') return a.name.localeCompare(b.name) * dir;
      if (key === 'injury_risk') return (RISK_ORDER[a.injury_risk] - RISK_ORDER[b.injury_risk]) * dir;
      const av = isNum(a[key]) ? a[key] : null;
      const bv = isNum(b[key]) ? b[key] : null;
      if (av === null && bv === null) return 0;
      if (av === null) return 1; // missing values always sort last
      if (bv === null) return -1;
      return (av - bv) * dir;
    });
  }, [players, search, riskFilter, sortConfig, jerseyFix]);
  const [tableScrollRef, tableOverflows] = useHorizontalOverflow(visiblePlayers.length);

  const leaderboard = useMemo(
    () =>
      players
        .filter((p) => isNum(p[focusMetric]))
        .sort((a, b) => b[focusMetric] - a[focusMetric])
        .slice(0, 5),
    [players, focusMetric],
  );

  const selectedPlayer = useMemo(
    () => players.find((p) => p.player_id === selectedId) || null,
    [players, selectedId],
  );

  // ---- Handlers -----------------------------------------------------------
  const handleSort = (key) => {
    setSortConfig((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' }
        : { key, direction: key === 'name' || key === 'player_id' ? 'asc' : 'desc' },
    );
    if (key in METRICS) setFocusMetric(key);
  };

  const handleMetricToggle = (metric) => {
    setFocusMetric(metric);
    setSortConfig({ key: metric, direction: 'desc' });
  };

  const toggleSelect = (id) => setSelectedId((prev) => (prev === id ? null : id));

  const resetFilters = () => {
    setSearch('');
    setRiskFilter('All');
  };

  const status = isLoading
    ? { label: 'Syncing', cls: 'bg-accent/10 text-accent ring-accent/40', dot: 'bg-accent animate-pulse' }
    : usingSample || (playersProp && sample)
      ? { label: 'Sample data', cls: 'bg-amber-500/15 text-amber-300 ring-amber-500/30', dot: 'bg-amber-400' }
      : { label: 'Live data', cls: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30', dot: 'bg-emerald-400 animate-pulse' };

  const thresholds = videoThresholds(players);
  const d = {
    speed: digits('top_speed_mph', 1),
    distance: digits('distance_km', 1),
    perMin: digits('distance_per_min', 0),
  };
  const focus = METRICS[focusMetric];
  const focusDigits = focusMetric === 'top_speed_mph' ? d.speed : d.distance;
  const focusMax = focusMetric === 'top_speed_mph' ? summary.maxSpeed : summary.maxDistance;

  // ---- Render -------------------------------------------------------------
  return (
    <div className="min-h-screen w-full bg-slate-950 font-sans text-slate-100 antialiased">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="flex flex-col gap-4 border-b border-slate-800 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">
              <span className="h-2 w-2 rounded-full bg-slate-400" />
              {eyebrow}
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">{title}</h1>
            <p className="mt-1 text-sm text-slate-400">{subtitle}</p>
            {headerExtra}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {actions}
            <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${status.cls}`}>
              <span className={`h-2 w-2 rounded-full ${status.dot}`} />
              {status.label}
            </span>
            {!playersProp && (
              <button
                type="button"
                onClick={() => setReloadKey((k) => k + 1)}
                disabled={isLoading}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isLoading ? 'Refreshing...' : 'Refresh'}
              </button>
            )}
          </div>
        </header>

        {/* API error banner (sample data fallback) */}
        {usingSample && error && (
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            <span className="mt-0.5 font-bold">!</span>
            <p>
              Could not load live stats from <code className="rounded bg-slate-900 px-1 py-0.5 text-xs">{endpoint}</code> ({error}).
              Showing sample data instead.
            </p>
          </div>
        )}

        {notice && <div className="mt-6">{notice}</div>}

        {!isLoading && summary.count > 0 && summary.missingCount > 0 && (
          <p role="note" className="mt-6 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3 text-sm text-slate-300">
            Speed or distance is unavailable (shown as &mdash;) for {summary.missingCount} of{' '}
            {summary.count} players, usually because the camera couldn&rsquo;t be calibrated to the pitch. Averages use only players with data.
          </p>
        )}

        {!isLoading && summary.lowCoverage > 0 && (
          <p role="note" className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
            Low tracking coverage: {summary.lowCoverage} of {summary.count} players were tracked for less than {LOW_COVERAGE_PCT}% of the match, so
            their distance and sprint totals are probably undercounted.
          </p>
        )}

        {/* KPI cards */}
        <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Avg Top Speed"
            value={isLoading ? '--' : fmt(summary.avgSpeed, d.speed)}
            unit="mph"
            estimated={isEstimate('top_speed_mph')}
            accent="bg-metric-speed"
            sub={
              (summary.speedCount === summary.count
                ? `${summary.count} players tracked`
                : `${summary.speedCount} of ${summary.count} players with speed data`) +
              (isNum(summary.avgCoverage) ? ` · avg coverage ${Math.round(summary.avgCoverage)}%` : '')
            }
          />
          <KpiCard
            label="Max Top Speed"
            value={isLoading ? '--' : fmt(summary.maxSpeed, d.speed)}
            unit="mph"
            estimated={isEstimate('top_speed_mph')}
            accent="bg-metric-speed"
            sub={summary.fastest ? displayName(summary.fastest, jerseyOf(summary.fastest)) : 'No data'}
          />
          <KpiCard
            label="Total Distance"
            value={isLoading ? '--' : fmt(summary.totalDistance, d.distance)}
            unit="km"
            estimated={isEstimate('distance_km')}
            accent="bg-metric-distance"
            sub={
              isNum(summary.avgDistance)
                ? `Avg ${fmt(summary.avgDistance, d.distance)} km per player${summary.distanceCount < summary.count ? ` (${summary.distanceCount} of ${summary.count})` : ''}`
                : 'No distance data for this match'
            }
          />
          <KpiCard
            label="High workload"
            value={isLoading ? '--' : summary.riskCounts.High}
            accent="bg-rose-500"
            sub={
              <div>
                <div className="flex h-1.5 overflow-hidden rounded-full bg-slate-800">
                  {RISK_LEVELS.map((level) =>
                    summary.count ? (
                      <div
                        key={level}
                        className={RISK_STYLES[level].bar}
                        style={{ width: `${(summary.riskCounts[level] / summary.count) * 100}%` }}
                      />
                    ) : null,
                  )}
                </div>
                <p className="mt-1.5">
                  {summary.riskCounts.Low} low / {summary.riskCounts.Medium} medium / {summary.riskCounts.High} high
                </p>
                <p className="mt-1">{WORKLOAD_DISCLAIMER}</p>
              </div>
            }
          />
        </section>

        {/* Controls */}
        <section className="mt-6 flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full lg:max-w-xs">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search player or #number"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder-slate-400 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/30"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Workload</span>
            {['All', ...RISK_LEVELS].map((level) => {
              const active = riskFilter === level;
              const count = level === 'All' ? summary.count : summary.riskCounts[level];
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => setRiskFilter(level)}
                  aria-pressed={active}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition ${
                    active
                      ? 'bg-accent/10 text-accent ring-accent/50'
                      : 'bg-slate-800 text-slate-300 ring-transparent hover:bg-slate-700 hover:text-white'
                  }`}
                >
                  {level} <span className={active ? 'text-accent' : 'text-slate-400'}>{count}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">Rank by</span>
            <div className="inline-flex rounded-lg bg-slate-800 p-1">
              {Object.entries(METRICS).map(([key, m]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => handleMetricToggle(key)}
                  className={`rounded-md px-3 py-1 text-sm font-medium transition ${
                    focusMetric === key ? 'bg-slate-950 text-white shadow' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Main grid: table + side panel */}
        <section className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Player table */}
          <div className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 lg:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-slate-800 px-4 py-3">
              <h2 className="text-sm font-semibold text-white">Squad Telemetry</h2>
              <p className="text-xs text-slate-400">
                Showing {visiblePlayers.length} of {summary.count} &middot; bars relative to squad max
              </p>
              {tableOverflows && (
                <p className="w-full text-xs text-slate-400" data-scroll-hint>
                  Scroll sideways for more columns <span aria-hidden="true">→</span>
                </p>
              )}
            </div>
            <div ref={tableScrollRef} className="overflow-x-auto" tabIndex={0} role="region" aria-label="Squad telemetry table">
              <table className="min-w-full divide-y divide-slate-800">
                <thead className="bg-slate-900">
                  <tr>
                    <SortHeader label="ID" sortKey="player_id" sortConfig={sortConfig} onSort={handleSort} className="hidden w-16 2xl:table-cell" />
                    <SortHeader label="Player" sortKey="name" sortConfig={sortConfig} onSort={handleSort} />
                    <SortHeader label="Top Speed" sortKey="top_speed_mph" sortConfig={sortConfig} onSort={handleSort} className="min-w-[200px]" />
                    <SortHeader label="Distance" sortKey="distance_km" sortConfig={sortConfig} onSort={handleSort} className="min-w-[200px]" />
                    <SortHeader label="m/min" sortKey="distance_per_min" sortConfig={sortConfig} onSort={handleSort} />
                    <SortHeader label="Workload" sortKey="injury_risk" sortConfig={sortConfig} onSort={handleSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {isLoading &&
                    Array.from({ length: 5 }).map((_, i) => (
                      <tr key={`skeleton-${i}`} className="animate-pulse">
                        {Array.from({ length: 6 }).map((__, j) => (
                          <td key={j} className={`px-4 py-4 ${j === 0 ? 'hidden 2xl:table-cell' : ''}`}>
                            <div className="h-3 rounded bg-slate-800" />
                          </td>
                        ))}
                      </tr>
                    ))}

                  {!isLoading && visiblePlayers.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-12 text-center text-sm text-slate-400">
                        No players match your filters.{' '}
                        <button type="button" onClick={resetFilters} className="font-medium text-accent hover:underline">
                          Clear filters
                        </button>
                      </td>
                    </tr>
                  )}

                  {!isLoading &&
                    visiblePlayers.map((p) => {
                      const selected = p.player_id === selectedId;
                      return (
                        <tr
                          key={p.player_id}
                          onClick={() => toggleSelect(p.player_id)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              toggleSelect(p.player_id);
                            }
                          }}
                          tabIndex={0}
                          aria-selected={selected}
                          className={`cursor-pointer transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent ${
                            selected ? 'bg-surface-selected shadow-[inset_3px_0_0_var(--color-accent)]' : 'hover:bg-slate-800/50'
                          }`}
                        >
                          <td className="hidden px-4 py-3 font-mono text-sm text-slate-400 2xl:table-cell">{p.player_id}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-bold text-slate-200 ring-1 ring-slate-700">
                                {initials(displayName(p, jerseyOf(p)))}
                              </span>
                              <span className="min-w-0">
                                <span className="block whitespace-nowrap text-sm font-medium text-white">{displayName(p, jerseyOf(p))}</span>
                                {(jerseyOf(p) != null || isNum(p.coverage_pct)) && (
                                  <span className="block whitespace-nowrap font-mono text-xs text-slate-400">
                                    {jerseyOf(p) != null && `#${jerseyOf(p)}${jerseyFix[p.player_id] != null ? ' · corrected' : ''}`}
                                    {jerseyOf(p) != null && isNum(p.coverage_pct) && ' · '}
                                    {isNum(p.coverage_pct) && (
                                      <span
                                        className={p.coverage_pct < LOW_COVERAGE_PCT ? 'text-amber-300' : undefined}
                                        title={`Tracked ${Math.round(p.coverage_pct)}% of match`}
                                      >
                                        {Math.round(p.coverage_pct)}% tracked
                                      </span>
                                    )}
                                  </span>
                                )}
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <MetricBar
                              value={p.top_speed_mph}
                              max={summary.maxSpeed}
                              unit="mph"
                              digits={d.speed}
                              barClass={METRICS.top_speed_mph.bar}
                              emphasized={focusMetric === 'top_speed_mph'}
                            />
                          </td>
                          <td className="px-4 py-3">
                            <MetricBar
                              value={p.distance_km}
                              max={summary.maxDistance}
                              unit="km"
                              digits={d.distance}
                              barClass={METRICS.distance_km.bar}
                              emphasized={focusMetric === 'distance_km'}
                            />
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 font-mono text-sm tabular-nums text-slate-200" title={p.per_min_note ?? undefined}>
                            {fmt(p.distance_per_min, d.perMin)}
                          </td>
                          <td className="px-4 py-3">
                            <RiskBadge risk={p.injury_risk} />
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Side panel: player detail OR leaderboard */}
          <aside className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            {selectedPlayer ? (
              <div>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-800 text-lg font-bold text-white ring-1 ring-slate-700">
                      {initials(displayName(selectedPlayer, jerseyOf(selectedPlayer)))}
                    </span>
                    <div>
                      <p className="text-lg font-semibold text-white">{displayName(selectedPlayer, jerseyOf(selectedPlayer))}</p>
                      <p className="font-mono text-xs text-slate-400">Player ID {selectedPlayer.player_id}</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedId(null)}
                    aria-label="Close player details"
                    className="rounded-md px-2 py-1 text-slate-400 transition hover:bg-slate-800 hover:text-white"
                  >
                    &times;
                  </button>
                </div>

                <JerseyControl
                  key={selectedPlayer.player_id}
                  detected={selectedPlayer.player_id in serverJersey ? serverJersey[selectedPlayer.player_id] : selectedPlayer.jersey_number}
                  override={jerseyFix[selectedPlayer.player_id] ?? null}
                  note={jerseyNote[selectedPlayer.player_id] ?? null}
                  onSave={(j) => saveJersey(selectedPlayer.player_id, j)}
                />

                {isNum(selectedPlayer.coverage_pct) && (
                  <div className="mt-3">
                    <CoverageBadge pct={selectedPlayer.coverage_pct} visible={selectedPlayer.visible_minutes} minutes={selectedPlayer.minutes_played} />
                    {selectedPlayer.coverage_pct < LOW_COVERAGE_PCT && (
                      <p role="note" className="mt-2 text-xs text-amber-200">
                        Low coverage: this player was out of view for much of the match, so distance and sprint totals are probably undercounted.
                      </p>
                    )}
                  </div>
                )}

                <div className="mt-4 flex items-center gap-2">
                  <RiskBadge risk={selectedPlayer.injury_risk} />
                  <span className="text-xs text-slate-400">{WORKLOAD_DISCLAIMER}</span>
                </div>

                <div className="mt-4 space-y-3">
                  <DetailStat
                    label="Top Speed"
                    value={selectedPlayer.top_speed_mph}
                    unit="mph"
                    digits={d.speed}
                    estimated={isEstimate('top_speed_mph')}
                    secondary={`${fmt(isNum(selectedPlayer.top_speed_kmh) ? selectedPlayer.top_speed_kmh : isNum(selectedPlayer.top_speed_mph) ? selectedPlayer.top_speed_mph * 1.60934 : null)} km/h`}
                    avg={summary.avgSpeed}
                    max={summary.maxSpeed}
                    rank={ranks.top_speed_mph.get(selectedPlayer.player_id)}
                    total={summary.count}
                    barClass={METRICS.top_speed_mph.bar}
                    textClass={METRICS.top_speed_mph.text}
                  />
                  <DetailStat
                    label="Distance Covered"
                    value={selectedPlayer.distance_km}
                    unit="km"
                    digits={d.distance}
                    estimated={isEstimate('distance_km')}
                    secondary={
                      isNum(selectedPlayer.distance_covered_meters)
                        ? `${fmt(selectedPlayer.distance_covered_meters, 0)} m · ${fmt(selectedPlayer.distance_covered_meters * 0.000621371, 2)} mi`
                        : `${fmt(isNum(selectedPlayer.distance_km) ? selectedPlayer.distance_km * 0.621371 : null, 2)} mi`
                    }
                    avg={summary.avgDistance}
                    max={summary.maxDistance}
                    rank={ranks.distance_km.get(selectedPlayer.player_id)}
                    total={summary.count}
                    barClass={METRICS.distance_km.bar}
                    textClass={METRICS.distance_km.text}
                  />
                  <DetailStat
                    label="Distance per minute"
                    value={selectedPlayer.distance_per_min}
                    unit="m/min"
                    digits={d.perMin}
                    estimated={isEstimate('distance_per_min')}
                    secondary={
                      isNum(selectedPlayer.visible_minutes)
                        ? `Over ${fmtMin(selectedPlayer.visible_minutes)} min tracked`
                        : isNum(selectedPlayer.minutes_played)
                          ? `${fmtMin(selectedPlayer.minutes_played)} min of video`
                          : 'Work rate while observed'
                    }
                    avg={summary.avgPerMin}
                    max={summary.maxPerMin}
                    rank={ranks.distance_per_min.get(selectedPlayer.player_id)}
                    total={summary.count}
                    barClass={METRICS.distance_km.bar}
                    textClass={METRICS.distance_km.text}
                    missingText={selectedPlayer.per_min_note || 'Not available yet: needs minutes tracked for this player'}
                  />
                  {(isNum(selectedPlayer.minutes_played) || isNum(selectedPlayer.sprint_count) || isNum(selectedPlayer.fatigue_risk_score)) && (
                    <div className="mt-1 grid gap-3 sm:grid-cols-3" data-erd-stats>
                      {isNum(selectedPlayer.minutes_played) && (
                        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                          <p className="text-[11px] font-medium uppercase tracking-widest text-slate-400">Minutes played</p>
                          <p className="mt-1 font-mono text-lg text-fg">{fmtMin(selectedPlayer.minutes_played)}</p>
                        </div>
                      )}
                      {isNum(selectedPlayer.sprint_count) && (
                        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                          <p className="text-[11px] font-medium uppercase tracking-widest text-slate-400">Sprints</p>
                          <p className="mt-1 font-mono text-lg text-metric-speed">{Math.round(selectedPlayer.sprint_count)}</p>
                        </div>
                      )}
                      {isNum(selectedPlayer.fatigue_risk_score) && (
                        <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                          <p className="text-[11px] font-medium uppercase tracking-widest text-slate-400">Fatigue score</p>
                          <p className="mt-1 font-mono text-lg text-fg">{Math.round(selectedPlayer.fatigue_risk_score)}</p>
                          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800" aria-hidden="true">
                            <div className="h-full rounded-full bg-slate-400" style={{ width: `${fatiguePct(selectedPlayer.fatigue_risk_score)}%` }} />
                          </div>
                          <p className="mt-1 text-[11px] text-slate-400">0–100 · workload indicator, not medical advice</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {selectedPlayer.avg_position || selectedPlayer.heatmap ? (
                  <div className="mt-4">
                    <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Heat map &amp; average position</p>
                    <div className="mt-2">
                      <MiniPitch
                        label={`Heat map for ${displayName(selectedPlayer, jerseyOf(selectedPlayer))}${selectedPlayer.avg_position ? `, average position ${Math.round(selectedPlayer.avg_position.x)} m by ${Math.round(selectedPlayer.avg_position.y)} m` : ''}`}
                        heatmap={selectedPlayer.heatmap}
                        points={selectedPlayer.avg_position ? [{ id: 'me', ...selectedPlayer.avg_position, text: 'avg' }] : []}
                      />
                    </div>
                    {selectedPlayer.heatmap ? (
                      <HeatLegend heatmap={selectedPlayer.heatmap} />
                    ) : (
                      <p className="mt-2 text-[11px] text-slate-400">No heat map for this player; the dot shows the average position.</p>
                    )}
                  </div>
                ) : null}

                {showExtras && (
                  <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
                    <p className="text-xs font-medium uppercase tracking-widest text-slate-400">Intensity</p>
                    <ThresholdNote thresholds={thresholds} className="mt-1" />
                    <div className="mt-2">
                      <NextReleaseList player={selectedPlayer} availability={availability} digits={digits} />
                    </div>
                  </div>
                )}

                <div className={`mt-4 rounded-xl p-4 text-sm ring-1 ring-inset ${RISK_STYLES[selectedPlayer.injury_risk].badge}`}>
                  <p className="text-xs font-semibold uppercase tracking-widest">Workload note &middot; not medical advice</p>
                  <p className="mt-1 text-slate-200">{RISK_NOTES[selectedPlayer.injury_risk]}</p>
                </div>

                <p className="mt-4 text-center text-xs text-slate-400">Press Esc or click the row again to close</p>
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-white">Top 5 &middot; {focus.label}</h2>
                  <span className="text-xs text-slate-400">{focus.unit}</span>
                </div>
                <ol className="mt-4 space-y-3">
                  {leaderboard.map((p, idx) => (
                    <li key={p.player_id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(p.player_id)}
                        className="w-full rounded-lg p-2 text-left transition hover:bg-slate-800/60"
                      >
                        <div className="flex items-center justify-between text-sm">
                          <span className="flex items-center gap-2">
                            <span className={`w-5 font-mono text-xs ${idx === 0 ? focus.text : 'text-slate-400'}`}>{idx + 1}</span>
                            <span className="font-medium text-slate-100">{displayName(p, jerseyOf(p))}</span>
                          </span>
                          <span className={`font-mono tabular-nums ${focus.text}`}>{fmt(p[focusMetric], focusDigits)}</span>
                        </div>
                        <div className="mt-1.5 ml-7 h-1.5 overflow-hidden rounded-full bg-slate-800">
                          <div
                            className={`h-full rounded-full ${focus.bar}`}
                            style={{ width: `${pctOf(p[focusMetric], focusMax)}%` }}
                          />
                        </div>
                      </button>
                    </li>
                  ))}
                  {!isLoading && leaderboard.length === 0 && (
                    <li className="text-sm text-slate-400">
                      {summary.count ? `No ${focus.label.toLowerCase()} data for this match yet.` : 'No player data yet.'}
                    </li>
                  )}
                </ol>
                <p className="mt-6 rounded-lg border border-dashed border-slate-700 p-3 text-center text-xs text-slate-400">
                  Select a player row to open the detailed performance panel.
                </p>
              </div>
            )}
          </aside>
        </section>

        {showExtras && !isLoading && summary.count > 0 && <SquadExtras players={players} jerseyOf={jerseyOf} availability={availability} digits={digits} isEstimate={isEstimate} thresholds={thresholds} />}
      </div>
    </div>
  );
}
