// Single API module. Every request to the FastAPI backend goes through here.
// Base URL comes from VITE_API_URL (see .env.example).
import { normalizeDetections, normalizeFrames, normalizeTrack, normalizeTrackList } from './tracking';
import { normalizeCsvUpload, normalizeCsvUploadList, normalizeRiskHistory, normalizeRosterRisk } from './risk';

export const API_BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

// Upload rules come from GET /api/config at runtime (see useConfig.js). These
// are the fallbacks used until it loads, or if it can't be reached.
const maxMb = Number(import.meta.env.VITE_MAX_UPLOAD_MB);
export const FALLBACK_MAX_UPLOAD_MB = Number.isFinite(maxMb) && maxMb > 0 ? maxMb : null;
// A5: camera / footage type at upload (backend v0.6.0). Omit → server defaults to tactical_cam.
export const VIDEO_TYPES = [
  { value: 'tactical_cam', label: 'Tactical cam (default)' },
  { value: 'broadcast', label: 'Broadcast' },
  { value: 'endzone_cam', label: 'End-zone cam' },
];

export const FALLBACK_EXTENSIONS = ['mp4', 'mov', 'avi', 'mkv'];

// MIME types for the accept attribute (extensions alone are enough for most
// browsers; types help mobile pickers).
export const VIDEO_MIME = { mp4: 'video/mp4', mov: 'video/quicktime', avi: 'video/x-msvideo', mkv: 'video/x-matroska' };

const TOKEN_KEY = 'sca.token';
const EXPIRES_KEY = 'sca.token_expires_at';
const DEMO_TOKEN = 'demo-session';

// ---------------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------------
export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

// expiresAt: epoch ms (from the login response's expires_in), optional.
export function setToken(token, expiresAt = null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
    if (token && expiresAt) localStorage.setItem(EXPIRES_KEY, String(expiresAt));
    else localStorage.removeItem(EXPIRES_KEY);
  } catch {
    /* storage unavailable (private mode); session will not persist */
  }
}

export function getTokenExpiry() {
  try {
    const v = Number(localStorage.getItem(EXPIRES_KEY));
    return Number.isFinite(v) && v > 0 ? v : null;
  } catch {
    return null;
  }
}

export const isDemoToken = (token) => token === DEMO_TOKEN;
export const DEMO_SESSION_TOKEN = DEMO_TOKEN;

// Decode a JWT payload without verifying it (display-only fallback).
export function decodeJwt(token) {
  try {
    const part = token.split('.')[1];
    const bin = atob(part.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(part.length / 4) * 4, '='));
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  // kind: 'network' (backend unreachable), 'http' (non-2xx), 'abort'
  constructor(message, { status = 0, kind = 'http', data = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
    this.data = data;
  }

  get isNetwork() {
    return this.kind === 'network';
  }
}

// Pull a readable message out of FastAPI error bodies ({detail: str | [{msg}]}).
function messageFrom(data, status) {
  const detail = data?.detail ?? data?.message ?? data?.error;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d?.msg || String(d)).join('; ');
  }
  if (status === 401) return 'Your session has expired. Please log in again.';
  if (status === 413) return 'File is too large.';
  if (status === 415) return `Unsupported file type (use ${FALLBACK_EXTENSIONS.map((e) => e.toUpperCase()).join(', ')}).`;
  if (status === 404) return 'Not found on the server (this endpoint may not exist yet).';
  if (status >= 500) return `The server had a problem (HTTP ${status}). Please try again.`;
  return `Request failed (HTTP ${status}).`;
}

const networkError = () =>
  new ApiError(`Can't reach the server at ${API_BASE}. Check that the backend is running.`, { kind: 'network' });

// Listeners notified when an authenticated request returns 401.
const unauthorizedListeners = new Set();
export function onUnauthorized(fn) {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
}

