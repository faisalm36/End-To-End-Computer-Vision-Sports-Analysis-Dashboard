// Track-a-player: the ONE adapter between the backend's tracking shapes and the UI,
// plus the pure maths the replay view uses (frame <-> time, letterboxing, segments,
// summary stats, issues). Frames are 0-based at the native fps; t = f / fps.
// Contract (backend v0.5.0): /workspace/capstone-backend/sync/CONTRACT_track_player.md. Boxes are
// [x, y, w, h] normalised 0-1 everywhere; frame state is tracked | occluded (interpolated) | lost.

const num = (v) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));
const clamp01 = (v) => Math.max(0, Math.min(1, v));

export const LOW_CONF = 0.5;
export const TRACK_STATES = ['tracked', 'occluded', 'lost'];

// [x, y, w, h] normalised 0-1 (also accepts {x,y,w,h}); null when unusable.
export function bboxFrom(b) {
  if (!b) return null;
  const arr = Array.isArray(b) ? b : [b.x, b.y, b.w ?? b.width, b.h ?? b.height];
  const [x, y, w, h] = arr.map(num);
  if ([x, y, w, h].some((v) => v === null) || w <= 0 || h <= 0) return null;
  return [clamp01(x), clamp01(y), Math.min(w, 1), Math.min(h, 1)];
}

const STATUS = {
  queued: 'queued',
  pending: 'queued',
  processing: 'processing',
  running: 'processing',
  done: 'done',
  complete: 'done',
  completed: 'done',
  failed: 'failed',
  error: 'failed',
};

const segPairs = (v) =>
  (Array.isArray(v) ? v : [])
    .map((p) => (Array.isArray(p) ? [num(p[0]), num(p[1])] : [num(p?.start), num(p?.end)]))
    .filter(([x, y]) => x !== null && y !== null && y >= x)
    .map(([x, y]) => [Math.round(x), Math.round(y)]);

// Server summary (null when the server sent none, e.g. while queued).
export function normalizeSummary(s) {
  if (!s || typeof s !== 'object') return null;
  return {
    tracked_frames: num(s.tracked_frames),
    occluded_frames: num(s.occluded_frames),
    lost_frames: num(s.lost_frames),
    coverage_pct: num(s.coverage_pct),
    avg_conf: num(s.avg_conf),
    reacquisition_count: num(s.reacquisition_count),
    lost_segments: segPairs(s.lost_segments),
  };
}

export const ERROR_CODE_TEXT = {
  target_not_found: 'The tracker couldn’t find that player on the chosen frame.',
  cv_unavailable: 'Tracking isn’t set up on the server (CV modules missing).',
  cv_failed: 'The tracker crashed on this video.',
  timeout: 'Tracking took too long and was stopped.',
  interrupted: 'Tracking was interrupted (the server restarted or the track was stopped).',
  source_missing: 'The original video file is no longer on the server.',
  bad_output: 'The tracker returned unusable output.',
};

export function normalizeTrack(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const t = raw.track && typeof raw.track === 'object' ? raw.track : raw;
  const target = t.target && typeof t.target === 'object' ? t.target : {};
  const status = STATUS[String(t.status || '').toLowerCase()] || 'queued';
  return {
    track_id: t.track_id ?? t.id ?? null,
    video_id: t.video_id ?? null,
    status,
    stage: t.stage ? String(t.stage).toLowerCase() : status === 'done' ? 'done' : null,
    progress: num(t.progress),
    error_message: t.error_message || null,
    error_code: t.error_code || null,
    target: {
      mode: target.mode || null,
      player_id: target.player_id ?? null,
      jersey_number: num(target.jersey_number),
      team: target.team === 'A' || target.team === 'B' ? target.team : null,
      frame: num(target.frame),
      t: num(target.t),
      bbox: bboxFrom(target.bbox),
    },
    fps: num(t.fps),
    frame_count: num(t.frame_count),
    width: num(t.width),
    height: num(t.height),
    annotated_url: t.annotated_url || null,
    frames_url: t.frames_url || null,
    source: t.source === 'stub' || t.source === 'real' ? t.source : null,
    summary: normalizeSummary(t.summary),
    stats: t.stats && typeof t.stats === 'object' ? t.stats : null,
    warnings: Array.isArray(t.warnings) ? t.warnings.map(String) : [],
    created_at: t.created_at || null,
    updated_at: t.updated_at || null,
    finished_at: t.finished_at || null,
  };
}

