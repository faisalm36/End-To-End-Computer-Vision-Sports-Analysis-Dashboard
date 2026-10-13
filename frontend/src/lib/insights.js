// Tag insights: compare metrics across the values of one tag key.
// Computed from REAL per-match stats only (backend GET /api/insights, or
// client-side from GET /api/videos + each video's stats). No invented numbers.
import { normalizePlayers, isNum } from './playerStats';
import { norm, tagsOf } from './tags';

export const MIN_SAMPLE = 3; // matches per group before we compare or rank it
export const MIN_PAIRS_FOR_CARD = 2; // below this the next-match card is hidden

export const INSIGHT_METRICS = {
  speed: { label: 'Top speed', unit: 'mph', field: 'avg_top_speed_mph', digits: 1, bar: 'bg-metric-speed', text: 'text-metric-speed' },
  distance: { label: 'Distance', unit: 'km', field: 'avg_distance_km', digits: 2, bar: 'bg-metric-distance', text: 'text-metric-distance' },
  sprints: { label: 'Sprints', unit: 'per player', field: 'avg_sprints', digits: 1, bar: 'bg-metric-speed', text: 'text-metric-speed', registry: 'sprint_count' },
  hsr: { label: 'High-speed running', short: 'HSR', unit: 'km', field: 'avg_hsr_distance_km', digits: 2, bar: 'bg-metric-distance', text: 'text-metric-distance', registry: 'hsr_distance_km' },
  workload: { label: 'Workload', unit: '', field: 'avg_workload', digits: 1, bar: 'bg-slate-400', text: 'text-fg' },
};

const RISK_SCORE = { Low: 1, Medium: 2, High: 3 };
const mean = (xs) => {
  const v = xs.filter(isNum);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
};

// Per-match summary for the squad, or for one player.
export function summarizeMatch(statsRows, playerId = null) {
  let rows = normalizePlayers(statsRows);
  if (playerId != null) rows = rows.filter((r) => String(r.player_id) === String(playerId));
  if (!rows.length) return null;
  const workload = { low: 0, medium: 0, high: 0 };
  rows.forEach((r) => {
    if (r.injury_risk === 'Low') workload.low += 1;
    else if (r.injury_risk === 'Medium') workload.medium += 1;
    else if (r.injury_risk === 'High') workload.high += 1;
  });
  return {
    avg_top_speed_mph: mean(rows.map((r) => r.top_speed_mph)),
    avg_top_speed_kmh: mean(rows.map((r) => r.top_speed_kmh)),
    avg_distance_km: mean(rows.map((r) => r.distance_km)),
    avg_distance_covered_meters: mean(rows.map((r) => r.distance_covered_meters)),
    avg_sprints: mean(rows.map((r) => r.sprint_count)),
    avg_sprint_count: mean(rows.map((r) => r.sprint_count)),
    avg_minutes_played: mean(rows.map((r) => r.minutes_played)),
    avg_hsr_distance_km: mean(rows.map((r) => r.hsr_distance_km)),
    avg_workload: mean(rows.map((r) => RISK_SCORE[r.injury_risk])),
    avg_fatigue_risk_score: mean(rows.map((r) => r.fatigue_risk_score)),
    workload,
  };
}

const FIELDS = ['avg_top_speed_mph', 'avg_top_speed_kmh', 'avg_distance_km', 'avg_distance_covered_meters', 'avg_sprints', 'avg_sprint_count', 'avg_minutes_played', 'avg_hsr_distance_km', 'avg_workload', 'avg_fatigue_risk_score'];
const emptyWdl = () => ({ w: 0, d: 0, l: 0, unknown: 0 });

// W/D/L from video.result (= the match's result from our side) or video.match.result.
export function resultOf(video) {
  const r = norm(video?.result ?? video?.match?.result);
  if (['w', 'win', 'won'].includes(r)) return 'w';
  if (['d', 'draw', 'drew', 'tie'].includes(r)) return 'd';
  if (['l', 'loss', 'lost', 'lose'].includes(r)) return 'l';
  return null;
}

const dateKey = (v) => v?.match_date || v?.match?.match_date || v?.uploaded_at || v?.created_at || '';