// ---------------------------------------------------------------------------
// Core request helper (fetch)
// ---------------------------------------------------------------------------
export async function request(path, { method = 'GET', body, form, auth = true, signal, headers = {} } = {}) {
  const token = getToken();
  const h = { Accept: 'application/json', ...headers };
  let payload;
  if (form) {
    payload = form; // FormData or URLSearchParams; browser sets Content-Type
  } else if (body !== undefined) {
    h['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const sentBearer = Boolean(auth && token && !isDemoToken(token));
  if (sentBearer) h.Authorization = `Bearer ${token}`;

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers: h, body: payload, signal });
  } catch (err) {
    if (err?.name === 'AbortError') throw new ApiError('Request cancelled', { kind: 'abort' });
    throw networkError();
  }

  let data = null;
  const text = await res.text().catch(() => '');
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    // Only a 401 on a request that actually carried the current token ends the
    // session. Login/register (auth: false) and token-less calls never do, so a
    // wrong password can't trigger a logout loop.
    if (res.status === 401 && sentBearer && getToken() === token) unauthorizedListeners.forEach((fn) => fn());
    throw new ApiError(messageFrom(data, res.status), { status: res.status, data });
  }
  return data;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
const tokenFrom = (data) => data?.access_token || data?.token || null;

// Login: { access_token, token_type, expires_in, user }. Register (201): the user
// fields plus the same token fields and a nested `user`.
function sessionFrom(data) {
  const token = tokenFrom(data);
  if (!token) throw new ApiError('The server did not return an access token.');
  const secs = Number(data?.expires_in);
  const expiresAt = Number.isFinite(secs) && secs > 0 ? Date.now() + secs * 1000 : null;
  return { token, expiresAt, user: normalizeUser(data?.user ?? null) };
}

// User objects carry both id and user_id.
export const normalizeUser = (u) => (u && typeof u === 'object' ? { ...u, id: u.id ?? u.user_id } : null);

export async function login(email, password) {
  try {
    const data = await request('/api/auth/login', { method: 'POST', body: { email, password }, auth: false });
    return sessionFrom(data);
  } catch (err) {
    // Wrong credentials are a 401 here; show it inline, never as "session expired".
    if (err instanceof ApiError && err.status === 401) {
      throw new ApiError('Incorrect email or password.', { status: 401, data: err.data });
    }
    throw err;
  }
}

export async function register({ name, email, password }) {
  const body = { email, password };
  if (name) body.name = name;
  const data = await request('/api/auth/register', { method: 'POST', body, auth: false });
  // If register doesn't hand back a token, log in with the same credentials.
  return tokenFrom(data) ? sessionFrom(data) : login(email, password);
}

// GET /api/auth/me -> { id, user_id, name, first_name, last_name, email, role, created_at }.
export const fetchMe = ({ signal } = {}) => request('/api/auth/me', { signal }).then(normalizeUser);

// PATCH {name} -> updated user. change-password -> 204; a wrong current
// password is a 400 (not 401), so it never ends the session.
export const updateMe = (patch) => request('/api/auth/me', { method: 'PATCH', body: patch }).then(normalizeUser);

export const changePassword = (current_password, new_password) =>
  request('/api/auth/change-password', { method: 'POST', body: { current_password, new_password } });

// ---------------------------------------------------------------------------
// Videos
// ---------------------------------------------------------------------------
export function normalizeVideoList(data) {
  if (Array.isArray(data)) return data;
  for (const key of ['videos', 'items', 'data', 'results']) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
}

// ?tag=key:value, repeatable (same key = OR, different keys = AND, case-insensitive).
export function tagQuery(tags) {
  const q = new URLSearchParams();
  for (const t of Array.isArray(tags) ? tags : []) if (t?.key && t?.value) q.append('tag', `${t.key}:${t.value}`);
  const s = q.toString();
  return s ? `?${s}` : '';
}

// Bare array; `id` is normalised from id/video_id so links always work.
// Optional `tags` filters on the server (GET /api/videos?tag=weather:Raining).
export const listVideos = ({ tags, ...opts } = {}) =>
  request(`/api/videos${tagQuery(tags)}`, opts).then((d) => normalizeVideoList(d).map((v) => ({ ...v, id: v?.id ?? v?.video_id })));
