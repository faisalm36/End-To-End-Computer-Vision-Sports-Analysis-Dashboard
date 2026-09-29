import { useState, useEffect, useMemo } from 'react';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const DEFAULT_ENDPOINT = `${API_BASE}/api/players/stats`;

// Fallback data (same shape the FastAPI backend returns) so the dashboard
// renders standalone when the API is unreachable.
const SAMPLE_PLAYERS = [
  { player_id: 21, name: 'Faisal Musa', top_speed_mph: 19.2, distance_km: 4.5, injury_risk: 'Low' },
  { player_id: 7, name: 'Luka Petrovic', top_speed_mph: 21.4, distance_km: 5.8, injury_risk: 'Medium' },
  { player_id: 10, name: 'Marco Silva', top_speed_mph: 20.1, distance_km: 6.3, injury_risk: 'High' },
  { player_id: 4, name: 'Tomas Novak', top_speed_mph: 17.8, distance_km: 5.1, injury_risk: 'Low' },
  { player_id: 9, name: 'Andrej Kovac', top_speed_mph: 22.0, distance_km: 4.9, injury_risk: 'Medium' },
  { player_id: 1, name: 'Ivan Horvat', top_speed_mph: 14.6, distance_km: 2.3, injury_risk: 'Low' },
  { player_id: 14, name: 'Jan Dvorak', top_speed_mph: 20.7, distance_km: 7.0, injury_risk: 'High' },
  { player_id: 8, name: 'Mateo Rossi', top_speed_mph: 18.9, distance_km: 6.1, injury_risk: 'Low' },
];

const RISK_LEVELS = ['Low', 'Medium', 'High'];
const RISK_ORDER = { Low: 0, Medium: 1, High: 2, Unknown: -1 };
const RISK_STYLES = {
  Low: { badge: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30', dot: 'bg-emerald-400', bar: 'bg-emerald-400' },
  Medium: { badge: 'bg-amber-500/15 text-amber-300 ring-amber-500/30', dot: 'bg-amber-400', bar: 'bg-amber-400' },
  High: { badge: 'bg-rose-500/15 text-rose-300 ring-rose-500/30', dot: 'bg-rose-400', bar: 'bg-rose-500' },
  Unknown: { badge: 'bg-slate-500/15 text-slate-300 ring-slate-500/30', dot: 'bg-slate-400', bar: 'bg-slate-500' },
};
const RISK_NOTES = {
  Low: 'Load within normal range. Cleared for full training.',
  Medium: 'Monitor workload. Consider managed minutes in the next session.',
  High: 'Elevated load flagged. Review with medical staff and plan recovery.',
  Unknown: 'No risk assessment available for this player yet.',
};

const METRICS = {
  top_speed_mph: { label: 'Top Speed', unit: 'mph', bar: 'bg-cyan-400', text: 'text-cyan-300' },
  distance_km: { label: 'Distance', unit: 'km', bar: 'bg-emerald-400', text: 'text-emerald-300' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function normalizeRisk(value) {
  const v = String(value ?? '').trim().toLowerCase();
  if (v === 'low') return 'Low';
  if (v === 'medium' || v === 'med' || v === 'moderate') return 'Medium';
  if (v === 'high') return 'High';
  return 'Unknown';
}

// Accepts a bare array or a wrapped payload like { players: [...] }.
function normalizePlayers(raw) {
  let list = [];
  if (Array.isArray(raw)) list = raw;
  else if (Array.isArray(raw?.players)) list = raw.players;
  else if (Array.isArray(raw?.data)) list = raw.data;

  return list.map((p, i) => ({
    player_id: p.player_id ?? i + 1,
    name: p.name || `Player ${p.player_id ?? i + 1}`,
    top_speed_mph: Number(p.top_speed_mph) || 0,
    distance_km: Number(p.distance_km) || 0,
    injury_risk: normalizeRisk(p.injury_risk),
  }));
}

const fmt = (n, digits = 1) => (Number.isFinite(n) ? n.toFixed(digits) : '0.0');

function initials(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();
}

function rankMap(players, key) {
  const map = new Map();
  [...players]
    .sort((a, b) => b[key] - a[key])
    .forEach((p, idx) => map.set(p.player_id, idx + 1));
  return map;
}

// ---------------------------------------------------------------------------
// Presentational sub-components
// ---------------------------------------------------------------------------
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

function MetricBar({ value, max, unit, barClass, emphasized }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 min-w-[80px] flex-1 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barClass} ${emphasized ? 'opacity-100' : 'opacity-60'}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-20 shrink-0 text-right font-mono text-sm tabular-nums text-slate-200">
        {fmt(value)} <span className="text-xs text-slate-500">{unit}</span>
      </span>
    </div>
  );
}

function KpiCard({ label, value, unit, sub, accent }) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/70 p-5 shadow-lg shadow-black/20">
      <div className={`absolute inset-x-0 top-0 h-0.5 ${accent}`} />
      <p className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</p>
      <p className="mt-2 text-3xl font-bold tracking-tight text-white">
        {value}
        {unit && <span className="ml-1 text-base font-medium text-slate-400">{unit}</span>}
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
        className={`inline-flex items-center gap-1.5 transition-colors hover:text-white ${active ? 'text-cyan-300' : 'text-slate-400'}`}
      >
        {label}
        <span className={`text-[10px] ${active ? 'opacity-100' : 'opacity-40'}`}>{arrow}</span>
      </button>
    </th>
  );
}

