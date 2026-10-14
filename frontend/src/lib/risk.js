// Injury-risk (workload) helpers for backend v0.7.0 (provisional contract):
//   GET  /api/roster/risk?team_id=&sort=desc|asc&match_id=
//   GET  /api/players/{id}/risk          (history, optional)
//   POST /api/uploads/csv                (athlete-log CSV, dry_run preview)
// All shapes are normalised here so components never touch raw payloads.
// Every display of these values must carry WORKLOAD_DISCLAIMER (lib/metrics.js).

export const RISK_LEVELS = ['red', 'yellow', 'green', 'unknown'];

// Colour is never the only signal: each level has an icon and a text label too.
export const LEVEL_META = {
  red: { label: 'High', icon: 'alert', text: 'text-risk-high', bg: 'bg-risk-high-bg', ring: 'ring-risk-high-ring', bar: 'bg-risk-high' },
  yellow: { label: 'Moderate', icon: 'gauge', text: 'text-risk-medium', bg: 'bg-risk-medium-bg', ring: 'ring-risk-medium-ring', bar: 'bg-risk-medium' },
  green: { label: 'Low', icon: 'check', text: 'text-risk-low', bg: 'bg-risk-low-bg', ring: 'ring-risk-low-ring', bar: 'bg-risk-low' },
  unknown: { label: 'Not scored', icon: null, text: 'text-risk-unknown', bg: 'bg-risk-unknown-bg', ring: 'ring-risk-unknown-ring', bar: 'bg-risk-unknown' },
};

// Additive v0.7.0 fields: score_status / score_note / data_quality. Anything other
// than 'scored' means no number: risk_percent null, level 'unknown', show the note.
export const SCORE_STATUSES = ['scored', 'uncalibrated', 'insufficient_data', 'no_data'];
export const SCORE_NOTE_FALLBACK = {
  uncalibrated: 'Video not calibrated — upload athlete logs (CSV) to score this player',
  insufficient_data: 'Not enough data to score',
  no_data: 'No workload data yet',
};
export const DATA_QUALITY = {
  calibrated: { label: 'Video (calibrated)' },
  csv: { label: 'Athlete log' },
  demo: { label: 'Demo data' },
};

export function scoreStatusOf(raw) {
  const s = typeof raw?.score_status === 'string' ? raw.score_status.trim().toLowerCase() : '';
  if (SCORE_STATUSES.includes(s)) return s;
  return num(raw?.risk_percent) === null ? 'no_data' : 'scored';
}

// Shared by roster players, history entries and CSV result rows.
export function scoreFields(raw, thresholds) {
  const score_status = scoreStatusOf(raw);
  const scored = score_status === 'scored';
  const risk = scored ? num(raw?.risk_percent) : null;
  const level = scored ? levelFor(risk, thresholds, raw?.level) : 'unknown';
  const dq = typeof raw?.data_quality === 'string' ? raw.data_quality.trim().toLowerCase() : '';
  const note = typeof raw?.score_note === 'string' && raw.score_note.trim() ? raw.score_note.trim() : null;
  // 'scored' without a usable number (or thresholds) is treated as not scored.
  const status = scored && level === 'unknown' ? 'no_data' : score_status;
  return {
    score_status: status,
    score_note: status === 'scored' ? note : note || SCORE_NOTE_FALLBACK[status],
    data_quality: DATA_QUALITY[dq] ? dq : null,
    risk_percent: status === 'scored' ? risk : null,
    level,
  };
}

export const isScored = (p) => p?.score_status === 'scored' && p?.risk_percent != null;