export const getVideo = (id, opts) => request(`/api/videos/${encodeURIComponent(id)}`, opts);
// Always a bare array of per-player rows (see lib/playerStats.js for the fields
// we read, including next-release ones the backend doesn't send yet).
export const getVideoStats = (id, opts) =>
  request(`/api/videos/${encodeURIComponent(id)}/stats`, opts).then((d) => (Array.isArray(d) ? d : []));
export const listMatches = ({ tags, ...opts } = {}) =>
  request(`/api/matches${tagQuery(tags)}`, opts).then((d) => (Array.isArray(d) ? d : Array.isArray(d?.matches) ? d.matches : []));

// Match object: { match_id, match_date, home_team, away_team, home_score, away_score,
//   our_side: 'home'|'away', our_team, opponent, result: 'W'|'D'|'L'|null, tags, video_count }
export const getMatch = (id, opts) => request(`/api/matches/${encodeURIComponent(id)}`, opts);

// PATCH /api/matches/{id} { home_score, away_score, our_side, result }. Scores go in pairs
// (both ints or both null); with scores the backend derives `result` (a contradicting one -> 422).
export const updateMatch = (id, patch) => request(`/api/matches/${encodeURIComponent(id)}`, { method: 'PATCH', body: patch });


// Public upload config: { max_upload_mb, allowed_extensions: ["avi","mkv","mov","mp4"] }.
export const getConfig = (opts) => request('/api/config', { ...opts, auth: false });

// thumbnail_url is relative and self-tokened; always build it from API_BASE.
export function thumbnailSrc(video) {
  const u = video?.thumbnail_url;
  if (!u || typeof u !== 'string') return null;
  if (/^https?:\/\//i.test(u)) return u;
  return `${API_BASE}${u.startsWith('/') ? '' : '/'}${u}`;
}

// Any relative, self-tokened media URL from the backend (source_url, frame_url,
// annotated_url, frames_url) -> absolute URL on API_BASE.
export function mediaSrc(u) {
  if (!u || typeof u !== 'string') return null;
  // Absolute URLs and the app's own static files (sample/demo media) are used as-is.
  if (/^(https?:|blob:|data:)/i.test(u) || (u.startsWith('/') && !u.startsWith('/api/'))) return u;
  return `${API_BASE}${u.startsWith('/') ? '' : '/'}${u}`;
}

// The original upload (GET /api/videos/{id}/source, Range) when the server exposes it.
export const videoSourceSrc = (video) => mediaSrc(video?.source_url);

// Same frame_url with another frame number (keeps the server's token).
export function frameSrc(frameUrl, frame) {
  const abs = mediaSrc(frameUrl);
  if (!abs) return null;
  try {
    const u = new URL(abs, window.location.href);
    u.searchParams.delete('t');
    u.searchParams.set('frame', String(Math.max(0, Math.round(frame))));
    return u.toString();
  } catch {
    return abs;
  }
}

export const deleteVideo = (id) => request(`/api/videos/${encodeURIComponent(id)}`, { method: 'DELETE' });

// Multipart upload with real progress via XMLHttpRequest.
// Returns { promise, abort }. onProgress receives { loaded, total, percent }.
// Fields: file + title, and either match_id or match_date + home_team + away_team.
// Backend answers 202 { id, status: "queued", ... }; any 2xx is success.
// Optional `tags` ([{key, value}]) is sent as a JSON string field (bad JSON -> 422) and
// tags the match. Optional `our_side` ('home'|'away') says which team is yours (for W/D/L).
export function uploadVideo({ file, title, match_id, match_date, home_team, away_team, tags, our_side, video_type }, { onProgress } = {}) {
  const xhr = new XMLHttpRequest();
  const promise = new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('file', file);
    if (title) form.append('title', title);
    if (match_id) {
      form.append('match_id', match_id);
    } else {
      if (match_date) form.append('match_date', match_date);
      if (home_team) form.append('home_team', home_team);
      if (away_team) form.append('away_team', away_team);
    }
    if (Array.isArray(tags) && tags.length) form.append('tags', JSON.stringify(tags.map(({ key, value }) => ({ key, value }))));
    if (our_side === 'home' || our_side === 'away') form.append('our_side', our_side);
    if (video_type) form.append('video_type', video_type);

    xhr.open('POST', `${API_BASE}/api/videos`);
    xhr.setRequestHeader('Accept', 'application/json');
    const token = getToken();
    if (token && !isDemoToken(token)) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      if (!onProgress) return;
      const total = e.lengthComputable ? e.total : file.size;
      onProgress({ loaded: e.loaded, total, percent: total ? Math.min(100, (e.loaded / total) * 100) : 0 });
    };
    xhr.onload = () => {
      let data = null;
      try {
        data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        data = xhr.responseText;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data?.video ?? data);
      } else {
        if (xhr.status === 401 && token && !isDemoToken(token) && getToken() === token) unauthorizedListeners.forEach((fn) => fn());
        // 413: prefer the server's detail ("File too large (max 500 MB)"); proxies
        // may send HTML, so fall back to fixed wording. 415 keeps fixed wording.
        const detail = typeof data?.detail === 'string' ? data.detail : null;
        const msg =
          xhr.status === 413
            ? detail || 'File is too large.'
            : xhr.status === 415
              ? `Unsupported file type (use ${FALLBACK_EXTENSIONS.map((e) => e.toUpperCase()).join(', ')}).`
              : messageFrom(data, xhr.status);
        reject(new ApiError(msg, { status: xhr.status, data }));
      }
    };
    xhr.onerror = () => reject(networkError());
    xhr.onabort = () => reject(new ApiError('Upload cancelled', { kind: 'abort' }));
    xhr.send(form);
  });
  return { promise, abort: () => xhr.abort() };
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------
// Backend lifecycle (top-level `stage`): queued -> detect -> track -> ocr ->
// metrics -> ingest -> done, or failed. `status` uses queued/processing/done/failed.
export function normalizeStatus(raw) {
  const v = String(raw ?? '').trim().toLowerCase();
  if (['done', 'completed', 'complete', 'success', 'succeeded', 'processed', 'finished'].includes(v)) return 'complete';
  if (['failed', 'error', 'errored', 'cancelled', 'canceled'].includes(v)) return 'failed';
  if (!v) return 'unknown';
  return 'processing'; // queued, processing, detect, track, ...
}