export const normalizeTrackList = (d) => (Array.isArray(d) ? d : Array.isArray(d?.tracks) ? d.tracks : []).map(normalizeTrack).filter(Boolean);

export const isActiveTrack = (t) => t && (t.status === 'queued' || t.status === 'processing');

const CLASSES = ['player', 'goalkeeper', 'referee'];

export function normalizeDetections(raw, frame = null) {
  const d = raw && typeof raw === 'object' ? raw : {};
  const list = Array.isArray(d.players) ? d.players : [];
  const players = list
    .map((p, i) => ({
      key: `${p?.player_id ?? 'x'}-${i}`,
      player_id: p?.player_id ?? null,
      jersey_number: num(p?.jersey_number),
      team: p?.team === 'A' || p?.team === 'B' ? p.team : null,
      cls: CLASSES.includes(p?.class) ? p.class : 'player',
      bbox: bboxFrom(p?.bbox),
      conf: num(p?.conf),
    }))
    .filter((p) => p.bbox);
  return {
    frame: num(d.frame) ?? frame,
    t: num(d.t),
    width: num(d.width),
    height: num(d.height),
    frame_url: d.frame_url || null,
    source: d.source === 'stub' || d.source === 'real' ? d.source : null,
    players,
  };
}

// Per-frame track data, dense by f (the server sends one entry per frame; any gap is treated as lost).
export function normalizeFrames(raw) {
  const d = raw && typeof raw === 'object' ? raw : {};
  const list = Array.isArray(d.frames) ? d.frames : [];
  const fps = num(d.fps);
  const frames = list
    .map((r) => {
      const f = num(r?.f);
      if (f === null) return null;
      const bbox = bboxFrom(r?.bbox);
      const state = !bbox ? 'lost' : TRACK_STATES.includes(r?.state) ? r.state : 'tracked';
      return { f: Math.round(f), t: num(r?.t) ?? (fps ? f / fps : null), bbox: state === 'lost' ? null : bbox, conf: state === 'lost' ? null : num(r?.conf), state };
    })
    .filter(Boolean)
    .sort((a, b) => a.f - b.f);
  const frameCount = num(d.frame_count) ?? (frames.length ? frames[frames.length - 1].f + 1 : 0);
  const byFrame = new Array(frameCount).fill(null);
  for (const r of frames) if (r.f >= 0 && r.f < frameCount) byFrame[r.f] = r;
  for (let f = 0; f < frameCount; f++) if (!byFrame[f]) byFrame[f] = { f, t: fps ? f / fps : null, bbox: null, conf: null, state: 'lost' };
  return { fps, width: num(d.width), height: num(d.height), frame_count: frameCount, source: d.source ?? null, frames: byFrame };
}

// ---- frame <-> time -------------------------------------------------------
export const frameToTime = (f, fps) => (fps > 0 ? f / fps : 0);
export const timeToFrame = (t, fps, frameCount = Infinity) => {
  if (!(fps > 0) || !Number.isFinite(t)) return 0;
  return Math.max(0, Math.min(frameCount - 1, Math.round(t * fps)));
};
// Seek target for frame f: just inside the frame (f + 0.1)/fps, so float error can't land
// on f-1 and round(currentTime*fps) maps back to f.
export const seekTimeForFrame = (f, fps) => (fps > 0 ? (f + 0.1) / fps : 0);
export const stepFrame = (current, delta, frameCount) => Math.max(0, Math.min(frameCount - 1, current + delta));

export function formatTime(sec, withMs = false) {
  if (!Number.isFinite(sec) || sec < 0) sec = 0;
  const m = Math.floor(sec / 60);
  const s = sec - m * 60;
  return withMs ? `${m}:${s.toFixed(2).padStart(5, '0')}` : `${m}:${String(Math.floor(s)).padStart(2, '0')}`;
}