function DetailStat({ label, value, unit, secondary, avg, max, rank, total, barClass, textClass }) {
  const diff = value - avg;
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-medium uppercase tracking-widest text-slate-400">{label}</p>
        <p className="text-xs text-slate-500">
          Rank <span className="font-semibold text-slate-200">{rank}</span> / {total}
        </p>
      </div>
      <p className={`mt-1 text-3xl font-bold tabular-nums ${textClass}`}>
        {fmt(value)}
        <span className="ml-1 text-sm font-medium text-slate-400">{unit}</span>
      </p>
      <p className="text-xs text-slate-500">{secondary}</p>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full rounded-full ${barClass}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-xs text-slate-400">
        <span className={diff >= 0 ? 'text-emerald-300' : 'text-rose-300'}>
          {diff >= 0 ? '+' : ''}
          {fmt(diff)} {unit}
        </span>{' '}
        vs squad avg ({fmt(avg)} {unit})
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function Dashboard({ players: playersProp, endpoint = DEFAULT_ENDPOINT, title = 'Player Stats Dashboard' }) {
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

  const summary = useMemo(() => {
    const count = players.length;
    const riskCounts = { Low: 0, Medium: 0, High: 0, Unknown: 0 };
    let totalSpeed = 0;
    let totalDistance = 0;
    let maxSpeed = 0;
    let maxDistance = 0;
    let fastest = null;
    let workhorse = null;

    players.forEach((p) => {
      totalSpeed += p.top_speed_mph;
      totalDistance += p.distance_km;
      riskCounts[p.injury_risk] = (riskCounts[p.injury_risk] || 0) + 1;
      if (!fastest || p.top_speed_mph > maxSpeed) {
        maxSpeed = p.top_speed_mph;
        fastest = p;
      }
      if (!workhorse || p.distance_km > maxDistance) {
        maxDistance = p.distance_km;
        workhorse = p;
      }
    });

    return {
      count,
      riskCounts,
      avgSpeed: count ? totalSpeed / count : 0,
      avgDistance: count ? totalDistance / count : 0,
      totalDistance,
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
    }),
    [players],
  );

  const visiblePlayers = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = players.filter((p) => {
      const matchesSearch = !q || p.name.toLowerCase().includes(q) || String(p.player_id).includes(q);
      const matchesRisk = riskFilter === 'All' || p.injury_risk === riskFilter;
      return matchesSearch && matchesRisk;
    });

    const { key, direction } = sortConfig;
    const dir = direction === 'asc' ? 1 : -1;
    return [...filtered].sort((a, b) => {
      let cmp;
      if (key === 'name') cmp = a.name.localeCompare(b.name);
      else if (key === 'injury_risk') cmp = RISK_ORDER[a.injury_risk] - RISK_ORDER[b.injury_risk];
      else cmp = Number(a[key]) - Number(b[key]);
      return cmp * dir;
    });
  }, [players, search, riskFilter, sortConfig]);

  const leaderboard = useMemo(
    () => [...players].sort((a, b) => b[focusMetric] - a[focusMetric]).slice(0, 5),
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
    ? { label: 'Syncing', cls: 'bg-cyan-500/15 text-cyan-300 ring-cyan-500/30', dot: 'bg-cyan-400 animate-pulse' }
    : usingSample
      ? { label: 'Sample data', cls: 'bg-amber-500/15 text-amber-300 ring-amber-500/30', dot: 'bg-amber-400' }
      : { label: 'Live data', cls: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30', dot: 'bg-emerald-400 animate-pulse' };

  const focus = METRICS[focusMetric];
  const focusMax = focusMetric === 'top_speed_mph' ? summary.maxSpeed : summary.maxDistance;

  // ---- Render -------------------------------------------------------------
  return (
    <div className="min-h-screen w-full bg-slate-950 font-sans text-slate-100 antialiased">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <header className="flex flex-col gap-4 border-b border-slate-800 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.25em] text-emerald-400">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              Tactical Telemetry
            </p>
            <h1 className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">{title}</h1>
            <p className="mt-1 text-sm text-slate-400">
              Top speed, distance covered and injury risk from YOLO + EasyOCR match tracking.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ${status.cls}`}>
              <span className={`h-2 w-2 rounded-full ${status.dot}`} />
              {status.label}
            </span>
            {!playersProp && (
              <button
                type="button"
                onClick={() => setReloadKey((k) => k + 1)}
                disabled={isLoading}
                className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:border-cyan-500/60 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
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

        {/* KPI cards */}
        <section className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Avg Top Speed"
            value={isLoading ? '--' : fmt(summary.avgSpeed)}
            unit="mph"
            accent="bg-cyan-400"
            sub={`${summary.count} players tracked`}
          />
          <KpiCard
            label="Max Top Speed"
            value={isLoading ? '--' : fmt(summary.maxSpeed)}
            unit="mph"
            accent="bg-sky-400"
            sub={summary.fastest ? `${summary.fastest.name} (#${summary.fastest.player_id})` : 'No data'}
          />
          <KpiCard
            label="Total Distance"
            value={isLoading ? '--' : fmt(summary.totalDistance)}
            unit="km"
            accent="bg-emerald-400"
            sub={`Avg ${fmt(summary.avgDistance)} km per player`}
          />
          <KpiCard
            label="High-Risk Players"
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
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none transition focus:border-cyan-500 focus:ring-2 focus:ring-cyan-500/30"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500">Risk</span>
            {['All', ...RISK_LEVELS].map((level) => {
              const active = riskFilter === level;
              const count = level === 'All' ? summary.count : summary.riskCounts[level];
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => setRiskFilter(level)}
                  className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                    active
                      ? 'bg-emerald-500 text-slate-950 shadow shadow-emerald-500/30'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white'
                  }`}
                >
                  {level} <span className={active ? 'text-slate-900/70' : 'text-slate-500'}>{count}</span>
                </button>
              );
            })}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-500">Rank by</span>
            <div className="inline-flex rounded-lg bg-slate-800 p-1">
              {Object.entries(METRICS).map(([key, m]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => handleMetricToggle(key)}
                  className={`rounded-md px-3 py-1 text-sm font-medium transition ${
                    focusMetric === key ? 'bg-slate-950 text-cyan-300 shadow' : 'text-slate-400 hover:text-white'
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
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
              <h2 className="text-sm font-semibold text-white">Squad Telemetry</h2>
              <p className="text-xs text-slate-500">
                Showing {visiblePlayers.length} of {summary.count} &middot; bars relative to squad max
              </p>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-800">
                <thead className="bg-slate-900">
                  <tr>
                    <SortHeader label="#" sortKey="player_id" sortConfig={sortConfig} onSort={handleSort} className="w-16" />
                    <SortHeader label="Player" sortKey="name" sortConfig={sortConfig} onSort={handleSort} />
                    <SortHeader label="Top Speed" sortKey="top_speed_mph" sortConfig={sortConfig} onSort={handleSort} className="min-w-[200px]" />
                    <SortHeader label="Distance" sortKey="distance_km" sortConfig={sortConfig} onSort={handleSort} className="min-w-[200px]" />
                    <SortHeader label="Injury Risk" sortKey="injury_risk" sortConfig={sortConfig} onSort={handleSort} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/70">
                  {isLoading &&
                    Array.from({ length: 5 }).map((_, i) => (
                      <tr key={`skeleton-${i}`} className="animate-pulse">
                        {Array.from({ length: 5 }).map((__, j) => (
                          <td key={j} className="px-4 py-4">
                            <div className="h-3 rounded bg-slate-800" />
                          </td>
                        ))}
                      </tr>
                    ))}

                  {!isLoading && visiblePlayers.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-12 text-center text-sm text-slate-400">
                        No players match your filters.{' '}
                        <button type="button" onClick={resetFilters} className="font-medium text-cyan-300 hover:underline">
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
                          className={`cursor-pointer transition-colors focus:outline-none focus-visible:bg-slate-800/60 ${
                            selected ? 'bg-cyan-500/10 shadow-[inset_3px_0_0_0_rgb(34,211,238)]' : 'hover:bg-slate-800/50'
                          }`}
                        >
                          <td className="px-4 py-3 font-mono text-sm text-slate-400">{p.player_id}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-800 text-xs font-bold text-slate-200 ring-1 ring-slate-700">
                                {initials(p.name)}
                              </span>
                              <span className="whitespace-nowrap text-sm font-medium text-white">{p.name}</span>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <MetricBar
                              value={p.top_speed_mph}
                              max={summary.maxSpeed}
                              unit="mph"
                              barClass={METRICS.top_speed_mph.bar}
                              emphasized={focusMetric === 'top_speed_mph'}
                            />
                          </td>
                          <td className="px-4 py-3">
                            <MetricBar
                              value={p.distance_km}
                              max={summary.maxDistance}
                              unit="km"
                              barClass={METRICS.distance_km.bar}
                              emphasized={focusMetric === 'distance_km'}
                            />
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
                    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-cyan-500/15 text-lg font-bold text-cyan-300 ring-1 ring-cyan-500/40">
                      {initials(selectedPlayer.name)}
                    </span>
                    <div>
                      <p className="text-lg font-semibold text-white">{selectedPlayer.name}</p>
                      <p className="font-mono text-xs text-slate-400">Player #{selectedPlayer.player_id}</p>
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

                <div className="mt-4 flex items-center gap-2">
                  <RiskBadge risk={selectedPlayer.injury_risk} />
                  <span className="text-xs text-slate-500">Injury risk</span>
                </div>

                <div className="mt-4 space-y-3">
                  <DetailStat
                    label="Top Speed"
                    value={selectedPlayer.top_speed_mph}
                    unit="mph"
                    secondary={`${fmt(selectedPlayer.top_speed_mph * 1.60934)} km/h`}
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
                    secondary={`${fmt(selectedPlayer.distance_km * 0.621371, 2)} mi`}
                    avg={summary.avgDistance}
                    max={summary.maxDistance}
                    rank={ranks.distance_km.get(selectedPlayer.player_id)}
                    total={summary.count}
                    barClass={METRICS.distance_km.bar}
                    textClass={METRICS.distance_km.text}
                  />
                </div>

                <div className={`mt-4 rounded-xl p-4 text-sm ring-1 ring-inset ${RISK_STYLES[selectedPlayer.injury_risk].badge}`}>
                  <p className="text-xs font-semibold uppercase tracking-widest">Workload note</p>
                  <p className="mt-1 text-slate-200">{RISK_NOTES[selectedPlayer.injury_risk]}</p>
                </div>

                <p className="mt-4 text-center text-xs text-slate-500">Press Esc or click the row again to close</p>
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-white">Top 5 &middot; {focus.label}</h2>
                  <span className="text-xs text-slate-500">{focus.unit}</span>
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
                            <span className={`w-5 font-mono text-xs ${idx === 0 ? focus.text : 'text-slate-500'}`}>{idx + 1}</span>
                            <span className="font-medium text-slate-100">{p.name}</span>
                          </span>
                          <span className={`font-mono tabular-nums ${focus.text}`}>{fmt(p[focusMetric])}</span>
                        </div>
                        <div className="mt-1.5 ml-7 h-1.5 overflow-hidden rounded-full bg-slate-800">
                          <div
                            className={`h-full rounded-full ${focus.bar}`}
                            style={{ width: `${focusMax > 0 ? (p[focusMetric] / focusMax) * 100 : 0}%` }}
                          />
                        </div>
                      </button>
                    </li>
                  ))}
                  {!isLoading && leaderboard.length === 0 && <li className="text-sm text-slate-500">No player data yet.</li>}
                </ol>
                <p className="mt-6 rounded-lg border border-dashed border-slate-700 p-3 text-center text-xs text-slate-500">
                  Select a player row to open the detailed performance panel.
                </p>
              </div>
            )}
          </aside>
        </section>
      </div>
    </div>
  );
}