export const isQueued = (raw) => ['queued', 'pending', 'uploaded'].includes(String(raw ?? '').trim().toLowerCase());

// Backend failure text (error_message), with older/other names as fallbacks.
export const videoError = (v) => v?.error_message || v?.error || null;

export const PROCESSING_STAGES = [
  { key: 'detect', label: 'Detecting players (YOLO)', match: ['detect', 'yolo'] },
  { key: 'track', label: 'Tracking players', match: ['track'] },
  { key: 'ocr', label: 'Reading jersey numbers (OCR)', match: ['ocr', 'jersey'] },
  { key: 'metrics', label: 'Computing metrics', match: ['metric'] },
  { key: 'ingest', label: 'Saving results', match: ['ingest'] },
];

export function stageIndex(stage) {
  if (typeof stage === 'number' && Number.isInteger(stage)) {
    return stage >= 0 && stage < PROCESSING_STAGES.length ? stage : -1;
  }
  const v = String(stage ?? '').trim().toLowerCase();
  if (!v) return -1;
  const exact = PROCESSING_STAGES.findIndex((s) => s.key === v);
  return exact >= 0 ? exact : PROCESSING_STAGES.findIndex((s) => s.match.some((m) => v.includes(m)));
}

// Progress for display: top-level `stage` + `progress` (0-100) first, then
// pipeline_meta only as a fallback. Returns { phase, stageIdx, percent, message }
// where phase is queued | processing | complete | failed | unknown.
export function videoProgress(video) {
  const status = normalizeStatus(video?.status);
  const stageRaw = String(video?.stage ?? '').trim().toLowerCase();
  let phase = status;
  if (stageRaw === 'done') phase = 'complete';
  else if (stageRaw === 'failed') phase = 'failed';
  else if (phase === 'processing' && (stageRaw === 'queued' || (!stageRaw && isQueued(video?.status)))) phase = 'queued';

  let stageIdx = stageIndex(stageRaw);
  let percent = toPercent(video?.progress, { fraction: false });
  let message = null;
  if (stageIdx < 0 || percent === null) {
    const meta = readPipelineMeta(video);
    if (stageIdx < 0) stageIdx = meta.stageIdx;
    if (percent === null) percent = meta.percent;
    message = meta.message;
  }
  if (phase === 'complete') percent = 100;
  const frames = readFrames(video);
  const raw = toPercent(video?.progress, { fraction: false });
  return { phase, stageIdx, percent, message, frames, failedStep: phase === 'failed' ? failedStepFrom(raw) : null };
}

