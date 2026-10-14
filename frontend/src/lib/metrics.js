// Single source of truth for which metrics we claim, and how stats fields map to them.
// AUTHORITY: the CV Engineer's /workspace/briefs/metrics-feasibility-2026-09-30.md
//   launch        = tracked now (after PR #1 fixes land)
//   next          = next release ("Coming soon"); inputs already exist in the CV pipeline
//   manual        = only via manual tagging by the user, never automatic
// Definitions/popularity: /workspace/briefs/trackable-metrics-2026-09-30.md
// NOT claimed (removed on purpose): passes, possession, dribbles, tackles, duels,
// pressures, PPDA, line breaks, off-ball runs, pass networks.
//
// metric: 'speed' | 'distance' | null. Only speed/distance get their data colour.

export const METRIC_GROUPS = [
  {
    id: 'physical',
    title: 'Physical',
    blurb: 'How far, how fast and how hard every player worked. Estimated from video.',
    estimated: true,
    metrics: [
      { id: 'distance', registry: ['distance_km'], name: 'Total distance', unit: 'km', metric: 'distance', status: 'launch', desc: 'Ground covered while tracked, measured in real pitch metres.' },
      { id: 'top_speed', registry: ['top_speed_mph'], name: 'Top speed', unit: 'mph · km/h', metric: 'speed', status: 'launch', desc: 'Max sustained speed: smoothed and held for about a second, not a single-frame spike.' },
      { id: 'distance_per_min', registry: ['distance_per_min'], name: 'Distance per minute', unit: 'm/min', metric: 'distance', status: 'launch', desc: 'Work rate while on the pitch, so part-time and full-match players compare fairly.' },
      { id: 'hsr', registry: ['hsr_distance_km'], name: 'High-speed running', unit: 'km', metric: 'distance', status: 'next', thresholds: true, desc: 'Distance above the high-speed threshold.' },
      { id: 'sprints', registry: ['sprint_distance_km', 'sprint_count'], name: 'Sprint distance & count', unit: 'km · count', metric: 'speed', status: 'next', thresholds: true, desc: 'Efforts above the sprint threshold held for at least a second.' },
      { id: 'hi_efforts', registry: ['high_intensity_efforts'], name: 'High-intensity efforts', unit: 'count', metric: null, status: 'next', thresholds: true, desc: 'High-speed runs plus sprints, counted per player.' },
      { id: 'speed_zones', registry: ['zone1_distance_km', 'zone2_distance_km', 'zone3_distance_km', 'zone4_distance_km', 'zone5_distance_km'], name: 'Speed-zone breakdown', unit: 'km per zone', metric: 'distance', status: 'next', desc: 'Distance spent walking, jogging, running, at high speed and sprinting.' },
      { id: 'accels', registry: ['accels', 'decels'], name: 'Accelerations & decelerations', unit: 'count · estimate', metric: null, status: 'next', desc: 'Hard speed changes (±3 m/s²). Labelled as an estimate: acceleration amplifies tracking noise.' },
    ],
  },
  {
    id: 'positional',
    title: 'Movement & positional',
    blurb: 'Where each player spent the match, mapped onto a real pitch.',
    metrics: [
      { id: 'heat_map', registry: ['avg_pitch_x', 'avg_pitch_y'], name: 'Heat map & average position', unit: 'pitch map', metric: null, status: 'launch', desc: 'Where a player, or the whole team, spent their time. Our most robust output.' },
      { id: 'compactness', name: 'Team compactness & shape', unit: 'm · m² · coverage %', metric: null, status: 'next', desc: 'How stretched or compact the team was, reported with how many players were in view.' },
    ],
  },
  {
    id: 'events',
    title: 'Match events',
    blurb: 'Tagged by you in the video, never guessed by the AI.',
    manual: true,
    metrics: [
      { id: 'goals', name: 'Goals & assists', unit: 'count', metric: null, status: 'manual', desc: 'Click-to-tag the moment in the video.' },
      { id: 'shots', name: 'Shots & shot map', unit: 'count · pitch map', metric: null, status: 'manual', desc: 'Tag each shot and where it was taken from.' },
      { id: 'xg', name: 'Basic xG', unit: '0–1 per shot', metric: null, status: 'manual', desc: 'A simple distance-and-angle model on your tagged shots. Not an Opta-grade model.' },
    ],
  },
];