// ---- letterboxing (object-fit: contain) -----------------------------------
// Content rectangle of a w×h media drawn "contain" inside a cw×ch box.
export function fitRect(cw, ch, w, h) {
  if (!(cw > 0) || !(ch > 0) || !(w > 0) || !(h > 0)) return { x: 0, y: 0, w: Math.max(cw, 0), h: Math.max(ch, 0) };
  const scale = Math.min(cw / w, ch / h);
  const rw = w * scale;
  const rh = h * scale;
  return { x: (cw - rw) / 2, y: (ch - rh) / 2, w: rw, h: rh };
}
export const bboxToRect = (bbox, rect) => ({ x: rect.x + bbox[0] * rect.w, y: rect.y + bbox[1] * rect.h, w: bbox[2] * rect.w, h: bbox[3] * rect.h });

// ---- segments, summary, issues --------------------------------------------
// Runs of equal state: [{state, start, end}] (inclusive frame indexes).
export function buildSegments(frames) {
  const out = [];
  for (const r of frames) {
    const last = out[out.length - 1];
    if (last && last.state === r.state && last.end === r.f - 1) last.end = r.f;
    else out.push({ state: r.state, start: r.f, end: r.f });
  }
  return out;
}

// Lost runs: the frames' own lost runs merged with the server's summary.lost_segments ([[start, end]], inclusive).
export function lostRuns(frames, serverSegments = null) {
  const n = frames.length;
  const runs = buildSegments(frames)
    .filter((s) => s.state === 'lost')
    .map((s) => [s.start, s.end]);
  for (const [a, b] of serverSegments || []) if (n === 0 || a < n) runs.push([Math.max(0, a), n ? Math.min(b, n - 1) : b]);
  runs.sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const [a, b] of runs) {
    const last = out[out.length - 1];
    if (last && a <= last.end + 1) last.end = Math.max(last.end, b);
    else out.push({ start: a, end: b });
  }
  return out;
}

// Replay summary. Uses the server's numbers (track.summary: coverage_pct, lost_segments, avg_conf,
// reacquisition_count) when present, else derives them from the per-frame data.
export function summarize(frames, fps, server = null) {
  const n = frames.length;
  if (!n && !server)
    return { frames: 0, trackedPct: null, lostSegments: 0, occludedSegments: 0, longestLostFrames: 0, longestLostSec: 0, reacquisitions: 0, avgConf: null, fromServer: false };
  const segs = buildSegments(frames);
  const lost = lostRuns(frames, server?.lost_segments);
  const tracked = frames.filter((r) => r.state === 'tracked').length;
  const longest = lost.reduce((m, s) => Math.max(m, s.end - s.start + 1), 0);
  // A re-acquisition = a lost run followed by a tracked/occluded frame.
  let reacq = 0;
  for (let i = 0; i < segs.length - 1; i++) if (segs[i].state === 'lost') reacq++;
  const confs = frames.filter((r) => r.state !== 'lost' && r.conf !== null).map((r) => r.conf);
  return {
    frames: n,
    trackedPct: server?.coverage_pct ?? (n ? (tracked / n) * 100 : null),
    lostSegments: server?.lost_segments ? server.lost_segments.length : lost.length,
    occludedSegments: segs.filter((s) => s.state === 'occluded').length,
    longestLostFrames: longest,
    longestLostSec: fps > 0 ? longest / fps : null,
    reacquisitions: server?.reacquisition_count ?? reacq,
    avgConf: server?.avg_conf ?? (confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null),
    fromServer: !!server,
  };
}