// Backend progress ranges (README): detect 10-70, track 72, ocr 75, metrics 78-80,
// ingest 90. On failure progress stays where it stopped, so it tells us the step.
// Returns an index into PROCESSING_STAGES.
export function failedStepFrom(progress) {
  if (progress === null || progress < 72) return 0;
  if (progress < 75) return 1;
  if (progress < 78) return 2;
  if (progress < 90) return 3;
  return 4;
}

// { done, total } frames if pipeline_meta reports them, else null.
function readFrames(video) {
  let meta = video?.pipeline_meta;
  if (typeof meta === 'string') {
    try {
      meta = JSON.parse(meta);
    } catch {
      return null;
    }
  }
  if (!meta || typeof meta !== 'object') return null;
  const done = finite(meta.frames_processed ?? meta.processed_frames ?? meta.current_frame);
  const total = finite(meta.total_frames ?? meta.frames_total ?? meta.frame_count ?? meta.num_frames);
  return Number.isFinite(done) && Number.isFinite(total) && total > 0 ? { done, total } : null;
}

const finite = (v) => (typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN);

function toPercent(v, { fraction = true } = {}) {
  const n = finite(v);
  if (!Number.isFinite(n) || n < 0) return null;
  if (fraction && n <= 1 && !Number.isInteger(n)) return n * 100; // 0-1 fraction
  return n <= 100 ? n : null;
}