// Offline fallback for GET /api/metrics availability (backend metrics_catalog.py
// DEFINITIONS). The live registry wins when it loads; see lib/useMetricDefs.js.
export const FALLBACK_AVAILABILITY = {
  distance_km: 'ready',
  top_speed_mph: 'ready',
  distance_per_min: 'ready',
  minutes_played: 'ready',
  avg_pitch_x: 'ready',
  avg_pitch_y: 'ready',
  hsr_distance_km: 'soon',
  sprint_distance_km: 'soon',
  sprint_count: 'soon',
  high_intensity_efforts: 'soon',
  accels: 'soon',
  decels: 'soon',
  zone1_distance_km: 'soon',
  zone2_distance_km: 'soon',
  zone3_distance_km: 'soon',
  zone4_distance_km: 'soon',
  zone5_distance_km: 'soon',
};

// Landing/metric-list status from registry availability: every registry key ready ->
// 'launch'; any key soon -> 'next'. Manual (tagged) metrics and unknown keys keep theirs.
export function statusFromRegistry(metric, availability) {
  if (!metric.registry || metric.status === 'manual') return metric.status;
  const states = metric.registry.map((k) => availability(k)).filter(Boolean);
  if (!states.length) return metric.status;
  return states.every((s) => s === 'ready') ? 'launch' : 'next';
}

export const STATUS_LABEL = { launch: 'Tracked', next: 'Coming soon', manual: 'Tagged by you' };

// Workload indicator (Low / Medium / High from the pipeline). Always use this wording.
export const WORKLOAD_LABEL = 'Workload indicator';
export const WORKLOAD_DISCLAIMER = 'Workload indicator, not medical advice';

// Speed thresholds (CV Engineer: GPS convention by default, held >= 1 s).
export const SPEED_THRESHOLD_PRESETS = {
  gps: { id: 'gps', label: 'GPS default', hsr_kmh: 19.8, sprint_kmh: 25.2 },
  round: { id: 'round', label: '20/25 preset', hsr_kmh: 20, sprint_kmh: 25 },
  relative: { id: 'relative', label: '% of personal max', hsr_pct: 70, sprint_pct: 85 },
};
export const DEFAULT_THRESHOLD_PRESET = 'gps';

// Human-readable threshold line, e.g. "GPS default · HSR > 19.8 km/h · Sprint > 25.2 km/h".
// Also takes the backend's per-video object {preset, hsr_kmh, sprint_kmh, zone_edges_kmh}.
const PRESET_NAMES = { gps: 'GPS default', gps_standard: 'GPS standard', round: '20/25 preset' };
export const presetName = (id) =>
  id ? PRESET_NAMES[id] ?? String(id).replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase()) : null;
const kmh = (n) => `${Number(n).toFixed(1).replace(/\.0$/, '')} km/h`;

export function thresholdText(preset = SPEED_THRESHOLD_PRESETS[DEFAULT_THRESHOLD_PRESET]) {
  const p = typeof preset === 'string' ? SPEED_THRESHOLD_PRESETS[preset] : preset;
  if (!p) return '';
  if (p.hsr_pct != null) return `${p.label} · HSR > ${p.hsr_pct}% · Sprint > ${p.sprint_pct}% of max`;
  const parts = [p.label ?? presetName(p.preset)];
  if (p.hsr_kmh != null) parts.push(`HSR > ${kmh(p.hsr_kmh)}`);
  if (p.sprint_kmh != null) parts.push(`Sprint > ${kmh(p.sprint_kmh)}`);
  return parts.filter(Boolean).join(' · ');
}

// "walk < 7 · jog 7–15 · run 15–20 · HSR 20–25 · sprint > 25 km/h", or '' without edges.
export function zoneText(edges) {
  if (!edges) return '';
  const { walk, jog, run, hsr } = edges;
  if ([walk, jog, run, hsr].some((n) => typeof n !== 'number')) return '';
  const f = (n) => Number(n).toFixed(1).replace(/\.0$/, '');
  return `walk < ${f(walk)} · jog ${f(walk)}–${f(jog)} · run ${f(jog)}–${f(run)} · HSR ${f(run)}–${f(hsr)} · sprint > ${f(hsr)} km/h`;
}

// Footage the claims depend on (CV Engineer). Shown near upload.
export const FOOTAGE_REQUIREMENTS = [
  'One fixed, elevated camera that sees the whole pitch (no panning or follow-cam)',
  '1080p preferred, 720p minimum, 25 fps or more',
  'Calibrated once per camera setup',
];