function num(v) {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// thresholds come from the response; never hardcoded. Invalid → null.
export function normalizeThresholds(t) {
  const red = num(t?.red);
  const yellow = num(t?.yellow);
  if (red === null || yellow === null) return null;
  return { red, yellow };
}

// Level for a score. The server's `level` wins when it is one of the four known
// values; otherwise it is derived from the response thresholds. A null score is
// always 'unknown' (and so is any score when no thresholds are available).
export function levelFor(riskPercent, thresholds, serverLevel) {
  const r = num(riskPercent);
  if (r === null) return 'unknown';
  const s = typeof serverLevel === 'string' ? serverLevel.trim().toLowerCase() : '';
  if (RISK_LEVELS.includes(s) && s !== 'unknown') return s;
  const t = normalizeThresholds(thresholds);
  if (!t) return 'unknown';
  if (r >= t.red) return 'red';
  if (r >= t.yellow) return 'yellow';
  return 'green';
}

export function thresholdText(thresholds) {
  const t = normalizeThresholds(thresholds);
  if (!t) return null;
  return `High ≥ ${t.red}% · Moderate ${t.yellow}–${t.red}% · Low < ${t.yellow}%`;
}

export const FEATURES = [
  { key: 'minutes_played', label: 'Minutes played', unit: 'min', digits: 0 },
  { key: 'distance_km', label: 'Distance', unit: 'km', digits: 2, tone: 'distance' },
  { key: 'hsr_distance_km', label: 'High-speed running', unit: 'km', digits: 2, tone: 'distance' },
  { key: 'top_speed_kmh', label: 'Top speed', unit: 'km/h', digits: 1, tone: 'speed' },
  { key: 'sprint_count', label: 'Sprints', unit: '', digits: 0 },
  { key: 'accels', label: 'Accelerations', unit: '', digits: 0 },
  { key: 'decels', label: 'Decelerations', unit: '', digits: 0 },
  { key: 'heart_rate_avg', label: 'Avg heart rate', unit: 'bpm', digits: 0 },
  { key: 'heart_rate_max', label: 'Max heart rate', unit: 'bpm', digits: 0 },
];
const FEATURE_BY_KEY = Object.fromEntries(FEATURES.map((f) => [f.key, f]));

export function formatFeature(key, value) {
  const n = num(value);
  if (n === null) return value == null || value === '' ? '—' : String(value);
  const f = FEATURE_BY_KEY[key];
  const digits = f ? f.digits : Number.isInteger(n) ? 0 : 2;
  const s = n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  return f?.unit ? `${s} ${f.unit}` : s;
}

// Factors: sorted by largest |contribution|. Contribution is log-odds, so only
// the relative bar length is shown (width = |c| / max|c|), never as a percent.
export function normalizeFactors(list) {
  const rows = (Array.isArray(list) ? list : [])
    .filter((f) => f && typeof f === 'object')
    .map((f) => {
      const c = num(f.contribution) ?? 0;
      const d = typeof f.direction === 'string' ? f.direction.toLowerCase() : '';
      const direction = d === 'up' || d === 'down' ? d : c < 0 ? 'down' : 'up';
      const feature = f.feature ?? null;
      return { feature, label: f.label || FEATURE_BY_KEY[feature]?.label || feature || 'Factor', value: f.value ?? null, contribution: c, direction };
    })
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
  const max = rows.reduce((m, f) => Math.max(m, Math.abs(f.contribution)), 0);
  return rows.map((f) => ({ ...f, width: max > 0 ? Math.round((Math.abs(f.contribution) / max) * 100) : 0 }));
}

function normalizeFeatures(raw) {
  const out = {};
  for (const f of FEATURES) out[f.key] = num(raw?.[f.key]);
  return out;
}

const fullName = (p) => p.name || `${p.first_name || ''} ${p.last_name || ''}`.trim() || (p.player_id != null ? `Player ${p.player_id}` : 'Unknown player');

export function normalizeRiskPlayer(raw, thresholds) {
  if (!raw || typeof raw !== 'object') return null;
  const score = scoreFields(raw, thresholds);
  const team = raw.team && typeof raw.team === 'object' ? { team_id: raw.team.team_id ?? null, team_name: raw.team.team_name || null } : null;
  return {
    player_id: raw.player_id ?? null,
    name: fullName(raw),
    first_name: raw.first_name ?? null,
    last_name: raw.last_name ?? null,
    jersey_number: num(raw.jersey_number),
    position: raw.position || null,
    team,
    ...score,
    source: raw.source === 'match' || raw.source === 'csv' ? raw.source : raw.source || null,
    match_id: raw.match_id ?? null,
    match_date: raw.match_date || null,
    video_id: raw.video_id ?? null,
    model_version: raw.model_version || null,
    computed_at: raw.computed_at || null,
    features: normalizeFeatures(raw.features),
    factors: normalizeFactors(raw.factors),
  };
}

export function normalizeRosterRisk(data) {
  const thresholds = normalizeThresholds(data?.thresholds);
  const list = Array.isArray(data) ? data : Array.isArray(data?.players) ? data.players : [];
  return {
    team_id: data?.team_id ?? null,
    match_id: data?.match_id ?? null,
    sort: data?.sort === 'asc' ? 'asc' : 'desc',
    model_version: data?.model_version || null,
    thresholds,
    generated_at: data?.generated_at || null,
    latency_ms: num(data?.latency_ms),
    players: list.map((p) => normalizeRiskPlayer(p, thresholds)).filter(Boolean),
  };
}

// Known scores by risk (desc default), ties by name; unknown always last.
export function sortByRisk(players, dir = 'desc') {
  const sign = dir === 'asc' ? 1 : -1;
  return [...(players || [])].sort((a, b) => {
    const ua = a.risk_percent == null;
    const ub = b.risk_percent == null;
    if (ua !== ub) return ua ? 1 : -1;
    if (!ua && a.risk_percent !== b.risk_percent) return sign * (a.risk_percent - b.risk_percent);
    return String(a.name).localeCompare(String(b.name));
  });
}

// Teams present in a roster response (for the team filter).
export function teamsFrom(players) {
  const map = new Map();
  for (const p of players || []) {
    const id = p.team?.team_id;
    if (id == null) continue;
    if (!map.has(String(id))) map.set(String(id), { team_id: id, team_name: p.team.team_name || `Team ${id}` });
  }
  return [...map.values()].sort((a, b) => String(a.team_name).localeCompare(String(b.team_name)));
}

// Coach should be pointed at the CSV upload when nothing (or most of the roster) is unscored.
export function mostlyUnscored(players) {
  const list = players || [];
  if (!list.length) return true;
  return list.filter(isScored).length * 2 < list.length;
}

export function countByLevel(players) {
  const c = { red: 0, yellow: 0, green: 0, unknown: 0 };
  for (const p of players || []) c[p.level] = (c[p.level] || 0) + 1;
  return c;
}

// GET /api/players/{id}/risk: tolerate a bare array, {history|items|scores: [...]}, or one object.
export function normalizeRiskHistory(data, thresholds) {
  const list = Array.isArray(data)
    ? data
    : Array.isArray(data?.history)
      ? data.history
      : Array.isArray(data?.items)
        ? data.items
        : Array.isArray(data?.scores)
          ? data.scores
          : data && typeof data === 'object' && 'risk_percent' in data
            ? [data]
            : [];
  const t = normalizeThresholds(data?.thresholds) || thresholds;
  return list
    .map((e) => {
      return { ...scoreFields(e, t), source: e?.source || null, date: e?.match_date || e?.date || e?.computed_at || null, model_version: e?.model_version || null };
    })
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')));
}

// ---------------------------------------------------------------------------
// CSV athlete-log upload
// ---------------------------------------------------------------------------
function normalizeColumnsDetected(raw) {
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  if (raw && typeof raw === 'object') {
    return Object.entries(raw).map(([canon, header]) => (header && String(header) !== String(canon) ? `${canon} ← ${header}` : String(canon)));
  }
  return [];
}

function detailText(err) {
  const d = err?.data?.detail ?? err?.data?.message;
  if (typeof d === 'string' && d.trim()) return d.trim();
  if (Array.isArray(d) && d.length) return d.map((x) => (typeof x === 'string' ? x : x?.msg || String(x))).join('; ');
  return null;
}

// Column hint for the upload page. Matching is case-insensitive and ignores punctuation
// (server-side); aliases below are the ones the contract lists as worth showing.
export const CSV_REQUIRED_HINT =
  'date (or log_date / session_date), plus one of player_id, jersey_number (or jersey / number), or player (or name / full_name)';
export const CSV_OPTIONAL_HINTS = [
  { name: 'gps_distance', hint: 'km, 0–30 (or gps_distance_m / distance_m in metres, 0–30000)' },
  { name: 'heart_rate', hint: 'avg bpm, 30–230' },
  { name: 'heart_rate_max', hint: 'max bpm, 30–230' },
  { name: 'minutes_played', hint: '0–130' },
  { name: 'sprints', hint: 'whole number 0–300' },
  { name: 'top_speed_kmh', hint: 'km/h, 0–45' },
];
/** @deprecated kept for any older import; prefer CSV_OPTIONAL_HINTS */
export const CSV_OPTIONAL_COLUMNS = CSV_OPTIONAL_HINTS.map((c) => c.name);

export function normalizeCsvUpload(data) {
  const arr = (v) => (Array.isArray(v) ? v : []);
  return {
    upload_id: data?.upload_id ?? null,
    dry_run: data?.dry_run === true,
    filename: data?.filename || null,
    rows_total: num(data?.rows_total) ?? 0,
    rows_valid: num(data?.rows_valid) ?? 0,
    rows_invalid: num(data?.rows_invalid) ?? 0,
    rows_unmatched: num(data?.rows_unmatched) ?? 0,
    columns_detected: normalizeColumnsDetected(data?.columns_detected),
    errors: arr(data?.errors).map((e) => ({ row: e?.row ?? null, column: e?.column ?? null, value: e?.value ?? null, message: e?.message || 'Invalid value' })),
    unmatched: arr(data?.unmatched).map((u) => ({ row: u?.row ?? null, player: u?.player ?? null })),
    results: arr(data?.results).map((r) => {
      return {
        row: r?.row ?? null,
        player_id: r?.player_id ?? null,
        name: r?.name || (r?.player_id != null ? `Player ${r.player_id}` : 'Unknown player'),
        date: r?.date || null,
        ...scoreFields(r, null),
        factors: normalizeFactors(r?.factors),
      };
    }),
    latency_ms: num(data?.latency_ms),
  };
}

export const normalizeCsvUploadList = (d) => {
  const list = Array.isArray(d) ? d : Array.isArray(d?.uploads) ? d.uploads : Array.isArray(d?.items) ? d.items : [];
  return list
    .filter((u) => u && typeof u === 'object' && u.upload_id != null)
    .map((u) => ({
      upload_id: u.upload_id,
      filename: u.filename || `Upload ${u.upload_id}`,
      created_at: u.created_at || u.uploaded_at || null,
      rows_valid: num(u.rows_valid),
      rows_total: num(u.rows_total),
      team_id: u.team_id ?? null,
    }));
};

// Readable message for a failed CSV upload (ApiError from lib/api.js).
export function csvErrorMessage(err) {
  const status = err?.status;
  const detail = detailText(err);
  if (err?.kind === 'network') return err.message;
  if (status === 401) return 'Your session has expired. Please log in again.';
  if (status === 413) return detail || 'That file is too large or has more than 5000 rows. Split it into smaller files and try again.';
  if (status === 415) return detail || 'That file isn’t a CSV, or isn’t UTF-8. Export the athlete log as a UTF-8 .csv and try again.';
  if (status === 404) return detail && detail !== 'Not Found' ? detail : 'CSV upload isn’t available on this server yet.';
  if (status === 422) return detail || err?.message || 'The CSV couldn’t be read.';
  if (status === 503) return detail || 'Risk scoring isn’t available on the server right now.';
  return err?.message || 'Upload failed.';
}

export const missingColumnsFrom = (err) => (Array.isArray(err?.data?.missing_columns) ? err.data.missing_columns.map(String) : []);
