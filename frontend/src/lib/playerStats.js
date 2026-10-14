// Tolerant normaliser for per-player stats rows.
// Backend contract (GET /api/videos/{id}/stats, a bare array):
//   { player_id, name, top_speed_mph|null, distance_km|null, injury_risk,
//     jersey_number, minutes_played, distance_per_min, hsr_distance_km, sprint_distance_km,
//     sprint_count, high_intensity_efforts, accels, decels,           (null until measured)
//     speed_zones {walk, jog, run, hsr, sprint} | null, avg_position {x, y} m | null,
//     heatmap {cols, rows, cells: row-major 0-1, samples, pitch_length_m, pitch_width_m} | null,
//     top_speed_kmh, visible_minutes, coverage_pct (0-100), hsr_count,
//     distance_covered_meters, fatigue_risk_score (0/50/100),   (v0.6.0 ERD names)
//     speed_thresholds {preset, hsr_kmh, sprint_kmh, zone_edges_kmh {walk, jog, run, hsr}} | null,
//     metrics {key: value|null} (only with ?include=metrics) }
// Older rows only have the first five fields; everything else is optional. Values in
// `metrics` fill any flat field that is missing.

const toNum = (v) => {
  if (v === null || v === undefined || v === '' || typeof v === 'boolean') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const first = (row, keys) => {
  for (const k of keys) if (row?.[k] !== undefined && row?.[k] !== null) return row[k];
  return undefined;
};

export const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

// Intensity fields. `key` is the backend field and /api/metrics registry key. Whether a
// missing value reads "Coming soon" (availability soon) or "—" (ready) comes from the
// registry via lib/useMetricDefs.js. `src` lists accepted spellings, first = contract.
export const NEXT_FIELDS = [
  { key: 'hsr_distance_km', src: ['hsr_distance_km', 'high_speed_distance_km'], unit: 'km', label: 'High-speed running', digits: 2, metric: 'distance', thresholds: true },
  { key: 'sprint_distance_km', src: ['sprint_distance_km'], unit: 'km', label: 'Sprint distance', digits: 2, metric: 'distance', thresholds: true },
  { key: 'sprint_count', src: ['sprint_count'], unit: '', label: 'Sprints', digits: 0, metric: 'speed', thresholds: true },
  { key: 'high_intensity_efforts', src: ['high_intensity_efforts'], unit: '', label: 'High-intensity efforts', digits: 0, metric: null, thresholds: true },
  { key: 'accels', src: ['accels'], unit: '', label: 'Accelerations (estimate)', digits: 0, metric: null },
  { key: 'decels', src: ['decels'], unit: '', label: 'Decelerations (estimate)', digits: 0, metric: null },
];

function jerseyFrom(row) {
  const j = toNum(first(row, ['jersey_number', 'jersey', 'shirt_number', 'number']));
  if (j !== null) return j;
  // Placeholder players are named "Unknown #7" by the backend.
  const m = String(row?.name ?? '').match(/#(\d{1,2})\b/);
  return m ? Number(m[1]) : null;
}

function normalizeRisk(value) {
  const v = String(value ?? '').trim().toLowerCase();
  if (v === 'low') return 'Low';
  if (v === 'medium' || v === 'med' || v === 'moderate') return 'Medium';
  if (v === 'high') return 'High';
  return 'Unknown';
}

function pointFrom(v) {
  if (!v) return null;
  const pt = Array.isArray(v) ? { x: toNum(v[0]), y: toNum(v[1]) } : typeof v === 'object' ? { x: toNum(v.x ?? v.pitch_x), y: toNum(v.y ?? v.pitch_y) } : null;
  return pt && pt.x !== null && pt.y !== null ? pt : null;
}

// Heatmap -> { cols, rows, grid: rows x cols (0-1), samples, length, width } or null.
// Contract: { cols, rows, cells: [...] row-major, 0-1 }; row 0 = pitch_y 0, col 0 = pitch_x 0.
// cols/rows are read from the payload (12 x 8 today, possibly 21 x 14 later). Also
// accepts a 2D array or { intensity|counts: [[...]] } (the /heatmap endpoints' shape).
export function heatmapFrom(v) {
  if (!v) return null;
  let grid = null;
  if (Array.isArray(v?.cells)) {
    const cols = Math.round(toNum(v.cols) ?? 0);
    const rows = Math.round(toNum(v.rows) ?? 0);
    if (cols < 1 || rows < 1 || v.cells.length < cols * rows) return null;
    grid = Array.from({ length: rows }, (_, r) => v.cells.slice(r * cols, r * cols + cols).map((c) => toNum(c) ?? 0));
  } else {
    const g = Array.isArray(v) ? v : Array.isArray(v?.intensity) ? v.intensity : Array.isArray(v?.counts) ? v.counts : Array.isArray(v?.grid) ? v.grid : null;
    if (!g || !g.length || !Array.isArray(g[0])) return null;
    grid = g.map((row) => row.map((c) => toNum(c) ?? 0));
  }
  const max = Math.max(0, ...grid.flat());
  if (!(max > 0)) return null;
  return {
    cols: grid[0].length,
    rows: grid.length,
    grid: grid.map((row) => row.map((c) => c / max)),
    samples: toNum(v?.samples),
    length: toNum(v?.pitch_length_m) ?? 105,
    width: toNum(v?.pitch_width_m) ?? 68,
  };
}

// Squad heat map: mean of the players' normalised grids that share the first grid's size.
export function combineHeatmaps(maps) {
  const list = maps.filter(Boolean);
  if (!list.length) return null;
  const { cols, rows } = list[0];
  const same = list.filter((m) => m.cols === cols && m.rows === rows);
  const sum = Array.from({ length: rows }, (_, r) => Array.from({ length: cols }, (_, c) => same.reduce((a, m) => a + m.grid[r][c], 0)));
  const max = Math.max(0, ...sum.flat());
  if (!(max > 0)) return null;
  const samples = same.reduce((a, m) => a + (m.samples ?? 0), 0);
  return { ...list[0], grid: sum.map((row) => row.map((c) => c / max)), samples: samples || null, players: same.length };
}

// Per-video speed thresholds (same object on every row of a video), or null.
export function thresholdsFrom(v) {
  if (!v || typeof v !== 'object') return null;
  const e = v.zone_edges_kmh && typeof v.zone_edges_kmh === 'object' ? v.zone_edges_kmh : null;
  const edges = e ? Object.fromEntries(['walk', 'jog', 'run', 'hsr'].map((k) => [k, toNum(e[k])])) : null;
  const out = {
    preset: typeof v.preset === 'string' && v.preset ? v.preset : null,
    hsr_kmh: toNum(v.hsr_kmh),
    sprint_kmh: toNum(v.sprint_kmh),
    zone_edges_kmh: edges && Object.values(edges).some((x) => x !== null) ? edges : null,
  };
  // v0.4.1: where the values came from (pipeline = reported by the CV run, default = the backend's
  // fallback because the run didn't report them, mixed = differs across players).
  out.source = ['pipeline', 'default', 'mixed'].includes(v.source) ? v.source : null;
  return out.preset || out.hsr_kmh !== null || out.sprint_kmh !== null || out.zone_edges_kmh ? out : null;
}

// Video-level thresholds: the first found on any row; source becomes "mixed" when rows disagree.
export function videoThresholds(players) {
  const rows = players.filter((p) => p.speed_thresholds);
  if (!rows.length) return null;
  const first = rows[0].speed_thresholds;
  const sources = new Set(rows.map((p) => p.speed_thresholds.source).filter(Boolean));
  return sources.size > 1 ? { ...first, source: 'mixed' } : first;
}

// Below this share of the match a player's totals are likely undercounted.
export const LOW_COVERAGE_PCT = 60;
// Above this the per-minute rate can't be a real running pace (elite match average is ~100-130 m/min).
const MAX_PLAUSIBLE_PER_MIN = 300;

function zonesFrom(v) {
  if (!v || typeof v !== 'object') return null;
  // null zones ({walk: null, ...}) mean "not measured", so they're dropped below.
  const entries = Array.isArray(v)
    ? v.map((z) => [z?.zone ?? z?.name ?? z?.label, toNum(z?.distance_km ?? z?.km ?? z?.value)])
    : Object.entries(v).map(([k, val]) => [k, toNum(val)]);
  const clean = entries.filter(([k, n]) => k && n !== null);
  return clean.length ? clean.map(([zone, km]) => ({ zone: String(zone), km })) : null;
}

export function normalizePlayerRow(raw, i = 0) {
  // ?include=metrics adds a `metrics` dict; flat fields win when both exist.
  const m = raw?.metrics && typeof raw.metrics === 'object' ? raw.metrics : null;
  const p = m ? { ...m, ...Object.fromEntries(Object.entries(raw).filter(([, v]) => v !== null && v !== undefined)) } : raw;
  const id = p?.player_id ?? i + 1;
  const distance = toNum(p?.distance_km);
  const minutes = toNum(first(p, ['minutes_played', 'minutes_tracked', 'minutes']));
  const visible = toNum(p?.visible_minutes);
  let perMin = toNum(first(p, ['distance_per_min', 'distance_per_min_m', 'meters_per_min', 'm_per_min']));
  // The backend sends distance_per_min; derive only if the field is absent. An explicit null
  // (v0.4.1 nulls rates it can't trust) is respected, not re-derived.
  const base = visible ?? minutes;
  const perMinSent = ['distance_per_min', 'distance_per_min_m', 'meters_per_min', 'm_per_min'].some((k) => p && k in p);
  let perMinNote = null;
  if (perMin === null && !perMinSent && distance !== null && base !== null && base > 0) perMin = (distance * 1000) / base;
  else if (perMin === null && perMinSent && distance !== null)
    perMinNote = base !== null && base < 1 ? 'Clip too short for a per-minute rate' : 'Per-minute rate not available for this player';
  // A rate over under a minute of footage (or an impossible pace) isn't meaningful: show "—".
  if (perMin !== null && ((base !== null && base < 1) || perMin > MAX_PLAUSIBLE_PER_MIN)) {
    perMinNote = base !== null && base < 1 ? 'Clip too short for a per-minute rate' : 'Per-minute rate out of range, so it isn’t shown';
    perMin = null;
  }
  let coverage = toNum(p?.coverage_pct);
  if (coverage !== null) coverage = Math.max(0, Math.min(100, coverage));

  const mph = toNum(p?.top_speed_mph);
  const kmh = toNum(p?.top_speed_kmh);
  const meters = toNum(first(p, ['distance_covered_meters', 'distance_m']));
  const row = {
    player_id: id,
    name: p?.name || `Player ${id}`,
    jersey_number: jerseyFrom(p),
    top_speed_mph: mph,
    distance_km: distance,
    top_speed_kmh: kmh ?? (mph != null ? mph * 1.609344 : null),
    distance_covered_meters: meters ?? (distance != null ? distance * 1000 : null),
    fatigue_risk_score: toNum(first(p, ['fatigue_risk_score', 'fatigue_score'])),
    minutes_played: minutes,
    distance_per_min: perMin,
    per_min_note: perMinNote,
    visible_minutes: visible,
    coverage_pct: coverage,
    hsr_count: toNum(p?.hsr_count),
    speed_thresholds: thresholdsFrom(p?.speed_thresholds),
    injury_risk: normalizeRisk(p?.injury_risk ?? p?.workload),
    avg_position:
      pointFrom(first(p, ['avg_position', 'average_position'])) ??
      (toNum(p?.avg_pitch_x) !== null && toNum(p?.avg_pitch_y) !== null ? { x: toNum(p.avg_pitch_x), y: toNum(p.avg_pitch_y) } : null),
    heatmap: heatmapFrom(first(p, ['heatmap', 'heat_map'])),
    speed_zones: zonesFrom(first(p, ['speed_zones', 'zones'])),
  };
  for (const f of NEXT_FIELDS) row[f.key] = toNum(first(p, f.src));
  return row;
}

export function normalizePlayers(raw) {
  let list = [];
  if (Array.isArray(raw)) list = raw;
  else if (Array.isArray(raw?.players)) list = raw.players;
  else if (Array.isArray(raw?.data)) list = raw.data;
  return list.filter((p) => p && typeof p === 'object').map(normalizePlayerRow);
}

// True when at least one player has a value for the field.
export const anyValue = (players, key) => players.some((p) => (key === 'heatmap' || key === 'avg_position' || key === 'speed_zones' ? p[key] : isNum(p[key])));

// fatigue_risk_score is 0 / 50 / 100 (or null). Prefer it for gauges; keep injury_risk for Low/Medium/High labels.
export function fatigueLabel(score) {
  if (!isNum(score)) return null;
  if (score <= 25) return 'Low';
  if (score <= 75) return 'Medium';
  return 'High';
}

export const fatiguePct = (score) => (isNum(score) ? Math.max(0, Math.min(100, score)) : null);