// Fallback only: defensively read whatever pipeline_meta carries. Never throws; returns
// { stageIdx, stageName, percent, message } with nulls/-1 for unknowns.
export function readPipelineMeta(video) {
  let meta = video?.pipeline_meta;
  if (typeof meta === 'string') {
    try {
      meta = JSON.parse(meta);
    } catch {
      meta = { stage: meta };
    }
  }
  const out = { stageIdx: -1, stageName: null, percent: null, message: null };
  const pick = (obj, keys) => {
    if (!obj || typeof obj !== 'object') return undefined;
    for (const k of keys) if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
    return undefined;
  };

  if (meta && typeof meta === 'object' && !Array.isArray(meta)) {
    const stage = pick(meta, ['stage', 'current_stage', 'step', 'current_step', 'phase', 'task']) ?? pick(video, ['stage']);
    if (typeof stage === 'string' || typeof stage === 'number') {
      out.stageIdx = stageIndex(stage);
      out.stageName = typeof stage === 'string' ? stage : null;
    }
    const pct = pick(meta, ['progress', 'percent', 'pct', 'progress_pct', 'percent_complete']);
    out.percent = toPercent(pct);
    if (out.percent === null) {
      const done = finite(pick(meta, ['frames_processed', 'processed_frames', 'frame', 'current_frame']));
      const total = finite(pick(meta, ['total_frames', 'frames_total', 'frame_count', 'num_frames']));
      if (Number.isFinite(done) && Number.isFinite(total) && total > 0) out.percent = Math.min(100, (done / total) * 100);
    }
    const msg = pick(meta, ['message', 'status_message', 'detail', 'description']);
    if (typeof msg === 'string') out.message = msg;
    // Per-stage map, e.g. { stages: { detect: "done", track: "running" } } or an array.
    const stages = meta.stages ?? meta.steps;
    if (out.stageIdx < 0 && stages && typeof stages === 'object') {
      const entries = Array.isArray(stages)
        ? stages.map((x) => [x?.name ?? x?.stage ?? x?.key, x?.status ?? x?.state])
        : Object.entries(stages).map(([k, v]) => [k, typeof v === 'object' && v ? v.status ?? v.state : v]);
      const running = entries.find(([, st]) => /run|progress|active|current|started/i.test(String(st)));
      if (running) out.stageIdx = stageIndex(running[0]);
      else {
        const doneIdx = entries.filter(([, st]) => /done|complete|success|finished/i.test(String(st))).map(([k]) => stageIndex(k));
        const last = Math.max(-1, ...doneIdx);
        if (last >= 0) out.stageIdx = Math.min(last + 1, PROCESSING_STAGES.length - 1);
      }
    }
  } else if (video?.stage !== undefined) {
    out.stageIdx = stageIndex(video.stage);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Match tags + insights (backend contract, see backend README "Tags" / "Insights").
// Tags live on the MATCH: tagging a video tags its match. Older backends 404 here,
// and every caller falls back (see isUnsupported).
// ---------------------------------------------------------------------------
// Endpoint missing on this backend version (route not found / method not allowed).
export const isUnsupported = (err) => err instanceof ApiError && (err.status === 404 || err.status === 405);

// GET /api/tags -> [{ key, values: [{ value, count }] }]  (the user's own tags)
export const getTags = (opts) =>
  request('/api/tags', opts).then((d) => (Array.isArray(d) ? d : Array.isArray(d?.tags) ? d.tags : []));

// PUT /api/videos/{id}/tags { tags: [{key, value}] } (replace all) -> the updated video
export const updateVideoTags = (id, tags) =>
  request(`/api/videos/${encodeURIComponent(id)}/tags`, {
    method: 'PUT',
    body: { tags: tags.map(({ key, value }) => ({ key, value })) },
  });

// GET /api/insights?tag_key=weather[&player_id=7] ->
// { baseline: { avg_*, workload: {low, medium, high}, wdl }, groups: [{ value, matches,
//   matches_with_data, low_sample, avg_distance_km, avg_top_speed_mph, avg_sprints,
//   avg_hsr_distance_km, avg_workload (Low=1..High=3), workload: {low, medium, high},
//   wdl: {w, d, l, unknown} }],
//   next_match_effect: [{ value, metric: distance|speed|sprints|hsr|workload, metric_key,
//   baseline, next, change_pct, n, pairs, low_sample }] }
export function getInsights(tagKey, { playerId, signal } = {}) {
  const q = new URLSearchParams({ tag_key: tagKey });
  if (playerId != null) q.set('player_id', String(playerId));
  return request(`/api/insights?${q}`, { signal });
}

// ---------------------------------------------------------------------------
// Metrics registry + player history
// ---------------------------------------------------------------------------
// GET /api/metrics (public) -> [{ key, label, unit, category, availability: 'ready'|'soon', is_estimate, ... }]
export const getMetricDefs = (opts) =>
  request('/api/metrics', { ...opts, auth: false }).then((d) => (Array.isArray(d) ? d : Array.isArray(d?.metrics) ? d.metrics : []));

// GET /api/players/{id}/metrics -> { player_id, name, series: [...], totals: {...} }
export const getPlayerMetrics = (id, opts) => request(`/api/players/${encodeURIComponent(id)}/metrics`, opts);

// ---------------------------------------------------------------------------
// Jersey-number corrections.
// Backend v0.4.1: PATCH /api/videos/{id}/players/{player_id} {jersey_number: 0-99|null}
// stores the number for THIS video and returns the player's stats row. Older servers
// (404/405), a missing migration (503) or no network fall back to a local-only
// override kept in localStorage per video.
// ---------------------------------------------------------------------------
const JERSEY_KEY = 'sca.jersey_overrides';

function readJerseyOverrides() {
  try {
    const v = JSON.parse(localStorage.getItem(JERSEY_KEY) || '{}');
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}

export function getJerseyCorrections(videoId) {
  return readJerseyOverrides()[String(videoId ?? 'all')] || {};
}

// jersey = integer 0-99, or null to clear the correction. Resolves to the new map.
export async function saveLocalJerseyCorrection({ videoId, playerId, jersey }) {
  const all = readJerseyOverrides();
  const key = String(videoId ?? 'all');
  const map = { ...(all[key] || {}) };
  if (jersey === null || jersey === undefined || jersey === '') delete map[playerId];
  else map[playerId] = Number(jersey);
  all[key] = map;
  try {
    localStorage.setItem(JERSEY_KEY, JSON.stringify(all));
  } catch {
    /* storage unavailable: correction lasts for this page view only */
  }
  return map;
}

export const patchVideoPlayer = (videoId, playerId, body) =>
  request(`/api/videos/${encodeURIComponent(videoId)}/players/${encodeURIComponent(playerId)}`, { method: 'PATCH', body });

const LOCAL_FALLBACK = {
  404: 'This server can’t store shirt-number corrections yet, so it’s saved on this device only.',
  405: 'This server can’t store shirt-number corrections yet, so it’s saved on this device only.',
  503: 'The server isn’t ready to store corrections (database update pending), so it’s saved on this device only.',
  0: 'Couldn’t reach the server, so the correction is saved on this device only.',
};

// Resolves to { mode: 'server', row } or { mode: 'local', map, note }.
// 409 (not processed / number taken) and 422 reject with the server's message.
export async function saveJerseyCorrection({ videoId, playerId, jersey }) {
  const value = jersey === '' || jersey === undefined ? null : jersey === null ? null : Number(jersey);
  if (videoId == null || isDemoToken(getToken())) {
    return { mode: 'local', map: await saveLocalJerseyCorrection({ videoId, playerId, jersey: value }), note: null };
  }
  try {
    const row = await patchVideoPlayer(videoId, playerId, { jersey_number: value });
    // The server copy wins; drop any stale local override for this player.
    const map = await saveLocalJerseyCorrection({ videoId, playerId, jersey: null });
    return { mode: 'server', row, map };
  } catch (err) {
    const status = err?.status ?? 0;
    if (status in LOCAL_FALLBACK) {
      return { mode: 'local', map: await saveLocalJerseyCorrection({ videoId, playerId, jersey: value }), note: LOCAL_FALLBACK[status] };
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Players roster (backend v0.6.0 ERD parity). Owner-scoped. Older backends without
// GET /api/players answer 404 — the Players page shows "not available yet".
// Per-video jersey overrides stay on PATCH /api/videos/{id}/players/{player_id}.
// ---------------------------------------------------------------------------
export const DOMINANT_FEET = ['Left', 'Right', 'Both'];

export function normalizePlayer(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const team = raw.team && typeof raw.team === 'object' ? raw.team : null;
  const j = raw.jersey_number;
  return {
    player_id: raw.player_id ?? raw.id ?? null,
    team_id: raw.team_id ?? team?.team_id ?? null,
    first_name: raw.first_name ?? '',
    last_name: raw.last_name ?? '',
    jersey_number: j === null || j === undefined || j === '' ? null : Number(j),
    position: raw.position ?? null,
    dominant_foot: DOMINANT_FEET.includes(raw.dominant_foot) ? raw.dominant_foot : null,
    contract_end_date: raw.contract_end_date || null,
    created_at: raw.created_at || null,
    team: team
      ? {
          team_id: team.team_id ?? null,
          team_name: team.team_name ?? team.name ?? 'Team',
          league: team.league ?? null,
          created_at: team.created_at || null,
        }
      : null,
  };
}

export const normalizePlayerList = (d) => (Array.isArray(d) ? d : []).map(normalizePlayer).filter(Boolean);

export const listPlayers = (opts = {}) => {
  const q = new URLSearchParams();
  if (opts.team_id != null) q.set('team_id', String(opts.team_id));
  const qs = q.toString() ? `?${q}` : '';
  return request(`/api/players${qs}`, { signal: opts.signal }).then(normalizePlayerList);
};

export const getPlayer = (playerId, opts) =>
  request(`/api/players/${encodeURIComponent(playerId)}`, opts).then(normalizePlayer);

// Partial update. Send JSON null to clear a nullable field. Empty body → 422.
export const patchPlayer = (playerId, body) =>
  request(`/api/players/${encodeURIComponent(playerId)}`, { method: 'PATCH', body }).then(normalizePlayer);

// ---------------------------------------------------------------------------
// Track a player (backend v0.5.0 "tracks" contract: /workspace/capstone-backend/sync/CONTRACT_track_player.md).
// Boxes are [x, y, w, h] normalised 0-1 everywhere, including the POST body. Shapes are normalised in ONE
// adapter, lib/tracking.js. Older servers (v0.4.x) have no such routes: a 404/503 there shows the
// "not available on this server yet" state.
// ---------------------------------------------------------------------------
const vid = (id) => encodeURIComponent(id);
const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== ''));

export const getDetections = (videoId, frame, opts) =>
  request(`/api/videos/${vid(videoId)}/detections?frame=${Math.max(0, Math.round(frame))}`, opts).then((d) => normalizeDetections(d, frame));

// Body: bbox + frame (the clicked box, with its player_id / jersey_number / team as labels), OR player_id,
// OR jersey_number (team optional). The server picks bbox, then player_id, then jersey_number.
export const createTrack = (videoId, { frame, bbox, player_id, jersey_number, team } = {}) =>
  request(`/api/videos/${vid(videoId)}/tracks`, { method: 'POST', body: clean({ frame: bbox ? frame : undefined, bbox, player_id, jersey_number, team }) }).then(normalizeTrack);

export const listTracks = (videoId, opts) => request(`/api/videos/${vid(videoId)}/tracks`, opts).then(normalizeTrackList);

export const getTrack = (trackId, opts) => request(`/api/tracks/${vid(trackId)}`, opts).then(normalizeTrack);

// Optional inclusive ?start&end window; the list is dense (one entry per frame).
export const getTrackFrames = (trackId, { start, end, signal } = {}) => {
  const q = new URLSearchParams();
  if (start != null) q.set('start', String(start));
  if (end != null) q.set('end', String(end));
  const qs = q.toString() ? `?${q}` : '';
  return request(`/api/tracks/${vid(trackId)}/frames${qs}`, { signal }).then(normalizeFrames);
};

export const deleteTrack = (trackId) => request(`/api/tracks/${vid(trackId)}`, { method: 'DELETE' });

export const annotatedSrc = (track) => mediaSrc(track?.annotated_url);

// ---------------------------------------------------------------------------
// Injury-risk workload scoring (backend v0.7.0, provisional contract). Shapes
// are normalised in lib/risk.js. 404/503 here means "not on this server yet".
// ---------------------------------------------------------------------------
export function getRosterRisk({ team_id, sort, match_id, signal } = {}) {
  const q = new URLSearchParams();
  if (team_id != null && team_id !== '') q.set('team_id', String(team_id));
  if (sort === 'asc' || sort === 'desc') q.set('sort', sort);
  if (match_id != null && match_id !== '') q.set('match_id', String(match_id));
  const qs = q.toString() ? `?${q}` : '';
  return request(`/api/roster/risk${qs}`, { signal }).then(normalizeRosterRisk);
}

export const getPlayerRisk = (playerId, { thresholds, signal } = {}) =>
  request(`/api/players/${encodeURIComponent(playerId)}/risk`, { signal }).then((d) => normalizeRiskHistory(d, thresholds));

// Multipart: file, optional team_id, dry_run. dry_run is sent both as a form
// field (contract) and in the query string, so a preview can never be stored
// whichever way the server reads it. 200 = preview, 201 = stored.
export function uploadAthleteCsv({ file, team_id, dry_run = false }, { signal } = {}) {
  const form = new FormData();
  form.append('file', file);
  if (team_id != null && team_id !== '') form.append('team_id', String(team_id));
  form.append('dry_run', dry_run ? 'true' : 'false');
  return request(`/api/uploads/csv?dry_run=${dry_run ? 'true' : 'false'}`, { method: 'POST', form, signal }).then(normalizeCsvUpload);
}

export const listCsvUploads = (opts) => request('/api/uploads/csv', opts).then(normalizeCsvUploadList);
export const deleteCsvUpload = (uploadId) => request(`/api/uploads/csv/${encodeURIComponent(uploadId)}`, { method: 'DELETE' });
