// Sample-mode tracking (demo session only): a SYNTHETIC clip (coloured boxes on a drawn pitch)
// with a pre-made track, served from /public/sample. Never used for real videos.
import { normalizeDetections, normalizeFrames, normalizeTrack } from './tracking';

const BASE = '/sample';
export const DEMO_SOURCE_URL = `${BASE}/track-demo.mp4`;
const DEMO_ANNOTATED_URL = `${BASE}/track-demo-annotated.mp4`;
const KEY = 'sca.demo_track';
const RUN_MS = 4000;

let detCache = null;
const loadDets = () => (detCache ??= fetch(`${BASE}/track-demo-detections.json`).then((r) => r.json()));

export const DEMO_META = { fps: 25, frame_count: 250, width: 640, height: 360 };

export async function demoDetections(frame) {
  const d = await loadDets();
  const f = Math.max(0, Math.min(d.frame_count - 1, Math.round(frame)));
  return normalizeDetections({ frame: f, t: f / d.fps, width: d.width, height: d.height, frame_url: null, players: d.detections[String(f)] || [] }, f);
}

export async function demoRoster() {
  const d = await loadDets();
  const seen = new Map();
  for (const p of d.detections['0'] || [])
    if (p.player_id != null) seen.set(p.player_id, { player_id: p.player_id, jersey_number: p.jersey_number, name: `Sample player ${p.player_id}` });
  return [...seen.values()];
}

function stored() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || 'null');
  } catch {
    return null;
  }
}

function view(s) {
  if (!s) return null;
  const el = Date.now() - s.t0;
  const p = Math.min(100, Math.round((el / RUN_MS) * 100));
  const status = el < 600 ? 'queued' : el < RUN_MS ? 'processing' : 'done';
  const stage = status === 'queued' ? 'queued' : status === 'done' ? 'done' : p < 25 ? 'detect' : p < 70 ? 'tracking' : 'rendering';
  return normalizeTrack({
    track_id: 'demo-1',
    video_id: s.video_id,
    status,
    stage,
    progress: status === 'queued' ? 0 : p,
    target: { ...s.target, jersey_number: 10, player_id: 24 },
    ...DEMO_META,
    annotated_url: status === 'done' ? DEMO_ANNOTATED_URL : null,
    frames_url: status === 'done' ? `${BASE}/track-demo-frames.json` : null,
    // Sample numbers for the synthetic clip (labelled as sample data on the page).
    stats: status === 'done' ? { top_speed_mph: 21.2, distance_km: 0.05 } : null,
    created_at: new Date(s.t0).toISOString(),
  });
}

// The sample track always follows the red #10, whoever is picked, and says so.
export function demoCreateTrack(videoId, body) {
  const s = { t0: Date.now(), video_id: videoId, target: { frame: body.frame ?? 0, bbox: body.bbox ?? null, team: 'A' } };
  sessionStorage.setItem(KEY, JSON.stringify(s));
  return Promise.resolve(view(s));
}
export const demoGetTrack = () => Promise.resolve(view(stored()));
export const demoListTracks = () => Promise.resolve(stored() ? [view(stored())] : []);
export const demoFrames = () =>
  fetch(`${BASE}/track-demo-frames.json`)
    .then((r) => r.json())
    .then(normalizeFrames);
export function demoDeleteTrack() {
  sessionStorage.removeItem(KEY);
  return Promise.resolve();
}