// matches: [{ video, stats }] where stats is the raw stats array.
export function computeInsights(matches, tagKey, { playerId = null } = {}) {
  const items = matches
    .map((m) => ({ video: m.video, s: summarizeMatch(m.stats, playerId), result: resultOf(m.video) }))
    .filter((m) => m.s)
    .sort((a, b) => String(dateKey(a.video)).localeCompare(String(dateKey(b.video))));

  const valueOf = (video) => tagsOf(video).find((t) => norm(t.key) === norm(tagKey))?.value ?? null;
  const groupsMap = new Map();
  items.forEach((m) => {
    const value = valueOf(m.video);
    if (!value) return;
    const k = norm(value);
    if (!groupsMap.has(k)) groupsMap.set(k, { value, items: [] });
    groupsMap.get(k).items.push(m);
  });

  const groups = [...groupsMap.values()].map((g) => {
    const wl = { low: 0, medium: 0, high: 0 };
    g.items.forEach((m) => {
      wl.low += m.s.workload.low;
      wl.medium += m.s.workload.medium;
      wl.high += m.s.workload.high;
    });
    const wdl = emptyWdl();
    g.items.forEach((m) => (wdl[m.result ?? 'unknown'] += 1));
    const out = { value: g.value, matches: g.items.length, low_sample: g.items.length < MIN_SAMPLE, workload: wl, wdl };
    FIELDS.forEach((f) => (out[f] = mean(g.items.map((m) => m.s[f]))));
    return out;
  });

  // Baseline = average over all analysed matches (tagged or not).
  const baseline = {};
  FIELDS.forEach((f) => (baseline[f] = mean(items.map((m) => m.s[f]))));

  // Next-match effect: the match right after each match with this value.
  const next_match_effect = [];
  groups.forEach((g) => {
    Object.entries(INSIGHT_METRICS).forEach(([metric, def]) => {
      const nextVals = [];
      let pairs = 0;
      items.forEach((m, i) => {
        if (norm(valueOf(m.video)) !== norm(g.value) || i === items.length - 1) return;
        pairs += 1;
        const v = items[i + 1].s[def.field];
        if (isNum(v)) nextVals.push(v);
      });
      const base = baseline[def.field];
      const next = mean(nextVals);
      next_match_effect.push({
        value: g.value,
        metric,
        baseline: base,
        next,
        change_pct: isNum(base) && isNum(next) && base !== 0 ? ((next - base) / base) * 100 : null,
        n: nextVals.length,
        pairs,
        low_sample: nextVals.length < MIN_SAMPLE,
      });
    });
  });

  return { groups, baseline, next_match_effect, matchesAnalysed: items.length, source: 'client' };
}

// Normalise the backend's GET /api/insights payload to the same shape.
export function normalizeInsights(raw) {
  const num = (v) => (isNum(v) ? v : null);
  const wlOf = (w) => (w && typeof w === 'object' ? { low: +w.low || 0, medium: +w.medium || 0, high: +w.high || 0 } : null);
  const wdlOf = (w) => (w && typeof w === 'object' ? { w: +w.w || 0, d: +w.d || 0, l: +w.l || 0, unknown: +w.unknown || 0 } : null);
  const groups = (Array.isArray(raw?.groups) ? raw.groups : []).map((g) => {
    const matches = Number(g.matches) || 0;
    const withData = isNum(g.matches_with_data) ? g.matches_with_data : matches;
    const out = {
      value: String(g.value ?? ''),
      matches,
      matches_with_data: withData,
      // Backend: low_sample = fewer than 3 matches with data.
      low_sample: typeof g.low_sample === 'boolean' ? g.low_sample : withData < MIN_SAMPLE,
      workload: wlOf(g.workload ?? lowerKeys(g.injury_risk)),
      wdl: wdlOf(g.wdl),
    };
    FIELDS.forEach((f) => (out[f] = num(g[f])));
    return out;
  });
  const weighted = (field) => {
    const pts = groups.filter((g) => isNum(g[field]) && g.matches > 0);
    const n = pts.reduce((a, g) => a + g.matches, 0);
    return n ? pts.reduce((a, g) => a + g[field] * g.matches, 0) / n : null;
  };
  const b = raw?.baseline && typeof raw.baseline === 'object' ? raw.baseline : null;
  const baseline = { workload: wlOf(b?.workload), wdl: wdlOf(b?.wdl) };
  FIELDS.forEach((f) => (baseline[f] = b ? num(b[f]) : weighted(f)));
  const next_match_effect = (Array.isArray(raw?.next_match_effect) ? raw.next_match_effect : [])
    .map((e) => {
      const n = Number(e.n) || 0;
      return {
        value: String(e.value ?? ''),
        metric: String(e.metric ?? ''),
        metric_key: e.metric_key ?? null,
        baseline: num(e.baseline),
        next: num(e.next ?? e.next_avg),
        change_pct: num(e.change_pct),
        n,
        pairs: isNum(e.pairs) ? e.pairs : n,
        low_sample: typeof e.low_sample === 'boolean' ? e.low_sample : n < MIN_SAMPLE,
      };
    })
    .map((e) => ({ ...e, metric: e.metric in INSIGHT_METRICS ? e.metric : metricAlias(e.metric_key || e.metric) }))
    .filter((e) => e.metric);
  const analysed = isNum(b?.matches_with_data) ? b.matches_with_data : isNum(b?.matches) ? b.matches : groups.reduce((a, g) => a + g.matches, 0);
  return { groups, baseline, next_match_effect, matchesAnalysed: analysed, source: 'server' };
}

function lowerKeys(o) {
  return o && typeof o === 'object' ? Object.fromEntries(Object.entries(o).map(([k, v]) => [k.toLowerCase(), v])) : null;
}

function metricAlias(m) {
  const v = norm(m);
  if (v.includes('hsr') || v.includes('high_speed')) return 'hsr';
  if (v.includes('distance')) return 'distance';
  if (v.includes('speed')) return 'speed';
  if (v.includes('sprint')) return 'sprints';
  if (v.includes('workload') || v.includes('risk')) return 'workload';
  return null;
}

// Tag keys present across videos (for the Compare-by select).
export function tagKeysOf(videos) {
  const m = new Map();
  videos.forEach((v) => tagsOf(v).forEach((t) => m.set(norm(t.key), t.key)));
  return [...m.values()].sort((a, b) => a.localeCompare(b));
}