// QA issues: lost runs, occluded runs and low-confidence (< 0.5) tracked runs.
// Lost issues also cover the server's summary.lost_segments (pass them as lostSegments).
export function buildIssues(frames, fps, { minFrames = 1, lostSegments = null } = {}) {
  const lostSet = new Set();
  if (lostSegments) for (const s of lostRuns(frames, lostSegments)) for (let f = s.start; f <= s.end; f++) lostSet.add(f);
  const kind = (r) => (r.state === 'lost' || lostSet.has(r.f) ? 'lost' : r.state === 'occluded' ? 'occluded' : r.conf !== null && r.conf < LOW_CONF ? 'low' : null);
  const out = [];
  let cur = null;
  for (const r of frames) {
    const k = kind(r);
    if (cur && k === cur.kind && r.f === cur.end + 1) cur.end = r.f;
    else {
      if (cur) out.push(cur);
      cur = k ? { kind: k, start: r.f, end: r.f } : null;
    }
  }
  if (cur) out.push(cur);
  return out
    .filter((s) => s.end - s.start + 1 >= minFrames)
    .map((s, i) => ({ ...s, id: i, startT: frameToTime(s.start, fps), endT: frameToTime(s.end + 1, fps), duration: frameToTime(s.end - s.start + 1, fps) }));
}

export const ISSUE_LABEL = { lost: 'Lost', occluded: 'Occluded', low: 'Low conf' };

export const nextIssue = (issues, f) => issues.find((s) => s.start > f) ?? null;
export function prevIssue(issues, f) {
  for (let i = issues.length - 1; i >= 0; i--) if (issues[i].start < f && !(f >= issues[i].start && f <= issues[i].end)) return issues[i];
  // Inside an issue: go to the one before it.
  const inside = issues.findIndex((s) => f >= s.start && f <= s.end);
  return inside > 0 ? issues[inside - 1] : null;
}

// What the replay shows for a frame.
export function frameView(frames, f) {
  const r = frames[f] ?? null;
  if (!r) return { state: 'lost', bbox: null, conf: null, low: false, estimate: false };
  return { state: r.state, bbox: r.bbox, conf: r.conf, low: r.state === 'tracked' && r.conf !== null && r.conf < LOW_CONF, estimate: r.state === 'occluded' };
}

// Trail: box centres over the last `seconds` (skips lost frames).
export function trailPoints(frames, f, fps, seconds = 1.5) {
  const n = Math.max(1, Math.round(seconds * (fps || 25)));
  const pts = [];
  for (let i = Math.max(0, f - n); i <= f; i++) {
    const b = frames[i]?.bbox;
    if (b) pts.push({ f: i, x: b[0] + b[2] / 2, y: b[1] + b[3] / 2 });
  }
  return pts;
}

// Track progress -> stepper.
// Server stages: queued -> detect -> tracking -> rendering -> done | failed (unknown names shown as-is).
export const TRACK_STEPS = ['Queued', 'Finding players', 'Following the player', 'Rendering video', 'Done'];
export function trackStep(track) {
  if (!track) return { current: 0, failed: false, unknown: null };
  if (track.status === 'done') return { current: 4, failed: false, unknown: null };
  const stage = track.stage || '';
  let idx = 0;
  let unknown = null;
  if (/render|annot|encod/.test(stage)) idx = 3;
  else if (/track|follow/.test(stage)) idx = 2;
  else if (/detect/.test(stage)) idx = 1;
  else if (stage && !/queue|fail|done/.test(stage)) {
    unknown = track.stage;
    idx = track.status === 'processing' ? 1 : 0;
  } else if (track.status === 'processing') idx = 1;
  return { current: idx, failed: track.status === 'failed', unknown };
}

export const targetLabel = (t) => (t?.jersey_number != null ? `#${t.jersey_number}` : t?.player_id != null ? `Player ID ${t.player_id}` : 'Selected player');

// Replay speeds and the keyboard sheet (UI/UX spec §4; 1.5× kept per Main).
export const SPEEDS = [0.25, 0.5, 1, 1.5, 2];

export const SHORTCUTS = [
  ['Space', 'Play / pause'],
  ['← / →', 'Back / forward 1 s'],
  ['Shift + ← / →', 'Back / forward 5 s'],
  [', or <', 'Previous frame'],
  ['. or >', 'Next frame'],
  ['N / P', 'Next / previous issue'],
  ['F', 'Fullscreen'],
  ['?', 'Show these shortcuts'],
];
